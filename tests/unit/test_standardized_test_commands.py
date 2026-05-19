"""Tests for the standardized pytest command surface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


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

    def test_makefile_test_medium_uses_five_workers(self):
        makefile_content = (Path.cwd() / "Makefile").read_text()

        assert "test-medium:" in makefile_content
        assert (
            '-m "medium and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=60 -n 5'
            in makefile_content
        )

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
