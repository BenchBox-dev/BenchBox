"""Fast-test coverage for tests/uat/phases/package.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

import pytest

from tests.uat.config import validate_config
from tests.uat.phases import package

pytestmark = pytest.mark.fast


def _fake_runner_factory(returncodes: list[int]):
    """Stub for subprocess.run that returns the given returncodes per invocation."""
    iterator = iter(returncodes)

    def runner(argv, check=False):
        rc = next(iterator)
        return Mock(returncode=rc, args=argv)

    return runner


def test_package_local_stage_invokes_output_mode(tmp_path: Path):
    cfg = validate_config({"name": "x", "package": {"submit_terminal_state": "local-stage"}})
    runner = _fake_runner_factory([0])
    result = package.run_package(
        cfg,
        result_paths=[tmp_path / "r.json"],
        submissions_dir=tmp_path / "subs",
        runner=runner,
    )
    assert result.terminal_state == "local-stage"
    assert result.success_count == 1
    assert "--output" in result.invocations[0]


def test_package_cloud_uploaded_requires_service(tmp_path: Path):
    cfg = validate_config({"name": "x", "package": {"submit_terminal_state": "cloud-uploaded"}})
    with pytest.raises(package.PackagePhaseError, match="package.service"):
        package.run_package(
            cfg,
            result_paths=[tmp_path / "r.json"],
            submissions_dir=tmp_path / "subs",
            runner=_fake_runner_factory([]),
        )


def test_package_cloud_uploaded_invokes_service(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "x",
            "package": {
                "submit_terminal_state": "cloud-uploaded",
                "service": "https://results.example.com",
            },
        }
    )
    runner = _fake_runner_factory([0])
    result = package.run_package(
        cfg,
        result_paths=[tmp_path / "r.json"],
        submissions_dir=tmp_path / "subs",
        runner=runner,
    )
    argv = result.invocations[0]
    assert "--service" in argv
    assert "https://results.example.com" in argv


def test_package_missing_terminal_state_raises(tmp_path: Path):
    cfg = validate_config({"name": "x"})
    with pytest.raises(package.PackagePhaseError, match="submit_terminal_state"):
        package.run_package(
            cfg,
            result_paths=[],
            submissions_dir=tmp_path,
            runner=_fake_runner_factory([]),
        )


def test_package_invalid_terminal_state_raises(tmp_path: Path):
    cfg = validate_config({"name": "x", "package": {"submit_terminal_state": "merged-mainline"}})
    with pytest.raises(package.PackagePhaseError, match="not in"):
        package.run_package(
            cfg,
            result_paths=[],
            submissions_dir=tmp_path,
            runner=_fake_runner_factory([]),
        )


def test_package_counts_failures(tmp_path: Path):
    cfg = validate_config({"name": "x", "package": {"submit_terminal_state": "local-stage"}})
    runner = _fake_runner_factory([0, 1, 0])
    result = package.run_package(
        cfg,
        result_paths=[tmp_path / f"r{i}.json" for i in range(3)],
        submissions_dir=tmp_path / "subs",
        runner=runner,
    )
    assert result.success_count == 2
    assert result.failure_count == 1
    assert result.exit_code() == 1


@pytest.mark.parametrize("state", sorted(package.PR_STUB_TERMINAL_STATES))
def test_package_warns_for_pr_stub_states(tmp_path: Path, state: str):
    cfg = validate_config({"name": "x", "package": {"submit_terminal_state": state}})
    runner = _fake_runner_factory([0])
    warnings: list[str] = []
    package.run_package(
        cfg,
        result_paths=[tmp_path / "r.json"],
        submissions_dir=tmp_path / "subs",
        runner=runner,
        warn=warnings.append,
    )
    assert warnings, f"no warning emitted for stub state {state!r}"
    assert state in warnings[0]
    assert "stub" in warnings[0].lower()


def test_package_local_stage_does_not_warn(tmp_path: Path):
    cfg = validate_config({"name": "x", "package": {"submit_terminal_state": "local-stage"}})
    runner = _fake_runner_factory([0])
    warnings: list[str] = []
    package.run_package(
        cfg,
        result_paths=[tmp_path / "r.json"],
        submissions_dir=tmp_path / "subs",
        runner=runner,
        warn=warnings.append,
    )
    assert warnings == []


def test_package_cloud_uploaded_does_not_warn(tmp_path: Path):
    cfg = validate_config(
        {
            "name": "x",
            "package": {
                "submit_terminal_state": "cloud-uploaded",
                "service": "https://results.example.com",
            },
        }
    )
    runner = _fake_runner_factory([0])
    warnings: list[str] = []
    package.run_package(
        cfg,
        result_paths=[tmp_path / "r.json"],
        submissions_dir=tmp_path / "subs",
        runner=runner,
        warn=warnings.append,
    )
    assert warnings == []
