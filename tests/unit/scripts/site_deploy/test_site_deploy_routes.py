from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.assemble_public_site import REPO_ROOT, assemble_public_site, main
from scripts.publication.assembler import PathOwnershipError
from scripts.site_deploy import routes

pytestmark = [pytest.mark.unit, pytest.mark.fast]

MANIFEST = REPO_ROOT / "deploy" / "routes.yml"


def _write(path: Path, content: str = "content") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _checkout(root: Path, label: str, *, explorer: bool, extra_docs: tuple[str, ...] = ()) -> Path:
    _write(root / "docs" / "_build" / "html" / "index.html", f"{label} docs")
    _write(root / "docs" / "_build" / "html" / "guide" / "index.html", f"{label} guide")
    _write(root / "docs" / "_build" / "html" / "blog" / "post.html", f"{label} blog")
    _write(root / "docs" / "_build" / "html" / "_static" / "theme.css", f"{label} css")
    _write(root / "docs" / "_build" / "html" / "_images" / "logo.svg", f"{label} svg")
    for name in extra_docs:
        _write(root / "docs" / "_build" / "html" / name, label)
    _write(root / "docs" / "CNAME", "benchbox.dev\n")
    _write(root / "landing" / "index.html", f"{label} landing")
    _write(root / "landing" / "prompts" / "docs" / "nested.txt", "landing asset in a docs folder")
    if explorer:
        _write(root / "results-explorer" / "package.json", "{}")
        _write(root / "results-explorer" / "dist" / "index.html", f"{label} explorer")
        _write(root / "results-explorer" / "dist" / "data" / "results.duckdb", f"{label} snapshot")
    return root


def _git_init(root: Path) -> str:
    env = ["-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false"]
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), *env, "commit", "-q", "-m", "fixture"], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _read(site: Path, relative: str) -> str:
    return (site / relative).read_text(encoding="utf-8")


def test_committed_manifest_declares_the_decided_routes() -> None:
    manifest = routes.load_manifest(MANIFEST)
    by_path = {route.path: (route.ref, route.builder) for route in manifest.routes}
    assert by_path == {
        "/": ("release", "landing"),
        "/docs/": ("release", "docs"),
        "/docs/dev/": ("trunk", "docs"),
        "/blog/": ("trunk", "blog"),
        "/results/": ("trunk", "explorer"),
    }
    assert manifest.refs == {"release": "release-tag", "trunk": "trunk"}
    assert manifest.root_files_ref == "trunk"


def test_manifest_is_tracked_not_ignored() -> None:
    manifest = subprocess.run(["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "deploy/routes.yml"], check=False)
    assert manifest.returncode == 1
    legacy = subprocess.run(["git", "-C", str(REPO_ROOT), "check-ignore", "-q", "site/index.html"], check=False)
    assert legacy.returncode == 0


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d.update(version=2), "unsupported"),
        (lambda d: d["routes"][0].update(ref="nope"), "unknown ref"),
        (lambda d: d["routes"][0].update(builder="nope"), "unknown builder"),
        (lambda d: d["routes"][0].update(path="docs"), "slash-terminated"),
        (lambda d: d["routes"][1].update(path="/"), "twice"),
        (lambda d: d["refs"]["trunk"].update(kind="branch"), "unsupported kind"),
        (lambda d: d["root_files"].update(files=["secrets.txt"]), "unsupported files"),
        (lambda d: d.update(routes=[]), "no routes"),
    ],
)
def test_manifest_validation_rejects_malformed_input(mutate, message: str) -> None:
    data = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    mutate(data)
    with pytest.raises(routes.RouteManifestError, match=message):
        routes.parse_manifest(data)


def test_routes_mode_mounts_each_route_from_its_own_ref(tmp_path: Path) -> None:
    release = _checkout(tmp_path / "release", "release", explorer=False)
    trunk = _checkout(tmp_path / "trunk", "trunk", explorer=True)
    release_sha = _git_init(release)
    trunk_sha = _git_init(trunk)
    site = tmp_path / "site-build"
    receipt_path = tmp_path / "receipt.json"

    exit_code = main(
        [
            "--routes",
            str(MANIFEST),
            "--ref-root",
            f"release={release}",
            "--ref-root",
            f"trunk={trunk}",
            "--site-dir",
            str(site),
            "--work-dir",
            str(tmp_path / "work"),
            "--receipt-out",
            str(receipt_path),
        ]
    )

    assert exit_code == 0
    assert _read(site, "index.html") == "release landing"
    assert _read(site, "prompts/docs/nested.txt") == "landing asset in a docs folder"
    assert _read(site, "docs/index.html") == "release docs"
    assert _read(site, "docs/guide/index.html") == "release guide"
    assert _read(site, "docs/_static/theme.css") == "release css"
    assert _read(site, "docs/dev/index.html") == "trunk docs"
    assert _read(site, "docs/dev/_static/theme.css") == "trunk css"
    assert _read(site, "blog/post.html") == "trunk blog"
    assert _read(site, "_static/theme.css") == "trunk css"
    assert _read(site, "_images/logo.svg") == "trunk svg"
    assert _read(site, "results/index.html") == "trunk explorer"
    assert _read(site, "results/data/results.duckdb") == "trunk snapshot"
    assert (site / "CNAME").read_text(encoding="utf-8") == "benchbox.dev\n"
    assert (site / ".nojekyll").is_file()
    assert "benchbox.results.redirect" in _read(site, "404.html")

    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    sources = {route["path"]: route["source_sha"] for route in receipt["routes"]}
    assert sources == {
        "/": release_sha,
        "/docs/": release_sha,
        "/docs/dev/": trunk_sha,
        "/blog/": trunk_sha,
        "/results/": trunk_sha,
    }
    assert receipt["refs"]["release"]["kind"] == "release-tag"
    assert len(receipt["tree_sha256"]) == 64
    owners = receipt["file_owners"]
    assert owners["_static/theme.css"].startswith("/blog/")
    assert owners["docs/_static/theme.css"].startswith("/docs/:")
    assert owners["docs/dev/_static/theme.css"].startswith("/docs/dev/:")
    assert len(owners) == receipt["total_files"]


