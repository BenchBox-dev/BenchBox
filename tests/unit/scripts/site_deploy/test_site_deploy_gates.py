from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from scripts.site_deploy import gates as g

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROUTES = Path(__file__).resolve().parents[4] / "deploy" / "routes.yml"
TRUNK = "a" * 40
OLD_TRUNK = "b" * 40
CORPUS = "1" * 40
OTHER_CORPUS = "2" * 40


class Recorder:
    def __init__(self, failing: tuple[str, ...] = (), outputs: dict[str, str] | None = None) -> None:
        self.commands: list[list[str]] = []
        self.failing = failing
        self.outputs = outputs or {}

    def __call__(self, command: list[str], cwd: Path) -> tuple[int, str]:
        self.commands.append(command)
        script = Path(command[1]).name
        key = f"{script} {command[2]}" if script == "compare_db_digest.py" or script == "site_inventory.py" else script
        if script == "compare_db_digest.py" and command[2] == "digest":
            return 0, self.outputs.get(command[3], "digest-" + Path(command[3]).name)
        if "--write-known-broken" in command:
            Path(command[command.index("--write-known-broken") + 1]).write_text("[]", encoding="utf-8")
        code = 1 if any(name in key for name in self.failing) else 0
        return code, f"{key} output"

    def scripts(self) -> list[str]:
        return [Path(command[1]).name for command in self.commands]


def _site(tmp_path: Path, ui_snapshot: int = 11) -> Path:
    site = tmp_path / "site"
    (site / "results" / "data").mkdir(parents=True, exist_ok=True)
    (site / "results" / "data" / "results.duckdb").unlink(missing_ok=True)
    with duckdb.connect(str(site / "results" / "data" / "results.duckdb")) as connection:
        connection.execute("CREATE TABLE metadata(read_model_version INTEGER)")
        connection.execute("INSERT INTO metadata VALUES (?)", [ui_snapshot])
    return site


def _repo(tmp_path: Path, ui: int = 11) -> Path:
    repo = tmp_path / "repo"
    (repo / "results-explorer" / "src").mkdir(parents=True, exist_ok=True)
    (repo / "results-explorer" / "src" / "db.ts").write_text(
        f"const EXPECTED_READ_MODEL_VERSION = {ui};\n", encoding="utf-8"
    )
    return repo


def _inputs(tmp_path: Path, **overrides) -> g.GateInputs:
    deployed = overrides.pop(
        "deployed",
        {"trunk_sha": OLD_TRUNK, "corpus_sha": CORPUS, "ui_version": 11, "snapshot_version": 11},
    )
    snapshot = tmp_path / "deployed.duckdb"
    snapshot.write_bytes(b"x")
    values = {
        "repo_root": _repo(tmp_path),
        "site_dir": _site(tmp_path),
        "work_dir": tmp_path / "work",
        "trunk_sha": TRUNK,
        "corpus_sha": CORPUS,
        "mode": "deploy",
        "deployed": deployed,
        "deployed_snapshot": snapshot,
        "release_tag": "v0.4.1",
        "routes_manifest": ROUTES,
    }
    values.update(overrides)
    return g.GateInputs(**values)


def test_every_decided_gate_is_wired_and_calls_its_script(tmp_path: Path) -> None:
    runner = Recorder()
    outcome = g.run_gates(
        _inputs(
            tmp_path,
            deployed={"trunk_sha": OLD_TRUNK, "corpus_sha": OTHER_CORPUS, "ui_version": 11, "snapshot_version": 11},
        ),
        runner,
    )
    assert set(outcome["results"]) == {
        "privacy",
        "explorer_compat",
        "mixed_version",
        "corpus_bijection",
        "digest",
        "validator_parity",
        "links",
    }
    scripts = runner.scripts()
    for expected in (
        "check_artifact_privacy.py",
        "check_explorer_compat.py",
        "check_corpus_bijection.py",
        "compare_db_digest.py",
        "validator_parity.py",
        "site_inventory.py",
    ):
        assert expected in scripts
    assert outcome["ok"] is True


