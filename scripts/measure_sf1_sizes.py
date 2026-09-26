#!/usr/bin/env python3
"""Measure actual uncompressed SF=1 source-data sizes for all benchmarks.

Runs each benchmark's generator at scale_factor=1.0 with compression disabled
and sums the emitted file bytes. Real-data benchmarks (nyctaxi, flightdata,
clickbench) download or sample from finite corpora, so the script measures
what the generator actually emits rather than projecting from row counts.

Results are written as JSON to stdout (or --output): one record per
benchmark with total bytes, file count, row counts where the manifest
reports them, elapsed seconds, method (generated | manifest | spec), and
any error.

Usage:
    uv run -- python scripts/measure_sf1_sizes.py --output /tmp/sf1.json
    uv run -- python scripts/measure_sf1_sizes.py --benchmark tpch,ssb

Sequential by default: several SF=1 datasets exceed 1 GB and the default
output roots share one disk. Use --jobs N only with ample scratch space.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SizeRecord:
    """One benchmark's measured SF=1 result."""

    benchmark: str
    scale_factor: float = 1.0
    method: str = "generated"
    total_bytes: int = 0
    file_count: int = 0
    total_rows: int | None = None
    elapsed_seconds: float = 0.0
    error: str | None = None
    notes: str = ""


# (benchmark_id, module, class, kwargs) for direct generator invocation.
# Benchmark-level classes are used where the generator needs benchmark
# wiring (tpcds manager, tpcdi source stages, real-data downloaders).
GENERATORS: list[tuple[str, str, str, dict]] = [
    ("tpch", "benchbox.core.tpch.generator", "TPCHDataGenerator", {}),
    ("tpcds", "benchbox.core.tpcds.generator.manager", "TPCDSDataGenerator", {}),
    ("ssb", "benchbox.core.ssb.generator", "SSBDataGenerator", {}),
    ("tpch_skew", "benchbox.core.tpch_skew.generator", "TPCHSkewDataGenerator", {}),
    ("tpchavoc", "benchbox.core.tpch.generator", "TPCHDataGenerator", {}),
    ("amplab", "benchbox.core.amplab.generator", "AMPLabDataGenerator", {}),
    ("h2odb", "benchbox.core.h2odb.generator", "H2ODataGenerator", {}),
    ("coffeeshop", "benchbox.core.coffeeshop.generator", "CoffeeShopDataGenerator", {}),
    ("tsbs_devops", "benchbox.core.tsbs_devops.generator", "TSBSDevOpsDataGenerator", {}),
    ("joinorder_synthetic", "benchbox.core.joinorder_synthetic.generator", "JoinOrderGenerator", {}),
    ("read_primitives", "benchbox.core.read_primitives.generator", "ReadPrimitivesDataGenerator", {}),
    ("write_primitives", "benchbox.core.write_primitives.generator", "WritePrimitivesDataGenerator", {}),
    (
        "transaction_primitives",
        "benchbox.core.transaction_primitives.generator",
        "TransactionPrimitivesDataGenerator",
        {},
    ),
    ("vector_search", "benchbox.core.vector_search.generator", "VectorSearchDataGenerator", {}),
    ("clickbench", "benchbox.core.clickbench.generator", "ClickBenchDataGenerator", {}),
]

# Benchmarks whose SF=1 data comes from a fixed corpus or a checked-in
# derived archive rather than a parameterized generator. Measuring means
# running the benchmark-level generate_data path (download + extract) or,
# for joinorder, sizing the canonical manifest-owned files.
BENCHMARK_LEVEL: list[tuple[str, str, str, dict]] = [
    ("tpcdi", "benchbox.core.tpcdi.benchmark", "TPCDIBenchmark", {}),
    ("nyctaxi", "benchbox.core.nyctaxi.benchmark", "NYCTaxiBenchmark", {}),
    ("flightdata", "benchbox.core.flightdata.benchmark", "FlightDataBenchmark", {}),
    ("joinorder", "benchbox.core.joinorder.benchmark", "JoinOrderBenchmark", {}),
    ("tpcds_obt", "benchbox.core.tpcds_obt.benchmark", "TPCDSOBTBenchmark", {}),
    ("datavault", "benchbox.core.datavault.benchmark", "DataVaultBenchmark", {}),
]


