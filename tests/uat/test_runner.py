"""Fast-test coverage for tests/uat/runner.py."""

from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.uat import runner
from tests.uat.artifact_hygiene import LocalArtifactGrowthError
from tests.uat.timeouts import TimeoutResult

pytestmark = pytest.mark.fast


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch):
    """Keep run_cell's hygiene snapshot off the real repo tree.

    run_cell() defaults benchmark_runs_dir to a home-directory root outside
    any worktree (see runner._default_benchmark_runs_dir), so the artifact
    hygiene guard is armed for every call and snapshots cwd/benchmark_runs.
    Without isolating cwd here, that snapshot targets the real, shared
    worktree directory, which concurrent pytest-xdist workers or leftover
    manual runs can mutate mid-test, causing spurious LocalArtifactGrowthError
    failures unrelated to what the test is exercising.
    """
    monkeypatch.chdir(tmp_path)


def _write_result_json(path: Path, *, failed: int = 0, compliance_class: str | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    passed = 1 if failed == 0 else 0
    payload = {
        "version": "2.1",
        "run": {
            "id": "uat-test",
            "timestamp": "2026-01-01T00:00:00",
            "total_duration_ms": 1,
            "query_time_ms": 1,
            "iterations": 1,
            "streams": 1,
        },
        "benchmark": {
            "id": "tpch",
            "name": "TPC-H",
            "scale_factor": 0.01,
            "test_type": "power",
        },
        "platform": {"name": "DuckDB"},
        "summary": {
            "queries": {"total": 1, "passed": passed, "failed": failed},
            "validation": {"status": "passed" if failed == 0 else "failed"},
        },
        "queries": [{"id": "Q1", "status": "SUCCESS" if failed == 0 else "ERROR", "execution_time_ms": 1}],
        "phases": {},
    }
    if compliance_class is not None:
        payload["benchmark"]["compliance_class"] = compliance_class
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_last_nonempty_output_line_picks_last_subprocess_line():
    log = """\
# uv run -- benchbox run --quiet
# BENCHBOX_OUTPUT_DIR=/tmp/shared-runs
[info] running...
[trace] retry...
/Users/joe/Developer/benchmark_runs/results/duckdb_tpch_20260502_FINAL.json
"""
    out = runner.last_nonempty_output_line(log)
    assert out == "/Users/joe/Developer/benchmark_runs/results/duckdb_tpch_20260502_FINAL.json"


def test_last_nonempty_output_line_accepts_custom_runs_root():
    log = "/tmp/shared-runs/results/duckdb_tpch_custom_root.json\n"
    assert runner.last_nonempty_output_line(log) == "/tmp/shared-runs/results/duckdb_tpch_custom_root.json"


def test_last_nonempty_output_line_returns_none_when_only_uat_comments():
    log = """\
# uv run -- benchbox run --quiet
# BENCHBOX_OUTPUT_DIR=/tmp/shared-runs
"""
    assert runner.last_nonempty_output_line(log) is None


def test_last_nonempty_output_line_returns_none_when_missing():
    assert runner.last_nonempty_output_line("") is None


def test_run_cell_writes_log_and_returns_result(tmp_path: Path):
    """Drive run_cell against a stub `benchbox run` (here: python -c)."""
    result_path = tmp_path / "benchmark_runs" / "results" / "duckdb_tpch_smoke.json"
    _write_result_json(result_path)
    fake_argv = [
        sys.executable,
        "-c",
        f"print({str(result_path)!r})",
    ]
    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            now=_dt.datetime(2026, 5, 5, 12, 0, 0),
        )

    assert result.status == "passed"
    assert result.exit_code == 0
    assert result.result_path is not None
    assert str(result.result_path).endswith("duckdb_tpch_smoke.json")
    assert result.log_path.exists()
    log_text = result.log_path.read_text()
    assert "benchmark_runs/results/" in log_text


