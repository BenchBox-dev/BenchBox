"""Fast-test coverage for tests/uat/phases/explorer_smoke.py."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tests.uat.phases import explorer_smoke

pytestmark = pytest.mark.fast


def write_bundle(bundles_dir: Path) -> Path:
    bundles_dir.mkdir(parents=True, exist_ok=True)
    path = bundles_dir / "tpch-duckdb-sf0.01-20260403-010ee756.json"
    path.write_text(
        json.dumps(
            {
                "run": {"id": "010ee756"},
                "benchmark": {"id": "tpch", "name": "TPC-H", "scale_factor": 0.01},
                "platform": {"name": "DuckDB"},
                "queries": [{"id": "Q1", "status": "SUCCESS"}],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_skipped_when_node_missing(tmp_path: Path):
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)
    with (
        patch.object(explorer_smoke, "explorer_present", return_value=True),
        patch.object(explorer_smoke, "has_node", return_value=False),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
        )
    assert result.skipped is True
    assert result.skip_reason == "node not on PATH"
    assert result.exit_code() == 0


def test_explorer_smoke_skips_with_reason_when_explorer_absent(tmp_path: Path):
    """Clean main checkout: explorer build inputs absent -> structured skip, not a hard fail."""
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)
    sentinel = Mock(side_effect=AssertionError("heavy path must not run when explorer is absent"))
    with (
        patch.object(explorer_smoke, "explorer_present", return_value=False),
        patch.object(explorer_smoke, "has_node", return_value=True),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            runner=sentinel,
        )
    assert result.skipped is True
    assert result.skip_reason is not None
    assert "explorer assets absent" in result.skip_reason
    assert result.exit_code() == 0
    sentinel.assert_not_called()
    # The minimal corpus contract still ran even though the heavy path was skipped.
    contract = (tmp_path / "logs" / "explorer_corpus_contract.json").read_text(encoding="utf-8")
    assert '"bundles": 1' in contract


def test_explorer_corpus_contract_runs_regardless_of_node(tmp_path: Path):
    """The always-on minimal corpus contract validates bundles even with no Node and no explorer."""
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)
    with (
        patch.object(explorer_smoke, "explorer_present", return_value=False),
        patch.object(explorer_smoke, "has_node", return_value=False),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            runner=Mock(side_effect=AssertionError("no subprocess on the minimal path")),
        )
    assert result.skipped is True
    contract_path = tmp_path / "logs" / "explorer_corpus_contract.json"
    assert contract_path.is_file()
    assert '"bundles": 1' in contract_path.read_text(encoding="utf-8")


def test_explorer_corpus_contract_fails_loudly_on_empty_bundles_without_node(tmp_path: Path):
    """The minimal corpus contract is a real gate: empty corpus fails even with no Node/explorer."""
    with (
        patch.object(explorer_smoke, "explorer_present", return_value=False),
        patch.object(explorer_smoke, "has_node", return_value=False),
    ):
        with pytest.raises(RuntimeError, match="no result bundles"):
            explorer_smoke.run_explorer_smoke(
                bundles_dir=tmp_path / "empty",
                output_dir=tmp_path / "out",
                log_dir=tmp_path / "logs",
                runner=Mock(),
            )


def test_explorer_smoke_uses_data_dir_flag():
    argv = explorer_smoke.build_argv(data_dir=Path("results-data"), output_dir=Path("out"))
    assert "--data-dir" in argv
    legacy_flag = "--" + "bundles" + "-dir"
    assert legacy_flag not in argv


def test_runs_builds_fixtures_then_playwright_smoke(tmp_path: Path):
    invocations: list[list[str]] = []
    cwd_by_invocation: list[Path | None] = []
    env_by_invocation: list[dict[str, str] | None] = []
    output_dir = tmp_path / "out"
    fixture_dir = tmp_path / "fixture-data"
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        cwd_by_invocation.append(cwd)
        env_by_invocation.append(env)
        if argv[:6] == list(explorer_smoke.EXPLORER_BUILD_ARGV):
            output_dir.mkdir(parents=True)
            (output_dir / "results.duckdb").write_text("fixture", encoding="utf-8")
        return Mock(returncode=0, args=argv)

    with (
        patch.object(explorer_smoke, "has_node", return_value=True),
        patch.object(explorer_smoke, "_find_free_local_port", return_value=45678),
    ):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=output_dir,
            log_dir=tmp_path / "logs",
            playwright_browsers=("chromium",),
            playwright_fixture_dir=fixture_dir,
            runner=fake_runner,
        )
    assert result.skipped is False
    assert result.exit_code() == 0
    assert len(invocations) == 3
    assert invocations[0][:6] == list(explorer_smoke.EXPLORER_BUILD_ARGV)
    assert "--data-dir" in invocations[0]
    assert invocations[1] == ["npm", "ci"]
    # UAT delegates build+playwright to the explorer's single npm script and
    # forwards browser projects via npm's `--` passthrough; it no longer issues
    # `npm run build` / `npx playwright` itself.
    assert invocations[2] == [
        "npm",
        "run",
        explorer_smoke.EXPLORER_SMOKE_NPM_SCRIPT,
        "--",
        "--project",
        "chromium",
    ]
    assert all(cwd == explorer_smoke.EXPLORER_DIR for cwd in cwd_by_invocation[1:])
    assert env_by_invocation[-1] is not None
    assert env_by_invocation[-1]["E2E_FIXTURE_DIR"] == str(fixture_dir)
    assert env_by_invocation[-1]["E2E_PORT"] == "45678"
    assert (fixture_dir / "results.duckdb").read_text(encoding="utf-8") == "fixture"
    contract = (tmp_path / "logs" / "explorer_corpus_contract.json").read_text(encoding="utf-8")
    assert '"bundles": 1' in contract


def test_short_circuits_on_build_failure(tmp_path: Path):
    invocations: list[list[str]] = []
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        return Mock(returncode=2, args=argv)

    with patch.object(explorer_smoke, "has_node", return_value=True):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            runner=fake_runner,
        )
    assert result.exit_code() == 2
    assert len(invocations) == 1


def test_default_playwright_fixture_dir_is_scoped_to_log_dir(tmp_path: Path):
    first = explorer_smoke._default_playwright_fixture_dir(log_dir=tmp_path / "run-a")
    second = explorer_smoke._default_playwright_fixture_dir(log_dir=tmp_path / "run-b")

    assert first == tmp_path / "run-a" / "playwright-fixtures" / "data"
    assert second == tmp_path / "run-b" / "playwright-fixtures" / "data"
    assert first != second
    assert explorer_smoke.EXPLORER_DIR not in first.parents


def test_delegated_npm_script_targets_external_corpus_tag():
    """The explorer's delegated smoke script must grep the tag UAT delegates to.

    UAT no longer issues the Playwright grep itself; it calls
    EXPLORER_SMOKE_NPM_SCRIPT. Pin the contract so the package.json script and
    the UAT tag constant cannot drift apart.
    """
    package_json = json.loads((explorer_smoke.EXPLORER_DIR / "package.json").read_text(encoding="utf-8"))
    script = package_json["scripts"][explorer_smoke.EXPLORER_SMOKE_NPM_SCRIPT]
    assert explorer_smoke.EXTERNAL_CORPUS_SMOKE_TAG in script
    assert "playwright test" in script


def test_serve_browser_tests_accepts_fixture_dir_env_override():
    serve_script = explorer_smoke.EXPLORER_DIR / "scripts" / "serve-browser-tests.mjs"
    serve_text = serve_script.read_text(encoding="utf-8")
    assert "process.env.E2E_FIXTURE_DIR" in serve_text
    assert '"test-fixtures", ".generated", "data"' in serve_text


def test_playwright_config_does_not_reuse_server_for_fixture_dir_override():
    config = explorer_smoke.EXPLORER_DIR / "playwright.config.ts"
    config_text = config.read_text(encoding="utf-8")
    assert "reuseExistingServer: !process.env.CI && !process.env.E2E_FIXTURE_DIR" in config_text


def test_default_fixture_dir_is_per_run_and_passed_to_playwright(tmp_path: Path):
    invocations: list[list[str]] = []
    env_by_invocation: list[dict[str, str] | None] = []
    output_dir = tmp_path / "out"
    log_dir = tmp_path / "logs"
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        env_by_invocation.append(env)
        if argv[:6] == list(explorer_smoke.EXPLORER_BUILD_ARGV):
            output_dir.mkdir(parents=True)
            (output_dir / "results.duckdb").write_text("fixture", encoding="utf-8")
        return Mock(returncode=0, args=argv)

    with (
        patch.object(explorer_smoke, "has_node", return_value=True),
        patch.object(explorer_smoke, "_find_free_local_port", return_value=45679),
    ):
        explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=output_dir,
            log_dir=log_dir,
            runner=fake_runner,
        )

    fixture_dir = log_dir / "playwright-fixtures" / "data"
    assert fixture_dir != explorer_smoke.EXPLORER_DIR / "test-fixtures" / ".generated" / "data"
    assert (fixture_dir / "results.duckdb").read_text(encoding="utf-8") == "fixture"
    assert env_by_invocation[-1] is not None
    assert env_by_invocation[-1]["E2E_FIXTURE_DIR"] == str(fixture_dir)
    assert env_by_invocation[-1]["E2E_PORT"] == "45679"
    assert invocations[-1][:3] == ["npm", "run", explorer_smoke.EXPLORER_SMOKE_NPM_SCRIPT]


def test_requested_browser_projects_are_not_silently_dropped(tmp_path: Path):
    invocations: list[list[str]] = []
    bundles_dir = tmp_path / "b"
    write_bundle(bundles_dir)

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        return Mock(returncode=0, args=argv)

    with patch.object(explorer_smoke, "has_node", return_value=True):
        explorer_smoke.run_explorer_smoke(
            bundles_dir=bundles_dir,
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            playwright_browsers=("chromium", "firefox"),
            runner=fake_runner,
        )

    smoke = invocations[-1]
    assert smoke[:3] == ["npm", "run", explorer_smoke.EXPLORER_SMOKE_NPM_SCRIPT]
    assert smoke.count("--project") == 2
    assert "chromium" in smoke
    assert "firefox" in smoke


def test_external_corpus_contract_fails_before_playwright_for_empty_bundles(tmp_path: Path):
    with patch.object(explorer_smoke, "has_node", return_value=True):
        with pytest.raises(RuntimeError, match="no result bundles"):
            explorer_smoke.run_explorer_smoke(
                bundles_dir=tmp_path / "empty",
                output_dir=tmp_path / "out",
                log_dir=tmp_path / "logs",
                runner=Mock(),
            )


def test_package_root_resolves_to_bundle_subdirectory(tmp_path: Path):
    package_root = tmp_path / "submission"
    bundle_dir = package_root / "bundle"
    write_bundle(bundle_dir)
    (package_root / "tpch.manifest.json").write_text('{"kind": "submission-manifest"}', encoding="utf-8")

    contract = explorer_smoke._validate_external_corpus(
        bundles_dir=explorer_smoke._resolve_bundles_dir(package_root),
    )

    assert contract["bundles"] == 1
    assert contract["benchmarks"] == ["tpch"]


def test_external_corpus_contract_ignores_tuning_sidecars(tmp_path: Path):
    bundles_dir = tmp_path / "bundles"
    bundle_path = write_bundle(bundles_dir)
    bundle_path.with_name(f"{bundle_path.stem}.tuning.json").write_text(
        json.dumps({"tuning_mode": "manual", "notes": "sidecar shape is not a result bundle"}),
        encoding="utf-8",
    )

    contract = explorer_smoke._validate_external_corpus(bundles_dir=bundles_dir)

    assert contract["bundles"] == 1
    assert contract["checked_bundles"] == 1
    assert contract["benchmarks"] == ["tpch"]
