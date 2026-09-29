#!/usr/bin/env python3
"""Assemble the exact directory tree published by the documentation workflow.

Two modes share this entry point:

* Local-build mode (default, no ``--manifest``): copy the already-built
  ``landing/``, ``docs/_build/html`` and ``results-explorer/dist`` directories of
  one checkout into a Pages-shaped tree.
* Route-manifest mode (``--manifest site/routes.yml``): every route is built from
  the commit its manifest entry pins (the latest release tag for ``/`` and
  ``/docs/``, the trunk commit for everything else). Each pinned commit is
  exported once with ``git archive`` into a scratch tree, built there, and copied
  into the site with file-level ownership, so two routes can never silently
  overwrite each other's bytes.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

RESULTS_FALLBACK = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Page Not Found - BenchBox</title>
  <script>
    var redirectKey = 'benchbox.results.redirect';

    if (window.location.pathname.startsWith('/results/')) {
      var originalPath = window.location.pathname + window.location.search + window.location.hash;

      try {
        window.sessionStorage.setItem(redirectKey, originalPath);
      } catch (error) {
        // Ignore sessionStorage failures and still redirect to the SPA entrypoint.
      }

      window.location.replace('/results/');
    }
  </script>
</head>
<body>
  <p>Page not found. <a href="/">Return to documentation</a>.</p>
</body>
</html>
"""


IgnorePattern = Callable[[str, list[str]], set[str]]


def _copy_tree(source: Path, destination: Path, *, ignore: IgnorePattern | None = None) -> None:
    shutil.copytree(source, destination, dirs_exist_ok=True, ignore=ignore)


def _validate_destination(repo_root: Path, site_dir: Path) -> None:
    resolved_root = repo_root.resolve()
    resolved_site = site_dir.resolve()
    forbidden = {Path("/").resolve(), Path.home().resolve(), resolved_root, resolved_root.parent}
    if site_dir.is_symlink() or resolved_site in forbidden:
        raise ValueError(f"refusing unsafe site output directory: {site_dir}")


def assemble_public_site(*, repo_root: Path, site_dir: Path, prose_only: bool = False) -> None:
    """Build the Pages-shaped landing, docs, blog, and optional Explorer tree."""
    repo_root = repo_root.resolve()
    _validate_destination(repo_root, site_dir)
    site_dir = site_dir.resolve()

    docs_html = repo_root / "docs" / "_build" / "html"
    if not docs_html.is_dir():
        raise FileNotFoundError(f"documentation build is missing: {docs_html}")

    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)
    (site_dir / "docs").mkdir()
    (site_dir / "blog").mkdir()

    landing = repo_root / "landing"
    if landing.is_dir():
        _copy_tree(landing, site_dir)
        _copy_tree(docs_html, site_dir / "docs", ignore=shutil.ignore_patterns("blog"))
    else:
        _copy_tree(docs_html, site_dir)

    blog = docs_html / "blog"
    if blog.is_dir():
        _copy_tree(blog, site_dir / "blog")

    static_assets = docs_html / "_static"
    if not static_assets.is_dir():
        raise FileNotFoundError(f"documentation static assets are missing: {static_assets}")
    _copy_tree(static_assets, site_dir / "_static")

    image_assets = docs_html / "_images"
    if image_assets.is_dir():
        _copy_tree(image_assets, site_dir / "_images")

    # CNAME and 404 are Pages deployment concerns; prose_only produces a
    # non-deployable artifact slice, so neither is emitted in that mode.
    if not prose_only:
        cname = repo_root / "docs" / "CNAME"
        if cname.is_file():
            shutil.copy2(cname, site_dir / "CNAME")
        (site_dir / ".nojekyll").touch()
    else:
        # Still mark as Jekyll-bypassed so prose_site can be inspected locally,
        # but do not claim the apex domain.
        (site_dir / ".nojekyll").touch()

    if not prose_only:
        explorer_package = repo_root / "results-explorer" / "package.json"
        explorer_dist = repo_root / "results-explorer" / "dist"
        if explorer_package.is_file() and not explorer_dist.is_dir():
            raise FileNotFoundError(f"Results Explorer build is missing: {explorer_dist}")
        if explorer_dist.is_dir():
            _copy_tree(explorer_dist, site_dir / "results")
            (site_dir / "404.html").write_text(RESULTS_FALLBACK, encoding="utf-8")


