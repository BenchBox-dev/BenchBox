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

from benchbox.utils.scale_factor import format_scale_factor

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
) -> Path | None:
    """Find the newest result JSON exported for (platform, benchmark[, scale]).

    `run-official` prints its result path through Rich's non-quiet console
    output (e.g. ``JSON: [dim]/path/to/result.json[/dim]``), which is not a
    bare, parseable stdout line -- unlike `--quiet` `benchbox run`, which
    `run_cell`'s default `last_nonempty_output_line` parsing expects.
    Locating the file by name + mtime instead works regardless of console
    formatting and also survives a non-clean (exit code != 0) run, which
    `run-official` still exports a full result JSON for.

    Filename grammar (pinned from the exporter every result JSON funnels
    through, ``benchbox.core.results.filenames.build_result_filename_base``,
    as exercised by the fixtures in ``tests/uat/test_throughput.py``)::

        {benchmark...}_{sf<N>}_{platform...}_{mode}_{timestamp}[_{execution_id}].json

    The exporter writes the registry ``benchmark_id`` and the normalized
    platform name verbatim, and BOTH can themselves contain underscores, so
    each spans a *variable-length* run of ``"_"``-split tokens rather than a
    single fixed slot:

    - single-token benchmark, single-token platform --
      ``tpch_sf1_duckdb_sql_20260709_223304_0865bb91.json`` ->
      ``["tpch", "sf1", "duckdb", "sql", ...]``
    - single-token benchmark, two-token platform (``pg-duckdb`` ->
      ``pg_duckdb``) -- ``tpch_sf1_pg_duckdb_sql_20260709.json`` ->
      ``["tpch", "sf1", "pg", "duckdb", "sql", ...]``
    - two-token benchmark (``tpcds_obt``, ``tsbs_devops``, ``tpch_skew``,
      ``vector_search``, ``*_primitives`` ...) --
      ``tpcds_obt_sf1_duckdb_sql_20260709.json`` ->
      ``["tpcds", "obt", "sf1", "duckdb", "sql", ...]``

    Matching is token-exact, not substring. A candidate's ``"_"``-split stem
    must (1) begin with the benchmark's own token sequence as a prefix, then
    (2) carry the scale-factor token at index ``len(benchmark_tokens)`` (only
    *checked* when `scale` is given, but always skipped over so the platform
    slice lines up), then (3) carry the platform's own token sequence in the
    slots immediately after. This is what stops ``platform="duckdb"`` from
    matching a ``pg_duckdb`` result file (or the reverse), and
    ``benchmark="tpcds_obt"`` from being shifted/rejected -- both of which
    the old glob-based ``f"{benchmark}_*{platform}*.json"`` pattern got
    wrong (a false-positive on the platform, a false-negative on the
    multi-token benchmark).

    `scale` is optional and keyword-only for backward compatibility with
    existing callers that don't (yet) pass it; when omitted, the
    scale-factor token is present in the filename but not checked.

    Ties (equal ``st_mtime``, e.g. within filesystem mtime granularity) are
    broken deterministically by filename, not left to whatever order the
    filesystem happens to yield candidates in.
    """
    if not results_dir.is_dir():
        return None
    benchmark_tokens = benchmark.lower().split("_")
    platform_tokens = platform.lower().replace("-", "_").split("_")
    scale_token = format_scale_factor(scale) if scale is not None else None
    scale_idx = len(benchmark_tokens)
    platform_start = scale_idx + 1
    platform_end = platform_start + len(platform_tokens)
    started_ts = started_after.timestamp()

    candidates: list[Path] = []
    for path in results_dir.glob(f"{benchmark.lower()}_*.json"):
        if not path.is_file() or path.stat().st_mtime < started_ts:
            continue
        tokens = path.stem.split("_")
        if tokens[:scale_idx] != benchmark_tokens:
            continue
        # The scale-factor token always occupies ``scale_idx`` in the pinned
        # grammar; only *check* it when the caller supplied `scale`, but the
        # platform slice below is offset past it regardless.
        if scale_token is not None and (len(tokens) <= scale_idx or tokens[scale_idx] != scale_token):
            continue
        if tokens[platform_start:platform_end] != platform_tokens:
            continue
        candidates.append(path)
    if not candidates:
        return None
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


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
    """Check that Throughput@Size was actually computed (> 0).

    It is ``None`` (and therefore absent from the exported JSON's
    ``summary.tpc_metrics``) whenever the run's overall validation status is
    not clean.

    HISTORICAL NOTE: prior to #1142, TPC-H throughput mode failed this check
    at SF=1 on DuckDB regardless of ``--seed`` choice -- queries 11/16/18/20
    (TPC-H's own "non-deterministic" query set) failed BenchBox's LOOSE
    (+-50%) row-count validation on every stream, because the throughput
    driver's per-stream/per-position seed derivation
    (``benchbox/core/tpch/throughput_test.py``: ``seed + stream_id * 1000 +
    position``) meant no stream after the first query of stream 0 could ever
    land on the reference-seed exact-match path that POWER mode gets when no
    seed is given. #1142 fixed this at the root by adding a thread-local
    reference-seed context (``benchbox.core.validation.query_validation.
    set_reference_seed_context``) so the four parameter-sensitive queries are
    excluded from EXACT row-count checks only when a non-reference seed is
    actually in effect. This was a correctness gap orthogonal to
    stream-count wiring -- see ``validate_stream_count`` for the check that
    guards that separate concern, and ``validate_stream_success`` for the
    per-stream pass/fail check this metric check doesn't cover.

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
