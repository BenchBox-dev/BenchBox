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

Parallel runs (--jobs N) execute benchmarks concurrently, one process per
benchmark. Keep the default sequential mode unless the scratch filesystem
has ample space: several SF=1 datasets exceed 1 GB.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import tempfile
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.datagen_manifest import MANIFEST_FILENAME

# Manifest row counts are advisory metadata: a generator may emit placeholder
# or modelled counts rather than exact per-file rows. The measurement records
# the summed manifest total whenever one is present.
_MANIFEST_TABLES_KEY = "tables"

# Transport archives retained alongside extracted source data (for example the
# canonical JoinOrder tarball) are the compressed form of bytes counted
# uncompressed after extraction. They are excluded so the same logical data
# is not counted twice against the uncompressed contract.
_ARCHIVE_SUFFIXES = (".tar.zst", ".tar.gz", ".tgz", ".tar", ".zip")


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


def _is_counted_file(path: Path) -> bool:
    """Return whether a file counts toward the uncompressed source total."""
    name = path.name
    if name == MANIFEST_FILENAME:
        return False
    lowered = name.lower()
    if any(lowered.endswith(suffix) for suffix in _ARCHIVE_SUFFIXES):
        return False
    return not lowered.endswith(".lock")


def _sum_tree(root: Path, seen: set[str]) -> tuple[int, int]:
    """Sum every data file under a generator-owned output root."""
    total = 0
    count = 0
    for child in sorted(root.rglob("*")):
        child_key = str(child)
        if child.is_file() and child_key not in seen and _is_counted_file(child):
            seen.add(child_key)
            total += child.stat().st_size
            count += 1
    return total, count


def _sum_paths(paths: object) -> tuple[int, int]:
    """Sum file bytes under generator return values (dict | list | nested).

    Some generators return only table paths while emitting additional corpora
    elsewhere in their output tree (for example the primitives bulk-load
    files). Directories are therefore walked in full, so every generator-owned
    file beneath a returned directory counts toward the total.
    """
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
            if candidate.is_file() and _is_counted_file(candidate):
                total += candidate.stat().st_size
                count += 1
            elif candidate.is_dir():
                dir_total, dir_count = _sum_tree(candidate, seen)
                total += dir_total
                count += dir_count
    return total, count


def _sum_manifest_rows(root: Path) -> int | None:
    """Sum row_count entries from manifests written beneath an output root.

    Returns None when no manifest with row metadata is present.
    """
    summed: int | None = None
    for manifest_path in sorted(root.rglob(MANIFEST_FILENAME)):
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        tables = manifest.get(_MANIFEST_TABLES_KEY)
        if not isinstance(tables, dict):
            continue
        manifest_rows = 0
        found = False
        for table_data in tables.values():
            if not isinstance(table_data, dict):
                continue
            formats = table_data.get("formats")
            entries_iter: list[object] = []
            if isinstance(formats, dict):
                for entries in formats.values():
                    if isinstance(entries, list):
                        entries_iter.extend(entries)
            elif isinstance(table_data.get("files"), list):
                entries_iter.extend(table_data["files"])
            for entry in entries_iter:
                if isinstance(entry, dict) and isinstance(entry.get("row_count"), int):
                    manifest_rows += entry["row_count"]
                    found = True
        if found:
            summed = (summed or 0) + manifest_rows
    return summed


def _run_generator(module: str, cls_name: str, extra: dict) -> tuple[int, int, int | None, float]:
    """Instantiate a generator at SF=1 uncompressed and sum its output."""
    module_obj = __import__(module, fromlist=[cls_name])
    cls = getattr(module_obj, cls_name)
    with tempfile.TemporaryDirectory(prefix="sf1measure-") as tmp:
        start = mono_time()
        try:
            instance = cls(scale_factor=1.0, output_dir=tmp, compress_data=False, **extra)
        except TypeError:
            # Generators with narrower constructors (no compression flags).
            instance = cls(scale_factor=1.0, output_dir=tmp, **extra)
        # Benchmarks with auxiliary source datasets (TPC-DS-OBT's TPC-DS
        # cache, DataVault's TPC-H cache) derive those paths from the output
        # root. Point them beneath the temp root too so multi-GB caches are
        # cleaned up with the measurement and never touch shared caches.
        tmp_path = Path(tmp)
        source_dir = tmp_path / "source_cache"
        if hasattr(instance, "tpcds_source_dir"):
            instance.tpcds_source_dir = source_dir / "tpcds_sf1"
        if hasattr(instance, "_tpch_source_dir"):
            instance._tpch_source_dir = source_dir / "tpch_sf1"
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
            paths = tmp_path
        elapsed = elapsed_seconds(start)
        # Measure the whole generator-owned tree, not just the returned
        # paths: primitives generators emit a bulk-load auxiliary corpus
        # alongside the returned table paths, and benchmark-level runners
        # may stage archives next to their outputs.
        total, count = _sum_paths([paths, tmp_path])
        rows = _sum_manifest_rows(tmp_path)
        return total, count, rows, elapsed


