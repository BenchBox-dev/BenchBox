#!/usr/bin/env python3

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path

CLI_DESCRIPTION = "Assemble the exact directory tree published by the documentation workflow."

REPO_ROOT = Path(__file__).resolve().parents[1]
ASTRO_DIST = Path("website") / "dist"

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

    if not prose_only:
        cname = repo_root / "docs" / "CNAME"
        if cname.is_file():
            shutil.copy2(cname, site_dir / "CNAME")
        (site_dir / ".nojekyll").touch()
    else:
        (site_dir / ".nojekyll").touch()

    if not prose_only:
        explorer_package = repo_root / "results-explorer" / "package.json"
        explorer_dist = repo_root / "results-explorer" / "dist"
        if explorer_package.is_file() and not explorer_dist.is_dir():
            raise FileNotFoundError(f"Results Explorer build is missing: {explorer_dist}")
        if explorer_dist.is_dir():
            _copy_tree(explorer_dist, site_dir / "results")
            (site_dir / "404.html").write_text(RESULTS_FALLBACK, encoding="utf-8")


def assemble_astro_stage(*, repo_root: Path, site_dir: Path, prose_only: bool = False) -> None:
    del prose_only
    repo_root = repo_root.resolve()
    _validate_destination(repo_root, site_dir)
    dist = repo_root / ASTRO_DIST
    if not (dist / "index.html").is_file():
        raise FileNotFoundError(f"Astro build is missing: {dist}; run make site-build in {repo_root}")
    if site_dir.exists():
        shutil.rmtree(site_dir)
    _copy_tree(dist, site_dir)


STAGE_BUILDERS: dict[str, Callable[..., None]] = {"sphinx": assemble_public_site, "astro": assemble_astro_stage}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument("--site-dir", type=Path, required=True, help="destination for the assembled Pages tree")
    parser.add_argument(
        "--prose-only",
        action="store_true",
        help="assemble prose, docs, and blog only without requiring or embedding Results Explorer",
    )
    parser.add_argument("--repo-root", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--routes", type=Path, help="assemble per-route trees from this routes.yml")
    parser.add_argument(
        "--ref-root",
        action="append",
        default=[],
        metavar="NAME=DIR",
        help="checkout providing the named ref of the routes manifest",
    )
    parser.add_argument("--receipt-out", type=Path, help="write the route assembly receipt here")
    parser.add_argument("--work-dir", type=Path, help="scratch directory for per-ref stages")
    parser.add_argument(
        "--renderer",
        choices=tuple(STAGE_BUILDERS),
        help="renderer the release ref selects; assembly refuses a value that differs from the selection",
    )
    return parser


def _parse_ref_roots(values: Sequence[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        name, separator, directory = value.partition("=")
        if not separator or not name or not directory:
            raise SystemExit(f"--ref-root expects NAME=DIR, got {value!r}")
        roots[name] = Path(directory)
    return roots


def _assemble_from_routes(args: argparse.Namespace) -> int:
    sys.path.insert(0, str(REPO_ROOT))
    from scripts.site_deploy import renderer as renderer_module
    from scripts.site_deploy.routes import (
        RouteManifestError,
        assemble_routes,
        load_manifest,
        release_ref,
        trunk_ref,
        write_assembly_receipt,
    )

    site_dir = args.site_dir.resolve()
    if site_dir == (REPO_ROOT / "site").resolve():
        raise SystemExit("routes mode refuses --site-dir site, the legacy assembly output")
    _validate_destination(REPO_ROOT, site_dir)
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="site-routes-"))
    ref_roots = _parse_ref_roots(args.ref_root)
    try:
        manifest = load_manifest(args.routes)
        release = ref_roots.get(release_ref(manifest))
        if release is None:
            raise RouteManifestError(f"no --ref-root for the release ref {release_ref(manifest)}")
        trunk = ref_roots.get(trunk_ref(manifest))
        if trunk is None:
            raise RouteManifestError(f"no --ref-root for the trunk ref {trunk_ref(manifest)}")
        selection = renderer_module.require_trunk_ready(
            renderer_module.select_for_commit(manifest.renderer_policy, release, "HEAD"),
            lambda: renderer_module.readiness_at(trunk, "HEAD"),
            f"ref root {trunk}",
        )
        if args.renderer is not None and args.renderer != selection.renderer:
            raise RouteManifestError(
                f"--renderer {args.renderer} differs from the release selection {selection.renderer}: {selection.reason}"
            )
        receipt = assemble_routes(
            manifest=manifest,
            ref_roots=ref_roots,
            site_dir=site_dir,
            work_dir=work_dir.resolve(),
            stage_builder=STAGE_BUILDERS[selection.renderer],
            renderer=selection.renderer,
        )
    except (RouteManifestError, renderer_module.RendererError) as exc:
        raise SystemExit(str(exc)) from exc
    receipt = {**receipt, "renderer_selection": selection.to_dict()}
    if args.receipt_out:
        write_assembly_receipt(args.receipt_out, receipt)
    print(f"assembled {receipt['total_files']} files with {selection.renderer}, tree sha256 {receipt['tree_sha256']}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.routes:
        if args.prose_only or args.repo_root is not None:
            raise SystemExit("routes mode rejects --prose-only and --repo-root; each ref names its own root")
        return _assemble_from_routes(args)
    assemble_public_site(repo_root=args.repo_root or REPO_ROOT, site_dir=args.site_dir, prose_only=args.prose_only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
