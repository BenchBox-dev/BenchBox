"""Plan, prepare, and finalize: pinned inputs in, a receipt bound to the assembled bytes out."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import assemble_public_site as asm
from scripts.site_deploy import generation as g, pipeline as p, probe, receipt as r
from tests.unit.scripts.site_deploy.helpers import commit_files, git

pytestmark = [pytest.mark.unit, pytest.mark.fast]

PROSE_MANIFEST = asm.parse_manifest(
    {
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
        ],
    }
)


def fake_runner(argv, cwd: Path, env) -> None:
    if "sphinx-build" not in argv:
        return
    tree = cwd.parent
    marker = (tree / "marker.txt").read_text()
    extra = (tree / "docs" / "blog-link.txt").read_text() if (tree / "docs" / "blog-link.txt").exists() else ""
    html = tree / "docs" / "_build" / "html"
    (html / "blog").mkdir(parents=True)
    (html / "_static").mkdir()
    (html / "index.html").write_text(f"<html>docs {marker}</html>", encoding="utf-8")
    (html / "blog" / "index.html").write_text(f"<html>blog {marker} {extra}</html>", encoding="utf-8")
    (html / "_static" / "theme.css").write_text("body{}", encoding="utf-8")


@pytest.fixture
def history(repo: Path) -> dict[str, str]:
    release = commit_files(
        repo,
        {
            "marker.txt": "release",
            "landing/index.html": '<a href="/docs/">docs</a><a href="/blog/">blog</a>',
            "docs/CNAME": "benchbox.dev\n",
        },
        "release",
    )
    git(repo, "tag", "v0.4.1")
    trunk = commit_files(repo, {"marker.txt": "trunk"}, "trunk")
    return {"release": release, "trunk": trunk}


def runs_for(*shas: str, conclusion: str = "success") -> list[dict]:
    return [
        {
            "id": 1000 + i,
            "head_sha": sha,
            "head_branch": f"gh-readonly-queue/develop/pr-{i}-{sha}",
            "event": "merge_group",
            "path": ".github/workflows/ci.yml",
            "status": "completed",
            "conclusion": conclusion,
            "created_at": f"2026-09-29T10:0{i}:00Z",
            "html_url": f"https://example.invalid/{i}",
        }
        for i, sha in enumerate(shas)
    ]


def api_with(runs: list[dict]):
    def api(path: str):
        if "head_sha=" in path:
            wanted = path.split("head_sha=")[1].split("&")[0]
            return {"workflow_runs": [run for run in runs if run["head_sha"] == wanted]}
        return {"workflow_runs": runs}

    return api


def make_plan(repo: Path, **kwargs) -> p.Plan:
    defaults = {
        "repo_root": repo,
        "manifest": PROSE_MANIFEST,
        "previous": None,
        "trunk_ref": "develop",
        "corpus_ref": "develop",
        "identity_mode": p.IDENTITY_SKIP,
    }
    defaults.update(kwargs)
    return p.make_plan(**defaults)


class TestPlan:
    def test_pins_trunk_release_and_corpus(self, repo: Path, history: dict[str, str]) -> None:
        plan = make_plan(repo)
        assert plan.generation.trunk_sha == history["trunk"]
        assert plan.generation.release_tag == "v0.4.1"
        assert plan.generation.corpus_sha == history["trunk"]
        assert plan.generation.trunk_index == 2
        assert plan.refs["release"].sha == history["release"]
        assert plan.decision.verdict is g.Verdict.FIRST_DEPLOY

    def test_selects_the_newest_trunk_commit_that_passed_the_merge_queue(
        self, repo: Path, history: dict[str, str]
    ) -> None:
        # trunk tip has only a red run; the release commit is the newest green one
        runs = runs_for(history["trunk"], conclusion="failure") + runs_for(history["release"])
        plan = make_plan(repo, identity_mode=p.IDENTITY_CI, api=api_with(runs), repo_slug="o/r")
        assert plan.generation.trunk_sha == history["release"]
        assert plan.identity["trunk"]["mode"] == "ci"
        assert plan.identity["trunk"]["eligible"] is True

    def test_no_eligible_commit_stops_the_run(self, repo: Path, history: dict[str, str]) -> None:
        with pytest.raises(p.PipelineError, match="no trunk commit"):
            make_plan(repo, identity_mode=p.IDENTITY_CI, api=api_with([]), repo_slug="o/r")

    def test_pinned_commit_without_a_green_run_is_refused(self, repo: Path, history: dict[str, str]) -> None:
        runs = runs_for(history["release"])
        with pytest.raises(p.PipelineError, match="not an eligible candidate"):
            make_plan(
                repo,
                identity_mode=p.IDENTITY_CI,
                api=api_with(runs),
                repo_slug="o/r",
                trunk_sha=history["trunk"],
            )

    def test_release_tag_must_have_passed_the_merge_queue_too(self, repo: Path, history: dict[str, str]) -> None:
        runs = runs_for(history["trunk"])  # green trunk, but the tagged commit has no run
        with pytest.raises(p.PipelineError, match="release tag v0.4.1 is not an eligible candidate"):
            make_plan(repo, identity_mode=p.IDENTITY_CI, api=api_with(runs), repo_slug="o/r")

    def test_release_tag_ahead_of_the_trunk_pin_is_refused(self, repo: Path, history: dict[str, str]) -> None:
        git(repo, "tag", "v0.5.0")  # tags the trunk commit
        runs = runs_for(history["release"], history["trunk"])
        with pytest.raises(p.PipelineError, match="not on trunk at or before"):
            make_plan(
                repo,
                identity_mode=p.IDENTITY_CI,
                api=api_with(runs),
                repo_slug="o/r",
                trunk_sha=history["release"],
                release_tag="v0.5.0",
            )

    def test_release_tag_off_trunk_is_refused(self, repo: Path, history: dict[str, str]) -> None:
        git(repo, "checkout", "-q", "-b", "release", history["release"])
        stray = commit_files(repo, {"marker.txt": "stray"}, "stray")
        git(repo, "tag", "v0.4.9")
        git(repo, "checkout", "-q", "develop")
        runs = runs_for(history["trunk"], stray)
        with pytest.raises(p.PipelineError, match="not on trunk"):
            make_plan(repo, identity_mode=p.IDENTITY_CI, api=api_with(runs), repo_slug="o/r", release_tag="v0.4.9")

    def test_identity_checks_need_api_access(self, repo: Path, history: dict[str, str]) -> None:
        with pytest.raises(p.PipelineError, match="API access"):
            make_plan(repo, identity_mode=p.IDENTITY_CI, api=None)

    def test_decision_uses_the_previous_receipt(self, repo: Path, history: dict[str, str], tmp_path: Path) -> None:
        first = make_plan(repo)
        previous = candidate_from(first, tmp_path)
        again = make_plan(repo, previous=previous)
        assert again.decision.verdict is g.Verdict.NOOP

        # An older pin than what is deployed is refused.
        older = make_plan(repo, previous=previous, trunk_sha=history["release"])
        assert older.decision.verdict is g.Verdict.REFUSE

    def test_previous_quarantine_blocks_the_candidate(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        older_pin = make_plan(repo, trunk_sha=history["release"])
        previous = candidate_from(older_pin, tmp_path)
        previous["quarantine"] = {"trunk_shas": [history["trunk"]], "release_tags": []}
        blocked = make_plan(repo, previous=previous)
        assert blocked.decision.verdict is g.Verdict.REFUSE
        assert "quarantined" in blocked.decision.reasons[0]

    def test_unknown_identity_mode_is_rejected(self, repo: Path, history: dict[str, str]) -> None:
        with pytest.raises(p.PipelineError):
            make_plan(repo, identity_mode="trust-me")


def candidate_from(plan: p.Plan, tmp_path: Path, *, target: str = "preview") -> dict:
    """A finalized-looking previous receipt for the plan's generation."""
    site = tmp_path / f"prev-{plan.generation.trunk_sha[:6]}"
    (site / "docs").mkdir(parents=True)
    (site / "index.html").write_text("x", encoding="utf-8")
    (site / "docs" / "index.html").write_text("x", encoding="utf-8")
    identity = r.tree_identity(site)
    return r.new_receipt(
        receipt_id="site-deploy-1-1",
        operation="deploy",
        target=target,
        generation=plan.generation,
        routes=[{"id": "landing"}],
        identity_evidence={},
        identity=identity,
        archive_sha256="a" * 64,
        explorer={},
        gates=[],
        checksums=r.build_probe_set(site, identity, ["/", "/docs/"]),
        quarantine=(set(), set()),
        workflow={"run_id": "1"},
        created_at="t",
    )


