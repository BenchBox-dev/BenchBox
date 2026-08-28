#!/usr/bin/env python3
"""Run TPC-H benchmark using cuDF (GPU-accelerated DataFrames).

cuDF is NVIDIA's GPU DataFrame library, part of the RAPIDS ecosystem.
It provides massive performance improvements through GPU acceleration
while maintaining a Pandas-compatible API.

Prerequisites:
    1. NVIDIA GPU with CUDA support (compute capability 6.0+)
    2. NVIDIA CUDA Toolkit installed
    3. cuDF library installed:
       pip install cudf-cu12  # For CUDA 12.x
       pip install cudf-cu11  # For CUDA 11.x

GPU Memory Considerations:
    - cuDF loads entire DataFrames into GPU memory
    - TPC-H SF=0.01 requires ~50MB GPU memory
    - TPC-H SF=1.0 requires ~1GB GPU memory
    - TPC-H SF=10.0 requires ~10GB GPU memory
    - Enable spill_to_host=True to avoid OOM errors

Performance Notes:
    - 10-100x faster than CPU Pandas for large datasets
    - Best for compute-intensive operations (joins, aggregations)
    - Data transfer GPU<->CPU is the main bottleneck
    - Pre-load data to GPU, run many queries, then extract results

Usage:
    # Generate data first (if not already done)
    benchbox run --platform duckdb --benchmark tpch --scale 0.01 --phases load

    # Run cuDF benchmark
    python examples/dataframe/cudf_tpch.py

    # With different scale factor
    python examples/dataframe/cudf_tpch.py --scale 1.0

Copyright 2026 Joe Harris / BenchBox Project.
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Check GPU availability early
try:
    import cudf

    print(f"cuDF version: {cudf.__version__}")

    # Check CUDA availability
    try:
        import cupy

        print(f"CuPy version: {cupy.__version__}")
        print(f"CUDA Device: {cupy.cuda.Device()}")
    except Exception as e:
        print(f"GPU info: {e}")
except ImportError:
    print("Error: cuDF not installed.")
    print()
    print("Install cuDF with:")
    print("  pip install cudf-cu12  # For CUDA 12.x")
    print("  pip install cudf-cu11  # For CUDA 11.x")
    print()
    print("Requirements:")
    print("  - NVIDIA GPU with CUDA support")
    print("  - NVIDIA CUDA Toolkit installed")
    print("  - cuDF version matching your CUDA version")
    sys.exit(1)


def check_gpu_memory() -> dict[str, float]:
    """Check available GPU memory.

    Returns:
        Dictionary with free and total memory in GB.
    """
    try:
        import cupy

        mempool = cupy.get_default_memory_pool()
        pinned_mempool = cupy.get_default_pinned_memory_pool()

        device = cupy.cuda.Device()
        free_mem, total_mem = device.mem_info

        return {
            "free_gb": free_mem / (1024**3),
            "total_gb": total_mem / (1024**3),
            "used_pool_gb": mempool.used_bytes() / (1024**3),
            "pinned_pool_gb": pinned_mempool.n_free_blocks(),
        }
    except Exception:
        return {"free_gb": 0, "total_gb": 0}


def estimate_memory_requirement(scale_factor: float) -> float:
    """Estimate GPU memory required for TPC-H at given scale.

    Args:
        scale_factor: TPC-H scale factor

    Returns:
        Estimated memory requirement in GB.
    """
    # Approximate: ~500MB per SF=0.1
    return scale_factor * 0.5


def main(argv: list[str] | None = None) -> int:
    """Run cuDF DataFrame TPC-H benchmark demonstration."""
    parser = argparse.ArgumentParser(description="Run TPC-H on cuDF (GPU)")
    parser.add_argument("--scale", type=float, default=0.01, help="Scale factor")
    parser.add_argument("--device", type=int, default=0, help="CUDA device ID")
    parser.add_argument("--spill", action="store_true", help="Enable GPU->CPU memory spilling")
    args = parser.parse_args(argv)

    scale_factor = args.scale
    device_id = args.device

    print("=" * 70)
    print("cuDF GPU DataFrame TPC-H Benchmark")
    print("=" * 70)

    # Check GPU memory
    print("\nGPU Status:")
    mem_info = check_gpu_memory()
    if mem_info["total_gb"] > 0:
        print(f"  Total GPU Memory: {mem_info['total_gb']:.1f} GB")
        print(f"  Free GPU Memory: {mem_info['free_gb']:.1f} GB")

        required = estimate_memory_requirement(scale_factor)
        print(f"\nMemory Requirement for SF={scale_factor}:")
        print(f"  Estimated: {required:.2f} GB")

        if required > mem_info["free_gb"]:
            print("  WARNING: May need more GPU memory! Consider:")
            print("    - Using smaller scale factor")
            print("    - Enabling spill_to_host with --spill flag")
            print("    - Closing other GPU applications")
    else:
        print("  Could not query GPU memory")

    # Check data availability
    data_dir = Path(f"benchmark_runs/tpch/sf{scale_factor}/data")
    if not data_dir.exists():
        print(f"\nWarning: Data directory not found: {data_dir}")
        print("Generate data first with:")
        print(f"  benchbox run --platform duckdb --benchmark tpch --scale {scale_factor} --phases load")
        print("\nSkipping query execution.")
        return 0

    # Import BenchBox components
    print("\nLoading BenchBox DataFrame components...")
    from benchbox.platforms.dataframe.cudf_df import CuDFDataFrameAdapter

    # Create adapter with GPU configuration
    print(f"\nCreating cuDF adapter (device={device_id}, spill={args.spill})...")
    adapter = CuDFDataFrameAdapter(
        device_id=device_id,
        spill_to_host=args.spill,
        verbose=True,
    )

    # Create context
    ctx = adapter.create_context()

    # Load tables from Parquet
    parquet_dir = data_dir / "parquet"
    if not parquet_dir.exists():
        print(f"Parquet directory not found: {parquet_dir}")
        return 1

    print("\nLoading tables to GPU memory...")
    print("  (This transfers data from CPU to GPU - may take a moment)")

    tables = [
        "lineitem",
        "orders",
        "customer",
        "supplier",
        "part",
        "partsupp",
        "nation",
        "region",
    ]

    load_start = time.time()
    for table in tables:
        table_path = parquet_dir / f"{table}.parquet"
        if table_path.exists():
            try:
                # Load directly to GPU memory
                start = time.time()
                df = cudf.read_parquet(str(table_path))
                load_time = time.time() - start

                row_count = len(df)
                mem_usage = df.memory_usage().sum() / (1024**2)

                ctx[table] = df
                print(f"  {table}: {row_count:,} rows, {mem_usage:.1f} MB GPU, loaded in {load_time:.2f}s")
            except Exception as e:
                print(f"  {table}: Error loading - {e}")
        else:
            print(f"  {table}: File not found")

    total_load_time = time.time() - load_start
    print(f"\nTotal load time: {total_load_time:.2f}s")

    # Check GPU memory after loading
    mem_after = check_gpu_memory()
    if mem_after["total_gb"] > 0:
        used = mem_after["total_gb"] - mem_after["free_gb"]
        print(f"GPU memory used: {used:.2f} GB / {mem_after['total_gb']:.1f} GB")

    # Execute sample queries
    print("\n" + "-" * 70)
    print("Executing Sample Queries")
    print("-" * 70)

    # Import TPC-H query definitions
    from benchbox.core.tpch.dataframe_queries import get_query

    sample_queries = ["Q1", "Q6"]  # Simple aggregation queries that work well on GPU

    for qid in sample_queries:
        try:
            query = get_query(qid)
        except KeyError:
            print(f"\nQuery {qid} not found")
            continue

        print(f"\n{qid}: {query.query_name}")
        print(f"  Description: {query.description}")

        try:
            # Execute on GPU
            start = time.time()
            result = query.execute(ctx, "pandas")  # cuDF uses pandas family API
            exec_time = time.time() - start

            print(f"  Execution time: {exec_time:.4f}s (GPU)")
            print(f"  Result shape: {result.shape}")
            print("  First 3 rows:")

            # Convert to pandas for display (small result set)
            display_df = result.head(3).to_pandas() if hasattr(result, "to_pandas") else result.head(3)
            print(display_df)

        except Exception as e:
            print(f"  Error: {e}")

    # Cleanup
    print("\n" + "-" * 70)
    print("Cleanup")
    print("-" * 70)

    # Clear GPU memory
    try:
        import cupy

        mempool = cupy.get_default_memory_pool()
        pinned_mempool = cupy.get_default_pinned_memory_pool()

        mempool.free_all_blocks()
        pinned_mempool.free_all_blocks()
        print("GPU memory pools cleared")
    except Exception:
        pass

    print("\n" + "=" * 70)
    print("cuDF GPU Benchmark Complete!")
    print("=" * 70)

    print("\nNext steps:")
    print("  - Try larger scale factors: --scale 1.0")
    print("  - Enable memory spilling: --spill")
    print("  - Compare with CPU: python examples/dataframe/polars_tpch.py")
    print("  - Run full benchmark: benchbox run --platform cudf-df --benchmark tpch")

    return 0


if __name__ == "__main__":
    sys.exit(main())
