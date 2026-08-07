"""Durability + SIGTERM teardown coverage for UAT sweeps.

uat-sweep-durability-and-signal-teardown:
  w1 -- incremental cells.jsonl append + atomic finalize marker; a report on an
        unfinalized (killed) run must never read green, while a marker-less
        legacy artifact still regenerates unchanged.
  w2 -- a sweep-process SIGTERM is upgraded to a Ctrl-C-equivalent cancellation
        so the platform `finally` teardown runs and the process exits nonzero.
  w3 -- the cancellation (signal name, phase, timestamp) is recorded in
        uat_lifecycle.log.
"""

from __future__ import annotations

import json
import signal
import sys
from collections.abc import Callable
from pathlib import Path
from types import FrameType
from typing import cast
from unittest.mock import patch

import pytest

# `test_timeouts` is imported for its real-process probe script and
# process-state predicates: they live with the module they exercise, and
# sharing them keeps one implementation instead of the verbatim `_pid_exists`
# copy this file used to carry.
from tests.uat import (
    _cli as uat_cli,
    cells_io,
    docker_assets,
    orchestrator,
    test_timeouts as timeouts_test,
    timeouts,
)
from tests.uat.config import validate_config
from tests.uat.phases import execute as exec_phase
from tests.uat.runner import CellResult

pytestmark = pytest.mark.fast


def _source_info() -> orchestrator.RunSourceInfo:
    return orchestrator.RunSourceInfo(commit_sha="deadbeef", commit_short_sha="deadbee", dirty=False)


def _passed_cell(platform: str, benchmark: str, scale: float, log_dir: Path) -> CellResult:
    return CellResult(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        status="passed",
        exit_code=0,
        elapsed_s=1.0,
        log_path=log_dir / f"{platform}_{benchmark}_{scale}.log",
        result_path=None,
    )


# --------------------------------------------------------------------------- w1


def test_disk_floor_runner_streams_each_row_before_a_mid_sweep_death(tmp_path: Path):
    """Incremental durability: a row is flushed to cells.jsonl the instant its
    cell completes, so a process death mid-sweep keeps every earned row instead
    of losing the whole in-memory batch. The lingering `.inprogress` marker (no
    `.finalized`) is how the run is later recognized as killed."""
    cells_jsonl = tmp_path / "cells.jsonl"
    writer = cells_io.CellStreamWriter(cells_jsonl, source_info=_source_info())
    attempted: list[CellResult] = []
    calls = {"n": 0}

    def base_runner(platform: str, benchmark: str, scale: float, **_kwargs) -> CellResult:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom: process dies mid-sweep")
        return _passed_cell(platform, benchmark, scale, tmp_path)

    runner = orchestrator._build_disk_floor_runner(
        base_runner,
        attempted_cells=attempted,
        watch_disk_floor=False,
        free_space_path=str(tmp_path),
        free_space_min_gib=0.0,
        cell_stream=writer.append,
    )

    runner("duckdb", "tpch", 0.01)
    with pytest.raises(RuntimeError):
        runner("duckdb", "tpch", 0.1)

    rows = cells_io.read_cells_jsonl(cells_jsonl)
    assert [(r.platform, r.scale) for r in rows] == [("duckdb", 0.01)]
    assert cells_io.cells_run_incomplete(cells_jsonl) is True
    assert cells_io.cells_are_finalized(cells_jsonl) is False


