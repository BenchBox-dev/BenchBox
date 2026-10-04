from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scripts.publication.assembler import LaneArtifact, SiteAssembler, compute_tree_digest

REF_KINDS = ("release-tag", "trunk")
BUILDERS = ("landing", "docs", "blog", "explorer")
ROOT_FILE_NAMES = ("CNAME", ".nojekyll", "404.html")
LANDING_EXCLUDES = ("docs", "blog", "results", "_static", "_images", *ROOT_FILE_NAMES)
BLOG_ASSET_DIRS = ("_static", "_images")
FULL_STAGE_BUILDERS = ("explorer",)
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
class RouteManifest:
    refs: dict[str, str]
    routes: tuple[Route, ...]
    root_files_ref: str
    root_files: tuple[str, ...]

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
    return RouteManifest(refs=refs, routes=tuple(routes), root_files_ref=root_ref, root_files=root_files)


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


def _mounts(route: Route) -> list[tuple[str, str, tuple[str, ...]]]:
    if route.builder == "landing":
        return [("", route.path, LANDING_EXCLUDES)]
    if route.builder == "docs":
        return [("docs", route.path, ())]
    if route.builder == "blog":
        mounts: list[tuple[str, str, tuple[str, ...]]] = [("blog", route.path, ())]
        mounts.extend((name, f"/{name}/", ()) for name in BLOG_ASSET_DIRS)
        return mounts
    return [("results", route.path, ())]


def owner_ref(manifest: RouteManifest, path: str) -> str | None:
    clean = path.split("#", 1)[0].split("?", 1)[0]
    if any(clean == f"/{name}" for name in manifest.root_files):
        return manifest.root_files_ref
    best: tuple[int, str] | None = None
    for route in manifest.routes:
        for _, prefix, _ in _mounts(route):
            if (clean.startswith(prefix) or clean == prefix.rstrip("/")) and (best is None or len(prefix) > best[0]):
                best = (len(prefix), route.ref)
    return best[1] if best else None


def is_trunk_owned(manifest: RouteManifest, path: str) -> bool:
    ref = owner_ref(manifest, path)
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


def assemble_routes(
    *,
    manifest: RouteManifest,
    ref_roots: Mapping[str, Path],
    site_dir: Path,
    work_dir: Path,
    stage_builder: Callable[..., None],
    resolve_sha: Callable[[Path], str] = git_head_sha,
) -> dict[str, Any]:
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
        stages[ref] = stage
    lanes: list[tuple[LaneArtifact, Path]] = []
    lane_routes: dict[str, str] = {}
    lane_digests: dict[str, str] = {}
    for index, route in enumerate(manifest.routes):
        if route.builder == "landing" and not (ref_roots[route.ref] / "landing").is_dir():
            raise RouteManifestError(f"route {route.path} needs landing/ in ref {route.ref}")
        for mount_index, (relative, prefix, excludes) in enumerate(_mounts(route)):
            extracted = _extract(stages[route.ref], relative, work_dir / "lanes" / f"{index}-{mount_index}", excludes)
            if extracted is None:
                raise RouteManifestError(
                    f"route {route.path} ({route.builder}) found no {relative!r} in ref {route.ref}"
                )
            name = f"{route.path}:{relative or '.'}"
            lane = _lane(name, prefix, extracted)
            lanes.append((lane, extracted))
            lane_routes[name] = route.path
            lane_digests[name] = lane.digest
    for index, filename in enumerate(manifest.root_files):
        extracted = _extract(stages[manifest.root_files_ref], filename, work_dir / "lanes" / f"root-{index}")
        if extracted is None:
            raise RouteManifestError(f"root file {filename} missing in ref {manifest.root_files_ref}")
        lanes.append((_lane(f"root:{filename}", "/", extracted), extracted))
    assembler = SiteAssembler(site_dir, receipt_path=work_dir / "assembly.json")
    receipt, _ = assembler.assemble(lanes)
    owners = assembler.claimed_paths
    shas = {ref: resolve_sha(ref_roots[ref]) for ref in sorted(wanted)}
    routes_out = []
    for route in manifest.routes:
        owned = sorted(path for path, lane in owners.items() if lane_routes.get(lane) == route.path)
        routes_out.append(
            {
                "path": route.path,
                "ref": route.ref,
                "ref_kind": manifest.refs[route.ref],
                "builder": route.builder,
                "source_sha": shas[route.ref],
                "corpus": route.corpus,
                "owned_files": len(owned),
                "lane_sha256": {
                    name: lane_digests[name] for name in sorted(lane_digests) if lane_routes[name] == route.path
                },
            }
        )
    root_owned = sorted(path for path, lane in owners.items() if lane.startswith("root:"))
    return {
        "schema": SCHEMA,
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