def _sum_paths(paths: object) -> tuple[int, int]:
    """Sum file bytes under generator return values (dict | list | nested)."""
    total = 0
    count = 0
    stack: list[object] = [paths]
    seen: set[str] = set()
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, (list, tuple)):
            stack.extend(item)
        elif isinstance(item, (str, Path)):
            key = str(item)
            if key in seen:
                continue
            seen.add(key)
            candidate = Path(key)
            if candidate.is_file() and candidate.name != "_datagen_manifest.json":
                total += candidate.stat().st_size
                count += 1
            elif candidate.is_dir():
                for child in candidate.rglob("*"):
                    child_key = str(child)
                    if child.is_file() and child_key not in seen and child.name != "_datagen_manifest.json":
                        seen.add(child_key)
                        total += child.stat().st_size
                        count += 1
    return total, count


def _run_generator(module: str, cls_name: str, extra: dict) -> tuple[int, int, float]:
    """Instantiate a generator at SF=1 uncompressed and sum its output."""
    module_obj = __import__(module, fromlist=[cls_name])
    cls = getattr(module_obj, cls_name)
    with tempfile.TemporaryDirectory(prefix="sf1measure-") as tmp:
        start = time.monotonic()
        try:
            instance = cls(scale_factor=1.0, output_dir=tmp, compress_data=False, **extra)
        except TypeError:
            # Generators with narrower constructors (no compression flags).
            instance = cls(scale_factor=1.0, output_dir=tmp, **extra)
        meth = (
            getattr(instance, "generate_data", None)
            or getattr(instance, "generate", None)
            or getattr(instance, "generate_all_source_data", None)
        )
        if meth is None:
            raise AttributeError(f"{cls_name} has no known generate method")
        paths = meth()
        if isinstance(paths, dict) and not paths:
            # Some generators return paths implicitly via output_dir.
            paths = Path(tmp)
        elapsed = time.monotonic() - start
        total, count = _sum_paths(paths)
        return total, count, elapsed


def measure_one(benchmark: str) -> SizeRecord:
    """Measure a single benchmark, never raising."""
    record = SizeRecord(benchmark=benchmark)
    start = time.monotonic()
    try:
        entry = next((g for g in GENERATORS if g[0] == benchmark), None)
        if entry is None:
            entry = next((g for g in BENCHMARK_LEVEL if g[0] == benchmark), None)
        if entry is None:
            record.error = f"no measurement entry for {benchmark}"
            return record
        _, module, cls_name, extra = entry
        total, count, elapsed = _run_generator(module, cls_name, extra)
        record.total_bytes = total
        record.file_count = count
        record.elapsed_seconds = round(elapsed, 1)
        if total == 0:
            record.error = "generator emitted no measurable files"
    except Exception as exc:  # noqa: BLE001 - record per-benchmark failures as data
        record.error = f"{type(exc).__name__}: {exc}"
        record.elapsed_seconds = round(time.monotonic() - start, 1)
        traceback.print_exc()
    return record


def all_benchmark_ids() -> list[str]:
    """Every benchmark with a measurement entry, in registry order."""
    return [g[0] for g in GENERATORS] + [g[0] for g in BENCHMARK_LEVEL]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        default="",
        help="Comma-separated subset to measure (default: all).",
    )
    parser.add_argument("--output", default="", help="Write JSON records here (default: stdout).")
    args = parser.parse_args(argv)

    wanted = all_benchmark_ids()
    if args.benchmark:
        subset = [b.strip() for b in args.benchmark.split(",") if b.strip()]
        unknown = sorted(set(subset) - set(wanted))
        if unknown:
            print(f"unknown benchmarks: {', '.join(unknown)}", file=sys.stderr)
            return 2
        wanted = subset

    records: list[dict] = []
    failed = 0
    for benchmark in wanted:
        print(f"measuring {benchmark} at SF=1 (uncompressed) ...", file=sys.stderr)
        record = measure_one(benchmark)
        if record.error:
            failed += 1
            print(f"  FAILED: {record.error}", file=sys.stderr)
        else:
            gib = record.total_bytes / (1024**3)
            print(f"  {record.total_bytes} bytes ({gib:.3f} GiB) in {record.elapsed_seconds}s", file=sys.stderr)
        records.append(asdict(record))

    payload = {"scale_factor": 1.0, "compression": "none", "records": records}
    text = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