def test_privacy_scans_the_assembled_site(tmp_path: Path) -> None:
    runner = Recorder()
    inputs = _inputs(tmp_path)
    g.privacy_gate(inputs, runner)
    assert runner.commands[0][2:] == [str(inputs.site_dir)]


def test_explorer_compat_receives_the_explorer_tree_and_snapshot(tmp_path: Path) -> None:
    runner = Recorder()
    inputs = _inputs(tmp_path)
    g.explorer_compat_gate(inputs, runner)
    command = runner.commands[0]
    assert command[command.index("--artifact") + 1] == str(inputs.site_dir / "results")
    assert command[command.index("--db-path") + 1].endswith("results/data/results.duckdb")


def test_corpus_bijection_is_pinned_to_the_trunk_sha_and_requires_the_snapshot(tmp_path: Path) -> None:
    runner = Recorder()
    g.corpus_bijection_gate(_inputs(tmp_path), runner)
    command = runner.commands[0]
    assert command[command.index("--accepted-ref") + 1] == TRUNK
    assert command[command.index("--expect-source") + 1] == TRUNK
    assert "--require-artifact" in command
    assert command[command.index("--ledger-seed") + 1].endswith("publication/ledger-seed.json")


@pytest.mark.parametrize(
    "failing",
    [
        "check_artifact_privacy",
        "check_explorer_compat",
        "check_corpus_bijection",
        "validator_parity",
        "site_inventory.py check",
    ],
)
def test_any_failing_script_fails_the_aggregate(tmp_path: Path, failing: str) -> None:
    deployed = {"trunk_sha": OLD_TRUNK, "corpus_sha": OTHER_CORPUS, "ui_version": 11, "snapshot_version": 11}
    outcome = g.run_gates(_inputs(tmp_path, deployed=deployed), Recorder(failing=(failing,)))
    assert outcome["ok"] is False
    failed = [name for name, result in outcome["results"].items() if result["status"] == g.FAIL]
    assert len(failed) == 1


def test_digest_gate_requires_equality_when_the_corpus_is_unchanged(tmp_path: Path) -> None:
    runner = Recorder()
    result = g.digest_gate(_inputs(tmp_path), runner)
    assert result["status"] == g.PASS
    assert runner.commands[0][2] == "compare"
    failing = g.digest_gate(_inputs(tmp_path), Recorder(failing=("compare_db_digest.py compare",)))
    assert failing["status"] == g.FAIL


def test_digest_gate_records_both_digests_when_the_corpus_changed(tmp_path: Path) -> None:
    runner = Recorder()
    deployed = {"trunk_sha": OLD_TRUNK, "corpus_sha": OTHER_CORPUS, "ui_version": 11, "snapshot_version": 11}
    result = g.digest_gate(_inputs(tmp_path, deployed=deployed), runner)
    assert result["status"] == g.SKIPPED
    assert set(result["digests"]) == {"candidate", "deployed"}


def test_digest_gate_fails_when_a_deployed_generation_has_no_snapshot(tmp_path: Path) -> None:
    result = g.digest_gate(_inputs(tmp_path, deployed_snapshot=None), Recorder())
    assert result["status"] == g.FAIL


def test_digest_and_parity_are_skipped_without_a_deployed_generation(tmp_path: Path) -> None:
    runner = Recorder()
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None)
    assert g.digest_gate(inputs, runner)["status"] == g.SKIPPED
    assert g.validator_parity_gate(inputs, runner)["status"] == g.SKIPPED
    assert runner.commands == []


def test_validator_parity_uses_the_deployed_trunk_as_base_only_when_the_corpus_changed(tmp_path: Path) -> None:
    unchanged = Recorder()
    assert g.validator_parity_gate(_inputs(tmp_path), unchanged)["status"] == g.SKIPPED
    assert unchanged.commands == []
    runner = Recorder()
    deployed = {"trunk_sha": OLD_TRUNK, "corpus_sha": OTHER_CORPUS, "ui_version": 11, "snapshot_version": 11}
    g.validator_parity_gate(_inputs(tmp_path, deployed=deployed), runner)
    command = runner.commands[0]
    assert command[command.index("--base-sha") + 1] == OLD_TRUNK
    assert command[command.index("--merge-sha") + 1] == TRUNK
    assert command[command.index("--head-sha") + 1] == TRUNK