def test_run_cell_sets_benchbox_output_dir_for_subprocess(tmp_path: Path):
    result_path = tmp_path / "shared-runs" / "results" / "duckdb_tpch_env.json"
    _write_result_json(result_path)
    fake_argv = [sys.executable, "-c", "print('unused')"]
    captured = {}

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        captured["env"] = env
        captured["argv"] = argv
        return TimeoutResult(
            exit_code=0,
            timed_out=False,
            elapsed_s=0.1,
            stdout=f"{result_path}\n".encode(),
            stderr=b"[warning] ignored stderr after quiet stdout\n",
        )

    def fake_benchbox_run_argv(*args, extra_args=(), **kwargs):
        return [*fake_argv, *extra_args]

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            benchmark_runs_dir=tmp_path / "shared-runs",
            now=_dt.datetime(2026, 5, 5, 12, 0, 0),
        )

    assert result.status == "passed"
    assert result.result_path == result_path
    assert captured["env"]["BENCHBOX_OUTPUT_DIR"] == str(tmp_path / "shared-runs")
    assert captured["argv"][-2:] == ["--output", str(tmp_path / "shared-runs" / "datagen")]
    log_text = result.log_path.read_text()
    assert "BENCHBOX_OUTPUT_DIR=" in log_text
    assert "ignored stderr" in log_text


@pytest.mark.parametrize("local_managed_platform", [False, True])
def test_run_cell_forwards_local_managed_platform_scope(local_managed_platform: bool, tmp_path: Path):
    captured = {}

    def fake_benchbox_run_argv(*args, **kwargs):
        captured["local_managed_platform"] = kwargs["local_managed_platform"]
        return [sys.executable, "-c", "print('unused')"]

    with patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv):
        runner.run_cell(
            "postgresql",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            local_managed_platform=local_managed_platform,
        )

    assert captured["local_managed_platform"] is local_managed_platform


