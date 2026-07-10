"""Support for real, multi-stream throughput/concurrent UAT cells.

`benchbox run` (the CLI surface `benchbox_run_argv` in `tests.uat.matrix`
shells out to for every other UAT phase) has no `--streams`/`--concurrency`
option of its own -- see the `throughput-stream-count-wiring-defect` TODO's
`deferred` section. `benchbox run-official --streams N` is, today, the only
CLI surface that can make a requested stream count reach the throughput
driver, via a transient `BenchmarkOrchestrator.execute_benchmark` patch
(`benchbox/cli/commands/run_official.py::_forward_requested_streams`). This
module supplies the two things a `run-official`-backed UAT cell needs that a
`--quiet` `benchbox run` cell gets for free:

1. `resolve_official_result_path` -- `run-official` has no `--quiet` flag, so
   it never prints a bare, parseable result-path line the way `run_cell`'s
   default stdout parsing (`last_nonempty_output_line`) expects. The result
   JSON is instead located on disk by filename + mtime.
2. `validate_throughput_result` -- checks the exported result JSON for the
   two things a silent concurrency regression would break: every requested
   stream actually executed at least one query, and Throughput@Size was
   actually computed.

`TPC_ALLOWED_SCALE_FACTORS` mirrors `run_official.py`'s own constant (kept as
a local copy rather than importing from a `deprecated` CLI command module)
so config validation can fail fast on a non-TPC-compliant scale factor
instead of surfacing only as a buried subprocess exit.
"""

from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any

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
) -> Path | None:
    """Find the newest result JSON exported for (platform, benchmark).

    `run-official` prints its result path through Rich's non-quiet console
    output (e.g. ``JSON: [dim]/path/to/result.json[/dim]``), which is not a
    bare, parseable stdout line -- unlike `--quiet` `benchbox run`, which
    `run_cell`'s default `last_nonempty_output_line` parsing expects.
    Locating the file by name + mtime instead works regardless of console
    formatting and also survives a non-clean (exit code != 0) run, which
    `run-official` still exports a full result JSON for.
    """
    if not results_dir.is_dir():
        return None
    platform_token = platform.lower().replace("-", "_")
    benchmark_token = benchmark.lower()
    started_ts = started_after.timestamp()
    candidates = [
        path
        for path in results_dir.glob(f"{benchmark_token}_*{platform_token}*.json")
        if path.is_file() and path.stat().st_mtime >= started_ts
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


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


def validate_throughput_metric(result_json: dict[str, Any]) -> tuple[bool, str]:
    """Check that Throughput@Size was actually computed (> 0).

    It is ``None`` (and therefore absent from the exported JSON's
    ``summary.tpc_metrics``) whenever the run's overall validation status is
    not clean.

    NOTE: as of this TODO's implementation, TPC-H throughput mode fails this
    check at SF=1 on DuckDB regardless of ``--seed`` choice (reproduced with
    a custom seed, a different custom seed, and no seed at all) -- queries
    11/16/18/20 (TPC-H's own "non-deterministic" query set) fail BenchBox's
    LOOSE (+-50%) row-count validation on every stream, because the
    throughput driver's per-stream/per-position seed derivation
    (``benchbox/core/tpch/throughput_test.py``: ``seed + stream_id * 1000 +
    position``) means no stream after the first query of stream 0 can ever
    land on the reference-seed exact-match path that POWER mode gets when no
    seed is given. Confirmed independent of concurrency: the identical 4
    queries fail identically in single-stream POWER mode with a non-reference
    seed too. This is a pre-existing, orthogonal correctness gap (tracked
    separately), not a regression in stream-count wiring -- see
    ``validate_stream_count`` for the check that guards against that.

    Returns ``(ok, reason)``; `reason` is a human-readable explanation on
    failure, or ``"ok"`` on success.
    """
    tpc_metrics = (result_json.get("summary") or {}).get("tpc_metrics") or {}
    throughput_at_size = tpc_metrics.get("throughput_at_size")
    if not isinstance(throughput_at_size, (int, float)) or throughput_at_size <= 0:
        return False, f"Throughput@Size not positive (got {throughput_at_size!r})"
    return True, "ok"


def validate_throughput_result(
    result_json: dict[str, Any],
    *,
    requested_streams: int,
) -> tuple[bool, str]:
    """Validate a throughput cell's exported result JSON.

    Combines the two checks a throughput cell needs to be acceptance-passing:
    ``validate_stream_count`` (the concurrency-wiring signal this TODO exists
    to protect) and ``validate_throughput_metric`` (the run produced a usable
    Throughput@Size). See each for what it checks and why they are split.

    Returns ``(ok, reason)``; `reason` is a human-readable explanation on
    failure, or ``"ok"`` on success.
    """
    ok, reason = validate_stream_count(result_json, requested_streams=requested_streams)
    if not ok:
        return ok, reason
    return validate_throughput_metric(result_json)