def test_link_gate_builds_an_inventory_then_checks_it(tmp_path: Path) -> None:
    runner = Recorder()
    g.link_gate(_inputs(tmp_path), runner)
    assert [command[2] for command in runner.commands] == ["build", "check", "check"]
    assert "--write-known-broken" in runner.commands[2]


def test_link_gate_stops_when_the_inventory_cannot_be_built(tmp_path: Path) -> None:
    runner = Recorder(failing=("site_inventory.py build",))
    result = g.link_gate(_inputs(tmp_path), runner)
    assert result["status"] == g.FAIL
    assert len(runner.commands) == 1


SUMMARY = "summary: 1 missing path, 2 missing fragment, {} broken internal link, {} missing image, 0 feed regression"


def _link_runner(listing: list[list[str]], broken: int = 1, images: int = 0):
    def run(command: list[str], cwd: Path) -> tuple[int, str]:
        if "--write-known-broken" in command:
            Path(command[command.index("--write-known-broken") + 1]).write_text(json.dumps(listing), encoding="utf-8")
            return 0, "wrote"
        if command[2] == "check":
            return 1, SUMMARY.format(broken, images)
        return 0, "wrote inventory"

    return run


def test_routed_allowance_repeats_docs_entries_under_the_dev_prefix() -> None:
    known = [
        ["/docs/blog.html", "/docs/blog/a.html", "missing path"],
        ["/blog/a.html", "/usage/x.html", "missing path"],
    ]
    routed = g.routed_allowance(known)
    assert ["/docs/dev/blog.html", "/docs/dev/blog/a.html", "missing path"] in routed
    assert known[0] in routed
    assert len(routed) == 3


def _deployed_with_baseline(links: list[list[str]] | None, tag: str = "v0.4.1") -> dict:
    deployed = {"trunk_sha": OLD_TRUNK, "corpus_sha": CORPUS, "ui_version": 11, "snapshot_version": 11}
    deployed["link_baseline"] = {} if links is None else {tag: links}
    return deployed


RELEASE_BROKEN = ["/docs/old.html", "/docs/gone.html", "missing path"]


def _release_routes_manifest(tmp_path: Path) -> Path:
    manifest = tmp_path / "release-routes.yml"
    manifest.write_text(
        "version: 1\nrefs:\n  release:\n    kind: release-tag\n  trunk:\n    kind: trunk\n"
        "routes:\n  - path: /\n    ref: release\n    builder: landing\n"
        "  - path: /docs/\n    ref: release\n    builder: docs\n"
        "  - path: /docs/dev/\n    ref: trunk\n    builder: docs\n"
        "  - path: /blog/\n    ref: trunk\n    builder: blog\n"
        "  - path: /results/\n    ref: trunk\n    builder: explorer\n"
        "root_files:\n  ref: trunk\n  files: [CNAME, .nojekyll, 404.html]\n",
        encoding="utf-8",
    )
    return manifest


def test_link_gate_tolerates_release_breakage_up_to_the_recorded_baseline(tmp_path: Path) -> None:
    manifest = _release_routes_manifest(tmp_path)
    result = g.link_gate(
        _inputs(tmp_path, deployed=_deployed_with_baseline([RELEASE_BROKEN]), routes_manifest=manifest),
        _link_runner([RELEASE_BROKEN]),
    )
    assert result["status"] == g.PASS
    assert "release tag v0.4.1" in result["detail"]
    assert result["link_baseline"] == {"release_tag": "v0.4.1", "broken": 1, "links": [RELEASE_BROKEN]}


