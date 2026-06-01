"""Tests for the standardized pytest command surface."""

from __future__ import annotations

import re
import subprocess
import sys
from configparser import ConfigParser
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

CI_FAST_EXPRESSION = "fast and not (slow or stress or resource_heavy or live_integration)"
CORRECTNESS_GATE_NODEID = (
    "tests/integration/test_local_platform_benchmark_matrix.py::test_local_platform_benchmark_matrix[tpch-duckdb]"
)
CORRECTNESS_GATE_QUERY_IDS = "6,14,15,17,19"


def _makefile_target_body(makefile_content: str, target_name: str) -> str:
    match = re.search(rf"(?ms)^{re.escape(target_name)}:\n(?P<body>(?:\t.*\n|@.*\n|[ \t].*\n)*)", makefile_content)
    assert match, f"Makefile target not found: {target_name}"
    return match.group("body")


def _workflow_job_run_text(workflow_path: Path, job_name: str) -> str:
    workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_name]["steps"]
    return "\n".join(str(step.get("run", "")) for step in steps)


def _load_ini_section(path: Path, section: str) -> dict[str, str]:
    parser = ConfigParser()
    parser.read(path)
    return dict(parser[section])


def _marker_names(path: Path) -> set[str]:
    marker_lines = _load_ini_section(path, "pytest")["markers"].splitlines()
    return {
        line.split(":", 1)[0].strip()
        for line in marker_lines
        if line.strip() and ":" in line and not line.strip().startswith("#")
    }


class TestStandardizedTestCommands:
    """Test the standardized test command system."""

    def test_pytest_marker_system_works(self):
        env = {**subprocess.os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert result.returncode in (0, 2), f"Unexpected exit code: {result.returncode}"
        assert "test_" in result.stdout or "collected" in result.stdout.lower()

    def test_fast_marker_functionality(self):
        env = {**subprocess.os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"}
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-m",
                "fast and not (slow or stress or resource_heavy or live_integration)",
                "--collect-only",
                "-q",
            ],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert result.returncode in (0, 2), f"Unexpected exit code: {result.returncode}"
        assert "test_" in result.stdout or "collected" in result.stdout.lower()

    def test_unit_marker_functionality(self):
        env = {**subprocess.os.environ, "BENCHBOX_SKIP_TEST_LOCK": "1"}
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-m", "unit", "--collect-only", "-q"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=120,
            env=env,
        )

        assert result.returncode in (0, 2), f"Unexpected exit code: {result.returncode}"
        assert "test_" in result.stdout or "collected" in result.stdout.lower()

    def test_makefile_commands_exist(self):
        makefile_path = Path.cwd() / "Makefile"
        assert makefile_path.exists(), "Makefile should exist"

        makefile_content = makefile_path.read_text()
        assert "test-fast:" in makefile_content
        assert "test-unit:" in makefile_content
        assert "test-integration:" in makefile_content
        assert "test-all:" in makefile_content
        assert "python -m pytest" in makefile_content
        assert "run_tests.py" not in makefile_content

    def test_no_legacy_run_tests_references(self):
        run_tests_path = Path.cwd() / "run_tests.py"
        assert not run_tests_path.exists(), "run_tests.py should not exist in project root"

    def test_pytest_configuration_is_valid(self):
        pytest_ini_path = Path.cwd() / "pytest.ini"
        assert pytest_ini_path.exists(), "pytest.ini should exist"

        pytest_ini_content = pytest_ini_path.read_text()
        assert "fast:" in pytest_ini_content
        assert "unit:" in pytest_ini_content
        assert "integration:" in pytest_ini_content
        assert "flaky:" in pytest_ini_content
        assert "local_only:" in pytest_ini_content
        assert "markers =" in pytest_ini_content
        assert "not slow and not stress and not live_integration and not resource_heavy" in pytest_ini_content

    def test_coverage_commands_use_pytest(self):
        makefile_path = Path.cwd() / "Makefile"
        makefile_content = makefile_path.read_text()

        coverage_section = False
        for line in makefile_content.split("\n"):
            if line.startswith("coverage:"):
                coverage_section = True
                continue
            if coverage_section and line.startswith("\t"):
                assert "python -m pytest" in line
                assert "--cov=" in line
                break


