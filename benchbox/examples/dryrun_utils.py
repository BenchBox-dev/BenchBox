from __future__ import annotations

from pathlib import Path

from benchbox.core.dryrun import DryRunExecutor
from benchbox.core.results.display import print_dry_run_summary
from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig, DryRunResult
from benchbox.core.system import SystemProfiler


def ensure_output_directory(path: Path) -> Path:

    resolved = Path(path).expanduser().resolve()
    if resolved.exists() and not resolved.is_dir():
        raise ValueError(f"Dry run output path must be a directory: {resolved}")
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def execute_example_dry_run(
    *,
    benchmark_config: BenchmarkConfig,
    database_config: DatabaseConfig | None,
    output_dir: Path,
    filename_prefix: str,
) -> tuple[DryRunResult, dict[str, Path]]:

    destination = ensure_output_directory(output_dir)

    executor = DryRunExecutor(destination)
    system_profile = SystemProfiler().get_system_profile()

    result = executor.execute_dry_run(
        benchmark_config=benchmark_config,
        system_profile=system_profile,
        database_config=database_config,
    )

    if result.warnings:
        target_name = benchmark_config.name.lower()
        filtered_warnings = []
        for warning in result.warnings:
            extracted = None
            marker = "benchmark '"
            if marker in warning:
                start = warning.find(marker) + len(marker)
                end = warning.find("'", start)
                if end != -1:
                    extracted = warning[start:end].lower()
            if extracted and extracted != target_name:
                continue
            filtered_warnings.append(warning)
        result.warnings = filtered_warnings

    if not result.queries:
        fallback_queries = _load_fallback_queries(benchmark_config)
        if fallback_queries:
            result.queries = fallback_queries
            preview = result.query_preview or {}
            preview.setdefault("query_count", len(fallback_queries))
            preview.setdefault("queries", list(fallback_queries.keys()))
            preview.setdefault("execution_context", "Standard sequential execution (fallback)")
            result.query_preview = preview

    saved_files = executor.save_dry_run_results(result, filename_prefix)
    print_dry_run_summary(result, destination, saved_files=saved_files)

    return result, saved_files


def _load_fallback_queries(benchmark_config: BenchmarkConfig) -> dict[str, str] | None:

    name = benchmark_config.name.lower()
    try:
        from benchbox import (
            SSB,
            TPCDS,
            TPCH,
            ClickBench,
            ReadPrimitives,
            WritePrimitives,
        )
    except ImportError:
        return None

    mapping = {
        "tpch": TPCH,
        "tpcds": TPCDS,
        "clickbench": ClickBench,
        "read_primitives": ReadPrimitives,
        "write_primitives": WritePrimitives,
        "ssb": SSB,
    }

    benchmark_cls = mapping.get(name)
    if benchmark_cls is None:
        return None

    try:
        benchmark = benchmark_cls(scale_factor=benchmark_config.scale_factor)
        queries = benchmark.get_queries()
    except Exception:
        return None

    if not queries:
        return None

    return {str(key): value for key, value in queries.items()}


__all__ = [
    "ensure_output_directory",
    "execute_example_dry_run",
]