def test_write_cells_jsonl_finalizes_and_clears_inprogress(tmp_path: Path):
    """An orderly complete write drops the finalize marker and clears the
    in-progress one, so the run is unambiguously finished."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_io.write_cells_inprogress_marker(cells_jsonl)
    assert cells_io.cells_inprogress_path(cells_jsonl).exists()

    cells_io.write_cells_jsonl(
        cells_jsonl,
        [_passed_cell("duckdb", "tpch", 0.01, tmp_path)],
        source_info=_source_info(),
    )

    assert cells_io.cells_are_finalized(cells_jsonl) is True
    assert cells_io.cells_inprogress_path(cells_jsonl).exists() is False
    assert cells_io.cells_run_incomplete(cells_jsonl) is False
    marker = cells_io.read_cells_finalized_marker(cells_jsonl)
    assert marker is not None and marker["row_count"] == 1


def test_stream_writer_reset_clears_stale_finalized_marker_on_dir_reuse(tmp_path: Path):
    """A CellStreamWriter that reuses a log dir from a previous *completed* run
    must start from an empty stream and clear the stale `.finalized` marker, so
    a rerun killed mid-sweep is recognized as INCOMPLETE instead of inheriting
    the prior run's finalized signal + stale rows (PR #1251 review follow-up)."""
    cells_jsonl = tmp_path / "cells.jsonl"

    # Model a prior completed run left behind in this (reused) directory.
    cells_io.write_cells_jsonl(
        cells_jsonl,
        [_passed_cell("duckdb", "tpch", 0.01, tmp_path)],
        source_info=_source_info(),
    )
    assert cells_io.cells_are_finalized(cells_jsonl) is True

    # Starting a new durable stream in the same dir resets it before marking in
    # progress: the stale finalize marker and prior rows are gone.
    writer = cells_io.CellStreamWriter(cells_jsonl, source_info=_source_info())
    assert cells_io.cells_are_finalized(cells_jsonl) is False
    assert cells_io.cells_run_incomplete(cells_jsonl) is True
    assert not cells_jsonl.exists()

    # A row from the new run, then a mid-sweep death (never finalized): only the
    # new row is durable, and the run is still recognized as killed/incomplete.
    writer.append(_passed_cell("duckdb", "tpch", 0.1, tmp_path))
    rows = cells_io.read_cells_jsonl(cells_jsonl)
    assert [(r.platform, r.scale) for r in rows] == [("duckdb", 0.1)]
    assert cells_io.cells_run_incomplete(cells_jsonl) is True


