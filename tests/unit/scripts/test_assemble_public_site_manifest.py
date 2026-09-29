"""Route-manifest assembly builds every route from the commit its ref pins."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from scripts import assemble_public_site as asm
from scripts.assemble_public_site import (
    ManifestError,
    RouteOwnershipError,
    assemble_from_manifest,
    build_steps_for,
    load_manifest,
    parse_manifest,
    resolve_refs,
)
from tests.unit.scripts.site_deploy.helpers import commit_files, git

pytestmark = [pytest.mark.unit, pytest.mark.fast]

MANIFEST = {
    "schema_version": 1,
    "refs": {
        "release": {"kind": "latest-tag", "pattern": "v[0-9]*.[0-9]*.[0-9]*"},
        "trunk": {"kind": "branch", "branch": "develop"},
    },
    "routes": [
        {"id": "landing", "mount": "/", "ref": "release", "kind": "landing"},
        {"id": "docs", "mount": "/docs/", "ref": "release", "kind": "docs"},
        {"id": "docs-dev", "mount": "/docs/dev/", "ref": "trunk", "kind": "docs"},
        {"id": "blog", "mount": "/blog/", "ref": "trunk", "kind": "blog"},
        {"id": "results", "mount": "/results/", "ref": "trunk", "kind": "explorer", "spa": True},
    ],
}


def manifest(**changes):
    data = {**MANIFEST, **changes}
    return parse_manifest(data)


def fake_runner(argv, cwd: Path, env) -> None:
    """Stand in for the Sphinx, npm, and Explorer build steps."""
    tree = cwd if cwd.name != "docs" and cwd.name != "results-explorer" else cwd.parent
    marker = (tree / "marker.txt").read_text() if (tree / "marker.txt").exists() else "none"
    if "sphinx-build" in argv:
        html = tree / "docs" / "_build" / "html"
        (html / "blog").mkdir(parents=True)
        (html / "_static").mkdir()
        (html / "index.html").write_text(f"docs {marker}", encoding="utf-8")
        (html / "blog" / "index.html").write_text(f"blog {marker}", encoding="utf-8")
        (html / "_static" / "theme.css").write_text(f"css {marker}", encoding="utf-8")
    elif argv[:3] == ("npm", "run", "build"):
        dist = tree / "results-explorer" / "dist"
        (dist / "data").mkdir(parents=True)
        (dist / "index.html").write_text(f"explorer {marker}", encoding="utf-8")
        (dist / "data" / "results.duckdb").write_text(f"db {marker}", encoding="utf-8")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "develop")
    return root


@pytest.fixture
def released_repo(repo: Path) -> Path:
    commit_files(
        repo,
        {
            "marker.txt": "release",
            "landing/index.html": "landing release",
            "docs/CNAME": "benchbox.dev\n",
            "results-explorer/package.json": "{}",
        },
    )
    git(repo, "tag", "v0.4.1")
    git(repo, "tag", "v0.4.2-rc1")  # pre-releases never become "latest"
    commit_files(repo, {"marker.txt": "trunk", "landing/index.html": "landing trunk"})
    return repo


class TestManifestParsing:
    def test_repository_manifest_is_valid(self) -> None:
        loaded = load_manifest(asm.REPO_ROOT / "site" / "routes.yml")
        mounts = {route.id: route.mount for route in loaded.routes}
        assert mounts == {
            "landing": "/",
            "docs": "/docs/",
            "docs-dev": "/docs/dev/",
            "blog": "/blog/",
            "results": "/results/",
        }
        refs = {route.id: route.ref for route in loaded.routes}
        assert refs["landing"] == refs["docs"] == "release"
        assert refs["docs-dev"] == refs["blog"] == refs["results"] == "trunk"

    def test_mounts_are_normalized_to_directory_form(self) -> None:
        routes = MANIFEST["routes"][:1] + [{"id": "extra", "mount": "/extra", "ref": "trunk", "kind": "blog"}]
        assert [r.mount for r in manifest(routes=routes).routes] == ["/", "/extra/"]

    @pytest.mark.parametrize(
        ("changes", "message"),
        [
            ({"schema_version": 2}, "schema_version"),
            ({"refs": {}}, "refs"),
            ({"routes": []}, "routes"),
            ({"routes": [{"id": "docs", "mount": "/docs/", "ref": "release", "kind": "docs"}]}, "landing route at '/'"),
            (
                {
                    "routes": MANIFEST["routes"][:1]
                    + [{"id": "landing", "mount": "/x/", "ref": "release", "kind": "docs"}]
                },
                "duplicate route id",
            ),
            (
                {"routes": MANIFEST["routes"][:1] + [{"id": "other", "mount": "/", "ref": "release", "kind": "docs"}]},
                "duplicate route mount",
            ),
            (
                {"routes": MANIFEST["routes"][:1] + [{"id": "x", "mount": "/x/", "ref": "nope", "kind": "docs"}]},
                "unknown ref",
            ),
            (
                {"routes": MANIFEST["routes"][:1] + [{"id": "x", "mount": "/x/", "ref": "trunk", "kind": "wasm"}]},
                "unknown kind",
            ),
            (
                {"routes": MANIFEST["routes"][:1] + [{"id": "x", "mount": "x/", "ref": "trunk", "kind": "docs"}]},
                "absolute path",
            ),
            (
                {"routes": MANIFEST["routes"][:1] + [{"id": "x", "mount": "/a/../b/", "ref": "trunk", "kind": "docs"}]},
                "clean path",
            ),
            (
                {"routes": MANIFEST["routes"][:1] + [{"id": "X", "mount": "/x/", "ref": "trunk", "kind": "docs"}]},
                "invalid route id",
            ),
        ],
    )
    def test_malformed_manifests_are_rejected(self, changes: dict, message: str) -> None:
        with pytest.raises(ManifestError, match=message):
            manifest(**changes)

    def test_unreadable_or_invalid_yaml_is_a_manifest_error(self, tmp_path: Path) -> None:
        with pytest.raises(ManifestError):
            load_manifest(tmp_path / "missing.yml")
        bad = tmp_path / "bad.yml"
        bad.write_text("routes: [unclosed", encoding="utf-8")
        with pytest.raises(ManifestError):
            load_manifest(bad)


class TestRefResolution:
    def test_release_is_the_latest_final_tag_and_trunk_is_the_branch_tip(self, released_repo: Path) -> None:
        refs = resolve_refs(released_repo, manifest())
        assert refs["release"].label == "v0.4.1"
        assert refs["release"].sha == git(released_repo, "rev-parse", "refs/tags/v0.4.1^{commit}")
        assert refs["trunk"].sha == git(released_repo, "rev-parse", "develop")
        assert refs["release"].sha != refs["trunk"].sha

    def test_highest_version_wins_numerically(self, released_repo: Path) -> None:
        commit_files(released_repo, {"marker.txt": "later"})
        git(released_repo, "tag", "v0.10.0")
        git(released_repo, "tag", "v0.9.0")
        assert resolve_refs(released_repo, manifest())["release"].label == "v0.10.0"

    def test_overrides_pin_a_tag_or_a_commit(self, released_repo: Path) -> None:
        first = git(released_repo, "rev-parse", "v0.4.1^{commit}")
        pinned = resolve_refs(released_repo, manifest(), {"trunk": first, "release": "v0.4.1"})
        assert pinned["trunk"].sha == first

    @pytest.mark.parametrize(
        "overrides",
        [{"release": "main"}, {"release": "v9.9.9"}, {"trunk": "f" * 40}, {"other": "x"}],
    )
    def test_bad_overrides_are_rejected(self, released_repo: Path, overrides: dict) -> None:
        with pytest.raises(ManifestError):
            resolve_refs(released_repo, manifest(), overrides)

    def test_missing_release_tag_is_an_error(self, repo: Path) -> None:
        commit_files(repo, {"f": "1"})
        with pytest.raises(ManifestError, match="no release tag"):
            resolve_refs(repo, manifest())

    def test_remote_tracking_branch_is_preferred_over_the_local_branch(self, released_repo: Path) -> None:
        remote_tip = git(released_repo, "rev-parse", "HEAD~1")
        git(released_repo, "update-ref", "refs/remotes/origin/develop", remote_tip)
        assert resolve_refs(released_repo, manifest())["trunk"].sha == remote_tip


class TestBuildSteps:
    def test_landing_needs_no_build(self) -> None:
        assert build_steps_for(["landing"]) == []

    def test_docs_and_blog_share_one_build(self) -> None:
        names = [s.name for s in build_steps_for(["docs", "blog"])]
        assert names == ["uv-sync", "sphinx"]

    def test_explorer_builds_the_snapshot_then_the_app(self) -> None:
        names = [s.name for s in build_steps_for(["explorer"])]
        assert names == [
            "uv-sync",
            "explorer-npm-ci",
            "explorer-typecheck",
            "explorer-data",
            "explorer-snapshot-invariants",
            "explorer-build",
        ]

    def test_steps_are_frozen_against_the_lockfile(self) -> None:
        for step in build_steps_for(["docs", "explorer"]):
            if step.argv[0] == "uv":
                assert "--frozen" in step.argv


class TestAssembly:
    def assemble(self, repo: Path, tmp_path: Path, **kwargs):
        return assemble_from_manifest(
            repo_root=repo,
            manifest=kwargs.pop("manifest", manifest()),
            site_dir=tmp_path / "site",
            work_dir=tmp_path / "work",
            runner=kwargs.pop("runner", fake_runner),
            **kwargs,
        )

    def test_each_route_comes_from_its_pinned_commit(self, released_repo: Path, tmp_path: Path) -> None:
        result = self.assemble(released_repo, tmp_path)
        site = tmp_path / "site"
        assert (site / "index.html").read_text() == "landing release"
        assert (site / "docs" / "index.html").read_text() == "docs release"
        assert (site / "docs" / "dev" / "index.html").read_text() == "docs trunk"
        assert (site / "blog" / "index.html").read_text() == "blog trunk"
        assert (site / "_static" / "theme.css").read_text() == "css trunk"
        assert (site / "results" / "index.html").read_text() == "explorer trunk"
        assert (site / "results" / "data" / "results.duckdb").read_text() == "db trunk"
        assert (site / "CNAME").read_text() == "benchbox.dev\n"
        assert (site / "404.html").read_text() == asm.RESULTS_FALLBACK
        assert (site / ".nojekyll").is_file()
        by_id = {item.route.id: item for item in result.routes}
        assert by_id["landing"].ref.label == "v0.4.1" and by_id["blog"].ref.label == "develop"
        assert by_id["docs"].ref.sha != by_id["docs-dev"].ref.sha

    def test_blog_is_not_duplicated_under_docs(self, released_repo: Path, tmp_path: Path) -> None:
        self.assemble(released_repo, tmp_path)
        assert not (tmp_path / "site" / "docs" / "blog").exists()
        assert not (tmp_path / "site" / "docs" / "dev" / "blog").exists()

    def test_each_ref_is_exported_and_built_once(self, released_repo: Path, tmp_path: Path) -> None:
        calls: list[tuple[str, ...]] = []

        def recording(argv, cwd, env) -> None:
            calls.append(tuple(argv))
            fake_runner(argv, cwd, env)

        self.assemble(released_repo, tmp_path, runner=recording)
        assert sum(1 for c in calls if "sphinx-build" in c) == 2  # release + trunk, not per route
        assert sum(1 for c in calls if c[:2] == ("npm", "ci")) == 1  # trunk only

    def test_each_ref_gets_its_own_python_environment(self, released_repo: Path, tmp_path: Path) -> None:
        seen: set[str] = set()

        def recording(argv, cwd, env) -> None:
            seen.add(env["UV_PROJECT_ENVIRONMENT"])
            fake_runner(argv, cwd, env)

        self.assemble(released_repo, tmp_path, runner=recording)
        assert {Path(p).name for p in seen} == {"release", "trunk"}

    def test_explicit_pins_override_resolution(self, released_repo: Path, tmp_path: Path) -> None:
        first = git(released_repo, "rev-parse", "v0.4.1^{commit}")
        result = self.assemble(released_repo, tmp_path, overrides={"trunk": first})
        assert (tmp_path / "site" / "docs" / "dev" / "index.html").read_text() == "docs release"
        assert result.refs["trunk"].sha == first

    def test_two_routes_may_not_write_the_same_path(self, released_repo: Path, tmp_path: Path) -> None:
        clash = manifest(
            routes=MANIFEST["routes"][:2]
            + [{"id": "blog-a", "mount": "/blog/", "ref": "trunk", "kind": "blog"}]
            + [{"id": "blog-b", "mount": "/notes/", "ref": "trunk", "kind": "blog"}]
        )
        with pytest.raises(RouteOwnershipError, match="_static"):
            self.assemble(released_repo, tmp_path, manifest=clash)

    def test_a_route_may_not_shadow_another_routes_file(self, released_repo: Path, tmp_path: Path) -> None:
        commit_files(released_repo, {"landing/docs/index.html": "shadow"})
        git(released_repo, "tag", "v0.4.3")
        with pytest.raises(RouteOwnershipError, match=r"/docs/index.html"):
            self.assemble(released_repo, tmp_path)

    def test_symlinks_in_a_pinned_tree_are_refused(self, released_repo: Path, tmp_path: Path) -> None:
        (released_repo / "landing" / "leak").symlink_to("/etc/hostname")
        git(released_repo, "add", "-A")
        git(released_repo, "commit", "-q", "-m", "link")
        git(released_repo, "tag", "v0.4.3")
        with pytest.raises(RouteOwnershipError, match="symlink"):
            self.assemble(released_repo, tmp_path)

    def test_missing_build_output_is_reported(self, released_repo: Path, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="documentation build is missing"):
            self.assemble(released_repo, tmp_path, runner=lambda *_: None)

    def test_a_failing_build_step_stops_assembly(self, released_repo: Path, tmp_path: Path) -> None:
        def failing(argv, cwd, env) -> None:
            raise subprocess.CalledProcessError(1, argv)

        with pytest.raises(subprocess.CalledProcessError):
            self.assemble(released_repo, tmp_path, runner=failing)

    def test_site_and_work_directories_may_not_nest(self, released_repo: Path, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="must not contain each other"):
            assemble_from_manifest(
                repo_root=released_repo,
                manifest=manifest(),
                site_dir=tmp_path / "site",
                work_dir=tmp_path / "site" / "work",
                runner=fake_runner,
            )

    def test_unsafe_output_directories_are_refused(self, released_repo: Path, tmp_path: Path) -> None:
        with pytest.raises(ValueError, match="unsafe site output"):
            assemble_from_manifest(
                repo_root=released_repo,
                manifest=manifest(),
                site_dir=Path("/"),
                work_dir=tmp_path / "work",
                runner=fake_runner,
            )

    def test_export_contains_no_git_metadata(self, released_repo: Path, tmp_path: Path) -> None:
        result = self.assemble(released_repo, tmp_path)
        assert not (result.ref_roots["release"] / ".git").exists()


class TestCommandLine:
    def test_manifest_mode_reports_each_route(self, released_repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
        manifest_path = tmp_path / "routes.yml"
        manifest_path.write_text(yaml.safe_dump(MANIFEST), encoding="utf-8")
        monkeypatch.setattr(asm, "_run_command", fake_runner)
        monkeypatch.setattr(
            asm, "assemble_from_manifest", lambda **kw: assemble_from_manifest(**{**kw, "runner": fake_runner})
        )
        code = asm.main(
            [
                "--manifest",
                str(manifest_path),
                "--site-dir",
                str(tmp_path / "site"),
                "--work-dir",
                str(tmp_path / "work"),
                "--repo-root",
                str(released_repo),
            ]
        )
        assert code == 0
        out = capsys.readouterr().out
        assert "route landing / <- release v0.4.1" in out and "route blog /blog/ <- trunk develop" in out

    def test_failures_exit_nonzero_without_a_traceback(self, tmp_path: Path, capsys) -> None:
        code = asm.main(["--manifest", str(tmp_path / "missing.yml"), "--site-dir", str(tmp_path / "site")])
        assert code == 1
        assert "ERROR" in capsys.readouterr().err

    def test_manifest_only_options_require_a_manifest(self, tmp_path: Path) -> None:
        with pytest.raises(SystemExit):
            asm.main(["--site-dir", str(tmp_path / "site"), "--ref", "trunk=develop"])
        with pytest.raises(SystemExit):
            asm.main(["--manifest", "x.yml", "--site-dir", str(tmp_path / "site"), "--prose-only"])
        with pytest.raises(SystemExit):
            asm.main(["--manifest", "x.yml", "--site-dir", str(tmp_path / "site"), "--ref", "broken"])
