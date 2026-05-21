"""Benchmark execution tools for BenchBox MCP server.

Provides tools for running benchmarks, validating configurations,
and performing dry runs.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from benchbox.core.benchmark_registry import (
    get_all_benchmarks,
    get_benchmark_class,
    get_benchmark_default_scale,
)
from benchbox.core.results.exporter import ResultExporter
from benchbox.core.results.schema import build_result_payload
from benchbox.core.schemas import ExecutionContext
from benchbox.mcp.errors import (
    ErrorCode,
    make_error,
    make_execution_error,
    make_not_found_error,
    make_unsupported_mode_error,
)
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path
from benchbox.utils.printing import get_quiet_console, silence_output

logger = logging.getLogger(__name__)

# Tool annotations for benchmark execution tools
RUN_BENCHMARK_ANNOTATIONS = ToolAnnotations(
    title="Execute benchmark",
    readOnlyHint=False,  # Creates files, runs queries
    destructiveHint=False,  # Does not delete existing data
    idempotentHint=False,  # Each run produces new results
    openWorldHint=True,  # Interacts with external databases
)

# Tool annotations for query details (read-only)
QUERY_DETAILS_ANNOTATIONS = ToolAnnotations(
    title="Get query details",
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)


def _get_platform_adapter(platform: str, mode: str | None = None, **config):
    """Get platform adapter from public API."""
    from benchbox.platforms import get_dataframe_adapter, get_platform_adapter, is_dataframe_platform

    platform_lower = platform.lower()
    use_dataframe = mode == "dataframe" or is_dataframe_platform(platform_lower)

    if use_dataframe:
        df_config = {k: v for k, v in config.items() if k not in ("benchmark", "scale_factor")}
        return get_dataframe_adapter(platform_lower, **df_config)
    else:
        return get_platform_adapter(platform_lower, **config)


def _validate_and_resolve_mode(platform: str, mode: str | None) -> tuple[str, dict | None]:
    """Validate mode against platform capabilities, resolve default if not specified."""
    from benchbox.core.platform_registry import PlatformRegistry

    if mode is not None:
        mode = mode.lower()
        if mode in ("datagen", "generate"):
            mode = "data_only"

    if mode == "data_only":
        return "data_only", None

    platform_lower = platform.lower()
    base_platform = platform_lower.replace("-df", "")

    caps = PlatformRegistry.get_platform_capabilities(base_platform)
    if caps is None:
        return mode or "sql", None

    supported = []
    if caps.supports_sql:
        supported.append("sql")
    if caps.supports_dataframe:
        supported.append("dataframe")
    supported.append("data_only")

    if mode is not None:
        if not PlatformRegistry.supports_mode(base_platform, mode):
            return mode, make_unsupported_mode_error(platform, mode, supported)
        return mode, None

    if platform_lower.endswith("-df"):
        return "dataframe", None
    return caps.default_mode, None


def _map_phases_to_test_execution_type(phases: list[str]) -> str:
    """Map benchmark phases to test execution type."""
    phases_set = set(phases)
    query_phases = {"power", "throughput", "maintenance"}

    if phases_set & query_phases:
        if "power" in phases_set and "throughput" in phases_set and "maintenance" in phases_set:
            return "combined"
        elif "power" in phases_set:
            return "power"
        elif "throughput" in phases_set:
            return "throughput"
        elif "maintenance" in phases_set:
            return "maintenance"
        else:
            return "standard"
    elif phases == ["load"] or ("load" in phases_set and not phases_set & query_phases):
        return "load_only"
    elif phases == ["generate"] or ("generate" in phases_set and not phases_set & ({"load"} | query_phases)):
        return "data_only"
    else:
        return "standard"


def register_benchmark_tools(mcp: FastMCP, *, results_dir: Path) -> None:
    """Register benchmark execution tools with the MCP server."""
    resolved_results_dir = Path(results_dir)

    @mcp.tool(annotations=RUN_BENCHMARK_ANNOTATIONS)
    def run_benchmark(
        platform: str,
        benchmark: str,
        scale_factor: float = 0.01,
        queries: str | None = None,
        phases: str | None = None,
        mode: str | None = None,
        capture_plans: bool = False,
        dry_run: bool = False,
        validate_only: bool = False,
    ) -> dict[str, Any]:
        """Run a benchmark on a database platform.

        Args:
            platform: Target platform (duckdb, polars-df, snowflake, etc.)
            benchmark: Benchmark to run (tpch, tpcds, tpcds_obt, ssb, joinorder, clickbench, nyctaxi, tsbs_devops, h2odb, amplab, coffeeshop, tpch_skew, datavault, tpcdi, write_primitives, read_primitives, and more)
            scale_factor: Data scale factor (0.01 for testing, 1+ for production; joinorder uses canonical IMDb 2013 data and only accepts 1.0)
            queries: Comma-separated query IDs to run (e.g., "1,3,6")
            phases: Comma-separated phases (default: "load,power")
            mode: Execution mode: 'sql', 'dataframe', or 'data_only'
            capture_plans: Capture query execution plans (3-8%% overhead). Supported: DuckDB, PostgreSQL, DataFusion.
            dry_run: Preview execution plan without running
            validate_only: Validate configuration without running

        Returns:
            Benchmark results, dry-run preview, or validation status.

        Platform options (passed via the CLI --platform-option KEY=VALUE flag):
            driver_version: Pin the Python driver package to a specific version (e.g. "1.2.0").
                Available for all platforms.
            driver_auto_install: Auto-install the requested driver version via uv if not already
                installed ("true"/"false"). Available for all platforms.
            engine_version: Select the Spark engine version for Athena Spark
                (e.g. "PySpark engine version 3"). Athena Spark only; auto-probed on other platforms.

        JoinOrder note:
            The public joinorder benchmark downloads and verifies the canonical IMDb 2013
            Parquet archive on first use, then reuses BENCHBOX_OUTPUT_DIR/benchmark_runs/datagen/joinorder_sf1/.
        """
        # Handle validate_only mode
        if validate_only:
            return _validate_config_impl(platform, benchmark, scale_factor, mode)

        # Handle dry_run mode
        if dry_run:
            return _dry_run_impl(platform, benchmark, scale_factor, queries, mode)

        # Run benchmark
        return _run_benchmark_impl(
            platform,
            benchmark,
            scale_factor,
            queries,
            phases,
            mode,
            capture_plans,
            results_dir=resolved_results_dir,
        )

    @mcp.tool(annotations=QUERY_DETAILS_ANNOTATIONS)
    def get_query_details(
        benchmark: str,
        query_id: str,
        platform: str | None = None,
        mode: str | None = None,
    ) -> dict[str, Any]:
        """Get detailed information about a specific query.

        Args:
            benchmark: Benchmark name (tpch, tpcds, ssb, clickbench, nyctaxi, tsbs_devops, h2odb, amplab, coffeeshop, tpch_skew, datavault, and more)
            query_id: Query identifier (e.g., '1', 'Q1', '17')
            platform: Target platform for dialect translation
            mode: Execution mode: 'sql' or 'dataframe'

        Returns:
            Query details including SQL text or DataFrame source code.
        """
        benchmark_lower = benchmark.lower()
        all_benchmarks = get_all_benchmarks()

        if benchmark_lower not in all_benchmarks:
            return make_not_found_error("benchmark", benchmark, available=list(all_benchmarks.keys()))

        try:
            resolved_mode = _resolve_query_details_mode(platform, mode)
            normalized_id = query_id.upper().lstrip("Q")
            if not normalized_id.isdigit():
                normalized_id = query_id

            meta = all_benchmarks[benchmark_lower]

            response: dict[str, Any] = {
                "benchmark": benchmark_lower,
                "query_id": query_id,
                "normalized_id": normalized_id,
                "execution_mode": resolved_mode,
            }

            if platform:
                response["platform"] = platform.lower()

            if resolved_mode == "dataframe":
                _populate_dataframe_query_details(response, benchmark_lower, normalized_id, platform)
            else:
                _populate_sql_query_details(response, benchmark_lower, normalized_id, platform)

            response["complexity_hints"] = _get_query_complexity_hints(benchmark_lower, normalized_id)
            response["benchmark_info"] = {
                "display_name": meta.get("display_name", benchmark_lower),
                "category": meta.get("category", "unknown"),
                "support_status": meta["support_status"],
            }

            return response

        except Exception as e:
            return make_error(
                ErrorCode.INTERNAL_ERROR,
                f"Failed to get query details: {e}",
                details={"benchmark": benchmark, "query_id": query_id, "exception_type": type(e).__name__},
            )


def _make_failed_response(error_response: dict[str, Any], execution_id: str) -> dict[str, Any]:
    """Attach execution_id and failed status to an error response."""
    error_response["execution_id"] = execution_id
    error_response["status"] = "failed"
    return error_response


def _export_and_build_payload(
    result: Any,
    execution_id: str,
    results_dir: Path,
) -> tuple[str | None, dict[str, Any] | None]:
    """Export benchmark result to JSON and build payload dict."""
    result_file_path = None
    result_payload: dict[str, Any] | None = None
    try:
        result.execution_id = execution_id
        exporter = ResultExporter(output_dir=results_dir, anonymize=False, console=get_quiet_console())
        exported_files = exporter.export_result(result, formats=["json"])
        if "json" in exported_files:
            result_file_path = str(exported_files["json"])
            with open(result_file_path, encoding="utf-8") as handle:
                result_payload = json.load(handle)
    except Exception as export_err:
        logger.warning(f"Failed to export benchmark results: {export_err}")
        try:
            result_payload = build_result_payload(result)
        except Exception as payload_err:
            logger.warning(f"Failed to build benchmark payload: {payload_err}")
    return result_file_path, result_payload


def _attach_summary_charts(response: dict[str, Any], result: Any) -> None:
    """Attach post-run summary charts to the response if available."""
    if not result or not result.query_results:
        return
    try:
        from benchbox.core.visualization.post_run_summary import generate_post_run_summary

        summary = generate_post_run_summary(result)
        if summary.charts:
            response["summary_charts"] = {
                "summary_box": summary.summary_box,
                "query_histogram": summary.query_histogram,
            }
    except Exception:
        logger.debug("Failed to generate post-run summary charts", exc_info=True)


def _run_benchmark_impl(
    platform: str,
    benchmark: str,
    scale_factor: float,
    queries: str | None,
    phases: str | None,
    mode: str | None,
    capture_plans: bool = False,
    *,
    results_dir: Path,
) -> dict[str, Any]:
    """Core implementation for running benchmarks."""
    execution_id = f"mcp_{uuid.uuid4().hex[:8]}"
    start_time = mono_time()

    try:
        benchmark_lower = benchmark.lower()
        all_benchmarks = get_all_benchmarks()

        if benchmark_lower not in all_benchmarks:
            return _make_failed_response(
                make_not_found_error("benchmark", benchmark, available=list(all_benchmarks.keys())), execution_id
            )

        benchmark_class = get_benchmark_class(benchmark_lower)
        if benchmark_class is None:
            return _make_failed_response(
                make_error(
                    ErrorCode.DEPENDENCY_MISSING,
                    f"Benchmark '{benchmark}' requires additional dependencies",
                    details={"benchmark": benchmark},
                ),
                execution_id,
            )

        resolved_mode, mode_error = _validate_and_resolve_mode(platform, mode)
        if mode_error:
            return _make_failed_response(mode_error, execution_id)

        if resolved_mode == "data_only":
            return _generate_data_impl(benchmark_lower, benchmark_class, scale_factor, execution_id, start_time)

        benchmark_instance = benchmark_class(scale_factor=scale_factor)

        try:
            adapter = _get_platform_adapter(
                platform, mode=resolved_mode, benchmark=benchmark_lower, scale_factor=scale_factor
            )
        except (ValueError, ImportError) as e:
            return _make_failed_response(
                make_error(ErrorCode.VALIDATION_UNSUPPORTED_PLATFORM, str(e), details={"platform": platform}),
                execution_id,
            )

        query_subset = [q.strip() for q in queries.split(",")] if queries else None
        phases_list = [p.strip() for p in (phases or "load,power").split(",")]
        execution_context = ExecutionContext(
            entry_point="mcp",
            phases=phases_list,
            query_subset=query_subset,
            mode=resolved_mode if resolved_mode in ("sql", "dataframe") else "sql",
        )

        test_execution_type = _map_phases_to_test_execution_type(phases_list)

        with silence_output(enabled=True):
            result = benchmark_instance.run_with_platform(
                adapter,
                query_subset=query_subset,
                test_execution_type=test_execution_type,
                capture_plans=capture_plans,
            )

        if result is not None:
            result.execution_context = execution_context.model_dump()

        execution_time = elapsed_seconds(start_time)

        result_file_path, result_payload = (
            _export_and_build_payload(result, execution_id, results_dir) if result else (None, None)
        )

        response: dict[str, Any] = result_payload or {}
        response["mcp_metadata"] = {
            "execution_id": execution_id,
            "status": "completed" if result else "no_results",
            "platform_requested": platform,
            "benchmark_requested": benchmark,
            "scale_factor_requested": scale_factor,
            "execution_mode": resolved_mode,
            "execution_time_seconds": round(execution_time, 2),
            "result_file": result_file_path,
        }

        _attach_summary_charts(response, result)

        return response

    except Exception as e:
        logger.exception(f"Benchmark execution failed: {e}")
        error_response = make_execution_error(
            f"Benchmark execution failed: {e}",
            execution_id=execution_id,
            exception=e,
            retry_hint=False,
        )
        error_response["status"] = "failed"
        error_response["platform"] = platform
        error_response["benchmark"] = benchmark
        error_response["execution_time_seconds"] = round(elapsed_seconds(start_time), 2)
        return error_response


def _generate_data_impl(
    benchmark_lower: str,
    benchmark_class: type,
    scale_factor: float,
    execution_id: str,
    start_time: float,
) -> dict[str, Any]:
    """Generate benchmark data without running queries."""
    data_dir = get_benchmark_runs_datagen_path(benchmark_lower, scale_factor)
    data_dir.mkdir(parents=True, exist_ok=True)

    bm = benchmark_class(scale_factor=scale_factor)

    if hasattr(bm, "generate_data"):
        with silence_output(enabled=True):
            bm.generate_data(output_dir=data_dir, format="parquet")
    elif hasattr(bm, "generate"):
        with silence_output(enabled=True):
            bm.generate(output_dir=data_dir)
    else:
        error_response = make_error(
            ErrorCode.INTERNAL_ERROR,
            f"Benchmark '{benchmark_lower}' does not support data generation",
            details={"benchmark": benchmark_lower},
        )
        error_response["execution_id"] = execution_id
        error_response["status"] = "failed"
        return error_response

    generated_files = list(data_dir.glob("*.parquet"))
    if not generated_files:
        generated_files = list(data_dir.glob("*.*"))

    total_size = sum(f.stat().st_size for f in generated_files if f.is_file())
    execution_time = elapsed_seconds(start_time)

    return {
        "mcp_metadata": {
            "execution_id": execution_id,
            "status": "completed",
            "execution_mode": "data_only",
            "execution_time_seconds": round(execution_time, 2),
            "result_file": None,
        },
        "data_generation": {
            "status": "generated",
            "benchmark": benchmark_lower,
            "scale_factor": scale_factor,
            "data_path": str(data_dir),
            "file_count": len(generated_files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "files": [f.name for f in generated_files[:20]],
            "files_truncated": len(generated_files) > 20,
        },
    }


def _dry_run_impl(
    platform: str,
    benchmark: str,
    scale_factor: float,
    queries: str | None,
    mode: str | None,
) -> dict[str, Any]:
    """Preview what a benchmark run would do without executing."""
    from benchbox.core.dryrun import DryRunExecutor
    from benchbox.core.platform_registry import PlatformRegistry
    from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig
    from benchbox.core.system import SystemProfiler

    try:
        benchmark_lower = benchmark.lower()
        all_benchmarks = get_all_benchmarks()

        if benchmark_lower not in all_benchmarks:
            error_response = make_not_found_error("benchmark", benchmark, available=list(all_benchmarks.keys()))
            error_response["status"] = "error"
            return error_response

        platform_lower = platform.lower()
        base_platform = platform_lower.replace("-df", "")
        platform_info = PlatformRegistry.get_platform_info(base_platform)

        warnings: list[str] = []
        if platform_info is None:
            warnings.append(f"Unknown platform: {platform}")
        elif not platform_info.available:
            warnings.append(f"Platform '{platform}' dependencies not installed: {platform_info.installation_command}")

        resolved_mode, mode_error = _validate_and_resolve_mode(platform, mode)
        if mode_error:
            mode_error["status"] = "error"
            return mode_error

        meta = all_benchmarks[benchmark_lower]
        display_name = meta.get("display_name", benchmark_lower.upper())

        benchmark_config = BenchmarkConfig(
            name=benchmark_lower,
            display_name=display_name,
            scale_factor=scale_factor,
            queries=[q.strip() for q in queries.split(",")] if queries else None,
        )

        database_config = DatabaseConfig(
            type=platform_lower,
            name=f"mcp_dryrun_{platform_lower}",
            execution_mode=resolved_mode,
        )

        profiler = SystemProfiler()
        system_profile = profiler.get_system_profile()

        executor = DryRunExecutor(output_dir=None)
        result = executor.execute_dry_run(benchmark_config, system_profile, database_config)

        warnings.extend(result.warnings)

        response: dict[str, Any] = {
            "status": "dry_run",
            "platform": platform,
            "benchmark": benchmark,
            "scale_factor": scale_factor,
            "execution_mode": result.execution_mode,
        }

        if result.query_preview:
            query_ids = result.query_preview.get("queries", [])
            response["execution_plan"] = {
                "phases": ["load", "power"],
                "total_queries": result.query_preview.get("query_count", 0),
                "query_ids": query_ids[:30],
                "query_ids_truncated": len(query_ids) > 30,
            }

        if result.estimated_resources:
            data_size_mb = result.estimated_resources.get("estimated_data_size_mb", 0)
            response["resource_estimates"] = {
                "data_size_gb": round(data_size_mb / 1024, 2),
                "memory_recommended_gb": max(2, round(data_size_mb / 1024 * 2, 1)),
            }

        if warnings:
            response["warnings"] = warnings

        return response

    except Exception as e:
        logger.exception(f"Dry run failed: {e}")
        error_response = make_error(
            ErrorCode.INTERNAL_ERROR,
            f"Dry run failed: {e}",
            details={"exception_type": type(e).__name__},
        )
        error_response["status"] = "error"
        return error_response


def _validate_platform_config(
    platform: str, platform_lower: str, base_platform: str, errors: list[str], warnings: list[str]
) -> Any:
    """Validate platform availability and return platform info."""
    from benchbox.core.platform_registry import PlatformRegistry

    info = PlatformRegistry.get_platform_info(base_platform)
    if info is None:
        errors.append(f"Unknown platform: {platform}")
    elif not info.available:
        errors.append(f"Platform '{platform}' dependencies not installed: {info.installation_command}")

    cloud_platforms = ["snowflake", "bigquery", "databricks", "redshift"]
    if base_platform in cloud_platforms:
        warnings.append(f"Cloud platform '{platform}' requires credential configuration")

    return info


def _validate_mode_config(
    mode: str | None, platform: str, base_platform: str, info: Any, errors: list[str]
) -> str | None:
    """Validate and resolve execution mode."""
    from benchbox.core.platform_registry import PlatformRegistry

    if mode is None:
        return PlatformRegistry.get_default_mode(base_platform)

    mode_lower = mode.lower()
    if mode_lower in ("datagen", "generate"):
        mode_lower = "data_only"

    if mode_lower not in ("sql", "dataframe", "data_only"):
        errors.append(f"Invalid mode: {mode}. Must be 'sql', 'dataframe', or 'data_only'")
        return None

    if mode_lower == "data_only":
        return "data_only"

    if info is not None and not PlatformRegistry.supports_mode(base_platform, mode_lower):
        supported = [m for m in ["sql", "dataframe"] if PlatformRegistry.supports_mode(base_platform, m)]
        supported.append("data_only")
        errors.append(f"Platform '{platform}' doesn't support {mode_lower} mode. Supported: {', '.join(supported)}")
        return None

    return mode_lower


def _validate_benchmark_config(
    benchmark: str,
    benchmark_lower: str,
    scale_factor: float,
    platform_lower: str,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Validate benchmark name, scale factor, and dataframe compatibility."""
    from benchbox.platforms import is_dataframe_platform

    all_benchmarks = get_all_benchmarks()

    if benchmark_lower not in all_benchmarks:
        errors.append(f"Unknown benchmark: {benchmark}. Available: {', '.join(all_benchmarks.keys())}")
    else:
        meta = all_benchmarks[benchmark_lower]
        min_scale = meta.get("min_scale", 0.01)
        if scale_factor < min_scale:
            warnings.append(f"{benchmark} requires scale factor >= {min_scale}")
        if is_dataframe_platform(platform_lower) and not meta.get("supports_dataframe", False):
            errors.append(f"DataFrame mode does not support {benchmark} benchmark")

    if scale_factor <= 0:
        errors.append(f"Scale factor must be positive, got: {scale_factor}")
    elif scale_factor < 0.01:
        warnings.append(f"Scale factor {scale_factor} is very small")


