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
    assert captured == {
        "docker_manage_platforms": True,
        "docker_platform_switch": "volumes",
        "cleanup_enabled": True,
        "free_space_checks_enabled": False,
    }
    assert '"name": "managed-cli"' in capsys.readouterr().out
