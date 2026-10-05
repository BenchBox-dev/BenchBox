"""Support for real, multi-stream throughput/concurrent UAT cells.

`benchbox run-official --streams N` is the CLI surface that forwards a requested
stream count to the throughput driver. This module resolves a cell's result,
validates the exported JSON (identity, stream count, per-stream success,
Throughput@Size) and provides the `assert` CLI the nightly workflow calls.
Baseline retention lives in `tests.uat.throughput_baseline`.
"""

from __future__ import annotations

import argparse
import glob
import json
import math
import os
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchbox.core.results.metrics import TPCMetricsCalculator
from tests.uat.throughput_baseline import observed_throughput_at_size, record_baseline

# Mirrors benchbox/cli/commands/run_official.py::TPC_ALLOWED_SCALE_FACTORS.
# `run-official` rejects any other scale factor outright, so a throughput UAT
# cell must pick one of these (the verification command in the
# throughput-uat-and-ci-coverage TODO uses the smallest, SF=1).
TPC_ALLOWED_SCALE_FACTORS = {1, 10, 30, 100, 300, 1000, 3000, 10000, 30000, 100000}

THROUGHPUT_TEST_TYPE = "throughput"
DEFAULT_FLOOR_MAX_DROP_FRACTION = 0.2


def resolve_official_result_path(results_dir: Path, *, emitted_path: str | None = None) -> Path | None:
    if not emitted_path:
        return None
    path = Path(emitted_path).expanduser()
    if path.is_absolute() or path.exists():
        return path
    runs_dir = results_dir.parent
    if len(path.parts) >= 2 and path.parts[0] == "benchmark_runs":
        return runs_dir.parent / path
    return runs_dir / path


def _throughput_rows(result_json: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        query
        for query in result_json.get("queries") or []
        if isinstance(query, dict)
        and query.get("test_type") == THROUGHPUT_TEST_TYPE
        and query.get("stream") is not None
    ]


def _is_success(query: dict[str, Any]) -> bool:
    return str(query.get("status", "")).upper() == "SUCCESS"


def _token(value: Any) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def validate_result_identity(
    result_json: dict[str, Any],
    *,
    platform: str,
    benchmark: str,
    scale: float,
) -> tuple[bool, str]:
    platform_name = (result_json.get("platform") or {}).get("name")
    benchmark_section = result_json.get("benchmark") or {}
    benchmark_id = benchmark_section.get("id")
    scale_factor = benchmark_section.get("scale_factor")
    if platform_name is None or _token(platform_name) != _token(platform):
        return False, f"result JSON platform {platform_name!r} does not match requested {platform!r}"
    if benchmark_id is None or _token(benchmark_id) != _token(benchmark):
        return False, f"result JSON benchmark {benchmark_id!r} does not match requested {benchmark!r}"
    if not isinstance(scale_factor, (int, float)) or not math.isclose(float(scale_factor), float(scale)):
        return False, f"result JSON scale factor {scale_factor!r} does not match requested {scale!r}"
    return True, "ok"


def validate_stream_count(
    result_json: dict[str, Any],
    *,
    requested_streams: int,
) -> tuple[bool, str]:
    executed = len({row["stream"] for row in _throughput_rows(result_json)})
    if executed != requested_streams:
        return (
            False,
            f"throughput stream count mismatch: requested {requested_streams}, executed {executed}",
        )
    return True, "ok"


def validate_stream_success(result_json: dict[str, Any]) -> tuple[bool, str]:
    stream_has_success: dict[Any, bool] = {}
    for query in _throughput_rows(result_json):
        stream_id = query["stream"]
        stream_has_success[stream_id] = stream_has_success.get(stream_id, False) or _is_success(query)

    if not stream_has_success:
        return False, "no throughput rows in result JSON"
    failed_streams = sorted(stream_id for stream_id, has_success in stream_has_success.items() if not has_success)
    if failed_streams:
        return (
            False,
            f"stream(s) {failed_streams} executed but had zero SUCCESSFUL queries",
        )
    return True, "ok"


def validate_throughput_metric(result_json: dict[str, Any]) -> tuple[bool, str]:
    tpc_metrics = (result_json.get("summary") or {}).get("tpc_metrics") or {}
    throughput_at_size = tpc_metrics.get("throughput_at_size")
    if not isinstance(throughput_at_size, (int, float)) or throughput_at_size <= 0:
        return False, f"Throughput@Size not positive (got {throughput_at_size!r})"

    rows = _throughput_rows(result_json)
    total_queries = sum(1 for row in rows if _is_success(row))
    scale_factor = (result_json.get("benchmark") or {}).get("scale_factor")
    duration_ms = ((result_json.get("phases") or {}).get("throughput_test") or {}).get("duration_ms")
    if not isinstance(scale_factor, (int, float)) or scale_factor <= 0:
        return False, f"Throughput@Size plausibility unavailable: invalid scale factor {scale_factor!r}"
    if not isinstance(duration_ms, (int, float)) or duration_ms <= 0:
        return False, f"Throughput@Size plausibility unavailable: invalid throughput duration {duration_ms!r}"

    stream_ids = {row["stream"] for row in rows}
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
    platform: str | None = None,
    benchmark: str | None = None,
    scale: float | None = None,
) -> tuple[bool, str]:
    if platform is not None and benchmark is not None and scale is not None:
        ok, reason = validate_result_identity(result_json, platform=platform, benchmark=benchmark, scale=scale)
        if not ok:
            return ok, reason
    ok, reason = validate_stream_count(result_json, requested_streams=requested_streams)
    if not ok:
        return ok, reason
    ok, reason = validate_stream_success(result_json)
    if not ok:
        return ok, reason
    return validate_throughput_metric(result_json)


