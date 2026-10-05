from __future__ import annotations

import argparse
import json
import math
import os
import platform as _platform
import re
import statistics
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASELINE_SCHEMA_VERSION = 1
DEFAULT_ROLLING_WINDOW = 10


def observed_throughput_at_size(result_json: dict[str, Any]) -> float | None:
    value = ((result_json.get("summary") or {}).get("tpc_metrics") or {}).get("throughput_at_size")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def detect_cpu_model() -> str:
    cpuinfo = Path("/proc/cpuinfo")
    try:
        for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
            key, _, value = line.partition(":")
            if key.strip().lower() in {"model name", "model", "hardware"} and value.strip():
                return value.strip()
    except OSError:
        pass
    if sys.platform == "darwin":
        completed = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=False
        )
        if completed.returncode == 0 and completed.stdout.strip():
            return completed.stdout.strip()
    return _platform.processor() or "unknown"


def runner_class_for(cpu_model: str, cpu_count: int) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", cpu_model.lower()).strip("-") or "unknown"
    return f"{slug}-{cpu_count}cpu"


def build_baseline_record(
    result_json: dict[str, Any],
    *,
    platform: str,
    benchmark: str,
    scale: float,
    streams: int,
    cpu_model: str,
    cpu_count: int,
    env: Mapping[str, str],
    recorded_at: datetime,
) -> dict[str, Any]:
    duration_ms = ((result_json.get("phases") or {}).get("throughput_test") or {}).get("duration_ms")
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "platform": platform,
        "benchmark": benchmark,
        "scale_factor": float(scale),
        "streams": streams,
        "throughput_at_size": observed_throughput_at_size(result_json),
        "throughput_duration_ms": duration_ms,
        "runner_class": runner_class_for(cpu_model, cpu_count),
        "cpu_model": cpu_model,
        "cpu_count": cpu_count,
        "runner_os": env.get("RUNNER_OS", ""),
        "runner_arch": env.get("RUNNER_ARCH", ""),
        "runner_image": env.get("ImageVersion", ""),
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "commit_sha": env.get("GITHUB_SHA", ""),
        "recorded_at": recorded_at.astimezone(timezone.utc).isoformat(),
    }


def baseline_filename(record: dict[str, Any]) -> str:
    return (
        f"throughput-baseline-{record['platform']}-{record['benchmark']}-sf{record['scale_factor']:g}"
        f"-{record['run_id'] or 'local'}-{record['run_attempt'] or '1'}.json"
    )


def write_baseline_record(directory: Path, record: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / baseline_filename(record)
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def load_baseline_records(directory: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(directory.rglob("throughput-baseline-*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and record.get("schema_version") == BASELINE_SCHEMA_VERSION:
            records.append(record)
    return records


@dataclass(frozen=True)
class RollingMedian:
    median: float
    count: int
    run_ids: tuple[str, ...]


def rolling_median(
    records: Sequence[dict[str, Any]],
    *,
    platform: str,
    benchmark: str,
    scale: float,
    runner_class: str,
    window: int = DEFAULT_ROLLING_WINDOW,
    min_samples: int = 1,
) -> RollingMedian | None:
    matching = [
        record
        for record in records
        if record.get("platform") == platform
        and record.get("benchmark") == benchmark
        and math.isclose(float(record.get("scale_factor", math.nan)), float(scale))
        and record.get("runner_class") == runner_class
        and isinstance(record.get("throughput_at_size"), (int, float))
        and record["throughput_at_size"] > 0
    ]
    matching.sort(key=lambda record: str(record.get("recorded_at", "")), reverse=True)
    selected = matching[:window]
    if len(selected) < max(1, min_samples):
        return None
    return RollingMedian(
        median=float(statistics.median(record["throughput_at_size"] for record in selected)),
        count=len(selected),
        run_ids=tuple(str(record.get("run_id", "")) for record in selected),
    )


def record_baseline(
    directory: Path, result_json: dict[str, Any], *, platform: str, benchmark: str, scale: float, streams: int
) -> Path:
    record = build_baseline_record(
        result_json,
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        streams=streams,
        cpu_model=detect_cpu_model(),
        cpu_count=os.cpu_count() or 0,
        env=os.environ,
        recorded_at=datetime.now(timezone.utc),
    )
    return write_baseline_record(directory, record)


def _run_rolling_median(args: argparse.Namespace) -> int:
    records = load_baseline_records(Path(args.baseline_dir).expanduser())
    runner_class = args.runner_class or runner_class_for(detect_cpu_model(), os.cpu_count() or 0)
    result = rolling_median(
        records,
        platform=args.platform,
        benchmark=args.benchmark,
        scale=args.scale,
        runner_class=runner_class,
        window=args.window,
        min_samples=args.min_samples,
    )
    if result is None:
        print(f"::error::fewer than {args.min_samples} retained baselines for runner class {runner_class!r}")
        return 1
    print(
        json.dumps(
            {
                "runner_class": runner_class,
                "median": result.median,
                "count": result.count,
                "run_ids": list(result.run_ids),
            },
            sort_keys=True,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tests.uat.throughput_baseline")
    subparsers = parser.add_subparsers(dest="command", required=True)
    median_parser = subparsers.add_parser("rolling-median")
    median_parser.add_argument("--baseline-dir", required=True)
    median_parser.add_argument("--platform", required=True)
    median_parser.add_argument("--benchmark", required=True)
    median_parser.add_argument("--scale", type=float, required=True)
    median_parser.add_argument("--runner-class")
    median_parser.add_argument("--window", type=int, default=DEFAULT_ROLLING_WINDOW)
    median_parser.add_argument("--min-samples", type=int, default=1)
    median_parser.set_defaults(handler=_run_rolling_median)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
