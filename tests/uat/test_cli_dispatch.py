"""Fast-test coverage for tests/uat/_cli.py main dispatch."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.uat import _cli
from tests.uat.config import validate_config

pytestmark = pytest.mark.fast


def test_main_routes_subcommand(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_execute(args):
        calls.append((args.cmd, args.config))
        return 0

    monkeypatch.setattr(_cli, "_handle_execute", fake_execute)
    rc = _cli.main(["execute", "--config", "x.yaml"])
    assert rc == 0
    assert calls == [("execute", "x.yaml")]


def test_main_no_args_uses_cell_parser(capsys):
    rc = _cli.main([])
    assert rc == 2
    err = capsys.readouterr().err
    assert "cell" in err
    assert "--platform" in err


def test_main_bare_flags_route_to_cell(monkeypatch):
    """Backward-compat: `python -m tests.uat._cli --platform=...` is the uat-cell make target."""
    calls: list[tuple[str, str, float]] = []

    def fake_cell(args):
        calls.append((args.platform, args.benchmark, args.scale))
        return 0

    monkeypatch.setattr(_cli, "_handle_cell", fake_cell)
    rc = _cli.main(["--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"])
    assert rc == 0
    assert calls == [("duckdb", "tpch", 0.01)]


@pytest.mark.parametrize(("platform", "expected_local_managed"), [("pg-duckdb", True), ("duckdb", False)])
def test_cell_main_scopes_local_managed_platform_to_uat_docker_platforms(
    platform,
    expected_local_managed,
    monkeypatch,
    capsys,
):
    captured = {}

    def fake_run_cell(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            platform=kwargs["platform"],
            benchmark=kwargs["benchmark"],
            scale=kwargs["scale"],
            status="passed",
            exit_code=0,
            elapsed_s=0.1,
            log_path=Path("cell.log"),
            result_path=None,
            submit_terminal_state=None,
        )

    monkeypatch.setattr("tests.uat.runner.run_cell", fake_run_cell)

    rc = _cli.main(["cell", "--platform", platform, "--benchmark", "tpch", "--scale", "0.01"])

    assert rc == 0
    assert captured["local_managed_platform"] is expected_local_managed
    assert json.loads(capsys.readouterr().out)["platform"] == platform


def test_main_unknown_subcommand_returns_2(capsys):
    rc = _cli.main(["nonsense"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "invalid choice" in err


def test_main_help_returns_0(capsys):
    rc = _cli.main(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cell" in out
    assert "preflight" in out
    assert "replay-classify" in out


def test_main_preflight_returns_2_when_preflight_aborts(tmp_path, monkeypatch, capsys):
    config = validate_config({"name": "preflight-smoke", "preflight": {"free_space_min_gib": 1000.0}})

    def fake_run_preflight(**kwargs):
        return SimpleNamespace(
            disk_budget_summary="budget: high water mark 1 GiB",
            free_space_report=("Free space: tmp 10.00 GiB (required 5.00 GiB) /tmp",),
            warnings=("disk nearly full",),
            aborted=True,
            abort_reason="free space 0.1 GiB < cutoff 1000.0 GiB",
        )

    monkeypatch.setattr("tests.uat.config.load_config", lambda path: config)
    monkeypatch.setattr("tests.uat.phases.execute.default_benchmark_runs_dir", lambda cfg: tmp_path / "runs")
    monkeypatch.setattr("tests.uat.phases.preflight.run_preflight", fake_run_preflight)

    rc = _cli.main(["preflight", "--config", "uat.yaml"])

    captured = capsys.readouterr()
    assert rc == 2
    assert "budget: high water mark 1 GiB" in captured.out
    assert "Free space: tmp 10.00 GiB (required 5.00 GiB) /tmp" in captured.out
    assert "[preflight warn] disk nearly full" in captured.err
    assert "[preflight] ABORT: free space 0.1 GiB < cutoff 1000.0 GiB" in captured.err


def test_execute_and_sweep_use_same_preflight_kwargs(tmp_path, monkeypatch):
    config_path = tmp_path / "uat.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "preflight-kwargs"',
                "phases: [preflight, execute]",
                "platforms:",
                '  include: ["postgresql"]',
                "preflight:",
                "  free_space_min_gib: 12.5",
                f'  free_space_path: "{tmp_path / "free-space"}"',
                "  docker_required: true",
                "  noisy_neighbor_warn_load: 3.5",
                "  local_platforms_check: true",
                "output:",
                f'  benchmark_runs_dir_template: "{tmp_path / "runs"}"',
                f'  logs_dir_template: "{tmp_path / "logs" / "{name}-{date}"}"',
            ]
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    def fake_run_preflight(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            disk_budget_summary=None,
            free_space_report=(),
            warnings=(),
            aborted=True,
            abort_reason="stop after capturing preflight kwargs",
            exit_code=lambda: 2,
        )

    monkeypatch.setattr("tests.uat.phases.preflight.run_preflight", fake_run_preflight)

    execute_rc = _cli.main(["execute", "--config", str(config_path)])
    sweep_rc = _cli.main(["sweep", "--config", str(config_path)])

    assert execute_rc == 2
    assert sweep_rc == 2
    assert len(calls) == 2
    execute_kwargs = {key: value for key, value in calls[0].items() if key != "disk_budget_config"}
    sweep_kwargs = {key: value for key, value in calls[1].items() if key != "disk_budget_config"}
    assert execute_kwargs == sweep_kwargs
    assert calls[0]["disk_budget_config"] == calls[1]["disk_budget_config"]


def test_subcommands_table_covers_all_make_targets():
    """The parser must cover every make uat-* target's subcommand."""
    expected = {
        "cell",
        "docker-cleanup",
        "execute",
        "gate-check",
        "validate",
        "package",
        "explorer-smoke",
        "report",
        "sweep",
        "stress",
        "verify-tuning-matrix",
    }
    assert set(_cli.MAKE_TARGET_SUBCOMMANDS) == expected