class ThroughputGateError(Exception):
    pass


@dataclass(frozen=True)
class CellResultFile:
    cells_jsonl: Path
    result_path: Path
    payload: dict[str, Any]


def locate_cells_jsonl(pattern: str) -> Path:
    matches = sorted(glob.glob(os.path.expanduser(pattern)))
    if len(matches) != 1:
        raise ThroughputGateError(f"expected exactly one cells.jsonl matching {pattern!r}, found {len(matches)}")
    return Path(matches[0])


def read_cell_row(cells_jsonl: Path, *, platform: str, benchmark: str, scale: float) -> dict[str, Any]:
    rows = []
    for line in cells_jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if (
            _token(row.get("platform")) == _token(platform)
            and _token(row.get("benchmark")) == _token(benchmark)
            and math.isclose(float(row.get("scale", math.nan)), float(scale))
        ):
            rows.append(row)
    if len(rows) != 1:
        raise ThroughputGateError(
            f"expected exactly one {platform}/{benchmark}/sf{scale:g} cell in {cells_jsonl}, found {len(rows)}"
        )
    return rows[0]


def load_cell_result(cells_glob: str, *, platform: str, benchmark: str, scale: float) -> CellResultFile:
    cells_jsonl = locate_cells_jsonl(cells_glob)
    row = read_cell_row(cells_jsonl, platform=platform, benchmark=benchmark, scale=scale)
    raw_path = row.get("result_path")
    if not raw_path:
        raise ThroughputGateError(
            f"cell {platform}/{benchmark}/sf{scale:g} recorded no result_path (status {row.get('status')!r})"
        )
    result_path = Path(raw_path).expanduser()
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ThroughputGateError(f"could not read result JSON {result_path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ThroughputGateError(f"result JSON {result_path} is not an object")
    return CellResultFile(cells_jsonl=cells_jsonl, result_path=result_path, payload=payload)


def evaluate_floor(
    observed: float | None,
    *,
    median: str | float | None,
    max_drop: str | float | None = None,
) -> tuple[bool, str]:
    if median is None or median == "":
        return True, "no Throughput@Size floor median configured; floor check in observe-only mode"
    try:
        median_value = float(median)
        max_drop_value = float(max_drop) if max_drop not in (None, "") else DEFAULT_FLOOR_MAX_DROP_FRACTION
    except ValueError:
        return False, "Throughput@Size floor misconfigured or unobserved; refusing to gate"
    if (
        not math.isfinite(median_value)
        or median_value <= 0
        or not math.isfinite(max_drop_value)
        or not 0 < max_drop_value < 1
        or observed is None
        or not math.isfinite(observed)
        or observed <= 0
    ):
        return False, "Throughput@Size floor misconfigured or unobserved; refusing to gate"
    floor = median_value * (1 - max_drop_value)
    if observed < floor:
        return False, (
            f"Throughput@Size regression: observed {observed:.2f} below floor {floor:.2f} "
            f"(median {median_value:.2f}, max drop {max_drop_value:.0%})"
        )
    return True, f"Throughput@Size {observed:.2f} clears floor {floor:.2f}"


def _run_assert(args: argparse.Namespace) -> int:
    try:
        cell = load_cell_result(args.cells_glob, platform=args.platform, benchmark=args.benchmark, scale=args.scale)
    except ThroughputGateError as exc:
        print(f"::error::{exc}")
        return 1
    ok, reason = validate_throughput_result(
        cell.payload,
        requested_streams=args.streams,
        platform=args.platform,
        benchmark=args.benchmark,
        scale=args.scale,
    )
    if not ok:
        print(f"::error::{reason}")
        return 1
    print(f"OK: identity, stream count and per-stream success verified ({cell.result_path})")
    observed = observed_throughput_at_size(cell.payload)
    print(f"::notice::Throughput@Size observed: {observed!r} ({args.platform}/{args.benchmark}-sf{args.scale:g})")
    if args.evaluate_floor:
        floor_ok, message = evaluate_floor(
            observed,
            median=os.environ.get("THROUGHPUT_FLOOR_MEDIAN"),
            max_drop=os.environ.get("THROUGHPUT_FLOOR_MAX_DROP_FRACTION"),
        )
        if not floor_ok:
            print(f"::error::{message}")
            return 1
        print(f"::notice::{message}" if "observe-only" in message else f"OK: {message}")
    if args.baseline_out:
        print(
            "OK: recorded baseline "
            f"{record_baseline(Path(args.baseline_out).expanduser(), cell.payload, platform=args.platform, benchmark=args.benchmark, scale=args.scale, streams=args.streams)}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tests.uat.throughput")
    subparsers = parser.add_subparsers(dest="command", required=True)

    assert_parser = subparsers.add_parser("assert")
    assert_parser.add_argument("--cells-glob", required=True)
    assert_parser.add_argument("--platform", required=True)
    assert_parser.add_argument("--benchmark", required=True)
    assert_parser.add_argument("--scale", type=float, required=True)
    assert_parser.add_argument("--streams", type=int, required=True)
    assert_parser.add_argument("--evaluate-floor", action="store_true")
    assert_parser.add_argument("--baseline-out")
    assert_parser.set_defaults(handler=_run_assert)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
