#!/usr/bin/env python3
"""Generate measured pytest speed buckets from a serial JUnit XML run."""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path


def _reconstruct_nodeid(repo_root: Path, classname: str, name: str) -> str:
    parts = classname.split(".")
    module_parts = parts
    remainder: list[str] = []

    for index in range(len(parts), 0, -1):
        candidate = repo_root.joinpath(*parts[:index]).with_suffix(".py")
        if candidate.exists():
            module_parts = parts[:index]
            remainder = parts[index:]
            break

    path = Path(*module_parts).with_suffix(".py").as_posix()
    segments = [path]
    segments.extend(remainder)
    segments.append(name)
    return "::".join(segments)


def _load_rows(repo_root: Path, junit_xml: Path) -> list[tuple[str, float]]:
    root = ET.parse(junit_xml).getroot()
    rows: list[tuple[str, float]] = []
    for testcase in root.iter("testcase"):
        nodeid = _reconstruct_nodeid(
            repo_root=repo_root,
            classname=testcase.attrib["classname"],
            name=testcase.attrib["name"],
        )
        rows.append((nodeid, float(testcase.attrib.get("time", "0") or 0.0)))
    rows.sort(key=lambda row: (row[1], row[0]))
    return rows


def _bucketize(rows: list[tuple[str, float]]) -> dict[str, object]:
    total = len(rows)
    fast_end = math.floor(total * 0.90)
    medium_end = math.floor(total * 0.99)

    fast_rows = rows[:fast_end]
    medium_rows = rows[fast_end:medium_end]
    slow_rows = rows[medium_end:]

    total_time = sum(duration for _, duration in rows)

    def build_bucket(entries: list[tuple[str, float]]) -> dict[str, object]:
        bucket_time = sum(duration for _, duration in entries)
        return {
            "count": len(entries),
            "serial_runtime_seconds": round(bucket_time, 6),
            "runtime_share_percent": round((bucket_time / total_time * 100) if total_time else 0.0, 3),
            "nodeids": [nodeid for nodeid, _ in entries],
        }

    return {
        "eligible_count": total,
        "eligible_serial_runtime_seconds": round(total_time, 6),
        "cutoffs_seconds": {
            "fast_max": rows[fast_end - 1][1] if fast_rows else 0.0,
            "medium_max": rows[medium_end - 1][1] if medium_rows else 0.0,
        },
        "buckets": {
            "fast": build_bucket(fast_rows),
            "medium": build_bucket(medium_rows),
            "slow": build_bucket(slow_rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate measured test speed buckets from JUnit XML timings.")
    parser.add_argument("junit_xml", help="JUnit XML file produced by the serial pytest timing run")
    parser.add_argument(
        "--output",
        default="_project/config/test_speed_buckets.json",
        help="Output JSON file path (default: _project/config/test_speed_buckets.json)",
    )
    parser.add_argument(
        "--markexpr",
        default="not slow and not stress and not resource_heavy and not live_integration",
        help="Mark expression used to produce the measured XML",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    junit_xml = Path(args.junit_xml).resolve()
    output_path = (repo_root / args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    rows = _load_rows(repo_root, junit_xml)
    bucket_data = _bucketize(rows)

    payload = {
        "source_junit_xml": str(junit_xml),
        "source_markexpr": args.markexpr,
        **bucket_data,
        "buckets": {
            bucket: {
                "count": data["count"],
                "serial_runtime_seconds": data["serial_runtime_seconds"],
                "runtime_share_percent": data["runtime_share_percent"],
                "nodeids": data["nodeids"],
            }
            for bucket, data in bucket_data["buckets"].items()
        },
    }

    output_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    for bucket in ("fast", "medium", "slow"):
        data = payload["buckets"][bucket]
        print(
            f"{bucket}: {data['count']} tests, "
            f"{data['serial_runtime_seconds']:.3f}s serial, "
            f"{data['runtime_share_percent']:.3f}% runtime"
        )
    print(
        "cutoffs:",
        f"fast_max={payload['cutoffs_seconds']['fast_max']:.6f}s",
        f"medium_max={payload['cutoffs_seconds']['medium_max']:.6f}s",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