def measure_one(benchmark: str) -> SizeRecord:
    """Measure a single benchmark, never raising."""
    record = SizeRecord(benchmark=benchmark)
    start = mono_time()
    try:
        entry = next((g for g in GENERATORS if g[0] == benchmark), None)
        if entry is None:
            entry = next((g for g in BENCHMARK_LEVEL if g[0] == benchmark), None)
        if entry is None:
            record.error = f"no measurement entry for {benchmark}"
            return record
        _, module, cls_name, extra = entry
        total, count, rows, elapsed = _run_generator(module, cls_name, extra)
        record.total_bytes = total
        record.file_count = count
        record.total_rows = rows
        record.elapsed_seconds = round(elapsed, 1)
        if total == 0:
            record.error = "generator emitted no measurable files"
    except Exception as exc:  # noqa: BLE001 - record per-benchmark failures as data
        record.error = f"{type(exc).__name__}: {exc}"
        record.elapsed_seconds = round(elapsed_seconds(start), 1)
        traceback.print_exc()
    return record


def all_benchmark_ids() -> list[str]:
    """Every benchmark with a measurement entry, in registry order."""
    return [g[0] for g in GENERATORS] + [g[0] for g in BENCHMARK_LEVEL]


def measure_many(benchmarks: list[str], jobs: int = 1) -> list[SizeRecord]:
    """Measure benchmarks sequentially or with bounded process parallelism."""
    if jobs < 1:
        raise ValueError(f"--jobs must be >= 1, got {jobs}")
    if jobs == 1 or len(benchmarks) <= 1:
        return [measure_one(benchmark) for benchmark in benchmarks]
    with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
        return list(pool.map(measure_one, benchmarks))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--benchmark",
        default="",
        help="Comma-separated subset to measure (default: all).",
    )
    parser.add_argument("--output", default="", help="Write JSON records here (default: stdout).")
    parser.add_argument(
        "--jobs",
        type=int,
        default=1,
        help="Parallel benchmark processes (default: 1, sequential). Use only with ample scratch space.",
    )
    args = parser.parse_args(argv)

    if args.jobs < 1:
        print(f"--jobs must be >= 1, got {args.jobs}", file=sys.stderr)
        return 2

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
    if args.jobs == 1:
        measured = [measure_one(benchmark) for benchmark in wanted]
        for benchmark, record in zip(wanted, measured, strict=True):
            print(f"measuring {benchmark} at SF=1 (uncompressed) ...", file=sys.stderr)
            _report_record(record)
            if record.error:
                failed += 1
            records.append(asdict(record))
    else:
        print(
            f"measuring {len(wanted)} benchmarks at SF=1 (uncompressed) with --jobs {args.jobs} ...",
            file=sys.stderr,
        )
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.jobs) as pool:
            future_map = {pool.submit(measure_one, benchmark): benchmark for benchmark in wanted}
            done: dict[str, dict] = {}
            for future in concurrent.futures.as_completed(future_map):
                record = future.result()
                done[record.benchmark] = asdict(record)
                _report_record(record)
                if record.error:
                    failed += 1
        records = [done[benchmark] for benchmark in wanted]

    payload = {"scale_factor": 1.0, "compression": "none", "records": records}
    text = json.dumps(payload, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)
    return 1 if failed else 0


def _report_record(record: SizeRecord) -> None:
    """Log one completed measurement to stderr."""
    if record.error:
        print(f"  {record.benchmark} FAILED: {record.error}", file=sys.stderr)
    else:
        gib = record.total_bytes / (1024**3)
        print(
            f"  {record.benchmark}: {record.total_bytes} bytes ({gib:.3f} GiB) in {record.elapsed_seconds}s",
            file=sys.stderr,
        )


if __name__ == "__main__":
    raise SystemExit(main())