def test_report_rejects_unfinalized_killed_run_as_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """make uat-report on a killed run (rows + lingering `.inprogress`, no
    `.finalized`) must exit nonzero and mark the run INCOMPLETE -- a partial
    stream of all-passed rows must never read as a clean sweep."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_jsonl.write_text(
        json.dumps(
            {
                "platform": "duckdb",
                "benchmark": "tpch",
                "scale": 0.01,
                "status": "passed",
                "exit_code": 0,
                "elapsed_s": 1.0,
                "log_path": "/tmp/a.log",
                "result_path": "/tmp/a.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cells_io.write_cells_inprogress_marker(cells_jsonl)  # killed: never finalized
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["finalized"] is False
    assert "run_status=INCOMPLETE" in output_tsv.read_text(encoding="utf-8")


def test_report_on_killed_run_with_no_rows_reports_incomplete(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """A sweep SIGTERM'd during its first cell leaves the `.inprogress` marker
    but no cells.jsonl rows yet. make uat-report must treat the missing stream
    as an empty incomplete run and emit INCOMPLETE, not crash with
    FileNotFoundError before the marker check (PR #1251 review follow-up)."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_io.write_cells_inprogress_marker(cells_jsonl)  # started; no rows written yet
    assert not cells_jsonl.exists()
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["finalized"] is False
    assert "run_status=INCOMPLETE" in output_tsv.read_text(encoding="utf-8")


def test_report_on_missing_stream_without_marker_is_a_hard_error(tmp_path: Path):
    """A missing cells.jsonl with NEITHER marker is a wrong --cells-jsonl path
    or a pruned artifact, not an interrupted sweep. make uat-report must raise
    rather than regenerate an empty COMPLETED (green) report, so a typo cannot
    produce a passing UAT report (PR #1259 review follow-up)."""
    cells_jsonl = tmp_path / "typo_cells.jsonl"
    assert not cells_jsonl.exists()
    assert not cells_io.cells_inprogress_path(cells_jsonl).exists()
    output_tsv = tmp_path / "matrix_summary.tsv"

    with pytest.raises(FileNotFoundError):
        uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    assert not output_tsv.exists()


def test_report_regenerates_marker_less_legacy_artifact_unchanged(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    """A legacy cells.jsonl carrying NEITHER marker predates the finalize
    machinery; the report must still regenerate it green, not conflate
    "no marker" with "killed"."""
    cells_jsonl = tmp_path / "cells.jsonl"
    cells_jsonl.write_text(
        json.dumps(
            {
                "platform": "duckdb",
                "benchmark": "tpch",
                "scale": 0.01,
                "status": "passed",
                "exit_code": 0,
                "elapsed_s": 1.0,
                "log_path": "/tmp/a.log",
                "result_path": "/tmp/a.json",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_tsv = tmp_path / "matrix_summary.tsv"

    exit_code = uat_cli.main(["report", "--cells-jsonl", str(cells_jsonl), "--output-tsv", str(output_tsv)])

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["finalized"] is True


# ------------------------------------------------------------------------ w2/w3


def test_sigterm_shim_raises_sweepcancelled_and_records_cancellation(tmp_path: Path):
    """The installed SIGTERM handler raises SweepCancelled (a KeyboardInterrupt
    subclass) and records the cancellation with signal name + phase to
    uat_lifecycle.log before unwinding."""
    phase_holder: list[str | None] = ["execute"]
    previous = orchestrator._install_sweep_sigterm_shim(tmp_path, phase_holder)
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        # signal.getsignal returns an opaque callable union; give it the real
        # handler signature so the call type-checks (ty call-top-callable).
        typed_handler = cast(Callable[[int, FrameType | None], None], handler)
        with pytest.raises(orchestrator.SweepCancelled) as excinfo:
            typed_handler(int(signal.SIGTERM), None)
        assert excinfo.value.signal_name == "SIGTERM"
        assert isinstance(excinfo.value, KeyboardInterrupt)
    finally:
        orchestrator._restore_sweep_sigterm_shim(previous)

    log_text = (tmp_path / "uat_lifecycle.log").read_text(encoding="utf-8")
    assert "[cancel] signal=SIGTERM phase=execute" in log_text
    # Handler restored so the shim does not leak across sweeps / tests.
    assert signal.getsignal(signal.SIGTERM) == previous


def test_run_sweep_restores_previous_sigterm_handler(tmp_path: Path):
    """run_sweep installs its shim for the run and always restores the prior
    handler, even on the (dry-run) happy path."""
    before = signal.getsignal(signal.SIGTERM)
    cfg = validate_config(
        {
            "name": "dry-run-shim",
            "phases": ["execute", "report"],
            "platforms": {"include": ["duckdb"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "dry_run": True,
        }
    )
    orchestrator.run_sweep(cfg, log_dir_override=tmp_path / "logs")
    assert signal.getsignal(signal.SIGTERM) == before


def test_interrupt_mid_cell_still_tears_down_docker_stack(tmp_path: Path):
    """A Ctrl-C / SIGTERM landing mid-cell must still run the platform
    `finally` teardown (compose down) before the interrupt propagates -- the
    exact behavior the SIGTERM shim upgrades a `kill` to."""
    cfg = validate_config(
        {
            "name": "interrupt-teardown",
            "platforms": {"include": ["clickhouse-server"]},
            "benchmarks": {"include": ["tpch"]},
            "scales": {"rungs": [0.01]},
            "cleanup": {"docker_manage_platforms": True, "docker_platform_switch": "volumes"},
        }
    )
    sequence: list[str] = []

    def fake_docker(argv, **_kwargs):
        # Classify up/ps/down, not just up/down: the post-start readiness
        # `compose ps` re-check must not be recorded as a teardown, or the
        # ordering assertion below matches that instead of the real `down`
        # (same three-way classify as test_phases.py's `_docker_verb`).
        action = "up" if "up" in argv else ("ps" if "ps" in argv else "down")
        sequence.append(action)
        return docker_assets.DockerCommandResult(tuple(argv), 0, "", "")

    def interrupting_runner(platform, benchmark, scale, **_kwargs):
        sequence.append("cell")
        raise KeyboardInterrupt

    with patch("tests.uat.phases.execute.platform_is_reachable", return_value=True):
        with pytest.raises(KeyboardInterrupt):
            exec_phase.run_execute(
                cfg,
                log_dir=tmp_path,
                databases_root=tmp_path / "databases",
                runner=interrupting_runner,
                docker_runner=fake_docker,
                free_space_checks_enabled=False,
                sleep_fn=lambda _s: None,
            )

    assert "cell" in sequence and "down" in sequence
    assert sequence.index("down") > sequence.index("cell")


# --------------------------------------------------------------------- w2/w4 (uat-cell-teardown-orphans-child-processes-20260805)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal/process-group behavior")
def test_sweep_cancel_reaps_orphaned_child_no_survivor(tmp_path: Path):
    """A cancelled sweep leaves no surviving descendant process.

    The end-to-end wiring test: the real sweep-process SIGTERM shim
    (`orchestrator._install_sweep_sigterm_shim`, the exact handler
    `run_sweep` installs) raising the real `SweepCancelled` through the real
    `timeouts.run_with_timeout` (the exact wrapper `runner.run_cell` uses --
    the call site is `tests/uat/runner.py`, NOT `phases/execute.py`, which
    never imports it), at the production timeout, around a real child that
    owns a real grandchild and traps SIGTERM the way a cell's database
    server does.

    Note what this test does NOT cover: it calls `run_with_timeout`
    directly, so it says nothing about whether `run_cell` is still wired to
    it. That consumer is pinned separately in
    `tests/uat/test_runner_timeout_process_group.py`; without it,
    re-pointing runner's import at a pre-#1630 implementation left this test
    (and 600 others) green.

    The unit-level equivalents in test_timeouts.py pin the same behavior
    against a locally defined `KeyboardInterrupt` subclass; this one proves
    the orchestrator's actual exception type reaches the guard, which is the
    whole premise of the fix -- `SweepCancelled` is not an `Exception`, so
    `except subprocess.TimeoutExpired` never saw it and the descendant tree
    survived.
    """
    phase_holder: list[str | None] = ["execute"]
    previous_sigterm = orchestrator._install_sweep_sigterm_shim(tmp_path, phase_holder)
    sigterm_handler = signal.getsignal(signal.SIGTERM)
    ready_path = tmp_path / "child.ready"
    child_pid_path = tmp_path / "child.pid"
    grandchild_pid_path = tmp_path / "grandchild.pid"
    argv = [
        sys.executable,
        "-c",
        timeouts_test._CANCEL_PROBE_SRC,
        str(child_pid_path),
        str(grandchild_pid_path),
        str(tmp_path / "child.sigterm"),
        str(ready_path),
        timeouts_test._GRANDCHILD_SRC,
    ]
    ticks = {"count": 0}

    def _deliver_cancellation(signum: int, frame: FrameType | None) -> None:
        # Fire the exact SIGTERM handler the orchestrator installed, from a
        # SIGALRM tick landing while the main thread is blocked inside
        # run_with_timeout's communicate() -- the same real scenario an
        # operator `kill` on the sweep process produces. No-op until the
        # probe reports ready so the grandchild is guaranteed to exist by
        # the time the cancellation lands, on a loaded machine too.
        ticks["count"] += 1
        if not ready_path.exists():
            if ticks["count"] >= timeouts_test._PROBE_MAX_TICKS:
                signal.setitimer(signal.ITIMER_REAL, 0)
                raise AssertionError("probe never reported readiness")
            return
        signal.setitimer(signal.ITIMER_REAL, 0)
        typed_handler = cast(Callable[[int, FrameType | None], None], sigterm_handler)
        typed_handler(signal.SIGTERM, frame)

    previous_alarm = signal.signal(signal.SIGALRM, _deliver_cancellation)
    signal.setitimer(signal.ITIMER_REAL, timeouts_test._PROBE_TICK_S, timeouts_test._PROBE_TICK_S)
    try:
        with pytest.raises(orchestrator.SweepCancelled) as cancelled:
            timeouts.run_with_timeout(argv, timeout_s=timeouts_test._PRODUCTION_LIKE_TIMEOUT_S)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_alarm)
        orchestrator._restore_sweep_sigterm_shim(previous_sigterm)

    child_pid = int(child_pid_path.read_text(encoding="utf-8"))
    grandchild_pid = int(grandchild_pid_path.read_text(encoding="utf-8"))
    assert timeouts_test._await_process_state(grandchild_pid, {timeouts_test._PROC_GONE}) == timeouts_test._PROC_GONE
    assert timeouts_test._await_process_state(child_pid, {timeouts_test._PROC_GONE}) == timeouts_test._PROC_GONE
    # Keeps run_with_timeout's `proc` local reachable through the traceback
    # for the duration of the assertions above; see _run_cancelled_probe.
    assert isinstance(cancelled.value, orchestrator.SweepCancelled)