def test_link_gate_fails_when_a_newer_release_tag_adds_broken_links(tmp_path: Path) -> None:
    listing = [RELEASE_BROKEN, ["/docs/x.html", "/docs/y.html", "missing path"]]
    manifest = _release_routes_manifest(tmp_path)
    result = g.link_gate(
        _inputs(tmp_path, deployed=_deployed_with_baseline([RELEASE_BROKEN]), routes_manifest=manifest),
        _link_runner(listing),
    )
    assert result["status"] == g.FAIL
    assert "outside the last deployed receipt baseline of 1" in result["detail"]


def test_link_gate_fails_when_fixed_links_are_swapped_for_new_ones(tmp_path: Path) -> None:
    swapped = ["/docs/x.html", "/docs/y.html", "missing path"]
    result = g.link_gate(_inputs(tmp_path, deployed=_deployed_with_baseline([RELEASE_BROKEN])), _link_runner([swapped]))
    assert result["status"] == g.FAIL
    assert "/docs/x.html" in result["detail"]


def test_link_gate_passes_a_pure_reduction_and_records_the_smaller_set(tmp_path: Path) -> None:
    other = ["/docs/x.html", "/docs/y.html", "missing path"]
    deployed = _deployed_with_baseline([RELEASE_BROKEN, other])
    manifest = _release_routes_manifest(tmp_path)
    result = g.link_gate(_inputs(tmp_path, deployed=deployed, routes_manifest=manifest), _link_runner([other]))
    assert result["status"] == g.PASS
    assert result["link_baseline"]["links"] == [other]


def test_link_gate_ignores_a_baseline_recorded_for_another_tag(tmp_path: Path) -> None:
    manifest = _release_routes_manifest(tmp_path)
    inputs = _inputs(
        tmp_path, deployed=_deployed_with_baseline([RELEASE_BROKEN], tag="v0.4.0"), routes_manifest=manifest
    )
    result = g.link_gate(inputs, _link_runner([RELEASE_BROKEN]))
    assert result["status"] == g.FAIL
    assert "outside the allowance file baseline of 0" in result["detail"]


def test_link_gate_without_a_receipt_pins_trunk_breakage_to_the_allowance_file(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None)
    allowance = inputs.repo_root / "_project" / "design" / "site-inventory" / "known-broken-links.json"
    allowance.parent.mkdir(parents=True)
    allowance.write_text(json.dumps([RELEASE_BROKEN]), encoding="utf-8")
    assert g.link_gate(inputs, _link_runner([RELEASE_BROKEN]))["status"] == g.PASS
    worse = [RELEASE_BROKEN, ["/docs/x.html", "/docs/y.html", "missing path"]]
    assert g.link_gate(inputs, _link_runner(worse))["status"] == g.FAIL


def _write_tag_allowance(inputs: g.GateInputs, tag: str, entries: list[list[str]]) -> None:
    tag_file = inputs.repo_root / "_project" / "design" / "site-inventory" / "release-known-broken" / f"{tag}.json"
    tag_file.parent.mkdir(parents=True)
    tag_file.write_text(json.dumps(entries), encoding="utf-8")


def test_link_gate_adds_the_tag_allowance_file_only_without_a_receipt_baseline(tmp_path: Path) -> None:
    manifest = _release_routes_manifest(tmp_path)
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None, routes_manifest=manifest)
    _write_tag_allowance(inputs, "v0.4.1", [RELEASE_BROKEN])
    result = g.link_gate(inputs, _link_runner([RELEASE_BROKEN]))
    assert result["status"] == g.PASS
    assert result["link_baseline"]["links"] == [RELEASE_BROKEN]
    receipt = _deployed_with_baseline([])
    result = g.link_gate(_inputs(tmp_path, deployed=receipt, routes_manifest=manifest), _link_runner([RELEASE_BROKEN]))
    assert result["status"] == g.FAIL
    assert "last deployed receipt baseline of 0" in result["detail"]


