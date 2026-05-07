"""Fast-test coverage for tests/uat/_cli.py main dispatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.uat import _cli

pytestmark = pytest.mark.fast


def test_main_routes_subcommand(monkeypatch):
    calls: list[tuple[str, list[str]]] = []

    def fake_execute_main(argv):
        calls.append(("execute", argv))
        return 0

    monkeypatch.setitem(_cli.SUBCOMMANDS, "execute", fake_execute_main)
    rc = _cli.main(["execute", "--config", "x.yaml"])
    assert rc == 0
    assert calls == [("execute", ["--config", "x.yaml"])]


def test_main_no_args_routes_to_cell(monkeypatch):
    calls: list[list[str]] = []

    def fake_cell_main(argv):
        calls.append(argv)
        return 0

    monkeypatch.setitem(_cli.SUBCOMMANDS, "cell", fake_cell_main)
    monkeypatch.setattr(_cli, "cell_main", fake_cell_main)
    rc = _cli.main([])
    assert rc == 0
    assert calls == [[]]


def test_main_bare_flags_route_to_cell(monkeypatch):
    """Backward-compat: `python -m tests.uat._cli --platform=...` is the uat-cell make target."""
    calls: list[list[str]] = []

    def fake_cell_main(argv):
        calls.append(argv)
        return 0

    monkeypatch.setattr(_cli, "cell_main", fake_cell_main)
    rc = _cli.main(["--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"])
    assert rc == 0
    assert calls == [["--platform", "duckdb", "--benchmark", "tpch", "--scale", "0.01"]]


def test_main_unknown_subcommand_returns_2(capsys):
    rc = _cli.main(["nonsense"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "unknown subcommand" in err


def test_main_help_returns_0(capsys):
    rc = _cli.main(["--help"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "subcommands" in out


def test_subcommands_table_covers_all_make_targets():
    """The dispatch table must cover every make uat-* target's subcommand."""
    expected = {
        "cell",
        "execute",
        "validate",
        "package",
        "explorer-smoke",
        "report",
        "sweep",
        "stress",
    }
    assert set(_cli.SUBCOMMANDS) == expected


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
    rc = _cli.sweep_main(["--config", "tests/uat/configs/uat-2026-05-02.yaml", "--dry-run"])

    assert rc == 0
    assert calls == [(Path("tests/uat/configs/uat-2026-05-02.yaml"), True)]
    assert '"phase_exit_codes"' in capsys.readouterr().out


def test_make_uat_sweep_forwards_dry_run_variable():
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("uat-sweep:", maxsplit=1)[1].split("# make uat-stress", maxsplit=1)[0]

    assert "[DRY_RUN=1]" in target
    assert "$(if $(DRY_RUN),--dry-run,)" in target


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
            },
        )()

    monkeypatch.setattr("tests.uat.phases.execute.run_execute", fake_run_execute)
    rc = _cli.execute_main(["--config", str(config_path)])

    assert rc == 0
    assert captured == {
        "docker_manage_platforms": True,
        "docker_platform_switch": "volumes",
        "cleanup_enabled": True,
        "free_space_checks_enabled": False,
    }
    assert '"name": "managed-cli"' in capsys.readouterr().out