def test_assets_of_the_release_build_never_claim_root_static_paths(tmp_path: Path) -> None:
    release = _checkout(tmp_path / "release", "release", explorer=False)
    trunk = _checkout(tmp_path / "trunk", "trunk", explorer=True)
    manifest = routes.load_manifest(MANIFEST)
    summary = routes.assemble_routes(
        manifest=manifest,
        ref_roots={"release": release, "trunk": trunk},
        site_dir=tmp_path / "out",
        work_dir=tmp_path / "work",
        stage_builder=assemble_public_site,
        resolve_sha=lambda root: root.name,
    )
    static_owners = {lane for path, lane in summary["file_owners"].items() if path.startswith(("_static/", "_images/"))}
    assert static_owners == {"/blog/:_static", "/blog/:_images"}


def test_path_collision_between_release_and_trunk_docs_is_refused(tmp_path: Path) -> None:
    release = _checkout(tmp_path / "release", "release", explorer=False, extra_docs=("dev/index.html",))
    trunk = _checkout(tmp_path / "trunk", "trunk", explorer=True)
    with pytest.raises(PathOwnershipError, match="docs/dev/index.html"):
        routes.assemble_routes(
            manifest=routes.load_manifest(MANIFEST),
            ref_roots={"release": release, "trunk": trunk},
            site_dir=tmp_path / "out",
            work_dir=tmp_path / "work",
            stage_builder=assemble_public_site,
            resolve_sha=lambda root: root.name,
        )


def test_ref_roots_must_match_manifest_refs(tmp_path: Path) -> None:
    trunk = _checkout(tmp_path / "trunk", "trunk", explorer=True)
    with pytest.raises(routes.RouteManifestError, match="do not match"):
        routes.assemble_routes(
            manifest=routes.load_manifest(MANIFEST),
            ref_roots={"trunk": trunk},
            site_dir=tmp_path / "out",
            work_dir=tmp_path / "work",
            stage_builder=assemble_public_site,
        )


def test_release_without_landing_fails_closed_for_the_landing_route(tmp_path: Path) -> None:
    release = _checkout(tmp_path / "release", "release", explorer=False)
    trunk = _checkout(tmp_path / "trunk", "trunk", explorer=True)
    shutil.rmtree(release / "landing")
    with pytest.raises(routes.RouteManifestError, match="needs landing"):
        routes.assemble_routes(
            manifest=routes.load_manifest(MANIFEST),
            ref_roots={"release": release, "trunk": trunk},
            site_dir=tmp_path / "out",
            work_dir=tmp_path / "work",
            stage_builder=assemble_public_site,
            resolve_sha=lambda root: root.name,
        )


def test_routes_mode_refuses_the_manifest_directory(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="refuses --site-dir site"):
        main(
            [
                "--routes",
                str(MANIFEST),
                "--ref-root",
                "release=x",
                "--ref-root",
                "trunk=y",
                "--site-dir",
                str(REPO_ROOT / "site"),
            ]
        )


@pytest.mark.parametrize("flag", [["--prose-only"], ["--repo-root", "elsewhere"]])
def test_routes_mode_rejects_single_ref_flags(tmp_path: Path, flag: list[str]) -> None:
    with pytest.raises(SystemExit, match="rejects --prose-only and --repo-root"):
        main(
            [
                "--routes",
                str(MANIFEST),
                "--ref-root",
                "release=x",
                "--ref-root",
                "trunk=y",
                "--site-dir",
                str(tmp_path / "out"),
                *flag,
            ]
        )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/", "release"),
        ("/index.html", "release"),
        ("/docs/index.html", "release"),
        ("/docs", "release"),
        ("/docs/dev/index.html", "trunk"),
        ("/docs/dev/x.html#frag", "trunk"),
        ("/blog/post/", "trunk"),
        ("/results/data/results.duckdb", "trunk"),
        ("/_static/site.css", "trunk"),
        ("/_images/a.png", "trunk"),
        ("/404.html", "trunk"),
        ("/CNAME", "trunk"),
        ("/usage/x.html", "release"),
    ],
)
def test_ownership_is_derived_from_the_manifest(path: str, expected: str) -> None:
    manifest = routes.load_manifest(MANIFEST)
    assert routes.owner_ref(manifest, path) == expected
    assert routes.is_trunk_owned(manifest, path) is (expected == "trunk")