def test_sweep_main_forwards_dry_run_override(monkeypatch, capsys):
    calls: list[tuple[Path, bool | None]] = []

    class StubResult:
        name = "stub"
        log_dir = Path("logs")
        aborted_phase = None
        abort_reason = None
        phase_exit_codes = {"execute": 0}

        def exit_code(self):
            return 0

    def fake_run_sweep_from_path(config_path, *, dry_run_override=None, stress_overrides=None):
        assert stress_overrides is None
        calls.append((config_path, dry_run_override))
        return StubResult()

    monkeypatch.setattr("tests.uat.orchestrator.run_sweep_from_path", fake_run_sweep_from_path)
    rc = _cli.main(["sweep", "--config", "tests/uat/configs/uat-2026-05-02.yaml", "--dry-run"])

    assert rc == 0
    assert calls == [(Path("tests/uat/configs/uat-2026-05-02.yaml"), True)]
    assert '"phase_exit_codes"' in capsys.readouterr().out


def test_stress_main_forwards_platform_benchmark_scale_as_stress_overrides(monkeypatch, capsys):
    """w3: _handle_stress routes through run_sweep_from_path(stress_overrides=...)
    instead of hand-duplicating the platform/benchmark/scale override logic.
    """
    calls: list[tuple[Path, dict]] = []

    class StubResult:
        name = "stub"
        log_dir = Path("logs")
        aborted_phase = None
        abort_reason = None
        phase_exit_codes = {"execute": 0}

        def exit_code(self):
            return 0

    def fake_run_sweep_from_path(config_path, *, dry_run_override=None, stress_overrides=None):
        assert dry_run_override is None
        calls.append((config_path, stress_overrides))
        return StubResult()

    monkeypatch.setattr("tests.uat.orchestrator.run_sweep_from_path", fake_run_sweep_from_path)
    rc = _cli.main(["stress", "--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.5"])

    assert rc == 0
    default_config_path = Path("tests/uat/_cli.py").resolve().parent / "configs" / "stress-default.yaml"
    assert calls == [(default_config_path, {"platform": "duckdb", "benchmark": "tpch", "scale": 0.5})]
    out = capsys.readouterr().out
    assert '"phase_exit_codes"' in out
    assert "abort_reason" not in out


def test_make_uat_sweep_forwards_dry_run_variable():
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("uat-sweep:", maxsplit=1)[1].split("# make uat-stress", maxsplit=1)[0]

    assert "[DRY_RUN=1]" in target
    assert "$(if $(DRY_RUN),--dry-run,)" in target


