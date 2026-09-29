"""Pre-deploy gates: mixed-version transitions, cross-route links, and the reused publication checks."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.site_deploy import gates as gt

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestMixedVersionTransitions:
    """The UI rejects snapshots older than it expects and only warns about newer ones."""

    def test_first_deployment_only_needs_a_readable_own_pair(self) -> None:
        assert gt.check_mixed_version_transition(None, (11, 11)) == []
        assert gt.check_mixed_version_transition(None, (12, 11))

    def test_unchanged_versions_are_fine(self) -> None:
        assert gt.check_mixed_version_transition((11, 11), (11, 11)) == []

    def test_snapshot_first_bump_is_allowed(self) -> None:
        # New snapshot, old UI: the old UI warns and reads forward-compatibly.
        assert gt.check_mixed_version_transition((11, 11), (11, 12)) == []

    def test_ui_bump_together_with_snapshot_is_refused(self) -> None:
        # Cached v11 snapshots would meet a UI that requires v12.
        problems = gt.check_mixed_version_transition((11, 11), (12, 12))
        assert len(problems) == 1
        assert "Deploy the newer snapshot before the UI" in problems[0]

    def test_ui_bump_after_the_snapshot_landed_is_allowed(self) -> None:
        assert gt.check_mixed_version_transition((11, 12), (12, 12)) == []

    def test_ui_only_rollback_is_allowed(self) -> None:
        # Old UI over the newer snapshot it already tolerates.
        assert gt.check_mixed_version_transition((12, 12), (11, 12)) == []

    def test_snapshot_rollback_with_the_ui_is_refused(self) -> None:
        # Cached v12 UI would meet a rolled-back v11 snapshot.
        problems = gt.check_mixed_version_transition((12, 12), (11, 11))
        assert len(problems) == 1
        assert "Roll the UI back before rolling the snapshot back" in problems[0]

    def test_two_step_rollback_is_the_supported_order(self) -> None:
        assert gt.check_mixed_version_transition((12, 12), (11, 12)) == []
        assert gt.check_mixed_version_transition((11, 12), (11, 11)) == []

    def test_a_ui_newer_than_its_own_snapshot_is_never_waivable(self) -> None:
        assert gt.check_mixed_version_transition((11, 11), (12, 11), waive_cache_window=True)

    def test_waiver_accepts_the_cache_window_pairs_in_both_directions(self) -> None:
        assert gt.check_mixed_version_transition((11, 11), (12, 12), waive_cache_window=True) == []
        assert gt.check_mixed_version_transition((12, 12), (11, 11), waive_cache_window=True) == []

    def test_gate_reports_the_verdict(self) -> None:
        assert gt.gate_mixed_versions((11, 11), (11, 11)).ok
        refused = gt.gate_mixed_versions((11, 11), (12, 12))
        assert not refused.ok and "snapshot" in refused.detail
        assert gt.gate_mixed_versions(None, None).ok

    def test_versions_are_read_from_the_pinned_sources(self, tmp_path: Path) -> None:
        db_ts = tmp_path / "results-explorer" / "src" / "db.ts"
        db_ts.parent.mkdir(parents=True)
        db_ts.write_text("// header\nconst EXPECTED_READ_MODEL_VERSION = 13;\n", encoding="utf-8")
        assert gt.read_ui_read_model_version(tmp_path) == 13
        db_ts.write_text("const OTHER = 1;\n", encoding="utf-8")
        with pytest.raises(ValueError):
            gt.read_ui_read_model_version(tmp_path)

    def test_repository_ui_version_is_readable(self) -> None:
        assert gt.read_ui_read_model_version(gt.REPO_ROOT) >= 11

    def test_snapshot_version_is_read_from_metadata(self, tmp_path: Path) -> None:
        duckdb = pytest.importorskip("duckdb")
        snapshot = tmp_path / "results.duckdb"
        with duckdb.connect(str(snapshot)) as con:
            con.execute("CREATE TABLE metadata (read_model_version INTEGER)")
            con.execute("INSERT INTO metadata VALUES (12)")
        assert gt.read_snapshot_read_model_version(snapshot) == 12


def write(root: Path, rel: str, html: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


MOUNTS = ["/", "/docs/", "/docs/dev/", "/blog/", "/results/"]


@pytest.fixture
def site(tmp_path: Path) -> Path:
    root = tmp_path / "site"
    for rel in ("index.html", "docs/index.html", "docs/dev/index.html", "blog/index.html", "results/index.html"):
        write(root, rel, "<html></html>")
    write(root, "docs/page.html", "<html></html>")
    write(root, "_static/site.css", "body{}")
    return root


class TestCrossRouteLinks:
    def test_working_links_pass(self, site: Path) -> None:
        write(site, "index.html", '<a href="/docs/">docs</a><a href="/blog/">blog</a><a href="/results/">r</a>')
        write(site, "blog/index.html", '<a href="../docs/page.html">p</a><link href="/_static/site.css">')
        assert gt.gate_links(site, MOUNTS, ["/results/"]).ok

    def test_broken_cross_route_link_fails(self, site: Path) -> None:
        write(site, "blog/post.html", '<a href="/docs/removed-page.html">gone</a>')
        result = gt.gate_links(site, MOUNTS)
        assert not result.ok
        assert "/blog/post.html -> /docs/removed-page.html" in result.detail

    def test_broken_relative_cross_route_link_fails(self, site: Path) -> None:
        write(site, "blog/post.html", '<a href="../docs/dev/missing.html">gone</a>')
        assert not gt.gate_links(site, MOUNTS).ok

    def test_broken_intra_route_link_is_reported_but_not_gating(self, site: Path) -> None:
        write(site, "docs/broken.html", '<a href="missing.html">gone</a>')
        result = gt.gate_links(site, MOUNTS)
        assert result.ok
        assert result.data["intra"] == ["/docs/broken.html -> missing.html"]

    def test_landing_link_into_docs_is_cross_route(self, site: Path) -> None:
        write(site, "index.html", '<a href="/docs/nope.html">gone</a>')
        assert not gt.gate_links(site, MOUNTS).ok

    def test_deep_link_into_an_spa_route_resolves_through_its_fallback(self, site: Path) -> None:
        write(site, "docs/page.html", '<a href="/results/compare/abc">compare</a>')
        assert gt.gate_links(site, MOUNTS, ["/results/"]).ok
        assert not gt.gate_links(site, MOUNTS, []).ok

    def test_directory_and_index_forms_resolve(self, site: Path) -> None:
        write(site, "index.html", '<a href="/docs">a</a><a href="/docs/index.html">b</a><a href="/docs/dev/">c</a>')
        assert gt.gate_links(site, MOUNTS).ok

    def test_external_anchor_mailto_and_data_links_are_ignored(self, site: Path) -> None:
        write(
            site,
            "index.html",
            '<a href="https://example.com/x">e</a><a href="#top">t</a><a href="mailto:a@b.c">m</a>'
            '<a href="//cdn.example/x.js">p</a><img src="data:image/png;base64,AAAA"><a href="/docs/#frag">f</a>',
        )
        assert gt.gate_links(site, MOUNTS).ok

    def test_query_strings_and_fragments_are_stripped(self, site: Path) -> None:
        write(site, "index.html", '<a href="/docs/page.html?x=1#y">ok</a>')
        assert gt.gate_links(site, MOUNTS).ok

    def test_link_that_escapes_the_site_root_is_broken(self, site: Path) -> None:
        write(site, "index.html", '<a href="../../etc/passwd">bad</a>')
        cross, intra = gt.check_links(site, MOUNTS)
        assert cross + intra == ["/index.html -> ../../etc/passwd"]

    def test_script_and_stylesheet_references_are_checked(self, site: Path) -> None:
        write(site, "blog/post.html", '<script src="/_static/missing.js"></script>')
        assert not gt.gate_links(site, MOUNTS).ok

    def test_owning_mount_prefers_the_most_specific_route(self) -> None:
        assert gt.owning_mount("docs/dev/x.html", MOUNTS) == "/docs/dev/"
        assert gt.owning_mount("docs/x.html", MOUNTS) == "/docs/"
        assert gt.owning_mount("_static/x.css", MOUNTS) == "/"
        assert gt.owning_mount("documents/x.html", MOUNTS) == "/"


class TestPrivacyGate:
    def test_clean_site_passes(self, site: Path) -> None:
        assert gt.gate_privacy(site).ok

    def test_leaked_token_fails(self, site: Path) -> None:
        write(site, "docs/leak.html", "token ghp_" + "a" * 36)
        result = gt.gate_privacy(site)
        assert not result.ok and "GitHub Personal Access Token" in result.detail


class TestReusedPublicationChecks:
    def test_bijection_error_becomes_a_failed_gate(self, tmp_path: Path) -> None:
        result = gt.gate_corpus_bijection(
            corpus_sha="f" * 40,
            bundles_dir=tmp_path,
            snapshot=tmp_path / "results.duckdb",
            ledger_seed=tmp_path / "ledger.json",
        )
        assert not result.ok
        assert result.name == "corpus-bijection"

    def test_digest_gate_compares_against_an_independent_rebuild(self, tmp_path: Path) -> None:
        duckdb = pytest.importorskip("duckdb")

        def database(name: str, value: int) -> Path:
            path = tmp_path / name
            with duckdb.connect(str(path)) as con:
                con.execute("CREATE TABLE results (id INTEGER, generated_at VARCHAR)")
                con.execute(f"INSERT INTO results VALUES ({value}, '{name}')")
            return path

        shipped = database("shipped.duckdb", 1)
        same = gt.gate_db_digest(shipped, lambda: database("rebuilt.duckdb", 1))
        assert same.ok and same.data["digest"]
        different = gt.gate_db_digest(shipped, lambda: database("other.duckdb", 2))
        assert not different.ok

    def test_load_publication_script_is_cached_and_rejects_unknown_names(self) -> None:
        first = gt.load_publication_script("verify_live")
        assert gt.load_publication_script("verify_live") is first
        with pytest.raises((ImportError, FileNotFoundError)):
            gt.load_publication_script("does_not_exist")