# ---------------------------------------------------------------------------
# Route-manifest mode
# ---------------------------------------------------------------------------

MANIFEST_SCHEMA_VERSION = 1
DEFAULT_MANIFEST = Path("site") / "routes.yml"

KIND_LANDING = "landing"
KIND_DOCS = "docs"
KIND_BLOG = "blog"
KIND_EXPLORER = "explorer"
ROUTE_KINDS = (KIND_LANDING, KIND_DOCS, KIND_BLOG, KIND_EXPLORER)

REF_KIND_LATEST_TAG = "latest-tag"
REF_KIND_BRANCH = "branch"
RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_ROUTE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
_REF_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class ManifestError(ValueError):
    """The route manifest is malformed or cannot be resolved."""


class RouteOwnershipError(RuntimeError):
    """Two routes tried to write the same output path."""


@dataclass(frozen=True)
class RefSpec:
    """How one named ref (for example ``release`` or ``trunk``) is resolved."""

    name: str
    kind: str
    pattern: str = "v[0-9]*.[0-9]*.[0-9]*"
    branch: str = ""


@dataclass(frozen=True)
class ResolvedRef:
    """A named ref pinned to an immutable commit."""

    name: str
    label: str  # tag or branch name shown in receipts; the commit is the identity
    sha: str


@dataclass(frozen=True)
class Route:
    id: str
    mount: str  # normalized: leading and trailing slash
    ref: str
    kind: str
    spa: bool = False


@dataclass(frozen=True)
class RouteManifest:
    schema_version: int
    refs: dict[str, RefSpec]
    routes: tuple[Route, ...]


@dataclass(frozen=True)
class BuildStep:
    name: str
    argv: tuple[str, ...]
    cwd: str = "."


@dataclass
class RouteAssembly:
    route: Route
    ref: ResolvedRef
    files: int = 0


@dataclass
class ManifestAssembly:
    site_dir: Path
    routes: list[RouteAssembly] = field(default_factory=list)
    refs: dict[str, ResolvedRef] = field(default_factory=dict)
    ref_roots: dict[str, Path] = field(default_factory=dict)
    file_owners: dict[str, str] = field(default_factory=dict)  # site-relative path -> route id


Runner = Callable[[Sequence[str], Path, Mapping[str, str]], None]


def _normalize_mount(raw: object) -> str:
    if not isinstance(raw, str) or not raw.startswith("/"):
        raise ManifestError(f"route mount must be an absolute path starting with '/': {raw!r}")
    if ".." in raw.split("/") or "//" in raw or "\\" in raw:
        raise ManifestError(f"route mount is not a clean path: {raw!r}")
    return raw if raw.endswith("/") else raw + "/"


def _parse_refs(raw_refs: object) -> dict[str, RefSpec]:
    if not isinstance(raw_refs, dict) or not raw_refs:
        raise ManifestError("route manifest needs a non-empty 'refs' mapping")
    refs: dict[str, RefSpec] = {}
    for name, spec in raw_refs.items():
        if not isinstance(name, str) or not _REF_NAME_RE.match(name):
            raise ManifestError(f"invalid ref name: {name!r}")
        if not isinstance(spec, dict) or spec.get("kind") not in (REF_KIND_LATEST_TAG, REF_KIND_BRANCH):
            raise ManifestError(f"ref {name!r} needs kind {REF_KIND_LATEST_TAG!r} or {REF_KIND_BRANCH!r}")
        if spec["kind"] == REF_KIND_BRANCH:
            branch = spec.get("branch")
            if not isinstance(branch, str) or not branch:
                raise ManifestError(f"branch ref {name!r} needs a 'branch'")
            refs[name] = RefSpec(name=name, kind=REF_KIND_BRANCH, branch=branch)
            continue
        pattern = spec.get("pattern", RefSpec.pattern)
        if not isinstance(pattern, str) or not pattern:
            raise ManifestError(f"tag ref {name!r} needs a 'pattern'")
        refs[name] = RefSpec(name=name, kind=REF_KIND_LATEST_TAG, pattern=pattern)
    return refs


