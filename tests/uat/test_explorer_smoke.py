"""Fast-test coverage for tests/uat/phases/explorer_smoke.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tests.uat.phases import explorer_smoke

pytestmark = pytest.mark.fast


def test_skipped_when_node_missing(tmp_path: Path):
    with patch.object(explorer_smoke, "has_node", return_value=False):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
        )
    assert result.skipped is True
    assert result.exit_code() == 0


def test_explorer_smoke_uses_data_dir_flag():
    argv = explorer_smoke.build_argv(data_dir=Path("results-data"), output_dir=Path("out"))
    assert "--data-dir" in argv
    legacy_flag = "--" + "bundles" + "-dir"
    assert legacy_flag not in argv


def test_runs_build_then_playwright_smoke(tmp_path: Path):
    invocations: list[list[str]] = []
    cwd_by_invocation: list[Path | None] = []
    output_dir = tmp_path / "out"

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        cwd_by_invocation.append(cwd)
        if argv[:3] == ["benchbox", "explorer", "build"]:
            output_dir.mkdir(parents=True)
            (output_dir / "results.duckdb").write_text("fixture", encoding="utf-8")
        return Mock(returncode=0, args=argv)

    with patch.object(explorer_smoke, "has_node", return_value=True):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=output_dir,
            log_dir=tmp_path / "logs",
            playwright_browsers=("chromium",),
            playwright_fixture_dir=tmp_path / "fixture-data",
            runner=fake_runner,
        )
    assert result.skipped is False
    assert result.exit_code() == 0
    assert len(invocations) == 4
    assert invocations[0][:3] == ["benchbox", "explorer", "build"]
    assert "--data-dir" in invocations[0]
    assert invocations[1] == ["npm", "ci"]
    assert invocations[2] == ["npm", "run", "build"]
    assert invocations[3][:4] == ["npx", "playwright", "test", "--grep"]
    assert "@smoke" in invocations[3]
    assert "--project" in invocations[3]
    assert "chromium" in invocations[3]
    assert all(cwd == explorer_smoke.EXPLORER_DIR for cwd in cwd_by_invocation[1:])
    assert (tmp_path / "fixture-data" / "results.duckdb").read_text(encoding="utf-8") == "fixture"


def test_short_circuits_on_build_failure(tmp_path: Path):
    invocations: list[list[str]] = []

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        return Mock(returncode=2, args=argv)

    with patch.object(explorer_smoke, "has_node", return_value=True):
        result = explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            runner=fake_runner,
        )
    assert result.exit_code() == 2
    assert len(invocations) == 1


def test_default_playwright_fixture_dir_matches_serve_browser_tests_mount():
    default = explorer_smoke._default_playwright_fixture_dir()
    assert default == explorer_smoke.EXPLORER_DIR / "test-fixtures" / ".generated" / "data"

    serve_script = explorer_smoke.EXPLORER_DIR / "scripts" / "serve-browser-tests.mjs"
    serve_text = serve_script.read_text(encoding="utf-8")
    assert '"test-fixtures", ".generated", "data"' in serve_text, (
        "serve-browser-tests.mjs default fixture mount diverged from "
        "_default_playwright_fixture_dir(); update both ends together"
    )


def test_requested_browser_projects_are_not_silently_dropped(tmp_path: Path):
    invocations: list[list[str]] = []

    def fake_runner(argv, stdout=None, stderr=None, check=False, cwd=None, env=None):
        invocations.append(argv)
        return Mock(returncode=0, args=argv)

    with patch.object(explorer_smoke, "has_node", return_value=True):
        explorer_smoke.run_explorer_smoke(
            bundles_dir=tmp_path / "b",
            output_dir=tmp_path / "out",
            log_dir=tmp_path / "logs",
            playwright_browsers=("chromium", "firefox"),
            runner=fake_runner,
        )

    playwright = invocations[-1]
    assert playwright.count("--project") == 2
    assert "chromium" in playwright
    assert "firefox" in playwright
