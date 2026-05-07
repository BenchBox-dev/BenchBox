"""Fast tests for UAT preflight local-platform provisioning checks."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

from tests.uat import config
from tests.uat.phases import preflight

pytestmark = pytest.mark.fast


def test_local_platforms_check_attempts_automated_platform_then_succeeds(tmp_path: Path, monkeypatch):
    calls: list[str] = []
    reachable_calls = 0

    def fake_reachable(platform: str) -> bool:
        nonlocal reachable_calls
        assert platform == "postgresql"
        reachable_calls += 1
        return reachable_calls > 1

    def fake_bring_up(platform: str) -> int:
        calls.append(platform)
        return 0

    monkeypatch.setattr(preflight, "free_space_gib", lambda path: 100.0)
    monkeypatch.setattr(preflight, "docker_reachable", lambda: True)
    monkeypatch.setattr(preflight, "host_load_1m", lambda: 0.5)

    result = preflight.run_preflight(
        free_space_path=tmp_path,
        local_platforms_check=True,
        requested_platforms=("postgresql",),
        bring_up_runner=fake_bring_up,
        reachability_checker=fake_reachable,
    )

    assert result.aborted is False
    assert calls == ["postgresql"]
    assert result.local_platforms_checked == ("postgresql",)
    assert result.local_platforms_attempted == ("postgresql",)
    assert any("recovered" in warning for warning in result.warnings)


def test_local_platforms_check_aborts_document_only_platform(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(preflight, "free_space_gib", lambda path: 100.0)
    monkeypatch.setattr(preflight, "docker_reachable", lambda: True)
    monkeypatch.setattr(preflight, "host_load_1m", lambda: 0.5)

    result = preflight.run_preflight(
        free_space_path=tmp_path,
        local_platforms_check=True,
        requested_platforms=("lakesail",),
        reachability_checker=lambda platform: False,
    )

    assert result.aborted is True
    assert "lakesail" in (result.abort_reason or "")
    assert "no automated UAT bring-up" in (result.abort_reason or "")


def test_preflight_config_accepts_local_platforms_check():
    cfg = config.validate_config({"name": "smoke", "preflight": {"local_platforms_check": True}})
    assert cfg.preflight.local_platforms_check is True


def test_requested_platforms_from_raw_matches_uat_defaults():
    assert preflight.requested_platforms_from_raw({"platforms": {"include": ["postgresql"]}}) == ("postgresql",)
    assert "duckdb" in preflight.requested_platforms_from_raw({})


def test_uat_bring_up_unknown_platform_returns_clear_error(capsys):
    module = _load_bring_up_module()
    rc = module.main(["--platform", "does-not-exist"])
    captured = capsys.readouterr()
    assert rc == 2
    assert "unknown platform" in captured.err


def test_make_platform_filter_does_not_trip_bring_up_validation():
    completed = subprocess.run(
        ["make", "-n", "uat-stress", "PLATFORM=duckdb", "CONFIG=tests/uat/configs/stress-default.yaml"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "unknown platform" not in completed.stderr


def test_uat_bring_up_velox_passes_benchmark_runs_dir_env(tmp_path: Path, monkeypatch, capsys):
    module = _load_bring_up_module()
    captured: dict[str, dict[str, str]] = {}

    def fake_run_docker_command(argv, **kwargs):
        captured["env"] = kwargs.get("env") or {}
        return module.docker_assets.DockerCommandResult(
            argv=tuple(argv), returncode=0, stdout="", stderr="", dry_run=True
        )

    monkeypatch.setattr(module.docker_assets, "run_docker_command", fake_run_docker_command)

    rc = module.main(["--platform", "velox", "--benchmark-runs-dir", str(tmp_path), "--dry-run"])

    assert rc == 0
    assert captured["env"] == {"BENCHBOX_DATA_DIR": str(tmp_path)}
    assert "UAT bring-up OK" in capsys.readouterr().out


def test_preflight_automated_set_matches_script_automated_set():
    """Preflight and the bring-up script must agree on which platforms are automated."""
    bring_up = _load_bring_up_module()

    assert bring_up.automated_platforms() == preflight.automated_local_platforms()
    assert bring_up.automated_platforms() == preflight.AUTOMATED_LOCAL_PLATFORMS


def _load_bring_up_module():
    path = Path("scripts/uat-bring-up/uat_bring_up.py").resolve()
    spec = importlib.util.spec_from_file_location("uat_bring_up", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