def test_run_cell_defaults_benchbox_output_dir_to_shared(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
    fake_argv = [sys.executable, "-c", "print('unused')"]
    captured = {}

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        captured["env"] = env
        return TimeoutResult(exit_code=0, timed_out=False, elapsed_s=0.1, stdout=b"")

    with (
        patch.object(runner, "benchbox_run_argv", return_value=fake_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            now=_dt.datetime(2026, 5, 5, 12, 0, 0),
        )

    assert captured["env"]["BENCHBOX_OUTPUT_DIR"] == str(Path.home() / "Developer" / "benchmark_runs")


def test_run_cell_marks_failure(tmp_path: Path):
    fake_argv = [sys.executable, "-c", "import sys; sys.exit(2)"]
    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)
    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.result_path is None


def test_run_cell_diagnostic_rerun_fires_for_empty_stdout_failure(tmp_path: Path):
    captured_quiet = []

    def fake_benchbox_run_argv(*args, quiet=True, **kwargs):
        captured_quiet.append(quiet)
        return [sys.executable, "-c", "unused"]

    outcomes = [
        TimeoutResult(exit_code=2, timed_out=False, elapsed_s=0.1, stdout=b"", stderr=b""),
        TimeoutResult(exit_code=2, timed_out=False, elapsed_s=0.1, stdout=b"diagnostic detail\n", stderr=None),
    ]

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        return outcomes.pop(0)

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert result.status == "failed"
    assert result.exit_code == 2
    assert captured_quiet == [True, False]
    log_text = result.log_path.read_text()
    assert "verbose diagnostic re-run" in log_text
    assert "diagnostic detail" in log_text


def test_run_cell_skips_diagnostic_rerun_when_failure_has_stderr(tmp_path: Path):
    captured_quiet = []

    def fake_benchbox_run_argv(*args, quiet=True, **kwargs):
        captured_quiet.append(quiet)
        return [sys.executable, "-c", "unused"]

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        if stderr is not None:
            stderr.write("uv run warning on stderr\n")
        return TimeoutResult(
            exit_code=2,
            timed_out=False,
            elapsed_s=0.1,
            stdout=b"",
            stderr=None,
        )

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert result.status == "failed"
    assert captured_quiet == [True]
    log_text = result.log_path.read_text()
    assert "uv run warning on stderr" in log_text
    assert "verbose diagnostic re-run" not in log_text


def test_run_cell_skips_diagnostic_rerun_for_real_stderr_only_failure(tmp_path: Path):
    captured_quiet = []

    def fake_benchbox_run_argv(*args, quiet=True, **kwargs):
        captured_quiet.append(quiet)
        return [
            sys.executable,
            "-c",
            "import sys; sys.stderr.write('stderr diagnostic\\n'); sys.exit(2)",
        ]

    with patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert result.status == "failed"
    assert result.exit_code == 2
    assert captured_quiet == [True]
    log_text = result.log_path.read_text()
    assert "stderr diagnostic" in log_text
    assert "verbose diagnostic re-run" not in log_text


def test_run_cell_diagnostic_rerun_fires_when_failure_has_only_whitespace_stderr(tmp_path: Path):
    captured_quiet = []

    def fake_benchbox_run_argv(*args, quiet=True, **kwargs):
        captured_quiet.append(quiet)
        return [sys.executable, "-c", "unused"]

    outcomes = [
        TimeoutResult(exit_code=2, timed_out=False, elapsed_s=0.1, stdout=b"", stderr=b"\n"),
        TimeoutResult(exit_code=2, timed_out=False, elapsed_s=0.1, stdout=b"diagnostic detail\n", stderr=None),
    ]

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        return outcomes.pop(0)

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert result.status == "failed"
    assert captured_quiet == [True, False]
    assert "diagnostic detail" in result.log_path.read_text()


def test_run_cell_skips_diagnostic_rerun_when_failure_has_stdout(tmp_path: Path):
    captured_quiet = []

    def fake_benchbox_run_argv(*args, quiet=True, **kwargs):
        captured_quiet.append(quiet)
        return [sys.executable, "-c", "unused"]

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        return TimeoutResult(
            exit_code=2,
            timed_out=False,
            elapsed_s=0.1,
            stdout=b"already diagnostic stdout\n",
            stderr=b"incidental stderr\n",
        )

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert result.status == "failed"
    assert captured_quiet == [True]
    log_text = result.log_path.read_text()
    assert "already diagnostic stdout" in log_text
    assert "incidental stderr" in log_text
    assert "verbose diagnostic re-run" not in log_text


def test_run_cell_diagnostic_rerun_error_does_not_mask_original_failure(tmp_path: Path):
    def fake_benchbox_run_argv(*args, quiet=True, **kwargs):
        return [sys.executable, "-c", "unused"]

    calls = 0

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            return TimeoutResult(exit_code=2, timed_out=False, elapsed_s=0.1, stdout=b"", stderr=b"")
        raise RuntimeError("diagnostic boom")

    with (
        patch.object(runner, "benchbox_run_argv", side_effect=fake_benchbox_run_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert result.status == "failed"
    assert result.exit_code == 2
    assert calls == 2
    assert "diagnostic re-run error RuntimeError: diagnostic boom" in result.log_path.read_text()


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX timeout semantics")
def test_run_cell_marks_timeout(tmp_path: Path):
    fake_argv = [sys.executable, "-c", "import time; time.sleep(3)"]
    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=1, log_dir=tmp_path)
    assert result.status == "timed-out"
    assert result.exit_code == 124  # EXIT_TIMEOUT
    assert "UAT_TIMEOUT timeout_s=1 exit_code=124" in result.log_path.read_text()


def test_run_cell_flags_local_datagen_leak_under_external_root(monkeypatch, tmp_path: Path):
    """run_cell fails loudly when a subprocess leaks datagen into cwd/benchmark_runs."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    external = tmp_path / "ext"
    external.mkdir()
    monkeypatch.chdir(worktree)

    leaked_dir = worktree / "benchmark_runs" / "datagen" / "tpch_sf001"

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        leaked_dir.mkdir(parents=True, exist_ok=True)
        (leaked_dir / "lineitem.tbl").write_bytes(b"x" * 4096)
        return TimeoutResult(exit_code=0, timed_out=False, elapsed_s=0.1)

    fake_argv = [sys.executable, "-c", "print('unused')"]
    with (
        patch.object(runner, "benchbox_run_argv", return_value=fake_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
        pytest.raises(LocalArtifactGrowthError) as excinfo,
    ):
        runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path / "logs",
            benchmark_runs_dir=external,
            now=_dt.datetime(2026, 6, 1, 12, 0, 0),
        )

    message = str(excinfo.value)
    assert str(external) in message
    assert str(worktree / "benchmark_runs") in message
    # Report-only: the leaked artifact is left untouched.
    assert (leaked_dir / "lineitem.tbl").exists()


def test_run_cell_local_root_run_is_not_guarded(monkeypatch, tmp_path: Path):
    """A run whose output root is inside cwd is a local run; the guard stays off."""
    worktree = tmp_path / "wt"
    worktree.mkdir()
    monkeypatch.chdir(worktree)
    local_runs = worktree / "benchmark_runs"

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        target = local_runs / "datagen" / "tpch_sf001"
        target.mkdir(parents=True, exist_ok=True)
        (target / "lineitem.tbl").write_bytes(b"x" * 4096)
        return TimeoutResult(exit_code=0, timed_out=False, elapsed_s=0.1)

    fake_argv = [sys.executable, "-c", "print('unused')"]
    with (
        patch.object(runner, "benchbox_run_argv", return_value=fake_argv),
        patch.object(runner, "run_with_timeout", side_effect=fake_run_with_timeout),
    ):
        # Output root inside the worktree => local run => no LocalArtifactGrowthError.
        # (Reaching this point without an exception is the assertion.)
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path / "logs",
            benchmark_runs_dir=local_runs,
            now=_dt.datetime(2026, 6, 1, 12, 0, 0),
        )
    assert isinstance(result, runner.CellResult)
    # The local write is left untouched — the guard is off, not silently cleaning.
    assert (local_runs / "datagen" / "tpch_sf001" / "lineitem.tbl").exists()


def test_default_log_dir_honours_benchbox_output_dir(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(tmp_path))
    out = runner._default_log_dir(_dt.datetime(2026, 5, 5))
    assert out == tmp_path / "logs" / "uat_20260505"


def test_classify_for_submit_vocabulary_and_clean_result(tmp_path: Path):
    result_path = tmp_path / "benchmark_runs" / "results" / "clean.json"
    _write_result_json(result_path)

    assert runner.classify_for_submit(result_path) is runner.SubmitTerminalState.submittable
    assert set(runner.SubmitTerminalState.__members__) == {
        "submittable",
        "unofficial",
        "query_failure",
        "schema_violation",
        "missing_manifest",
    }


def test_classify_for_submit_marks_query_failure_and_run_cell_failed(tmp_path: Path):
    result_path = tmp_path / "benchmark_runs" / "results" / "failed-query.json"
    _write_result_json(result_path, failed=1)
    fake_argv = [sys.executable, "-c", f"print({str(result_path)!r})"]

    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpch", 0.01, timeout_s=10, log_dir=tmp_path)

    assert runner.classify_for_submit(result_path) is runner.SubmitTerminalState.query_failure
    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.submit_terminal_state == "query_failure"


def test_classify_for_submit_keeps_unofficial_as_passed_cell(tmp_path: Path):
    result_path = tmp_path / "benchmark_runs" / "results" / "unofficial.json"
    _write_result_json(result_path, compliance_class="unofficial_subscale")
    fake_argv = [sys.executable, "-c", f"print({str(result_path)!r})"]

    with patch.object(runner, "benchbox_run_argv", return_value=fake_argv):
        result = runner.run_cell("duckdb", "tpcds", 0.01, timeout_s=10, log_dir=tmp_path)

    assert runner.classify_for_submit(result_path) is runner.SubmitTerminalState.unofficial
    assert result.status == "passed"
    assert result.submit_terminal_state == "unofficial"


# ---------------------------------------------------------------------------
# w1: official/throughput status guard (uat-status-taxonomy-exit-code-fixes).
#
# Regression coverage for finding 1: the throughput validation block used to
# set status="failed" unconditionally whenever no result JSON was resolved,
# silently overwriting a "timed-out" classification and corrupting
# downstream terminal_state()/cells.jsonl accounting. The fix mirrors the
# existing `if status == "passed"` guard on the submit-classification
# downgrade a few lines above (runner.py:258).
# ---------------------------------------------------------------------------


def _fake_run_with_timeout_factory(*, exit_code: int, timed_out: bool):
    """Fabricate a TimeoutResult so the fast lane never spawns a real subprocess.

    The three w1 guard tests only exercise post-subprocess classification
    logic; a live `sleep 3` against a 1s cap would cost ~1s of wall time and
    add flake surface for nothing.
    """

    def fake_run_with_timeout(argv, timeout_s, *, stdout=None, stderr=None, env=None, cwd=None):
        return TimeoutResult(exit_code=exit_code, timed_out=timed_out, elapsed_s=0.1, stdout=b"", stderr=b"")

    return fake_run_with_timeout


def test_run_cell_official_timeout_preserves_timed_out_status(tmp_path: Path):
    """A timed-out official cell must stay 'timed-out', not be overwritten to 'failed'."""
    fake_argv = [sys.executable, "-c", "print('unused')"]
    with (
        patch.object(runner, "benchbox_run_official_argv", return_value=fake_argv),
        patch.object(
            runner, "run_with_timeout", side_effect=_fake_run_with_timeout_factory(exit_code=124, timed_out=True)
        ),
        patch.object(runner, "resolve_official_result_path", return_value=None),
    ):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=1,
            log_dir=tmp_path,
            official=True,
            streams=3,
        )

    assert result.status == "timed-out"
    assert result.exit_code == 124
    assert result.result_path is None
    # The reason explains the skip instead of the generic "no result JSON
    # resolved" message, so the artifact self-explains without implying a
    # throughput check ran and failed.
    assert result.throughput_check == "not validated: cell timed out"


def test_run_cell_official_missing_result_downgrades_passed_cell(tmp_path: Path):
    """A clean-exit official cell that resolved no result JSON is still a genuine failure."""
    fake_argv = [sys.executable, "-c", "print('unused')"]
    with (
        patch.object(runner, "benchbox_run_official_argv", return_value=fake_argv),
        patch.object(
            runner, "run_with_timeout", side_effect=_fake_run_with_timeout_factory(exit_code=0, timed_out=False)
        ),
        patch.object(runner, "resolve_official_result_path", return_value=None),
    ):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            official=True,
            streams=3,
        )

    assert result.status == "failed"
    assert result.exit_code == 1
    assert result.throughput_check == "no result JSON resolved for throughput validation"


def test_run_cell_official_failed_exit_with_missing_result_keeps_original_exit_code(tmp_path: Path):
    """A cell that already failed (nonzero exit, no timeout) keeps its own exit code."""
    fake_argv = [sys.executable, "-c", "print('unused')"]
    with (
        patch.object(runner, "benchbox_run_official_argv", return_value=fake_argv),
        patch.object(
            runner, "run_with_timeout", side_effect=_fake_run_with_timeout_factory(exit_code=2, timed_out=False)
        ),
        patch.object(runner, "resolve_official_result_path", return_value=None),
    ):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            official=True,
            streams=3,
        )

    assert result.status == "failed"
    assert result.exit_code == 2
    assert result.throughput_check == "no result JSON resolved for throughput validation"


def test_run_cell_official_downgrades_passed_cell_on_stream_count_mismatch(tmp_path: Path):
    """Existing behavior is preserved: a passed cell still downgrades on a real throughput failure."""
    result_path = tmp_path / "benchmark_runs" / "results" / "official.json"
    _write_result_json(result_path)  # no "stream" keys on the queries -> stream-count mismatch
    fake_argv = [sys.executable, "-c", "pass"]
    with (
        patch.object(runner, "benchbox_run_official_argv", return_value=fake_argv),
        patch.object(runner, "resolve_official_result_path", return_value=result_path),
    ):
        result = runner.run_cell(
            "duckdb",
            "tpch",
            0.01,
            timeout_s=10,
            log_dir=tmp_path,
            official=True,
            streams=3,
        )

    assert result.status == "failed"
    assert result.exit_code == 1
    assert "throughput stream count mismatch" in (result.throughput_check or "")