def test_link_gate_ignores_the_allowance_file_of_another_tag(tmp_path: Path) -> None:
    manifest = _release_routes_manifest(tmp_path)
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None, release_tag="v0.4.2", routes_manifest=manifest)
    _write_tag_allowance(inputs, "v0.4.1", [RELEASE_BROKEN])
    result = g.link_gate(inputs, _link_runner([RELEASE_BROKEN]))
    assert result["status"] == g.FAIL
    assert "outside the allowance file baseline of 0" in result["detail"]


def test_link_gate_fails_an_entry_outside_the_develop_and_tag_allowances(tmp_path: Path) -> None:
    manifest = _release_routes_manifest(tmp_path)
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None, routes_manifest=manifest)
    _write_tag_allowance(inputs, "v0.4.1", [RELEASE_BROKEN])
    stray = ["/docs/x.html", "/docs/y.html", "missing path"]
    result = g.link_gate(inputs, _link_runner([RELEASE_BROKEN, stray]))
    assert result["status"] == g.FAIL
    assert "allowance files (develop and v0.4.1.json) baseline of 1" in result["detail"]
    assert "/docs/x.html" in result["detail"]


def test_link_gate_tag_allowance_cannot_allow_trunk_breakage(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None)
    trunk = ["/blog/p.html", "/x.html", "missing path"]
    _write_tag_allowance(inputs, "v0.4.1", [RELEASE_BROKEN, trunk])
    result = g.link_gate(inputs, _link_runner([RELEASE_BROKEN, trunk]))
    assert result["status"] == g.FAIL
    assert "touching trunk routes" in result["detail"]


def test_link_gate_passes_real_inventory_output_with_stale_allowances(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, deployed=None, deployed_snapshot=None)
    (inputs.site_dir / "docs").mkdir(parents=True)
    (inputs.site_dir / "docs" / "old.html").write_text(
        '<!doctype html><html><head><title>Old</title></head><body><h1>Old</h1><a href="gone.html">gone</a></body></html>',
        encoding="utf-8",
    )
    stale = ["/docs/old.html", "/docs/fixed.html", "missing path"]
    allowance = inputs.repo_root / "_project" / "design" / "site-inventory" / "known-broken-links.json"
    allowance.parent.mkdir(parents=True)
    allowance.write_text(json.dumps([stale, RELEASE_BROKEN]), encoding="utf-8")
    result = g.link_gate(inputs, g.run_subprocess)
    assert result["status"] == g.PASS, result["detail"]
    assert result["link_baseline"]["links"] == []


def test_link_gate_fails_new_breakage_whose_source_is_a_trunk_route(tmp_path: Path) -> None:
    runner = _link_runner([RELEASE_BROKEN, ["/blog/p.html", "/x.html", "missing path"]])
    result = g.link_gate(_inputs(tmp_path, deployed=_deployed_with_baseline([RELEASE_BROKEN])), runner)
    assert result["status"] == g.FAIL
    assert "/docs/old.html" in result["detail"]


@pytest.mark.parametrize(
    "entry",
    [
        ["/docs/old.html", "/docs/dev/gone.html", "missing path"],
        ["/docs/old.html", "/results/gone.html", "missing path"],
        ["/index.html", "/blog/gone/", "missing path"],
        ["/docs/old.html", "/404.html", "missing path"],
        ["/docs/old.html", "/_static/gone.css", "missing path"],
    ],
)
def test_link_gate_fails_new_breakage_whose_target_is_trunk_owned(tmp_path: Path, entry: list[str]) -> None:
    result = g.link_gate(_inputs(tmp_path, deployed=_deployed_with_baseline([])), _link_runner([entry]))
    assert result["status"] == g.FAIL
    assert "trunk routes" in result["detail"]


def test_link_gate_allows_allowance_listed_entries_that_touch_trunk_routes(tmp_path: Path) -> None:
    entry = ["/blog/p.html", "/x.html", "missing path"]
    inputs = _inputs(tmp_path, deployed=_deployed_with_baseline([]))
    allowance = inputs.repo_root / "_project" / "design" / "site-inventory" / "known-broken-links.json"
    allowance.parent.mkdir(parents=True)
    allowance.write_text(json.dumps([entry]), encoding="utf-8")
    result = g.link_gate(inputs, _link_runner([entry]))
    assert result["status"] == g.PASS
    assert result["link_baseline"]["links"] == []