def _parse_route(entry: object, refs: Mapping[str, RefSpec]) -> Route:
    if not isinstance(entry, dict):
        raise ManifestError(f"route entry must be a mapping: {entry!r}")
    route_id = entry.get("id")
    if not isinstance(route_id, str) or not _ROUTE_ID_RE.match(route_id):
        raise ManifestError(f"invalid route id: {route_id!r}")
    ref = entry.get("ref")
    if ref not in refs:
        raise ManifestError(f"route {route_id!r} names unknown ref {ref!r}")
    kind = entry.get("kind")
    if kind not in ROUTE_KINDS:
        raise ManifestError(f"route {route_id!r} has unknown kind {kind!r}; expected one of {ROUTE_KINDS}")
    spa = entry.get("spa", False)
    if not isinstance(spa, bool):
        raise ManifestError(f"route {route_id!r}: 'spa' must be a boolean")
    return Route(id=route_id, mount=_normalize_mount(entry.get("mount")), ref=str(ref), kind=str(kind), spa=spa)


def parse_manifest(data: object) -> RouteManifest:
    """Validate a decoded route manifest."""
    if not isinstance(data, dict):
        raise ManifestError("route manifest must be a mapping")
    if data.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ManifestError(f"unsupported route manifest schema_version: {data.get('schema_version')!r}")
    refs = _parse_refs(data.get("refs"))
    raw_routes = data.get("routes")
    if not isinstance(raw_routes, list) or not raw_routes:
        raise ManifestError("route manifest needs a non-empty 'routes' list")
    routes = [_parse_route(entry, refs) for entry in raw_routes]
    for label, values in (("route id", [r.id for r in routes]), ("route mount", [r.mount for r in routes])):
        duplicates = sorted({value for value in values if values.count(value) > 1})
        if duplicates:
            raise ManifestError(f"duplicate {label}: {duplicates}")
    if "/" not in {r.mount for r in routes}:
        raise ManifestError("route manifest must mount a landing route at '/'")
    return RouteManifest(schema_version=MANIFEST_SCHEMA_VERSION, refs=refs, routes=tuple(routes))


def load_manifest(path: Path) -> RouteManifest:
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ManifestError(f"cannot read route manifest {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ManifestError(f"route manifest {path} is not valid YAML: {exc}") from exc
    return parse_manifest(data)


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args], check=False, capture_output=True, text=True, encoding="utf-8"
    )
    if result.returncode != 0:
        raise ManifestError(f"git {' '.join(args)} failed: {result.stderr.strip() or result.stdout.strip()}")
    return result.stdout.strip()


def _verify_commit(repo_root: Path, revision: str) -> str:
    sha = _git(repo_root, "rev-parse", "--verify", f"{revision}^{{commit}}")
    if not SHA_RE.match(sha):
        raise ManifestError(f"{revision!r} did not resolve to a 40-hex commit: {sha!r}")
    return sha


def latest_release_tag(repo_root: Path, pattern: str = "v[0-9]*.[0-9]*.[0-9]*") -> str:
    """Return the highest final ``vX.Y.Z`` tag; pre-releases and odd names never qualify."""
    listing = _git(repo_root, "tag", "--list", pattern, "--sort=-v:refname")
    for tag in listing.splitlines():
        if RELEASE_TAG_RE.match(tag):
            return tag
    raise ManifestError(f"no release tag matches {pattern!r}")


