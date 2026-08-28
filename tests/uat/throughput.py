"""Support for real, multi-stream throughput/concurrent UAT cells.

`benchbox run` (the CLI surface `benchbox_run_argv` in `tests.uat.matrix`
shells out to for every other UAT phase) has no `--streams`/`--concurrency`
option of its own -- see the `throughput-stream-count-wiring-defect` TODO's
`deferred` section. `benchbox run-official --streams N` is, today, the only
CLI surface that can make a requested stream count reach the throughput
driver, via a transient `BenchmarkOrchestrator.execute_benchmark` patch
(`benchbox/cli/commands/run_official.py::_forward_requested_streams`). UAT
now runs that deprecated command with `--quiet`, so it reuses the same final
bare-path stdout contract as every other `benchbox run` cell. This module
supplies the two things a `run-official`-backed UAT cell needs:

1. `resolve_official_result_path` -- reads the emitted quiet-path line through
   a backward-compatible resolver wrapper, so the official branch keeps its
   existing call shape while retiring glob/mtime inference entirely.
2. `validate_throughput_result` -- checks the exported result JSON for the
   three things a silent concurrency regression would break: every requested
   stream actually executed at least one query (`validate_stream_count`),
   every stream that executed actually had at least one SUCCESSFUL query and
   didn't just fail out immediately (`validate_stream_success`), and
   Throughput@Size was actually computed (`validate_throughput_metric`).

`TPC_ALLOWED_SCALE_FACTORS` mirrors `run_official.py`'s own constant (kept as
a local copy rather than importing from a `deprecated` CLI command module)
so config validation can fail fast on a non-TPC-compliant scale factor
instead of surfacing only as a buried subprocess exit.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

from benchbox.core.results.metrics import TPCMetricsCalculator

# Mirrors benchbox/cli/commands/run_official.py::TPC_ALLOWED_SCALE_FACTORS.
# `run-official` rejects any other scale factor outright, so a throughput UAT
# cell must pick one of these (the verification command in the
# throughput-uat-and-ci-coverage TODO uses the smallest, SF=1).
TPC_ALLOWED_SCALE_FACTORS = {1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000}


def resolve_official_result_path(
    results_dir: Path,
    *,
    platform: str,
    benchmark: str,
    started_after: _dt.datetime,
    scale: float | None = None,
    emitted_path: str | None = None,
) -> Path | None:
    """Resolve the result JSON path emitted by `run-official --quiet`.

    The authoritative contract is now the same one `benchbox run --quiet`
    already exposes: the final non-empty stdout line is the exported result
    JSON path. `run_cell` passes that line here via `emitted_path`.

    `results_dir`/`platform`/`benchmark`/`started_after`/`scale` remain in the
    signature for backward compatibility with the historical glob-based
    resolver and existing call sites/tests, but resolution itself is now a
    read, not a filename search. There is intentionally NO fallback to glob or
    mtime inference: a missing/invalid emitted path returns `None`, and the
    caller must fail loudly.

    Relative paths resolve the same way the runner resolves quiet output from
    normal `benchbox run` cells: relative to the shared runs root, with a
    leading `benchmark_runs/...` anchored one directory above it.
    """
    _ = (platform, benchmark, started_after, scale)
    if not emitted_path:
        return None
    path = Path(emitted_path).expanduser()
    if path.is_absolute() or path.exists():
        return path
    runs_dir = results_dir.parent
    if len(path.parts) >= 2 and path.parts[0] == "benchmark_runs":
        return runs_dir.parent / path
    return runs_dir / path


def validate_stream_count(
    result_json: dict[str, Any],
    *,
    requested_streams: int,
) -> tuple[bool, str]:
    """Check that every requested stream actually executed at least one query.

    This is the core signal the throughput-uat-and-ci-coverage TODO exists to
    protect: a regression that silently drops the requested stream count (see
    the throughput-stream-count-wiring-defect TODO) must be caught even when
    an unrelated correctness issue (see ``validate_throughput_metric``) keeps
    the overall run from being "clean". Split out from
    ``validate_throughput_result`` so a caller (e.g. nightly CI) can hard-gate
    on this specific invariant independent of that separate concern.

    Derived from the distinct ``stream`` ids across ``queries[]`` -- NOT the
    top-level ``run.streams`` field, which is ``max(stream_id)`` (an index,
    not a count) and so is off-by-one from the real stream count (see
    ``benchbox/core/results/schema.py::_build_run_section``).

    Deliberately status-blind: a stream counts as "executed" the moment it
    contributes >=1 row to ``queries[]``, regardless of whether that query
    passed or failed. That is by design -- this check exists purely to catch
    the concurrency-wiring regression (a requested stream never reaching the
    driver at all), and stays a pure "did the request reach the driver"
    signal so callers (e.g. the nightly wiring-defect assert step) can use it
    independent of run outcome. See ``validate_stream_success`` for the
    stricter, outcome-sensitive companion that checks each executed stream
    actually succeeded.

    Returns ``(ok, reason)``; `reason` is a human-readable explanation on
    failure, or ``"ok"`` on success.
    """
    queries = result_json.get("queries") or []
    streams_seen = {
        query.get("stream") for query in queries if isinstance(query, dict) and query.get("stream") is not None
    }
    executed = len(streams_seen)
    if executed != requested_streams:
        return (
            False,
            f"throughput stream count mismatch: requested {requested_streams}, executed {executed}",
        )
    return True, "ok"


def validate_stream_success(result_json: dict[str, Any]) -> tuple[bool, str]:
    """Check that every stream that executed at least one query had at least
    one SUCCESSFUL query.

    ``validate_stream_count`` counts a stream as "executed" the moment it
    contributes >=1 row to ``queries[]``, REGARDLESS of that row's
    ``status`` -- so a stream whose every query failed (e.g. it errored out
    on its first query and never got another chance) still counts as
    "executed", silently masking a fully-dead stream behind a passing
    stream-count check. This is the stricter companion: every distinct
    stream id present in ``queries[]`` must carry at least one row whose
    ``status`` is ``"SUCCESS"`` (matched case-insensitively, mirroring
    ``benchbox/core/results/schema.py``'s own status comparison).

    Deliberately independent of ``requested_streams`` (unlike
    ``validate_stream_count``): a stream missing entirely from ``queries[]``
    is a count mismatch -- that check's job. A stream that's present but
    100% failed is this check's job. Both are needed for a throughput cell
    to be trustworthy, which is why ``validate_throughput_result`` runs both
    (plus ``validate_throughput_metric``).

    Split out (rather than folded into ``validate_stream_count``) so the
    nightly wiring-defect assert step -- which must stay a pure
    concurrency-wiring signal, independent of run outcome, see
    ``validate_stream_count`` -- is unaffected by this stricter,
    outcome-sensitive check. This check instead feeds the sweep/report-facing
    ``validate_throughput_result`` composition.

    Returns ``(ok, reason)``; `reason` is a human-readable explanation on
    failure, or ``"ok"`` on success.
    """
    queries = result_json.get("queries") or []
    stream_has_success: dict[Any, bool] = {}
    for query in queries:
        if not isinstance(query, dict):
            continue
        stream_id = query.get("stream")
        if stream_id is None:
            continue
        is_success = str(query.get("status", "")).upper() == "SUCCESS"
        stream_has_success[stream_id] = stream_has_success.get(stream_id, False) or is_success

    failed_streams = sorted(stream_id for stream_id, has_success in stream_has_success.items() if not has_success)
    if failed_streams:
        return (
            False,
            f"stream(s) {failed_streams} executed but had zero SUCCESSFUL queries",
        )
    return True, "ok"


def validate_throughput_metric(result_json: dict[str, Any]) -> tuple[bool, str]:
    """Check that Throughput@Size is positive and plausibly spec-scaled.

    It is ``None`` (and therefore absent from the exported JSON's
    ``summary.tpc_metrics``) whenever the run's overall validation status is
    not clean.

    HISTORICAL NOTE: prior to #1142, TPC-H throughput mode failed this check
    at SF=1 on DuckDB regardless of ``--seed`` choice -- queries 11/16/18/20
    (TPC-H's own parameter-sensitive query set) were EXACT-compared against
    one answer-set parameterization even when throughput derived different
    parameters for each stream and position. #1142 added a thread-local
    reference-seed context that excluded those queries under a non-reference
    seed. The expected-results provider now gives Q11/Q18/Q20 exact SF=1.0
    RANGE bounds and Q16 a LOOSE tolerance, and the runtime validator uses that
    same reference-seed context to relax the four queries from EXACT to
    RANGE/LOOSE under a non-reference seed while keeping the exact answer-file
    check under the reference seed -- a bound instead of the old skip. This is
    orthogonal to stream-count wiring -- see ``validate_stream_count`` for that
    separate concern, and ``validate_stream_success`` for the per-stream
    pass/fail check this metric check doesn't cover.

    Returns ``(ok, reason)``; `reason` is a human-readable explanation on
    failure, or ``"ok"`` on success.
    """
    tpc_metrics = (result_json.get("summary") or {}).get("tpc_metrics") or {}
    throughput_at_size = tpc_metrics.get("throughput_at_size")
    if not isinstance(throughput_at_size, (int, float)) or throughput_at_size <= 0:
        return False, f"Throughput@Size not positive (got {throughput_at_size!r})"

    queries = result_json.get("queries") or []
    total_queries = sum(1 for query in queries if isinstance(query, dict) and "stream" in query)
    scale_factor = (result_json.get("benchmark") or {}).get("scale_factor")
    duration_ms = ((result_json.get("phases") or {}).get("throughput_test") or {}).get("duration_ms")
    if not isinstance(scale_factor, (int, float)) or scale_factor <= 0:
        return False, f"Throughput@Size plausibility unavailable: invalid scale factor {scale_factor!r}"
    if not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
        return False, f"Throughput@Size plausibility unavailable: invalid throughput duration {duration_ms!r}"

    stream_ids = {query.get("stream") for query in queries if isinstance(query, dict) and "stream" in query}
    expected = TPCMetricsCalculator.calculate_throughput_at_size(
        total_queries=total_queries,
        total_time_seconds=duration_ms / 1000.0,
        scale_factor=float(scale_factor),
        num_streams=len(stream_ids),
    )
    lower_bound = expected / 2.0
    upper_bound = expected * 2.0
    if not lower_bound <= throughput_at_size <= upper_bound:
        return False, (
            f"Throughput@Size outside plausibility band: got {throughput_at_size:.2f}, "
            f"expected {expected:.2f} ({lower_bound:.2f}..{upper_bound:.2f})"
        )
    return True, "ok"


def validate_throughput_result(
    result_json: dict[str, Any],
    *,
    requested_streams: int,
) -> tuple[bool, str]:
    """Validate a throughput cell's exported result JSON.

    Combines the three checks a throughput cell needs to be
    acceptance-passing: ``validate_stream_count`` (the concurrency-wiring
    signal this TODO exists to protect), ``validate_stream_success`` (every
    executed stream actually had a SUCCESSFUL query, not just rows that all
    failed), and ``validate_throughput_metric`` (the run produced a usable
    Throughput@Size). See each for what it checks and why they are split.

    Checked in that order and short-circuits on the first failure, so a
    stream-count mismatch is reported ahead of a same-run success or
    throughput-metric failure.

    Returns ``(ok, reason)``; `reason` is a human-readable explanation on
    failure, or ``"ok"`` on success.
    """
    ok, reason = validate_stream_count(result_json, requested_streams=requested_streams)
    if not ok:
        return ok, reason
    ok, reason = validate_stream_success(result_json)
    if not ok:
        return ok, reason
    return validate_throughput_metric(result_json)
