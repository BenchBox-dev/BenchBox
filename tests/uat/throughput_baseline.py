from __future__ import annotations

import json
import math
import os
import platform as _platform
import re
import statistics
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

BASELINE_SCHEMA_VERSION = 1
DEFAULT_ROLLING_WINDOW = 10
MIN_FLOOR_SAMPLES = 5


class RollingMedian(NamedTuple):
    median: float
    count: int


def observed_throughput_at_size(result_json: dict[str, Any]) -> float | None:
    value = ((result_json.get("summary") or {}).get("tpc_metrics") or {}).get("throughput_at_size")
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def parse_cpuinfo(text: str) -> str | None:
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, _, value = line.partition(":")
        if value.strip():
            fields.setdefault(key.strip().lower(), value.strip())
    for key in ("model name", "hardware"):
        if key in fields:
            return fields[key]
    if not fields.get("model", "0").isdigit():
        return fields["model"]
    if "cpu implementer" in fields and "cpu part" in fields:
        return f"arm {fields['cpu implementer']} {fields['cpu part']}"
    return None


def detect_cpu_model() -> str:
    try:
        model = parse_cpuinfo(Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        model = None
    return model or _platform.processor() or "unknown"


def runner_class_for(cpu_model: str, cpu_count: int) -> str:
    return f"{re.sub(r'[^a-z0-9]+', '-', cpu_model.lower()).strip('-') or 'unknown'}-{cpu_count}cpu"


def current_runner_class() -> str:
    return runner_class_for(detect_cpu_model(), os.cpu_count() or 0)


def record_baseline(
    directory: Path,
    result_json: dict[str, Any],
    *,
    platform: str,
    benchmark: str,
    scale: float,
    streams: int,
    env: Mapping[str, str] | None = None,
    cpu_model: str | None = None,
    cpu_count: int | None = None,
    recorded_at: datetime | None = None,
) -> Path:
    env = os.environ if env is None else env
    cpu_model = cpu_model or detect_cpu_model()
    cpu_count = cpu_count or os.cpu_count() or 0
    record = {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "platform": platform,
        "benchmark": benchmark,
        "scale_factor": float(scale),
        "streams": streams,
        "throughput_at_size": observed_throughput_at_size(result_json),
        "runner_class": runner_class_for(cpu_model, cpu_count),
        "cpu_model": cpu_model,
        "cpu_count": cpu_count,
        "run_id": env.get("GITHUB_RUN_ID", ""),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""),
        "commit_sha": env.get("GITHUB_SHA", ""),
        "runner_image": env.get("ImageVersion", ""),
        "recorded_at": (recorded_at or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(),
    }
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / (
        f"throughput-baseline-{platform}-{benchmark}-sf{float(scale):g}"
        f"-{record['run_id'] or 'local'}-{record['run_attempt'] or '1'}.json"
    )
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


def rolling_median(
    records: Sequence[dict[str, Any]],
    *,
    platform: str,
    benchmark: str,
    scale: float,
    runner_class: str,
    window: int = DEFAULT_ROLLING_WINDOW,
) -> RollingMedian | None:
    matching = sorted(
        (
            record
            for record in records
            if (record.get("platform"), record.get("benchmark"), record.get("runner_class"))
            == (platform, benchmark, runner_class)
            and math.isclose(float(record.get("scale_factor", math.nan)), float(scale))
            and isinstance(record.get("throughput_at_size"), (int, float))
            and record["throughput_at_size"] > 0
        ),
        key=lambda record: str(record.get("recorded_at", "")),
        reverse=True,
    )[:window]
    if not matching:
        return None
    return RollingMedian(float(statistics.median(r["throughput_at_size"] for r in matching)), len(matching))