def test_make_uat_docker_cleanup_defaults_to_dry_run_and_supports_apply():
    dry_run = subprocess.run(
        ["make", "--no-print-directory", "-n", "uat-docker-cleanup"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    apply = subprocess.run(
        ["make", "--no-print-directory", "-n", "uat-docker-cleanup", "APPLY=1", "PREFIX=benchbox-uat-test"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert dry_run.returncode == 0, dry_run.stderr
    assert "docker-cleanup" in dry_run.stdout
    assert "--apply" not in dry_run.stdout
    assert apply.returncode == 0, apply.stderr
    assert '--prefix "benchbox-uat-test"' in apply.stdout
    assert "--apply" in apply.stdout


@pytest.mark.parametrize(
    ("target", "variables", "expected_fragment"),
    [
        (
            "uat-cell",
            ["PLATFORM=duckdb", "BENCHMARK=tpch", "SCALE=0.01"],
            '--platform "duckdb"',
        ),
        (
            "uat-stress",
            ["PLATFORM=duckdb", "BENCHMARK=tpch"],
            '--platform "duckdb"',
        ),
    ],
)
def test_make_uat_targets_accept_non_bring_up_platforms(target, variables, expected_fragment):
    result = subprocess.run(
        ["make", "--no-print-directory", "-n", target, *variables],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert expected_fragment in result.stdout
    assert "unknown platform" not in result.stderr


def test_make_uat_bring_up_unknown_platform_still_fails_clearly():
    result = subprocess.run(
        ["make", "--no-print-directory", "uat-bring-up", "PLATFORM=does-not-exist"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode != 0
    assert "unknown platform" in result.stderr.strip().splitlines()[-1]


def test_execute_main_reads_cleanup_config_for_standalone_path(tmp_path, monkeypatch, capsys):
    config_path = tmp_path / "uat.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "managed-cli"',
                "phases: [execute]",
                "platforms:",
                '  include: ["clickhouse-server"]',
                "benchmarks:",
                '  include: ["tpch"]',
                "scales:",
                "  rungs: [0.01]",
                "cleanup:",
                "  docker_manage_platforms: true",
                '  docker_platform_switch: "volumes"',
            ]
        ),
        encoding="utf-8",
    )
    captured: dict[str, object] = {}

    def fake_run_execute(config, **kwargs):
        captured["docker_manage_platforms"] = config.cleanup.docker_manage_platforms
        captured["docker_platform_switch"] = config.cleanup.docker_platform_switch
        captured["cleanup_enabled"] = kwargs["cleanup_enabled"]
        captured["free_space_checks_enabled"] = kwargs["free_space_checks_enabled"]
        return type(
            "ExecuteOutcome",
            (),
            {
                "results": (),
                "pruned": (),
                "skipped_unreachable": (),
                "docker_events": (),
                "aborted": False,
                "abort_reason": None,
                "exit_code": lambda self: 0,
            },
        )()

    monkeypatch.setattr("tests.uat.phases.execute.run_execute", fake_run_execute)
    rc = _cli.main(["execute", "--config", str(config_path)])

    assert rc == 0
    # free_space_checks_enabled is True even though "preflight" is absent from
    # `phases:` -- the disk gate is always-on for execute-bearing runs,
    # decoupled from phase-list membership (uat-disk-gate-always-on w1).
    assert captured == {
        "docker_manage_platforms": True,
        "docker_platform_switch": "volumes",
        "cleanup_enabled": True,
        "free_space_checks_enabled": True,
    }
    assert '"name": "managed-cli"' in capsys.readouterr().out


def test_uat_execute_and_execute_only_sweep_produce_identical_cells_jsonl(tmp_path, monkeypatch, capsys):
    """uat-execute-path-unification w2 parity requirement.

    Post-unification, both `make uat-execute` and `make uat-sweep` share
    `orchestrator.run_sweep`, so byte-identical cells.jsonl is largely a
    given. What this test actually pins is that `_handle_execute`'s
    config-scoping (phases narrowed to `[preflight?, execute]`, cleanup
    override applied) is cell-output-neutral, and it guards against a
    future change quietly re-diverging the two entry points.
    """
    from tests.uat.config import load_config
    from tests.uat.orchestrator import run_sweep
    from tests.uat.runner import CellResult

    def fake_run_cell(platform, benchmark, scale, **kwargs):
        return CellResult(
            platform=platform,
            benchmark=benchmark,
            scale=scale,
            status="passed",
            exit_code=0,
            elapsed_s=1.23,
            log_path=Path("/nonexistent/cell.log"),
            result_path=Path("/nonexistent/result.json"),
        )

    monkeypatch.setattr("tests.uat.phases.execute.run_cell", fake_run_cell)

    config_path = tmp_path / "uat.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "parity-smoke"',
                "phases: [execute]",
                "platforms:",
                '  include: ["duckdb"]',
                "benchmarks:",
                '  include: ["tpch"]',
                "scales:",
                "  rungs: [0.01]",
                "preflight:",
                "  free_space_min_gib: 0",
                "output:",
                f'  logs_dir_template: "{tmp_path / "execute-run"}"',
            ]
        ),
        encoding="utf-8",
    )

    rc = _cli.main(["execute", "--config", str(config_path)])
    assert rc == 0
    execute_summary = json.loads(capsys.readouterr().out)
    execute_log_dir = Path(execute_summary["log_dir"])

    sweep_config = load_config(config_path)
    sweep_log_dir = tmp_path / "sweep-run"
    run_sweep(sweep_config, log_dir_override=sweep_log_dir)

    execute_cells = (execute_log_dir / "cells.jsonl").read_text(encoding="utf-8")
    sweep_cells = (sweep_log_dir / "cells.jsonl").read_text(encoding="utf-8")
    assert execute_cells == sweep_cells

    execute_sidecar = (execute_log_dir / "cells.jsonl.accounting.json").read_text(encoding="utf-8")
    sweep_sidecar = (sweep_log_dir / "cells.jsonl.accounting.json").read_text(encoding="utf-8")
    assert execute_sidecar == sweep_sidecar


def test_execute_main_reports_success_for_dry_run_config(tmp_path, monkeypatch, capsys):
    """#1146 review: a `dry_run: true` config never invokes run_execute, so
    `result.execute_outcome` stays None -- but that's not an abort. Before
    this fix, `_handle_execute` treated a None outcome as *always* an abort
    and hardcoded exit 2, so `make uat-execute` on a dry-run config failed
    even though the (no-op) phase loop succeeded.
    """
    config_path = tmp_path / "uat.yaml"
    config_path.write_text(
        "\n".join(
            [
                'name: "dry-run-smoke"',
                "dry_run: true",
                "phases: [execute]",
                "platforms:",
                '  include: ["duckdb"]',
                "benchmarks:",
                '  include: ["tpch"]',
                "scales:",
                "  rungs: [0.01]",
                "output:",
                f'  logs_dir_template: "{tmp_path / "dry-run-execute"}"',
            ]
        ),
        encoding="utf-8",
    )

    def fail_run_execute(config, **kwargs):
        raise AssertionError("dry_run: true must not invoke run_execute")

    monkeypatch.setattr("tests.uat.phases.execute.run_execute", fail_run_execute)

    rc = _cli.main(["execute", "--config", str(config_path)])

    summary = json.loads(capsys.readouterr().out)
    assert summary["aborted"] is False
    assert summary["abort_reason"] is None
    assert rc == 0


# ---------------------------------------------------------------------------
# uat-release-gate-enforcement w3: gate-check subcommand.
# ---------------------------------------------------------------------------


def _write_stage(tmp_path: Path, index: int, name: str, completed_at: str, **overrides) -> Path:
    from tests.uat import gate_summary

    kwargs = {
        "config_name": name,
        "source_commit_sha": "abc123",
        "source_dirty": False,
        "container_engine": "docker",
        "completed_at": completed_at,
        "dry_run": False,
        "aborted": False,
        "abort_phase": None,
        "abort_reason": None,
        "phase_exit_codes": {"execute": 0, "validate": 0, "explorer_smoke": 0, "report": 0},
        "accounting": gate_summary.PhaseAccounting(attempted=5, passed=5, total_defined=5),
        "unreachable_is_estimated": False,
        "validator_clean_rate": 1.0,
        "validator_clean_rate_floor": 1.0,
        "validator_floor_breached": False,
        "cross_scale_clean_pairs": 10,
        "cross_scale_floor": 8,
        "cross_scale_floor_breached": False,
        "explorer_smoke_status": "ran",
        "verdict": "green",
    }
    kwargs.update(overrides)
    stage_dir = tmp_path / f"stage{index}"
    stage_dir.mkdir(exist_ok=True)
    gate_summary.write_gate_summary(stage_dir, gate_summary.GateSummary(**kwargs))
    return stage_dir


def test_gate_check_green_writes_combined_evidence(tmp_path: Path, capsys):
    s1 = _write_stage(tmp_path, 1, "release-gate-01-native-dataframe", "2026-07-10T10:00:00")
    s2 = _write_stage(tmp_path, 2, "release-gate-02-docker-nonoltp", "2026-07-10T12:00:00")
    s3 = _write_stage(tmp_path, 3, "release-gate-03-docker-oltp", "2026-07-10T14:00:00")
    (s2 / "uat_lifecycle.log").write_text(
        "2026-07-10T11:00:00 [docker] platform=starrocks action=up status=ok\n", encoding="utf-8"
    )
    (s3 / "uat_lifecycle.log").write_text(
        "2026-07-10T13:00:00 [docker] platform=postgresql action=up status=ok\n", encoding="utf-8"
    )
    output = tmp_path / "evidence" / "uat-gate-summary.json"

    rc = _cli.main(
        ["gate-check", "--stage1", str(s1), "--stage2", str(s2), "--stage3", str(s3), "--output", str(output)]
    )

    assert rc == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verdict"] == "green"
    assert payload["source_commit_sha"] == "abc123"
    assert payload["ordering_violations"] == []
    stdout = capsys.readouterr().out
    assert "APPROVE" in stdout


def test_gate_check_flags_docker_up_before_stage1_completion(tmp_path: Path, capsys):
    s1 = _write_stage(tmp_path, 1, "release-gate-01-native-dataframe", "2026-07-10T10:00:00")
    s2 = _write_stage(tmp_path, 2, "release-gate-02-docker-nonoltp", "2026-07-10T12:00:00")
    s3 = _write_stage(tmp_path, 3, "release-gate-03-docker-oltp", "2026-07-10T14:00:00")
    # Stage-2 Docker stack came up BEFORE stage 1 completed: the contamination
    # the 2026-05-28/29 evidence had.
    (s2 / "uat_lifecycle.log").write_text(
        "2026-07-10T09:00:00 [docker] platform=starrocks action=up status=ok\n", encoding="utf-8"
    )
    output = tmp_path / "evidence.json"

    rc = _cli.main(
        ["gate-check", "--stage1", str(s1), "--stage2", str(s2), "--stage3", str(s3), "--output", str(output)]
    )

    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verdict"] == "red"
    assert any("stage1 boundary" in violation for violation in payload["ordering_violations"])


def test_gate_check_flags_stage3_docker_up_before_stage2_completion(tmp_path: Path):
    s1 = _write_stage(tmp_path, 1, "release-gate-01-native-dataframe", "2026-07-10T10:00:00")
    s2 = _write_stage(tmp_path, 2, "release-gate-02-docker-nonoltp", "2026-07-10T12:00:00")
    s3 = _write_stage(tmp_path, 3, "release-gate-03-docker-oltp", "2026-07-10T14:00:00")
    # After stage 1, but stage 3's stack overlapped stage 2's window.
    (s3 / "uat_lifecycle.log").write_text(
        "2026-07-10T11:00:00 [docker] platform=postgresql action=up status=ok\n", encoding="utf-8"
    )
    output = tmp_path / "evidence.json"

    rc = _cli.main(
        ["gate-check", "--stage1", str(s1), "--stage2", str(s2), "--stage3", str(s3), "--output", str(output)]
    )

    assert rc == 1
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert any("stage2 boundary" in violation for violation in payload["ordering_violations"])


def test_gate_check_red_stage_blocks_and_reports_reason(tmp_path: Path, capsys):
    s1 = _write_stage(tmp_path, 1, "release-gate-01-native-dataframe", "2026-07-10T10:00:00")
    s2 = _write_stage(
        tmp_path,
        2,
        "release-gate-02-docker-nonoltp",
        "2026-07-10T12:00:00",
        verdict="red",
        phase_exit_codes={"execute": 1, "report": 1},
    )
    s3 = _write_stage(tmp_path, 3, "release-gate-03-docker-oltp", "2026-07-10T14:00:00")
    output = tmp_path / "evidence.json"

    rc = _cli.main(
        ["gate-check", "--stage1", str(s1), "--stage2", str(s2), "--stage3", str(s3), "--output", str(output)]
    )

    assert rc == 1
    assert "HOLD" in capsys.readouterr().err
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["verdict"] == "red"


def test_gate_check_missing_stage_summary_is_a_hard_error(tmp_path: Path, capsys):
    s1 = _write_stage(tmp_path, 1, "release-gate-01-native-dataframe", "2026-07-10T10:00:00")
    s2 = _write_stage(tmp_path, 2, "release-gate-02-docker-nonoltp", "2026-07-10T12:00:00")
    missing = tmp_path / "stage3-not-run"
    output = tmp_path / "evidence.json"

    rc = _cli.main(
        ["gate-check", "--stage1", str(s1), "--stage2", str(s2), "--stage3", str(missing), "--output", str(output)]
    )

    assert rc == 2
    assert not output.exists()
    assert "not found" in capsys.readouterr().err