def resolve_ref(repo_root: Path, spec: RefSpec, override: str | None = None) -> ResolvedRef:
    """Pin one named ref to a commit. ``override`` is a tag, branch, or 40-hex commit."""
    if override:
        if SHA_RE.match(override):
            return ResolvedRef(spec.name, override, _verify_commit(repo_root, override))
        if spec.kind == REF_KIND_LATEST_TAG:
            if not RELEASE_TAG_RE.match(override):
                raise ManifestError(f"release override must be a vX.Y.Z tag or a commit, got {override!r}")
            return ResolvedRef(spec.name, override, _verify_commit(repo_root, f"refs/tags/{override}"))
        return ResolvedRef(spec.name, override, _verify_commit(repo_root, override))
    if spec.kind == REF_KIND_LATEST_TAG:
        tag = latest_release_tag(repo_root, spec.pattern)
        return ResolvedRef(spec.name, tag, _verify_commit(repo_root, f"refs/tags/{tag}"))
    for candidate in (f"refs/remotes/origin/{spec.branch}", f"refs/heads/{spec.branch}"):
        try:
            return ResolvedRef(spec.name, spec.branch, _verify_commit(repo_root, candidate))
        except ManifestError:
            continue
    raise ManifestError(f"branch {spec.branch!r} not found locally or on origin")


def resolve_refs(
    repo_root: Path, manifest: RouteManifest, overrides: Mapping[str, str] | None = None
) -> dict[str, ResolvedRef]:
    overrides = dict(overrides or {})
    unknown = sorted(set(overrides) - set(manifest.refs))
    if unknown:
        raise ManifestError(f"override for unknown ref(s): {unknown}")
    used = sorted({route.ref for route in manifest.routes})
    return {name: resolve_ref(repo_root, manifest.refs[name], overrides.get(name)) for name in used}


def materialize_ref(repo_root: Path, ref: ResolvedRef, destination: Path) -> Path:
    """Export the pinned commit's tree (no ``.git``) into ``destination``."""
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    archive = subprocess.Popen(
        ["git", "-C", str(repo_root), "archive", "--format=tar", ref.sha], stdout=subprocess.PIPE
    )
    assert archive.stdout is not None
    extract = subprocess.run(["tar", "-x", "-C", str(destination)], stdin=archive.stdout, check=False)
    archive.stdout.close()
    if archive.wait() != 0 or extract.returncode != 0:
        raise ManifestError(f"could not export {ref.name} ({ref.sha}) from {repo_root}")
    return destination


_UV_SYNC = BuildStep("uv-sync", ("uv", "sync", "--frozen", "--group", "dev"))
_SPHINX = BuildStep(
    "sphinx", ("uv", "run", "--frozen", "sphinx-build", "-b", "html", "--keep-going", ".", "_build/html"), "docs"
)
_EXPLORER_STEPS = (
    BuildStep("explorer-npm-ci", ("npm", "ci"), "results-explorer"),
    BuildStep("explorer-typecheck", ("npm", "run", "typecheck"), "results-explorer"),
    BuildStep(
        "explorer-data",
        (
            "uv",
            "run",
            "--frozen",
            "--",
            "python",
            "_project/scripts/explorer_publish.py",
            "build",
            "--data-dir",
            "results-data/",
            "--output",
            "results-explorer/public/data/",
        ),
    ),
    BuildStep(
        "explorer-snapshot-invariants",
        (
            "uv",
            "run",
            "--frozen",
            "--",
            "python",
            "_project/scripts/results_explorer_snapshot_invariants.py",
            "results-explorer/public/data/results.duckdb",
        ),
    ),
    BuildStep("explorer-build", ("npm", "run", "build"), "results-explorer"),
)


def build_steps_for(kinds: Sequence[str]) -> list[BuildStep]:
    """Ordered, de-duplicated build steps needed to produce the given route kinds."""
    steps: list[BuildStep] = []
    if KIND_DOCS in kinds or KIND_BLOG in kinds or KIND_EXPLORER in kinds:
        steps.append(_UV_SYNC)
    if KIND_DOCS in kinds or KIND_BLOG in kinds:
        steps.append(_SPHINX)
    if KIND_EXPLORER in kinds:
        steps.extend(_EXPLORER_STEPS)
    return steps


def _run_command(argv: Sequence[str], cwd: Path, env: Mapping[str, str]) -> None:
    subprocess.run(list(argv), cwd=cwd, env=dict(env), check=True)


def _step_env(work_dir: Path, ref: ResolvedRef, isolate_envs: bool) -> dict[str, str]:
    env = dict(os.environ)
    if isolate_envs:
        # Each pinned commit owns its lockfile, so it gets its own environment
        # instead of re-syncing one shared environment between refs.
        env["UV_PROJECT_ENVIRONMENT"] = str(work_dir / "venvs" / ref.name)
    return env


