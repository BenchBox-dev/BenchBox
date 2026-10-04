from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.publication.assembler import LaneArtifact, SiteAssembler, compute_file_sha256, compute_tree_digest
from scripts.site_deploy import mixed_version
from scripts.site_deploy.renderer import ASTRO, POLICIES, RENDERERS, SPHINX

REF_KINDS = ("release-tag", "trunk")
BUILDERS = ("landing", "docs", "blog", "explorer")
ROOT_FILE_NAMES = ("CNAME", ".nojekyll", "404.html")
LANDING_EXCLUDES = ("docs", "blog", "results", "_static", "_images", *ROOT_FILE_NAMES)
BLOG_ASSET_DIRS = ("_static", "_images")
FULL_STAGE_BUILDERS = ("explorer",)
ASTRO_SHARED_ASSET_DIRS = ("_astro", "_images")
ASTRO_LANDING_EXCLUDES = ("docs", "blog", "results", *ROOT_FILE_NAMES)
EXPLORER_SNAPSHOT = "data/results.duckdb"
EXPLORER_SNAPSHOT_DIR = "data"
SCHEMA = "site-deploy-route-assembly/v1"


class RouteManifestError(ValueError):
    pass


@dataclass(frozen=True)
class Route:
    path: str
    ref: str
    builder: str
    corpus: str | None = None


@dataclass(frozen=True)
class Mount:
    relative: str
    prefix: str
    excludes: tuple[str, ...] = ()
    shared: bool = False


@dataclass(frozen=True)
class RouteManifest:
    refs: dict[str, str]
    routes: tuple[Route, ...]
    root_files_ref: str
    root_files: tuple[str, ...]
    renderer_policy: str = SPHINX

    def ref_names(self) -> set[str]:
        return {route.ref for route in self.routes} | {self.root_files_ref}


def _normalise_path(path: str) -> str:
    if not path.startswith("/") or not path.endswith("/") or "//" in path or ".." in path.split("/"):
        raise RouteManifestError(f"route path must be absolute, slash-terminated and normalised: {path!r}")
    return path


def parse_manifest(data: Mapping[str, Any]) -> RouteManifest:
    if data.get("version") != 1:
        raise RouteManifestError(f"unsupported routes manifest version: {data.get('version')!r}")
    refs_raw = data.get("refs")
    if not isinstance(refs_raw, dict) or not refs_raw:
        raise RouteManifestError("routes manifest needs a non-empty refs mapping")
    refs: dict[str, str] = {}
    for name, spec in refs_raw.items():
        kind = spec.get("kind") if isinstance(spec, dict) else None
        if kind not in REF_KINDS:
            raise RouteManifestError(f"ref {name!r} has unsupported kind {kind!r}; expected one of {REF_KINDS}")
        refs[str(name)] = kind
    routes: list[Route] = []
    for entry in data.get("routes") or []:
        route = Route(
            path=_normalise_path(str(entry.get("path", ""))),
            ref=str(entry.get("ref", "")),
            builder=str(entry.get("builder", "")),
            corpus=entry.get("corpus"),
        )
        if route.ref not in refs:
            raise RouteManifestError(f"route {route.path} names unknown ref {route.ref!r}")
        if route.builder not in BUILDERS:
            raise RouteManifestError(f"route {route.path} names unknown builder {route.builder!r}")
        routes.append(route)
    if not routes:
        raise RouteManifestError("routes manifest declares no routes")
    paths = [route.path for route in routes]
    if len(set(paths)) != len(paths):
        raise RouteManifestError("routes manifest declares a path twice")
    root = data.get("root_files") or {}
    root_ref = str(root.get("ref", ""))
    root_files = tuple(str(name) for name in root.get("files") or ())
    if root_ref not in refs:
        raise RouteManifestError(f"root_files names unknown ref {root_ref!r}")
    unknown = sorted(set(root_files) - set(ROOT_FILE_NAMES))
    if unknown:
        raise RouteManifestError(f"root_files names unsupported files: {unknown}")
    policy = str(data.get("renderer", SPHINX))
    if policy not in POLICIES:
        raise RouteManifestError(f"renderer policy {policy!r} is not one of {POLICIES}")
    if sorted(set(refs.values())) != sorted(REF_KINDS):
        raise RouteManifestError(f"routes manifest needs exactly one ref of each kind {REF_KINDS}")
    return RouteManifest(
        refs=refs, routes=tuple(routes), root_files_ref=root_ref, root_files=root_files, renderer_policy=policy
    )


def release_ref(manifest: RouteManifest) -> str:
    return next(name for name, kind in manifest.refs.items() if kind == "release-tag")