def _validate_config_impl(
    platform: str,
    benchmark: str,
    scale_factor: float,
    mode: str | None,
) -> dict[str, Any]:
    """Validate a benchmark configuration before running."""
    errors: list[str] = []
    warnings: list[str] = []

    platform_lower = platform.lower()
    base_platform = platform_lower.replace("-df", "")

    info = _validate_platform_config(platform, platform_lower, base_platform, errors, warnings)
    resolved_mode = _validate_mode_config(mode, platform, base_platform, info, errors)

    benchmark_lower = benchmark.lower()
    _validate_benchmark_config(benchmark, benchmark_lower, scale_factor, platform_lower, errors, warnings)

    return {
        "valid": len(errors) == 0,
        "platform": platform,
        "benchmark": benchmark,
        "scale_factor": scale_factor,
        "execution_mode": resolved_mode,
        "errors": errors,
        "warnings": warnings,
    }


def _resolve_query_details_mode(platform: str | None, mode: str | None) -> str:
    """Resolve the execution mode for get_query_details."""
    if mode is not None:
        return mode.lower()

    if platform is not None:
        from benchbox.platforms import is_dataframe_platform

        if is_dataframe_platform(platform.lower()):
            return "dataframe"

    return "sql"


def _get_dataframe_family_for_platform(platform: str | None) -> str | None:
    """Determine the DataFrame family for a platform."""
    if platform is None:
        return None

    from benchbox import DATAFRAME_PLATFORMS

    base = platform.lower().replace("-df", "")
    info = DATAFRAME_PLATFORMS.get(base)
    if info is not None:
        return info.family.value
    return None