def test_link_gate_derives_ownership_from_the_routes_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "routes.yml"
    manifest.write_text(
        "version: 1\nrefs:\n  release:\n    kind: release-tag\n  trunk:\n    kind: trunk\n"
        "routes:\n  - path: /\n    ref: release\n    builder: landing\n"
        "  - path: /docs/\n    ref: trunk\n    builder: docs\n"
        "root_files:\n  ref: release\n  files: [CNAME]\n",
        encoding="utf-8",
    )
    inputs = _inputs(tmp_path, deployed=_deployed_with_baseline([]), routes_manifest=manifest)
    result = g.link_gate(inputs, _link_runner([RELEASE_BROKEN]))
    assert result["status"] == g.FAIL
    assert "trunk routes" in result["detail"]


def test_link_gate_fails_without_a_routes_manifest(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path, routes_manifest=tmp_path / "missing.yml")
    outcome = g.run_gates(inputs, Recorder())
    assert outcome["results"]["links"]["status"] == g.FAIL


def test_link_gate_fails_on_missing_images_even_without_broken_links(tmp_path: Path) -> None:
    runner = _link_runner([], broken=0, images=2)
    assert g.link_gate(_inputs(tmp_path), runner)["status"] == g.FAIL


def test_mixed_version_gate_refuses_a_snapshot_older_than_the_ui(tmp_path: Path) -> None:
    inputs = _inputs(tmp_path)
    inputs = g.GateInputs(**{**inputs.__dict__, "repo_root": _repo(tmp_path, ui=12)})
    result = g.mixed_version_gate(inputs, Recorder())
    assert result["status"] == g.FAIL
    assert result["versions"] == {"ui_expected": 12, "snapshot": 11}


def test_mixed_version_gate_refuses_a_new_snapshot_that_the_deployed_ui_cannot_read_older_than_ui(
    tmp_path: Path,
) -> None:
    deployed = {"trunk_sha": OLD_TRUNK, "corpus_sha": CORPUS, "ui_version": 12, "snapshot_version": 12}
    result = g.mixed_version_gate(_inputs(tmp_path, deployed=deployed), Recorder())
    assert result["status"] == g.FAIL
    assert any(not pair["ok"] for pair in result["evaluation"]["pairs"])


def test_mixed_version_gate_passes_when_snapshot_is_at_least_ui_for_each_pair(tmp_path: Path) -> None:
    result = g.mixed_version_gate(_inputs(tmp_path), Recorder())
    assert result["status"] == g.PASS
    assert result["versions"] == {"ui_expected": 11, "snapshot": 11}


def test_rollback_runs_only_the_artifact_level_gates(tmp_path: Path) -> None:
    runner = Recorder()
    outcome = g.run_gates(_inputs(tmp_path, mode="rollback", ui_version=11), runner)
    skipped = {name for name, result in outcome["results"].items() if result["status"] == g.SKIPPED}
    assert skipped == {"corpus_bijection", "digest", "validator_parity", "links"}
    assert set(runner.scripts()) == {"check_artifact_privacy.py", "check_explorer_compat.py"}


def test_a_raising_gate_is_recorded_as_a_failure(tmp_path: Path) -> None:
    def boom(command: list[str], cwd: Path) -> tuple[int, str]:
        raise RuntimeError("tool crashed")

    outcome = g.run_gates(_inputs(tmp_path), boom)
    assert outcome["ok"] is False
    assert "RuntimeError" in outcome["results"]["privacy"]["detail"]


def test_write_gates_emits_json_and_returns_its_digest(tmp_path: Path) -> None:
    outcome = g.run_gates(_inputs(tmp_path), Recorder())
    target = tmp_path / "out" / "gates.json"
    digest = g.write_gates(target, outcome)
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded["ok"] is True
    assert len(digest) == 64