def load_manifest(path: Path) -> RouteManifest:
    return parse_manifest(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def git_head_sha(root: Path) -> str:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def _extract(stage: Path, relative: str, destination: Path, excludes: tuple[str, ...] = ()) -> Path | None:
    source = stage / relative if relative else stage
    if not source.exists():
        return None
    destination.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        shutil.copy2(source, destination / source.name)
        return destination

    def ignore(directory: str, names: list[str]) -> set[str]:
        return {name for name in names if name in excludes} if Path(directory) == source else set()

    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)
    return destination


def _mounts(route: Route, renderer: str = SPHINX) -> list[Mount]:
    astro = renderer == ASTRO
    if route.builder == "landing":
        return [Mount("", route.path, ASTRO_LANDING_EXCLUDES if astro else LANDING_EXCLUDES)]
    if route.builder == "docs":
        return [Mount("docs", route.path)]
    if route.builder == "blog":
        assets = ASTRO_SHARED_ASSET_DIRS if astro else BLOG_ASSET_DIRS
        return [Mount("blog", route.path), *(Mount(name, f"/{name}/", shared=astro) for name in assets)]
    return [Mount("results", route.path)]


def owner_ref(manifest: RouteManifest, path: str, renderer: str = SPHINX) -> str | None:
    clean = path.split("#", 1)[0].split("?", 1)[0]
    if any(clean == f"/{name}" for name in manifest.root_files):
        return manifest.root_files_ref
    best: tuple[int, str] | None = None
    for route in manifest.routes:
        for mount in _mounts(route, renderer):
            prefix = mount.prefix
            if (clean.startswith(prefix) or clean == prefix.rstrip("/")) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), route.ref)
    return best[1] if best else None


def is_trunk_owned(manifest: RouteManifest, path: str, renderer: str = SPHINX) -> bool:
    ref = owner_ref(manifest, path, renderer)
    return ref is not None and manifest.refs[ref] == "trunk"


def _lane(name: str, prefix: str, source: Path) -> LaneArtifact:
    digest, size, manifest = compute_tree_digest(source)
    return LaneArtifact(
        lane_name=name,
        digest=digest,
        size_bytes=size,
        source_path=str(source),
        output_prefix=prefix,
        file_manifest=manifest,
    )


def _stage_requires_full(manifest: RouteManifest, ref: str) -> bool:
    if any(route.ref == ref and route.builder in FULL_STAGE_BUILDERS for route in manifest.routes):
        return True
    return manifest.root_files_ref == ref and "404.html" in manifest.root_files


def _check_stage(ref: str, stage: Path, renderer: str) -> None:
    if renderer == ASTRO and not (stage / mixed_version.ASTRO_ASSET_DIR).is_dir():
        raise RouteManifestError(f"ref {ref} did not produce an astro build: no {mixed_version.ASTRO_ASSET_DIR}/")
    foreign = sorted(kind for kind in mixed_version.tree_renderers(stage) if kind != renderer)
    if foreign:
        raise RouteManifestError(f"ref {ref} stage for {renderer} carries {', '.join(foreign)} output")


def _drop_shared_duplicates(extracted: Path, prefix: str, claimed: Mapping[str, str], lane: str) -> bool:
    _, _, files = compute_tree_digest(extracted)
    for relative, sha in files.items():
        final = f"{prefix.strip('/')}/{relative}"
        if final not in claimed:
            continue
        if claimed[final] != sha:
            raise RouteManifestError(f"{lane} and an earlier route ship different bytes at shared path {final}")
        (extracted / relative).unlink()
    remaining = [path for path in extracted.rglob("*") if path.is_file()]
    return bool(remaining)


def _explorer_pins(extracted: Path, scratch: Path, source_sha: str) -> dict[str, Any]:
    ui = scratch / "ui"
    shutil.copytree(
        extracted,
        ui,
        ignore=lambda directory, names: {EXPLORER_SNAPSHOT_DIR} if Path(directory) == extracted else set(),
    )
    ui_digest, _, _ = compute_tree_digest(ui)
    snapshot = extracted / EXPLORER_SNAPSHOT
    return {
        "ui": {"source_sha": source_sha, "sha256": ui_digest},
        "snapshot": {
            "path": EXPLORER_SNAPSHOT,
            "sha256": compute_file_sha256(snapshot) if snapshot.is_file() else None,
        },
    }