def _resolve_dataframe_impl(df_query: Any, family: str | None) -> tuple[Any | None, str | None]:
    """Resolve the best DataFrame implementation for the given family.

    Returns (impl, resolved_family) where resolved_family is set only when
    family was None and we auto-detected which implementation to use.
    """
    if family == "expression" and df_query.expression_impl is not None:
        return df_query.expression_impl, None
    if family == "pandas" and df_query.pandas_impl is not None:
        return df_query.pandas_impl, None
    if df_query.expression_impl is not None:
        return df_query.expression_impl, "expression" if family is None else None
    if df_query.pandas_impl is not None:
        return df_query.pandas_impl, "pandas" if family is None else None
    return None, None


def _populate_dataframe_query_details(
    response: dict[str, Any],
    benchmark: str,
    normalized_id: str,
    platform: str | None,
) -> None:
    """Populate response dict with DataFrame query details."""
    import inspect

    family = _get_dataframe_family_for_platform(platform)
    if family:
        response["dataframe_family"] = family

    registry_id = f"Q{normalized_id}"
    df_query = None

    if benchmark == "tpch":
        from benchbox import TPCH_DATAFRAME_QUERIES

        df_query = TPCH_DATAFRAME_QUERIES.get(registry_id)
    elif benchmark == "tpcds":
        from benchbox import TPCDS_DATAFRAME_QUERIES

        df_query = TPCDS_DATAFRAME_QUERIES.get(registry_id)

    if df_query is None:
        response["error"] = f"No DataFrame query found for {benchmark} {registry_id}"
        return

    response["query_name"] = df_query.query_name
    response["description"] = df_query.description
    response["has_expression_impl"] = df_query.has_expression_impl()
    response["has_pandas_impl"] = df_query.has_pandas_impl()

    impl, resolved_family = _resolve_dataframe_impl(df_query, family)
    if resolved_family:
        response["dataframe_family"] = resolved_family

    if impl is not None:
        try:
            source = inspect.getsource(impl)
            if len(source) > 5000:
                response["source_code"] = source[:5000]
                response["source_truncated"] = True
            else:
                response["source_code"] = source
                response["source_truncated"] = False
        except OSError:
            response["source_code"] = None
            response["source_truncated"] = False