class TestMakefileCommands:
    """Test that Makefile commands work as expected."""

    def test_makefile_test_targets_defined(self):
        makefile_path = Path.cwd() / "Makefile"
        makefile_content = makefile_path.read_text()

        expected_targets = [
            "test:",
            "test-all:",
            "test-unit:",
            "test-integration:",
            "test-fast:",
            "test-medium:",
            "test-slow:",
            "coverage:",
            "coverage-html:",
        ]

        for target in expected_targets:
            assert target in makefile_content, f"Makefile should contain target: {target}"

    def test_makefile_test_unlock_expands_user_lock_dir_without_uv(self, tmp_path):
        home = tmp_path / "home"
        lock_dir = home / "tmp" / "benchbox-lock-probe"
        lock_dir.mkdir(parents=True)
        lock_path = lock_dir / "test.lock"
        lock_path.write_text("stale lock\n", encoding="utf-8")
        env = {
            **subprocess.os.environ,
            "BENCHBOX_TEST_LOCK_DIR": "~/tmp/benchbox-lock-probe",
            "HOME": str(home),
            "PATH": "/usr/bin:/bin",
        }

        result = subprocess.run(
            ["make", "--no-print-directory", "test-unlock"],
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

        expected_path = str(lock_path)
        assert result.returncode == 0, result.stderr
        assert expected_path in result.stdout
        assert "~/tmp/benchbox-lock-probe/test.lock" not in result.stdout
        assert "uv:" not in result.stdout + result.stderr
        assert not lock_path.exists()

    def test_makefile_test_all_splits_parallel_and_serial_lanes_explicitly(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-all:" in makefile_content
        assert '-m "not (slow or stress or resource_heavy or live_integration)"' in makefile_content
        assert '-m "(slow or resource_heavy) and not (stress or live_integration)" -n 0' in makefile_content

    def test_makefile_test_fast_excludes_heavy_and_opt_in_lanes(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-fast:" in makefile_content
        assert '-m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short' in makefile_content

    def test_pr_preflight_fast_tests_uses_required_ci_marker_expression(self):
        repo_root = Path.cwd()
        makefile_content = (repo_root / "Makefile").read_text()
        preflight_body = _makefile_target_body(makefile_content, "pr-preflight-fast-tests")
        develop_pr_run_text = _workflow_job_run_text(repo_root / ".github" / "workflows" / "pr.yml", "code-test")
        main_pr_run_text = _workflow_job_run_text(repo_root / ".github" / "workflows" / "test.yml", "test")

        assert f'-m "{CI_FAST_EXPRESSION}"' in preflight_body
        assert "-m fast -q" not in preflight_body
        assert f'-m "{CI_FAST_EXPRESSION}"' in develop_pr_run_text
        assert f'-m "{CI_FAST_EXPRESSION}"' in main_pr_run_text
        assert "--cov-fail-under=70" in develop_pr_run_text
        assert "--cov-fail-under=70" in main_pr_run_text
        assert "coverage remains CI-only" in makefile_content

    def test_test_ci_is_maintained_broad_local_profile(self):
        repo_root = Path.cwd()
        makefile_content = (repo_root / "Makefile").read_text()
        pytest_ci_content = (repo_root / "pytest-ci.ini").read_text()
        pytest_ci_addopts = _load_ini_section(repo_root / "pytest-ci.ini", "pytest")["addopts"]

        test_ci_body = _makefile_target_body(makefile_content, "test-ci")
        assert "-c pytest-ci.ini" in test_ci_body
        assert '-m "not (slow or flaky or local_only)"' in test_ci_body
        assert "--cov=benchbox" in test_ci_body
        assert "Maintained broad local CI profile" in makefile_content
        assert "flaky:" in pytest_ci_content
        assert "local_only:" in pytest_ci_content
        assert "source = benchbox" in pytest_ci_content
        assert "--cov-config=.coveragerc_core" not in pytest_ci_addopts
        assert _marker_names(repo_root / "pytest.ini") <= _marker_names(repo_root / "pytest-ci.ini")

    def test_coverage_threshold_policy_distinguishes_blocking_and_advisory_thresholds(self):
        repo_root = Path.cwd()
        makefile_content = (repo_root / "Makefile").read_text()
        pr_workflow = (repo_root / ".github" / "workflows" / "pr.yml").read_text()
        test_workflow = (repo_root / ".github" / "workflows" / "test.yml").read_text()
        conftest_content = (repo_root / "tests" / "conftest.py").read_text()

        assert "--cov-fail-under=70" in makefile_content
        assert "--cov-fail-under=70" in pr_workflow
        assert "--cov-fail-under=70" in test_workflow
        assert "70 is the blocking CI floor" in makefile_content
        assert "threshold = 80.0" in conftest_content
        assert "intentionally advisory" in conftest_content
        assert "pytest.fail" not in conftest_content.split("def pytest_terminal_summary", maxsplit=1)[1]

    def test_makefile_test_medium_uses_five_workers(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-medium:" in makefile_content
        assert (
            '-m "medium and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=60 -n 5'
            in makefile_content
        )

    def test_medium_marker_policy_is_documented_as_explicit_routing(self):
        repo_root = Path.cwd()
        readme_content = (repo_root / "tests" / "README.md").read_text()
        makefile_content = (repo_root / "Makefile").read_text()

        assert "Medium tests are an explicit local routing tier" in readme_content
        assert "Correctness-relevant medium tests must be promoted" in readme_content
        assert "test-medium:" in makefile_content

    def test_makefile_correctness_gate_runs_expected_results_backed_matrix_slice(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()
        gate_body = _makefile_target_body(makefile_content, "test-correctness-gate")

        assert "BENCHBOX_STRICT_EXPECTED_RESULTS=1" in gate_body
        assert f"BENCHBOX_CORRECTNESS_GATE_QUERY_IDS={CORRECTNESS_GATE_QUERY_IDS}" in gate_body
        assert CORRECTNESS_GATE_NODEID in gate_body
        assert "-m stress" in gate_body
        assert "-n 0" in gate_body
        assert "--timeout=1200" in gate_body

    def test_develop_pr_invokes_bounded_correctness_gate(self):
        repo_root = Path.cwd()
        workflow = yaml.safe_load((repo_root / ".github" / "workflows" / "pr.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["correctness-gate"]
        aggregate = workflow["jobs"]["ci-required-result"]

        assert job["needs"] == "ci-paths"
        assert "needs-code-ci == 'true'" in job["if"]
        assert "make test-correctness-gate" in _workflow_job_run_text(
            repo_root / ".github" / "workflows" / "pr.yml",
            "correctness-gate",
        )
        assert "correctness-gate" in aggregate["needs"]
        assert "CORRECTNESS_RESULT" in _workflow_job_run_text(
            repo_root / ".github" / "workflows" / "pr.yml",
            "ci-required-result",
        )

    def test_main_release_required_includes_bounded_correctness_gate(self):
        repo_root = Path.cwd()
        workflow = yaml.safe_load((repo_root / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))
        job = workflow["jobs"]["correctness-gate"]
        aggregate = workflow["jobs"]["release-required-result"]

        assert "github.base_ref == 'main'" in job["if"]
        assert "make test-correctness-gate" in _workflow_job_run_text(
            repo_root / ".github" / "workflows" / "test.yml",
            "correctness-gate",
        )
        assert "correctness-gate" in aggregate["needs"]

    def test_lint_markers_runs_marker_strategy_policy_explicitly(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()
        lint_body = _makefile_target_body(makefile_content, "lint-markers")

        assert "--collect-only" in lint_body
        assert "tests/unit/test_marker_strategy.py -q" in lint_body

    def test_makefile_test_slow_runs_serially(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-slow:" in makefile_content
        assert '-m "slow and not (stress or live_integration)" -n 0 --tb=short -v' in makefile_content

    def test_runtime_no_longer_depends_on_generated_bucket_files(self):
        assert not (Path.cwd() / "_project" / "config" / "test_speed_buckets.json").exists()
        assert not (Path.cwd() / "_project" / "scripts" / "generate_test_speed_buckets.py").exists()

    def test_makefile_uses_pytest_consistently(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        test_lines = [line for line in makefile_content.split("\n") if line.startswith("\tuv run -- python -m pytest")]

        assert len(test_lines) > 5, "Should have multiple pytest-based commands"
        for line in test_lines:
            assert line.startswith("\tuv run -- python -m pytest"), f"Line should use pytest: {line}"