def _walk_files(root: Path, ignore: IgnorePattern | None) -> list[tuple[Path, str]]:
    found: list[tuple[Path, str]] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        if ignore is not None:
            skipped = ignore(current, dirnames + filenames)
            dirnames[:] = sorted(name for name in dirnames if name not in skipped)
            filenames = [name for name in filenames if name not in skipped]
        else:
            dirnames.sort()
        for name in sorted(filenames):
            source = current_path / name
            if source.is_symlink():
                raise RouteOwnershipError(f"refusing symlink in route source: {source}")
            found.append((source, source.relative_to(root).as_posix()))
        for name in dirnames:
            if (current_path / name).is_symlink():
                raise RouteOwnershipError(f"refusing symlinked directory in route source: {current_path / name}")
    return found


def _mount_rel(mount: str) -> str:
    return mount.strip("/")


def _join_rel(prefix: str, rel: str) -> str:
    return f"{prefix}/{rel}" if prefix else rel


def _claim_and_copy(
    assembly: ManifestAssembly,
    route: Route,
    source_root: Path,
    dest_prefix: str,
    ignore: IgnorePattern | None = None,
) -> int:
    copied = 0
    for source, rel in _walk_files(source_root, ignore):
        dest_rel = _join_rel(dest_prefix, rel)
        owner = assembly.file_owners.get(dest_rel)
        if owner is not None:
            raise RouteOwnershipError(f"path /{dest_rel} is written by both route {owner!r} and route {route.id!r}")
        destination = assembly.site_dir / dest_rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        assembly.file_owners[dest_rel] = route.id
        copied += 1
    return copied


def _claim_bytes(assembly: ManifestAssembly, route: Route, dest_rel: str, content: bytes) -> None:
    owner = assembly.file_owners.get(dest_rel)
    if owner is not None:
        raise RouteOwnershipError(f"path /{dest_rel} is written by both route {owner!r} and route {route.id!r}")
    destination = assembly.site_dir / dest_rel
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    assembly.file_owners[dest_rel] = route.id


def _require_dir(path: Path, what: str) -> Path:
    if not path.is_dir():
        raise FileNotFoundError(f"{what} is missing: {path}")
    return path


def _copy_route(assembly: ManifestAssembly, route: Route, ref_root: Path) -> int:
    """Copy one route's files from its built ref tree, claiming every output path."""
    prefix = _mount_rel(route.mount)
    docs_html = ref_root / "docs" / "_build" / "html"
    copied = 0
    if route.kind == KIND_LANDING:
        copied += _claim_and_copy(assembly, route, _require_dir(ref_root / "landing", "landing directory"), prefix)
        cname = ref_root / "docs" / "CNAME"
        if route.mount == "/" and cname.is_file():
            _claim_bytes(assembly, route, "CNAME", cname.read_bytes())
            copied += 1
    elif route.kind == KIND_DOCS:
        copied += _claim_and_copy(
            assembly,
            route,
            _require_dir(docs_html, "documentation build"),
            prefix,
            ignore=shutil.ignore_patterns("blog"),
        )
    elif route.kind == KIND_BLOG:
        _require_dir(docs_html, "documentation build")
        copied += _claim_and_copy(assembly, route, _require_dir(docs_html / "blog", "blog build"), prefix)
        # Blog pages resolve their theme assets against the site root.
        static_assets = _require_dir(docs_html / "_static", "documentation static assets")
        copied += _claim_and_copy(assembly, route, static_assets, "_static")
        if (docs_html / "_images").is_dir():
            copied += _claim_and_copy(assembly, route, docs_html / "_images", "_images")
    elif route.kind == KIND_EXPLORER:
        dist = _require_dir(ref_root / "results-explorer" / "dist", "Results Explorer build")
        copied += _claim_and_copy(assembly, route, dist, prefix)
        _claim_bytes(assembly, route, "404.html", RESULTS_FALLBACK.encode("utf-8"))
        copied += 1
    else:  # pragma: no cover - parse_manifest rejects unknown kinds
        raise ManifestError(f"unknown route kind {route.kind!r}")
    return copied