def _populate_sql_query_details(
    response: dict[str, Any],
    benchmark: str,
    normalized_id: str,
    platform: str | None,
) -> None:
    """Populate response dict with SQL query details."""
    benchmark_class = get_benchmark_class(benchmark)
    if benchmark_class is None:
        response["error"] = f"Benchmark '{benchmark}' requires additional dependencies"
        return

    bm = benchmark_class(scale_factor=get_benchmark_default_scale(benchmark))

    dialect = None
    if platform is not None:
        from benchbox.core.config_inheritance import get_platform_family_dialect

        platform_lower = platform.lower().replace("-df", "")
        try:
            dialect = get_platform_family_dialect(platform_lower)
        except Exception:
            pass

    query_sql = None
    try:
        kwargs: dict[str, Any] = {}
        if dialect:
            kwargs["dialect"] = dialect
        try:
            query_sql = bm.get_query(int(normalized_id), **kwargs)
        except (ValueError, TypeError):
            query_sql = bm.get_query(normalized_id, **kwargs)
    except (KeyError, ValueError, TypeError):
        import contextlib

        with contextlib.suppress(KeyError, ValueError):
            query_sql = bm.get_query(normalized_id)

    if query_sql:
        if len(query_sql) > 2000:
            response["sql"] = query_sql[:2000]
            response["sql_truncated"] = True
        else:
            response["sql"] = query_sql
            response["sql_truncated"] = False