def assemble_routes(
    *,
    manifest: RouteManifest,
    ref_roots: Mapping[str, Path],
    site_dir: Path,
    work_dir: Path,
    stage_builder: Callable[..., None],
    resolve_sha: Callable[[Path], str] = git_head_sha,
    renderer: str = SPHINX,
) -> dict[str, Any]:
    if renderer not in RENDERERS:
        raise RouteManifestError(f"unknown renderer {renderer!r}; expected one of {RENDERERS}")
    wanted = manifest.ref_names()
    if set(ref_roots) != wanted:
        raise RouteManifestError(f"ref roots {sorted(ref_roots)} do not match manifest refs {sorted(wanted)}")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)
    stages: dict[str, Path] = {}
    for ref in sorted(wanted):
        stage = work_dir / "stage" / ref
        stage_builder(repo_root=ref_roots[ref], site_dir=stage, prose_only=not _stage_requires_full(manifest, ref))
        _check_stage(ref, stage, renderer)
        stages[ref] = stage
    shas = {ref: resolve_sha(ref_roots[ref]) for ref in sorted(wanted)}
    planned = [
        (index, mount_index, route, mount)
        for index, route in enumerate(manifest.routes)
        for mount_index, mount in enumerate(_mounts(route, renderer))
    ]
    planned.sort(key=lambda item: item[3].shared)
    lanes: list[tuple[LaneArtifact, Path]] = []
    lane_routes: dict[str, str] = {}
    lane_digests: dict[str, str] = {}
    claimed: dict[str, str] = {}
    pins: dict[str, dict[str, Any]] = {}
    for index, mount_index, route, mount in planned:
        if route.builder == "landing" and renderer == SPHINX and not (ref_roots[route.ref] / "landing").is_dir():
            raise RouteManifestError(f"route {route.path} needs landing/ in ref {route.ref}")
        destination = work_dir / "lanes" / f"{index}-{mount_index}"
        extracted = _extract(stages[route.ref], mount.relative, destination, mount.excludes)
        if extracted is None:
            if mount.shared:
                continue
            raise RouteManifestError(
                f"route {route.path} ({route.builder}) found no {mount.relative!r} in ref {route.ref}"
            )
        name = f"{route.path}:{mount.relative or '.'}"
        if mount.shared and not _drop_shared_duplicates(extracted, mount.prefix, claimed, name):
            continue
        lane = _lane(name, mount.prefix, extracted)
        lanes.append((lane, extracted))
        lane_routes[name] = route.path
        lane_digests[name] = lane.digest
        base = mount.prefix.strip("/")
        claimed.update({f"{base}/{rel}" if base else rel: sha for rel, sha in lane.file_manifest.items()})
        if route.builder == "explorer":
            pins[route.path] = _explorer_pins(extracted, work_dir / "pins" / str(index), shas[route.ref])
    for index, filename in enumerate(manifest.root_files):
        extracted = _extract(stages[manifest.root_files_ref], filename, work_dir / "lanes" / f"root-{index}")
        if extracted is None:
            raise RouteManifestError(f"root file {filename} missing in ref {manifest.root_files_ref}")
        lanes.append((_lane(f"root:{filename}", "/", extracted), extracted))
    assembler = SiteAssembler(site_dir, receipt_path=work_dir / "assembly.json")
    receipt, _ = assembler.assemble(lanes)
    try:
        renderer_pages = mixed_version.require_single_renderer(site_dir, renderer)
    except mixed_version.RendererMixError as exc:
        shutil.rmtree(site_dir, ignore_errors=True)
        raise RouteManifestError(f"refusing a mixed-renderer artifact: {exc}") from exc
    owners = assembler.claimed_paths
    routes_out = []
    for route in manifest.routes:
        owned = sorted(path for path, lane in owners.items() if lane_routes.get(lane) == route.path)
        entry = {
            "path": route.path,
            "ref": route.ref,
            "ref_kind": manifest.refs[route.ref],
            "builder": route.builder,
            "renderer": renderer,
            "source_sha": shas[route.ref],
            "corpus": route.corpus,
            "owned_files": len(owned),
            "lane_sha256": {
                name: lane_digests[name] for name in sorted(lane_digests) if lane_routes[name] == route.path
            },
        }
        if route.path in pins:
            entry["pins"] = pins[route.path]
        routes_out.append(entry)
    root_owned = sorted(path for path, lane in owners.items() if lane.startswith("root:"))
    return {
        "schema": SCHEMA,
        "renderer": renderer,
        "renderer_policy": manifest.renderer_policy,
        "renderer_pages": renderer_pages,
        "refs": {ref: {"kind": manifest.refs[ref], "source_sha": shas[ref]} for ref in sorted(wanted)},
        "routes": routes_out,
        "root_files": root_owned,
        "tree_sha256": receipt["assembly_digest"],
        "total_bytes": receipt["total_bytes"],
        "total_files": receipt["total_files"],
        "file_manifest": receipt["file_manifest"],
        "file_owners": dict(sorted(owners.items())),
    }


def write_assembly_receipt(path: Path, receipt: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