def assemble_from_manifest(
    *,
    repo_root: Path,
    manifest: RouteManifest,
    site_dir: Path,
    work_dir: Path,
    overrides: Mapping[str, str] | None = None,
    runner: Runner = _run_command,
    isolate_envs: bool = True,
    prebuilt_roots: Mapping[str, Path] | None = None,
) -> ManifestAssembly:
    """Build every route from its pinned ref and assemble the Pages tree.

    ``prebuilt_roots`` maps a ref name to an already built tree; it exists so tests
    and local re-runs can skip export and build for that ref.
    """
    repo_root = repo_root.resolve()
    _validate_destination(repo_root, site_dir)
    site_dir = site_dir.resolve()
    work_dir = work_dir.resolve()
    if site_dir == work_dir or site_dir in work_dir.parents or work_dir in site_dir.parents:
        raise ValueError("site output and work directories must not contain each other")

    refs = resolve_refs(repo_root, manifest, overrides)
    if site_dir.exists():
        shutil.rmtree(site_dir)
    site_dir.mkdir(parents=True)
    assembly = ManifestAssembly(site_dir=site_dir, refs=refs)

    for name, ref in refs.items():
        if prebuilt_roots and name in prebuilt_roots:
            assembly.ref_roots[name] = Path(prebuilt_roots[name])
            continue
        root = materialize_ref(repo_root, ref, work_dir / "refs" / f"{name}-{ref.sha[:12]}")
        assembly.ref_roots[name] = root
        kinds = [route.kind for route in manifest.routes if route.ref == name]
        env = _step_env(work_dir, ref, isolate_envs)
        for step in build_steps_for(kinds):
            print(f"[{name}@{ref.sha[:12]}] {step.name}")
            runner(step.argv, root / step.cwd, env)

    for route in manifest.routes:
        ref = refs[route.ref]
        copied = _copy_route(assembly, route, assembly.ref_roots[route.ref])
        assembly.routes.append(RouteAssembly(route=route, ref=ref, files=copied))

    (site_dir / ".nojekyll").touch()
    return assembly


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, required=True, help="destination for the assembled Pages tree")
    parser.add_argument(
        "--prose-only",
        action="store_true",
        help="assemble prose, docs, and blog only without requiring or embedding Results Explorer",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="route manifest (site/routes.yml); build every route from its pinned ref instead of local build output",
    )
    parser.add_argument(
        "--work-dir", type=Path, default=None, help="scratch directory for per-ref exports and builds (manifest mode)"
    )
    parser.add_argument(
        "--ref",
        action="append",
        default=[],
        metavar="NAME=REV",
        help="pin a manifest ref to a tag, branch, or commit instead of resolving it (repeatable)",
    )
    parser.add_argument(
        "--shared-env",
        action="store_true",
        help="do not give each pinned ref its own uv environment (manifest mode)",
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.manifest is None:
        if args.ref or args.work_dir is not None or args.shared_env:
            parser.error("--ref, --work-dir and --shared-env require --manifest")
        assemble_public_site(repo_root=args.repo_root, site_dir=args.site_dir, prose_only=args.prose_only)
        return 0
    if args.prose_only:
        parser.error("--prose-only cannot be combined with --manifest")
    overrides: dict[str, str] = {}
    for item in args.ref:
        name, sep, rev = item.partition("=")
        if not sep or not name or not rev:
            parser.error(f"--ref expects NAME=REV, got {item!r}")
        overrides[name] = rev
    work_dir = args.work_dir or args.site_dir.parent / f"{args.site_dir.name}-work"
    try:
        result = assemble_from_manifest(
            repo_root=args.repo_root,
            manifest=load_manifest(args.manifest),
            site_dir=args.site_dir,
            work_dir=work_dir,
            overrides=overrides,
            isolate_envs=not args.shared_env,
        )
    except (ManifestError, RouteOwnershipError, FileNotFoundError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for item in result.routes:
        print(
            f"route {item.route.id} {item.route.mount} <- {item.ref.name} {item.ref.label} {item.ref.sha} ({item.files} files)"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