def _get_query_complexity_hints(benchmark: str, query_id: str) -> dict[str, Any]:
    """Get complexity hints for a specific query."""
    tpch_hints: dict[str, dict[str, Any]] = {
        "1": {"type": "aggregation", "tables": ["lineitem"], "complexity": "simple", "joins": 0},
        "2": {
            "type": "correlated_subquery",
            "tables": ["part", "supplier", "partsupp", "nation", "region"],
            "complexity": "complex",
            "joins": 5,
        },
        "3": {
            "type": "join_aggregate",
            "tables": ["customer", "orders", "lineitem"],
            "complexity": "medium",
            "joins": 2,
        },
        "4": {"type": "exists_subquery", "tables": ["orders", "lineitem"], "complexity": "medium", "joins": 1},
        "5": {
            "type": "multi_join",
            "tables": ["customer", "orders", "lineitem", "supplier", "nation", "region"],
            "complexity": "complex",
            "joins": 5,
        },
        "6": {"type": "scan_filter", "tables": ["lineitem"], "complexity": "simple", "joins": 0},
        "7": {
            "type": "multi_join",
            "tables": ["supplier", "lineitem", "orders", "customer", "nation"],
            "complexity": "complex",
            "joins": 6,
        },
        "8": {
            "type": "multi_join",
            "tables": ["part", "supplier", "lineitem", "orders", "customer", "nation", "region"],
            "complexity": "complex",
            "joins": 7,
        },
        "9": {
            "type": "multi_join",
            "tables": ["part", "supplier", "lineitem", "partsupp", "orders", "nation"],
            "complexity": "complex",
            "joins": 5,
        },
        "10": {
            "type": "join_aggregate",
            "tables": ["customer", "orders", "lineitem", "nation"],
            "complexity": "medium",
            "joins": 3,
        },
        "11": {
            "type": "having_subquery",
            "tables": ["partsupp", "supplier", "nation"],
            "complexity": "medium",
            "joins": 2,
        },
        "12": {"type": "case_aggregate", "tables": ["orders", "lineitem"], "complexity": "medium", "joins": 1},
        "13": {"type": "outer_join", "tables": ["customer", "orders"], "complexity": "medium", "joins": 1},
        "14": {"type": "case_aggregate", "tables": ["lineitem", "part"], "complexity": "simple", "joins": 1},
        "15": {"type": "view_with_max", "tables": ["lineitem", "supplier"], "complexity": "medium", "joins": 1},
        "16": {
            "type": "distinct_aggregate",
            "tables": ["partsupp", "part", "supplier"],
            "complexity": "medium",
            "joins": 2,
        },
        "17": {"type": "correlated_subquery", "tables": ["lineitem", "part"], "complexity": "complex", "joins": 1},
        "18": {
            "type": "having_subquery",
            "tables": ["customer", "orders", "lineitem"],
            "complexity": "complex",
            "joins": 3,
        },
        "19": {"type": "or_predicates", "tables": ["lineitem", "part"], "complexity": "medium", "joins": 1},
        "20": {
            "type": "exists_subquery",
            "tables": ["supplier", "nation", "partsupp", "part", "lineitem"],
            "complexity": "complex",
            "joins": 4,
        },
        "21": {
            "type": "not_exists",
            "tables": ["supplier", "lineitem", "orders", "nation"],
            "complexity": "complex",
            "joins": 4,
        },
        "22": {"type": "not_exists", "tables": ["customer", "orders"], "complexity": "complex", "joins": 1},
    }

    if benchmark == "tpch" and query_id in tpch_hints:
        return tpch_hints[query_id]

    return {
        "type": "unknown",
        "complexity": "unknown",
        "note": f"Complexity hints not available for {benchmark} query {query_id}",
    }