class TestPrepare:
    def prepare(self, repo: Path, tmp_path: Path, plan: p.Plan, **kwargs) -> p.Prepared:
        return p.prepare_candidate(
            repo_root=repo,
            manifest=PROSE_MANIFEST,
            plan=plan,
            out_dir=tmp_path / "out",
            work_dir=tmp_path / "work",
            target=kwargs.pop("target", "preview"),
            runner=fake_runner,
            workflow={"run_id": "42", "run_attempt": "1"},
            **kwargs,
        )

    def test_receipt_records_sources_corpus_and_artifact_digest(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        plan = make_plan(repo)
        prepared = self.prepare(repo, tmp_path, plan)
        assert prepared.ok, [g.detail for g in prepared.gates if not g.ok]
        receipt = prepared.receipt

        assert receipt["generation"]["trunk_sha"] == history["trunk"]
        assert receipt["generation"]["corpus_sha"] == history["trunk"]
        routes = {route["id"]: route for route in receipt["routes"]}
        assert routes["landing"]["source_sha"] == history["release"] and routes["landing"]["label"] == "v0.4.1"
        assert routes["docs"]["source_sha"] == history["release"]
        assert routes["docs-dev"]["source_sha"] == history["trunk"]
        assert routes["blog"]["source_sha"] == history["trunk"]

        assert receipt["artifact"]["sha256"] == r.sha256_file(prepared.archive)
        assert receipt["artifact"]["tree_digest"] == r.tree_identity(prepared.site_dir).tree_digest
        assert (prepared.site_dir / "docs" / "index.html").read_text() == "<html>docs release</html>"
        assert (prepared.site_dir / "docs" / "dev" / "index.html").read_text() == "<html>docs trunk</html>"
        assert receipt["receipt_id"] == "site-deploy-42-1"
        assert receipt["status"] == r.STATUS_CANDIDATE
        assert [gate["name"] for gate in receipt["gates"]] == ["privacy", "cross-route-links"]
        assert r.read_receipt(tmp_path / "out" / "receipt.json") == receipt

    def test_the_archive_is_reproducible_for_the_same_pins(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        first = self.prepare(repo, tmp_path / "one", make_plan(repo))
        second = self.prepare(repo, tmp_path / "two", make_plan(repo))
        assert first.receipt["artifact"]["sha256"] == second.receipt["artifact"]["sha256"]

    def test_dry_run_probes_the_local_server_against_the_receipt(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        prepared = self.prepare(repo, tmp_path, make_plan(repo))
        mounts = [route["mount"] for route in prepared.receipt["routes"]]
        with probe.serve_directory(prepared.site_dir) as base_url:
            summary = probe.probe_once(base_url, tmp_path / "out" / "receipt.json", mounts)
        assert summary["ok"], summary["errors"]
        final = r.finalize_receipt(
            prepared.receipt,
            probes=summary,
            deployment={"confirmed": False, "mode": "local-static-server"},
            observed_at="t",
        )
        assert final["status"] == r.STATUS_PREVIEW_VERIFIED

    def test_a_broken_cross_route_link_fails_the_gate_and_still_writes_evidence(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        commit_files(repo, {"docs/blog-link.txt": '<a href="/docs/only-in-trunk.html">new</a>'}, "link")
        prepared = self.prepare(repo, tmp_path, make_plan(repo))
        assert not prepared.ok
        failed = [gate for gate in prepared.gates if not gate.ok]
        assert [gate.name for gate in failed] == ["cross-route-links"]
        assert "/blog/index.html -> /docs/only-in-trunk.html" in failed[0].detail
        assert (tmp_path / "out" / "receipt.json").is_file()

    def test_production_refuses_skipped_identity_and_skipped_gates(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        with pytest.raises(p.PipelineError, match="identity checks can only be skipped in preview"):
            self.prepare(repo, tmp_path, make_plan(repo), target="production")
        runs = runs_for(history["release"], history["trunk"])
        ci_plan = make_plan(repo, identity_mode=p.IDENTITY_CI, api=api_with(runs), repo_slug="o/r")
        with pytest.raises(p.PipelineError, match="gates can only be skipped in preview"):
            self.prepare(repo, tmp_path, ci_plan, target="production", skip_gates=frozenset({"privacy"}))

    def test_production_with_verified_identity_carries_the_ci_evidence(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        runs = runs_for(history["release"], history["trunk"])
        plan = make_plan(repo, identity_mode=p.IDENTITY_CI, api=api_with(runs), repo_slug="o/r")
        prepared = self.prepare(repo, tmp_path, plan, target="production")
        evidence = prepared.receipt["candidate_identity"]
        assert evidence["trunk"]["run_id"] and evidence["release"]["run_id"]
        assert evidence["trunk"]["mode"] == "ci"

    def test_skipped_gates_are_recorded_as_skipped(self, repo: Path, history: dict[str, str], tmp_path: Path) -> None:
        prepared = self.prepare(repo, tmp_path, make_plan(repo), skip_gates=frozenset({"privacy"}))
        privacy = next(gate for gate in prepared.receipt["gates"] if gate["name"] == "privacy")
        assert "skipped" in privacy["detail"]

    def test_a_crashing_gate_counts_as_failed(
        self, repo: Path, history: dict[str, str], tmp_path: Path, monkeypatch
    ) -> None:
        def boom(_site):
            raise RuntimeError("scanner crashed")

        monkeypatch.setattr(p.gates, "gate_privacy", boom)
        prepared = self.prepare(repo, tmp_path, make_plan(repo))
        assert not prepared.ok
        assert "RuntimeError: scanner crashed" in next(g.detail for g in prepared.gates if g.name == "privacy")

    def test_previous_quarantine_is_carried_into_the_new_receipt(
        self, repo: Path, history: dict[str, str], tmp_path: Path
    ) -> None:
        older = make_plan(repo, trunk_sha=history["release"])
        previous = candidate_from(older, tmp_path)
        previous["quarantine"] = {"trunk_shas": ["e" * 40], "release_tags": ["v0.3.0"]}
        plan = make_plan(repo, previous=previous)
        prepared = self.prepare(repo, tmp_path, plan, previous_receipt=previous)
        assert prepared.receipt["quarantine"] == {"trunk_shas": ["e" * 40], "release_tags": ["v0.3.0"]}


class TestExplorerGateWiring:
    """The Explorer gates run only when the manifest has an Explorer route."""

    def test_versions_digest_and_previous_transition_are_wired(
        self, repo: Path, history: dict[str, str], tmp_path: Path, monkeypatch
    ) -> None:
        duckdb = pytest.importorskip("duckdb")
        manifest = asm.parse_manifest(
            {
                "schema_version": 1,
                "refs": {"release": {"kind": "latest-tag"}, "trunk": {"kind": "branch", "branch": "develop"}},
                "routes": [
                    {"id": "landing", "mount": "/", "ref": "release", "kind": "landing"},
                    {"id": "results", "mount": "/results/", "ref": "trunk", "kind": "explorer", "spa": True},
                ],
            }
        )
        commit_files(
            repo,
            {
                "results-explorer/src/db.ts": "const EXPECTED_READ_MODEL_VERSION = 12;\n",
                "results-explorer/package.json": "{}",
            },
            "explorer",
        )

        def write_snapshot(path: Path, version: int) -> Path:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.unlink(missing_ok=True)
            with duckdb.connect(str(path)) as con:
                con.execute("CREATE TABLE metadata (read_model_version INTEGER)")
                con.execute(f"INSERT INTO metadata VALUES ({version})")
            return path

        def runner(argv, cwd: Path, env) -> None:
            if argv[:3] == ("npm", "run", "build"):
                dist = cwd / "dist"
                dist.mkdir(parents=True)
                (dist / "index.html").write_text("<html>explorer</html>", encoding="utf-8")
                write_snapshot(dist / "data" / "results.duckdb", 12)

        stubs = {
            "gate_explorer_compat": lambda site, mount: p.gates.GateResult("explorer-compat", True, "stub"),
            "gate_corpus_bijection": lambda **kw: p.gates.GateResult("corpus-bijection", True, "stub"),
            "gate_validator_parity": lambda **kw: p.gates.GateResult("validator-parity", True, "stub"),
        }
        for name, stub in stubs.items():
            monkeypatch.setattr(p.gates, name, stub)

        plan = make_plan(repo, manifest=manifest)
        rebuilt: list[Path] = []

        def rebuild(trunk_root: Path, scratch: Path) -> Path:
            rebuilt.append(trunk_root)
            return write_snapshot(scratch / "results.duckdb", 12)

        def run(previous):
            return p.prepare_candidate(
                repo_root=repo,
                manifest=manifest,
                plan=plan,
                out_dir=tmp_path / "out",
                work_dir=tmp_path / "work",
                target="preview",
                previous_receipt=previous,
                runner=runner,
                rebuild=rebuild,
                workflow={"run_id": "7"},
            )

        first = run(None)
        assert first.ok, [(g.name, g.detail) for g in first.gates if not g.ok]
        explorer = first.receipt["explorer"]
        assert (explorer["ui_read_model_version"], explorer["snapshot_read_model_version"]) == (12, 12)
        assert explorer["db_canonical_digest"] and explorer["db_sha256"]
        assert rebuilt, "the snapshot must be rebuilt independently for the digest gate"

        # Previous site served snapshot v11 with UI v11: moving straight to UI v12 is refused.
        previous = candidate_from(plan, tmp_path)
        previous["explorer"] = {"ui_read_model_version": 11, "snapshot_read_model_version": 11}
        second = run(previous)
        assert [g.name for g in second.gates if not g.ok] == ["explorer-mixed-versions"]

        # Once the snapshot v12 is live (UI still v11), the UI bump is fine.
        previous["explorer"] = {"ui_read_model_version": 11, "snapshot_read_model_version": 12}
        assert run(previous).ok
