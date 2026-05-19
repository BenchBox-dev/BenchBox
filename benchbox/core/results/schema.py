"""Schema v2.0 utilities for benchmark result export.

This module provides construction and validation of the BenchBox result export format
(schema version 2.0). All exporters and downstream tooling should rely on these helpers
to ensure the canonical layout stays consistent.

Schema v2.0 Design Principles:
1. Single Source of Truth - No duplication
2. Progressive Detail - Summary first, then details
3. Omit Empty - No null placeholders, no unused sections
4. Clear Separation - Identity / Config / Results / Phases
5. Flat Where Possible - Reduce nesting depth
6. Consistent Units - All times in milliseconds
"""

from __future__ import annotations

import logging
import statistics
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.results.builder import normalize_benchmark_id
from benchbox.core.results.environment import (
    build_environment_payload,
    build_platform_metadata_payload,
)
from benchbox.core.results.query_normalizer import normalize_query_id

if TYPE_CHECKING:
    from benchbox.core.results.models import BenchmarkResults

SCHEMA_VERSION = "2.1"

logger = logging.getLogger(__name__)

CANONICAL_KEY_ORDER = [
    "version",
    "run",
    "benchmark",
    "platform",
    "config",
    "summary",
    "phases",
    "queries",
    "tables",
    "validation",
    "comparisons",
    "cost",
    "normalized_cost",
    "execution",
    "environment",
    "export",
    "errors",
]

QUERY_KEY_ORDER = ["id", "ms", "rows", "iter", "stream", "run_type", "status", "dataframe_skip_summary"]
CONFIG_KEY_ORDER = [
    "compression",
    "seed",
    "phases",
    "query_subset",
    "parallelism",
    "tuning_mode",
    "tuning_config",
    "platform_options",
    "platform_option_sources",
    "table_mode",
    "external_format",
    "table_format",
    "table_format_compression",
    "table_format_partition_cols",
    "mode",
    "test_type",
]
PHASE_KEY_ORDER = [
    "data_generation",
    "schema_creation",
    "data_loading",
    "validation",
    "migration",
    "power_test",
    "throughput_test",
]
DRIVER_METADATA_KEYS = (
    "driver_package",
    "driver_version_requested",
    "driver_version_resolved",
    "driver_version_actual",
    "driver_runtime_strategy",
    "driver_runtime_path",
    "driver_runtime_python_executable",
    "driver_auto_install_used",
)
ENGINE_VERSION_KEYS = (
    "engine_version",
    "engine_version_source",
)

# Maps driver metadata source keys to their result JSON destination keys.
_DRIVER_PLATFORM_KEYS = [
    ("driver_package", "driver_package"),
    ("driver_version_requested", "driver_requested_version"),
    ("driver_version_resolved", "driver_resolved_version"),
    ("driver_version_actual", "driver_actual_version"),
    ("driver_runtime_strategy", "driver_runtime_strategy"),
]


def order_dict(d: dict[str, Any], key_order: list[str]) -> dict[str, Any]:
    """Return dict with keys ordered for stable JSON diffs."""
    from collections import OrderedDict

    ordered: OrderedDict[str, Any] = OrderedDict()
    for key in key_order:
        if key in d:
            ordered[key] = d[key]
    for key in sorted(d.keys()):
        if key not in ordered:
            ordered[key] = d[key]
    return ordered


def _normalize_query_result(qr: Any) -> dict[str, Any]:
    """Normalize a query result entry to a dictionary.

    Handles dict, dataclass, Pydantic model, or object with attributes.
    """
    if isinstance(qr, dict):
        return qr
    if is_dataclass(qr) and not isinstance(qr, type):
        return asdict(qr)
    # Handle Pydantic models (have model_dump method)
    if hasattr(qr, "model_dump"):
        return qr.model_dump()
    # Handle older Pydantic models (have dict method)
    if hasattr(qr, "dict"):
        return qr.dict()
    # Fallback: try to extract common attributes
    result: dict[str, Any] = {}
    for attr in (
        "query_id",
        "id",
        "status",
        "execution_time_seconds",
        "execution_time_ms",
        "rows_returned",
        "iteration",
        "stream_id",
        "error_message",
        "run_type",
        "error",
        "error_type",
        "query_plan",
        "plan_fingerprint",
        "dataframe_skip_summary",
    ):
        if hasattr(qr, attr):
            val = getattr(qr, attr)
            if val is not None:
                result[attr] = val
    return result


def _round_duration_ms_for_export(value: float) -> float:
    """Round milliseconds for schema-v2 export without erasing measured sub-ms durations."""
    rounded = round(value, 1)
    if value <= 0 or rounded > 0:
        return rounded
    return float(f"{value:.6g}")


class SchemaV2ValidationError(ValueError):
    """Raised when schema v2.0 validation fails."""


class SchemaV2Validator:
    """Validates schema v2.0 structure.

    Required keys: version, run, benchmark, platform, summary, queries
    Optional keys: environment, tables, errors, cost, export
    """

    REQUIRED_KEYS = ("version", "run", "benchmark", "platform", "summary", "queries")
    OPTIONAL_KEYS = (
        "environment",
        "tables",
        "errors",
        "cost",
        "normalized_cost",
        "export",
        "tuning",
        "execution",
        "config",
        "phases",
    )

    RUN_REQUIRED = ("id", "timestamp", "total_duration_ms", "query_time_ms")
    BENCHMARK_REQUIRED = ("id", "name", "scale_factor")
    PLATFORM_REQUIRED = ("name",)
    SUMMARY_REQUIRED = ("queries", "timing")

    def validate(self, payload: dict[str, Any]) -> None:
        """Raise ``SchemaV2ValidationError`` when the payload lacks required structure."""
        # Check top-level keys
        missing_top = [key for key in self.REQUIRED_KEYS if key not in payload]
        if missing_top:
            raise SchemaV2ValidationError(f"schema v2.0 payload missing keys: {missing_top}")

        # Validate version (accept 2.0 and 2.1 as valid)
        valid_versions = ("2.0", "2.1")
        if payload.get("version") not in valid_versions:
            raise SchemaV2ValidationError(
                f"invalid schema version {payload.get('version')} (expected one of {valid_versions})"
            )

        # Validate run block
        run = payload.get("run", {})
        if not isinstance(run, Mapping):
            raise SchemaV2ValidationError("run block must be a mapping")
        missing_run = [key for key in self.RUN_REQUIRED if key not in run]
        if missing_run:
            raise SchemaV2ValidationError(f"run block missing keys: {missing_run}")

        # Validate benchmark block
        benchmark = payload.get("benchmark", {})
        if not isinstance(benchmark, Mapping):
            raise SchemaV2ValidationError("benchmark block must be a mapping")
        missing_benchmark = [key for key in self.BENCHMARK_REQUIRED if key not in benchmark]
        if missing_benchmark:
            raise SchemaV2ValidationError(f"benchmark block missing keys: {missing_benchmark}")

        # Validate platform block
        platform = payload.get("platform", {})
        if not isinstance(platform, Mapping):
            raise SchemaV2ValidationError("platform block must be a mapping")
        missing_platform = [key for key in self.PLATFORM_REQUIRED if key not in platform]
        if missing_platform:
            raise SchemaV2ValidationError(f"platform block missing keys: {missing_platform}")

        # Validate summary block
        summary = payload.get("summary", {})
        if not isinstance(summary, Mapping):
            raise SchemaV2ValidationError("summary block must be a mapping")
        missing_summary = [key for key in self.SUMMARY_REQUIRED if key not in summary]
        if missing_summary:
            raise SchemaV2ValidationError(f"summary block missing keys: {missing_summary}")

        # Validate queries is a list
        queries = payload.get("queries")
        if not isinstance(queries, list):
            raise SchemaV2ValidationError("queries must be a list")

        # Check for unexpected top-level keys
        unexpected = set(payload.keys()) - set(self.REQUIRED_KEYS) - set(self.OPTIONAL_KEYS)
        if unexpected:
            raise SchemaV2ValidationError(f"schema v2.0 payload contains unexpected keys: {sorted(unexpected)}")


def build_result_payload(result: BenchmarkResults) -> dict[str, Any]:
    """Build v2.0 result payload from BenchmarkResults.

    Args:
        result: A BenchmarkResults instance from the lifecycle runner.

    Returns:
        A dictionary conforming to schema v2.0 and ready for JSON serialization.

    The compact query format:
        {"id": "Q1", "ms": 632.9, "rows": 100}
        {"id": "1", "ms": 189.2, "rows": 4, "iter": 1}
        {"id": "11", "ms": 376.8, "rows": 91, "stream": 1}
    """
    # Extract query data
    query_times_ms, queries_list, errors_list, iterations_set, streams_set = _build_query_results_section(result)

    # Compute timing statistics
    measurement_queries = [q for q in queries_list if q.get("run_type") == "measurement"]
    total_queries = len(measurement_queries)
    successful_queries = len([q for q in measurement_queries if q.get("status") == "SUCCESS"])
    skipped_queries = len([q for q in measurement_queries if q.get("status") == "SKIPPED"])
    failed_count = total_queries - successful_queries - skipped_queries

    summary = _build_summary_section(
        result, query_times_ms, total_queries, successful_queries, failed_count, skipped_queries
    )
    run = _build_run_section(result, query_times_ms, iterations_set, streams_set)
    benchmark = _build_benchmark_section(result)
    driver_metadata = _collect_driver_metadata(result)
    platform = _build_platform_section(result, driver_metadata)

    # Build environment block
    environment = _build_environment_block(result)

    # Build tables block (compact)
    tables = _build_tables_block(result.table_statistics)

    # Build config and phases blocks
    config_block = _build_config_block(result)
    phases_block = _build_phases_block(result)

    # Add table loading errors if present
    if result.execution_phases:
        table_errors = _extract_table_errors(result.execution_phases)
        errors_list.extend(table_errors)

    # Build the payload
    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "run": order_dict(
            run, ["id", "timestamp", "total_duration_ms", "query_time_ms", "iterations", "streams", "query_subset"]
        ),
        "benchmark": order_dict(benchmark, ["id", "name", "scale_factor", "test_type"]),
        "platform": order_dict(
            platform,
            [
                "name",
                "version",
                "client_version",
                "variant",
                "config",
                "deployment",
                "cloud",
                "compute",
                "storage",
                "raw_config",
                "raw_metadata",
                "tuning",
            ],
        ),
        "config": order_dict(config_block, CONFIG_KEY_ORDER),
        "summary": order_dict(summary, ["queries", "timing", "data", "validation", "tpc_metrics"]),
        "phases": order_dict(phases_block, PHASE_KEY_ORDER),
        "queries": queries_list,
    }

    # Add optional sections (only if non-empty)
    if environment:
        payload["environment"] = environment
    if tables:
        payload["tables"] = tables
    if errors_list:
        errors_list.sort(key=lambda e: (e.get("phase", ""), e.get("query_id", ""), e.get("type", "")))
        payload["errors"] = errors_list

    _add_comparisons_section(payload, result)
    _add_cost_section(payload, result)
    _add_execution_section(payload, result, driver_metadata)

    return order_dict(payload, CANONICAL_KEY_ORDER)


def _build_query_results_section(
    result: BenchmarkResults,
) -> tuple[list[float], list[dict[str, Any]], list[dict[str, Any]], set[int], set[int]]:
    """Extract and normalize query results into timing data, query list, and errors."""
    query_times_ms: list[float] = []
    queries_list: list[dict[str, Any]] = []
    errors_list: list[dict[str, Any]] = []
    iterations_set: set[int] = set()
    streams_set: set[int] = set()

    normalized_results = [_normalize_query_result(qr) for qr in (result.query_results or [])]

    for qr in normalized_results:
        iteration = qr.get("iteration", 1)
        stream_id = qr.get("stream_id", 0)
        if iteration is not None:
            iterations_set.add(int(iteration))
        if stream_id is not None:
            streams_set.add(int(stream_id))

    for qr in normalized_results:
        raw_id = qr.get("query_id") or qr.get("id") or qr.get("query") or ""
        query_id = normalize_query_id(raw_id)
        status = qr.get("status", "UNKNOWN")

        # Get execution time in ms, preferring canonical seconds key.
        exec_time_ms = qr.get("execution_time_ms")
        exec_time_seconds = qr.get("execution_time_seconds")
        if exec_time_ms is None and exec_time_seconds is not None:
            exec_time_ms = float(exec_time_seconds) * 1000.0

        rows = qr.get("rows_returned") or qr.get("rows") or qr.get("result_count")
        iteration = int(qr.get("iteration", 1))
        stream_id = int(qr.get("stream_id", 0))
        run_type = qr.get("run_type")
        if not run_type:
            run_type = "warmup" if iteration == 0 else "measurement"

        if status == "SUCCESS":
            if exec_time_ms is not None and run_type == "measurement":
                query_times_ms.append(exec_time_ms)
        elif status != "SKIPPED":
            error_entry = {
                "phase": "query",
                "query_id": str(query_id),
            }
            error_type = (
                qr.get("error_type") or qr.get("error_message", "").split(":")[0]
                if qr.get("error_message")
                else "UnknownError"
            )
            error_entry["type"] = error_type or "UnknownError"
            error_entry["message"] = qr.get("error_message") or qr.get("error") or "Query failed"
            errors_list.append(error_entry)

        entry: dict[str, Any] = {"id": str(query_id)}
        if exec_time_ms is not None:
            entry["ms"] = _round_duration_ms_for_export(float(exec_time_ms))
        if rows is not None:
            entry["rows"] = rows
        entry["iter"] = iteration
        entry["stream"] = stream_id
        entry["run_type"] = run_type
        entry["status"] = status
        if qr.get("dataframe_skip_summary"):
            entry["dataframe_skip_summary"] = qr["dataframe_skip_summary"]

        queries_list.append(order_dict(entry, QUERY_KEY_ORDER))

    return query_times_ms, queries_list, errors_list, iterations_set, streams_set


def _build_summary_section(
    result: BenchmarkResults,
    query_times_ms: list[float],
    total_queries: int,
    successful_queries: int,
    failed_count: int,
    skipped_queries: int = 0,
) -> dict[str, Any]:
    """Build the summary block of the payload."""
    timing_stats = _compute_timing_stats(query_times_ms)

    summary: dict[str, Any] = {
        "queries": {
            "total": total_queries,
            "passed": successful_queries,
            "failed": failed_count,
        },
        "timing": timing_stats,
    }
    if skipped_queries:
        summary["queries"]["skipped"] = skipped_queries

    if result.total_rows_loaded or result.data_loading_time:
        data_stats: dict[str, Any] = {}
        if result.total_rows_loaded:
            data_stats["rows_loaded"] = result.total_rows_loaded
        if result.data_loading_time:
            data_stats["load_time_ms"] = round(result.data_loading_time * 1000, 1)
        if data_stats:
            summary["data"] = data_stats

    if result.validation_status:
        summary["validation"] = result.validation_status.lower()

    tpc_metrics = _build_tpc_metrics(result)
    if tpc_metrics:
        summary["tpc_metrics"] = tpc_metrics

    return summary


def _build_run_section(
    result: BenchmarkResults,
    query_times_ms: list[float],
    iterations_set: set[int],
    streams_set: set[int],
) -> dict[str, Any]:
    """Build the run block of the payload."""
    run: dict[str, Any] = {
        "id": result.execution_id,
        "timestamp": result.timestamp.isoformat() if result.timestamp else datetime.now().isoformat(),
        "total_duration_ms": round(result.duration_seconds * 1000),
        "query_time_ms": round(sum(query_times_ms)),
    }
    run["iterations"] = max(iterations_set) if iterations_set else 1
    run["streams"] = max(streams_set) if streams_set else 1
    if result.query_subset:
        run["query_subset"] = result.query_subset
    return run


def _build_benchmark_section(result: BenchmarkResults) -> dict[str, Any]:
    """Build the benchmark block of the payload."""
    benchmark_name = _shorten_benchmark_name(result.benchmark_name)
    section: dict[str, Any] = {
        "id": result.benchmark_id,
        "name": benchmark_name,
        "scale_factor": result.scale_factor,
        "test_type": result.test_execution_type,
    }
    compliance_class = getattr(result, "compliance_class", None)
    if compliance_class is not None:
        section["compliance_class"] = compliance_class
    section.update(_dataset_identity_fields(result))
    return section


def _dataset_identity_fields(result: BenchmarkResults) -> dict[str, str]:
    """Return canonical dataset identity fields for data-manifest benchmarks."""
    captured_identity = {
        "dataset_version": getattr(result, "dataset_version", None),
        "manifest_hash": getattr(result, "manifest_hash", None),
        "data_archive_hash": getattr(result, "data_archive_hash", None),
    }
    if any(value is not None for value in captured_identity.values()):
        return {key: str(value) for key, value in captured_identity.items() if value is not None}

    benchmark_id = result.benchmark_id
    try:
        from benchbox.core.benchmark_registry import get_benchmark_metadata
        from benchbox.core.data_fetch import load_manifest

        metadata = get_benchmark_metadata(benchmark_id) or {}
        manifest_rel = metadata.get("data_manifest")
        if not manifest_rel:
            return {}
        repo_root = Path(__file__).resolve().parents[3]
        manifest = load_manifest(repo_root / str(manifest_rel))
    except Exception as exc:  # pragma: no cover - identity is best-effort for export
        logger.warning("Unable to load dataset identity for %s: %s", benchmark_id, exc)
        return {}
    return {
        "dataset_version": manifest.dataset_version,
        "manifest_hash": manifest.manifest_hash,
        "data_archive_hash": manifest.data_archive_hash,
    }


def _build_platform_section(result: BenchmarkResults, driver_metadata: dict[str, Any]) -> dict[str, Any]:
    """Build the platform block of the payload."""
    platform_name = str(result.platform).replace(" (DataFrame)", "")
    platform: dict[str, Any] = {"name": platform_name}
    config: dict[str, Any] = {}

    if result.platform_info:
        version = result.platform_info.get("platform_version") or result.platform_info.get("version")
        client_version = result.platform_info.get("client_library_version")
        platform["version"] = version or "unknown"
        platform["client_version"] = client_version or "unknown"
        variant = result.platform_info.get("variant")
        if variant:
            platform["variant"] = variant

        config = _extract_platform_config(result.platform_info)
        if config:
            platform["config"] = config

    platform.update(
        build_platform_metadata_payload(
            platform_info=result.platform_info,
            platform_config=config,
            deployment=getattr(result, "platform_deployment", None),
            cloud=getattr(result, "platform_cloud", None),
            compute=getattr(result, "platform_compute", None),
            storage=getattr(result, "platform_storage", None),
            raw_config=getattr(result, "platform_raw_config", None) or config,
            raw_metadata=(
                getattr(result, "platform_raw_metadata", None)
                if getattr(result, "platform_raw_metadata", None) is not None
                else getattr(result, "platform_metadata", None)
            ),
        )
    )

    for src_key, dest_key in _DRIVER_PLATFORM_KEYS:
        if driver_metadata.get(src_key):
            platform[dest_key] = driver_metadata[src_key]

    engine_metadata = _collect_engine_version_metadata(result)
    if engine_metadata.get("engine_version"):
        platform["engine_version"] = engine_metadata["engine_version"]
    if engine_metadata.get("engine_version_source"):
        platform["engine_version_source"] = engine_metadata["engine_version_source"]

    if "version" not in platform:
        platform["version"] = "unknown"
    if "client_version" not in platform:
        platform["client_version"] = "unknown"

    tuning = _build_tuning_summary(result)
    if tuning:
        platform["tuning"] = tuning

    return platform


def _add_comparisons_section(payload: dict[str, Any], result: BenchmarkResults) -> None:
    """Add pg_duckdb vs native DuckDB comparison to payload if available (omit-empty)."""
    nc = getattr(result, "native_comparison", None)
    if nc is None:
        return
    payload["comparisons"] = {
        "native_duckdb": {
            "generated_at": nc.generated_at,
            "scale_factor": nc.scale_factor,
            "total_queries": nc.total_queries,
            "mean_delta_ms": nc.mean_delta_ms,
            "max_delta_ms": nc.max_delta_ms,
            "queries": [
                {
                    "id": e.query_id,
                    "pg_duckdb_ms": e.pg_duckdb_ms,
                    "duckdb_ms": e.duckdb_ms,
                    "delta_ms": e.delta_ms,
                }
                for e in nc.entries
            ],
        }
    }


def _add_cost_section(payload: dict[str, Any], result: BenchmarkResults) -> None:
    """Add cost summary to payload if available."""
    if result.cost_summary:
        normalized_cost = result.cost_summary.get("normalized_cost")
        if isinstance(normalized_cost, dict):
            payload["normalized_cost"] = normalized_cost
        cost_block: dict[str, Any] = {}
        if "total_cost" in result.cost_summary and _normalized_cost_allows_direct_total(normalized_cost):
            cost_block["total_usd"] = result.cost_summary["total_cost"]
        cost_block["model"] = result.cost_summary.get("cost_model", "estimated")
        if cost_block:
            payload["cost"] = cost_block


def _normalized_cost_allows_direct_total(normalized_cost: Any) -> bool:
    """Return True when legacy direct cost totals can satisfy the public contract.

    A genuinely missing normalized_cost block (legacy bundles produced before
    the normalized_cost contract existed) means we have nothing to *reject*
    — the direct total is the only signal available, so allow it. Only an
    explicitly-rejected normalized_cost dict (e.g. ``cost_status="unavailable"``)
    blocks emitting the direct total.
    """
    if normalized_cost is None:
        return True
    if not isinstance(normalized_cost, dict):
        return False
    if normalized_cost.get("cost_status") not in {"normalized", "not_applicable_local"}:
        return False
    return normalized_cost.get("normalized_cost_usd") is not None


def _add_execution_section(payload: dict[str, Any], result: BenchmarkResults, driver_metadata: dict[str, Any]) -> None:
    """Add execution context section to payload."""
    if result.execution_context:
        exec_block = _build_execution_from_context(result, driver_metadata)
        if exec_block:
            payload["execution"] = exec_block

    if "execution" not in payload:
        exec_block = _build_execution_fallback(result, driver_metadata)
        if exec_block:
            payload["execution"] = exec_block


# Simple ctx-key → exec-block-key passthrough fields for _build_execution_from_context.
_EXEC_CTX_PASSTHROUGH = [
    ("entry_point", "entry_point"),
    ("invocation_timestamp", "timestamp"),
]
_EXEC_CTX_TRUTHY = [
    ("official", "official", True),
    ("capture_plans", "capture_plans", True),
    ("strict_plan_capture", "strict_plan_capture", True),
    ("non_interactive", "non_interactive", True),
]
_EXEC_CTX_VALUE = ["validation_mode", "query_subset", "tuning_mode"]


def _build_execution_from_context(result: BenchmarkResults, driver_metadata: dict[str, Any]) -> dict[str, Any]:
    """Build execution block from execution_context."""
    exec_block: dict[str, Any] = {}
    ctx = result.execution_context

    for ctx_key, block_key in _EXEC_CTX_PASSTHROUGH:
        if ctx.get(ctx_key):
            exec_block[block_key] = ctx[ctx_key]

    phases = ctx.get("phases")
    if phases and phases != ["power"]:
        exec_block["phases"] = phases

    if ctx.get("seed") is not None:
        exec_block["seed"] = ctx["seed"]

    if ctx.get("compression_enabled"):
        compression = {"type": ctx.get("compression_type", "none")}
        if ctx.get("compression_level"):
            compression["level"] = ctx["compression_level"]
        exec_block["compression"] = compression

    mode_value = _resolve_execution_mode(result, ctx)
    if mode_value:
        exec_block["mode"] = mode_value

    _inject_driver_metadata(exec_block, driver_metadata)

    for ctx_key, block_key, value in _EXEC_CTX_TRUTHY:
        if ctx.get(ctx_key):
            exec_block[block_key] = value

    force_flags = [f for f, key in [("datagen", "force_datagen"), ("upload", "force_upload")] if ctx.get(key)]
    if force_flags:
        exec_block["force"] = force_flags

    for key in _EXEC_CTX_VALUE:
        if ctx.get(key):
            exec_block[key] = ctx[key]

    return exec_block


def _build_execution_fallback(result: BenchmarkResults, driver_metadata: dict[str, Any]) -> dict[str, Any]:
    """Build execution block when no execution_context is available."""
    exec_block: dict[str, Any] = {}
    mode_value = None
    if isinstance(result.execution_metadata, Mapping):
        mode_value = result.execution_metadata.get("mode")
    if not mode_value and result.platform_info:
        mode_value = result.platform_info.get("execution_mode")
    if mode_value:
        exec_block["mode"] = mode_value
    _inject_driver_metadata(exec_block, driver_metadata)
    return exec_block


def _resolve_execution_mode(result: BenchmarkResults, ctx: dict[str, Any]) -> Any:
    """Resolve the execution mode from context, metadata, or platform_info."""
    if ctx.get("mode"):
        return ctx["mode"]
    if isinstance(result.execution_metadata, Mapping):
        mode = result.execution_metadata.get("mode")
        if mode:
            return mode
    if result.platform_info:
        return result.platform_info.get("execution_mode")
    return None


def _collect_driver_metadata(result: BenchmarkResults) -> dict[str, Any]:
    """Collect driver metadata from result fields and compatibility fallbacks."""
    metadata: dict[str, Any] = {}

    for key in DRIVER_METADATA_KEYS:
        value = getattr(result, key, None)
        if value:
            metadata[key] = value

    execution_metadata = result.execution_metadata if isinstance(result.execution_metadata, Mapping) else {}
    for key in DRIVER_METADATA_KEYS:
        if key in metadata:
            continue
        value = execution_metadata.get(key)
        if value:
            metadata[key] = value

    platform_info = result.platform_info if isinstance(result.platform_info, Mapping) else {}
    # Compatibility aliases from platform_info.
    aliases = {
        "driver_package": ("driver_package",),
        "driver_version_requested": ("driver_version_requested",),
        "driver_version_resolved": ("driver_version_resolved",),
        "driver_version_actual": ("driver_version_actual", "runtime_version_actual"),
        "driver_runtime_strategy": ("driver_runtime_strategy",),
        "driver_runtime_path": ("driver_runtime_path",),
        "driver_runtime_python_executable": ("driver_runtime_python_executable",),
    }
    for canonical, keys in aliases.items():
        if canonical in metadata:
            continue
        for key in keys:
            value = platform_info.get(key)
            if value:
                metadata[canonical] = value
                break

    return metadata


def _collect_engine_version_metadata(result: BenchmarkResults) -> dict[str, Any]:
    """Collect engine/service version metadata from result fields and fallbacks.

    Engine version is the database service/runtime version, which may differ from
    the Python driver/client version. For coupled platforms (DuckDB, DataFusion),
    engine version equals driver version. For decoupled platforms (Snowflake, etc.),
    engine version is probed from connection or API metadata.
    """
    metadata: dict[str, Any] = {}

    # Direct result fields (set by adapter or runner).
    for key in ENGINE_VERSION_KEYS:
        value = getattr(result, key, None)
        if value:
            metadata[key] = value

    # Fallback: check execution_metadata.
    if not metadata.get("engine_version"):
        execution_metadata = result.execution_metadata if isinstance(result.execution_metadata, Mapping) else {}
        for key in ENGINE_VERSION_KEYS:
            if key not in metadata:
                value = execution_metadata.get(key)
                if value:
                    metadata[key] = value

    # Fallback: check platform_info.
    if not metadata.get("engine_version"):
        platform_info = result.platform_info if isinstance(result.platform_info, Mapping) else {}
        for key in ENGINE_VERSION_KEYS:
            if key not in metadata:
                value = platform_info.get(key)
                if value:
                    metadata[key] = value

    return metadata


def _inject_driver_metadata(exec_block: dict[str, Any], driver_metadata: dict[str, Any]) -> None:
    """Inject driver metadata into execution block."""
    for key in DRIVER_METADATA_KEYS:
        value = driver_metadata.get(key)
        if value:
            exec_block[key] = value


def _shorten_benchmark_name(name: str) -> str:
    if name.lower().endswith(" benchmark"):
        return name[: -len(" benchmark")]
    return name


# Fields that fall back from ctx → run_cfg (use_is_not_none=True for seed).
_CONFIG_CTX_OR_RUN = ["seed", "phases", "query_subset"]
_CONFIG_RUN_ONLY = [
    "platform_options",
    "platform_option_sources",
    "tuning_mode",
    "tuning_config",
    "table_mode",
    "external_format",
    "table_format",
    "table_format_compression",
    "table_format_partition_cols",
]


def _build_config_block(result: BenchmarkResults) -> dict[str, Any]:
    config: dict[str, Any] = {}
    ctx = result.execution_context or {}
    run_cfg = {}
    if isinstance(result.execution_metadata, Mapping):
        run_cfg = result.execution_metadata.get("run_config") or {}

    # Compression has special merging logic
    compression = None
    if ctx.get("compression_type") or run_cfg.get("compression"):
        if ctx.get("compression_type"):
            compression = {"type": ctx.get("compression_type"), "level": ctx.get("compression_level")}
        else:
            compression = run_cfg.get("compression")
    if compression:
        config["compression"] = compression

    # Fields that prefer ctx, fall back to run_cfg
    for key in _CONFIG_CTX_OR_RUN:
        value = ctx.get(key)
        if value is None:
            value = run_cfg.get(key)
        if value is not None:
            config[key] = value

    # Fields sourced only from run_cfg
    for key in _CONFIG_RUN_ONLY:
        if run_cfg.get(key):
            config[key] = run_cfg[key]

    # Execution mode for reproducibility
    exec_mode = None
    if isinstance(result.execution_metadata, Mapping):
        exec_mode = result.execution_metadata.get("mode")
    if not exec_mode and result.platform_info:
        exec_mode = result.platform_info.get("execution_mode")
    if exec_mode:
        config["mode"] = exec_mode

    return config


def _build_phases_block(result: BenchmarkResults) -> dict[str, Any]:
    phases: dict[str, Any] = {}
    standard = [
        "data_generation",
        "schema_creation",
        "data_loading",
        "validation",
        "power_test",
        "throughput_test",
    ]

    setup = getattr(result.execution_phases, "setup", None) if result.execution_phases else None
    if setup:
        if setup.data_generation:
            phases["data_generation"] = {
                "status": setup.data_generation.status,
                "duration_ms": setup.data_generation.duration_ms,
            }
        if setup.schema_creation:
            phases["schema_creation"] = {
                "status": setup.schema_creation.status,
                "duration_ms": setup.schema_creation.duration_ms,
            }
        if setup.data_loading:
            phases["data_loading"] = {
                "status": setup.data_loading.status,
                "duration_ms": setup.data_loading.duration_ms,
            }
        if setup.validation:
            phases["validation"] = {
                "status": setup.validation.row_count_validation,
                "duration_ms": setup.validation.duration_ms,
            }

    if result.execution_phases and result.execution_phases.power_test:
        power_test = result.execution_phases.power_test
        # FAILED when only the error sentinel ran (no real queries were generated/executed).
        # COMPLETED when at least one real query execution was attempted (even if it failed).
        real_executions = [qe for qe in power_test.query_executions if qe.query_id != "power_test_error"]
        power_test_status = "COMPLETED" if real_executions else "FAILED"
        phases["power_test"] = {
            "status": power_test_status,
            "duration_ms": power_test.duration_ms,
        }
    if result.execution_phases and result.execution_phases.throughput_test:
        phases["throughput_test"] = {
            "status": "COMPLETED",
            "duration_ms": result.execution_phases.throughput_test.duration_ms,
        }

    # pg_mooncake heap-to-columnstore migration phase (omit when not run).
    # per_table_stats intentionally excluded - summary-level only per schema v2 design.
    if result.execution_phases and result.execution_phases.migration:
        m = result.execution_phases.migration
        phases["migration"] = {
            "status": m.status,
            "duration_ms": m.duration_ms,
            "tables_migrated": m.tables_migrated,
            "tables_failed": m.tables_failed,
            "storage_before_bytes": m.storage_before_bytes,
            "storage_after_bytes": m.storage_after_bytes,
            "storage_delta_bytes": m.storage_delta_bytes,
        }

    if isinstance(result.execution_metadata, Mapping):
        phase_status = result.execution_metadata.get("phase_status") or {}
        for name, status in phase_status.items():
            if name not in phases:
                phases[name] = status

    for phase in standard:
        if phase not in phases:
            phases[phase] = {"status": "NOT_RUN"}

    return phases


def compute_plan_capture_stats(
    query_results: list[dict[str, Any]],
    capture_plans: bool,
    *,
    existing_errors: list[dict[str, Any]] | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    """Compute plan capture statistics from a list of query result dicts.

    Produces iteration-stable counts keyed on unique query IDs so the metrics
    do not inflate with warmup/measurement iteration count.  Both the SQL adapter
    and the DataFrame mixin call this function so their result fields are always
    computed with the same logic.

    Args:
        query_results: Query result dicts containing ``query_id``, ``status``,
            optional ``run_type``, and optionally ``query_plan``.
        capture_plans: Whether plan capture was requested for this run.
        existing_errors: When provided (SQL path), filter these rich error dicts
            to only include entries whose ``query_id`` maps to a failed capture.
            When None (DataFrame path), generate minimal error dicts.

    Returns:
        Tuple of ``(plans_captured, capture_failures, capture_errors)`` where:

        - *plans_captured*: unique query IDs with a plan in **any** execution.
        - *capture_failures*: unique query IDs that succeeded in the measurement
          phase but had no plan captured across any execution.  Always 0 when
          ``capture_plans`` is False.
        - *capture_errors*: per-query-id failure detail dicts.
    """
    ids_with_plan: set[str] = {
        str(qr.get("query_id", "")) for qr in query_results if isinstance(qr, dict) and qr.get("query_plan") is not None
    }
    plans_captured = len(ids_with_plan)

    if not capture_plans:
        return plans_captured, 0, []

    measurement_success_ids: set[str] = {
        str(qr.get("query_id", ""))
        for qr in query_results
        if isinstance(qr, dict)
        and str(qr.get("status", "")).upper() == "SUCCESS"
        and str(qr.get("run_type", "")) == "measurement"
    }
    # For power-style runs, prefer measurement-only semantics. For standard
    # runs where run_type is absent, fall back to all successes.
    successful_ids: set[str]
    if measurement_success_ids:
        successful_ids = measurement_success_ids
    else:
        successful_ids = {
            str(qr.get("query_id", ""))
            for qr in query_results
            if isinstance(qr, dict) and str(qr.get("status", "")).upper() == "SUCCESS"
        }

    failed_ids = successful_ids - ids_with_plan

    if existing_errors is not None:
        failed_ids_str = {str(i) for i in failed_ids}
        capture_errors: list[dict[str, Any]] = [
            e for e in existing_errors if str(e.get("query_id", "")) in failed_ids_str
        ]
    else:
        capture_errors = [{"query_id": qid, "error": "Query plan not captured"} for qid in sorted(failed_ids)]

    return plans_captured, len(failed_ids), capture_errors


def build_plans_payload(result: BenchmarkResults) -> dict[str, Any] | None:
    """Build companion plans file payload.

    Returns None if no plans were captured.

    Args:
        result: A BenchmarkResults instance.

    Returns:
        Dictionary for plans companion file, or None if no plans.
    """
    if not result.query_plans_captured or result.query_plans_captured == 0:
        return None

    plans_by_query: dict[str, Any] = {}
    errors_list: list[dict[str, Any]] = []

    for qr in result.query_results or []:
        query_id = str(qr.get("query_id", qr.get("id", "")))
        query_plan = qr.get("query_plan")
        plan_fingerprint = qr.get("plan_fingerprint")
        capture_time = qr.get("plan_capture_time_ms")

        if query_plan is not None:
            plan_entry: dict[str, Any] = {}
            if plan_fingerprint:
                plan_entry["fingerprint"] = plan_fingerprint
            if capture_time:
                plan_entry["capture_time_ms"] = round(capture_time, 1)

            # Serialize the plan
            if is_dataclass(query_plan):
                plan_entry["plan"] = asdict(query_plan)
            elif isinstance(query_plan, dict):
                plan_entry["plan"] = query_plan
            elif hasattr(query_plan, "to_dict"):
                plan_entry["plan"] = query_plan.to_dict()
            else:
                plan_entry["plan"] = str(query_plan)

            plans_by_query[query_id] = plan_entry

    # Add plan capture errors
    for error in result.plan_capture_errors or []:
        errors_list.append(
            {
                "query_id": error.get("query_id", "unknown"),
                "error": error.get("error", "Unknown error"),
            }
        )

    if not plans_by_query and not errors_list:
        return None

    return {
        "version": SCHEMA_VERSION,
        "run_id": result.execution_id,
        "plans_captured": len(plans_by_query),
        "capture_failures": result.plan_capture_failures or 0,
        "queries": plans_by_query,
        "errors": errors_list if errors_list else None,
    }


def build_tuning_payload(result: BenchmarkResults) -> dict[str, Any] | None:
    """Build companion tuning file payload.

    Returns None if no tuning was applied.

    Args:
        result: A BenchmarkResults instance.

    Returns:
        Dictionary for tuning companion file, or None if no tuning.
    """
    if not result.tunings_applied:
        return None

    tuning_applied = result.tunings_applied or {}
    if not tuning_applied:
        return None

    payload: dict[str, Any] = {
        "version": SCHEMA_VERSION,
        "run_id": result.execution_id,
    }

    # Source information
    if result.tuning_source_file:
        payload["source_file"] = result.tuning_source_file
    payload["source"] = "yaml" if result.tuning_source_file else "auto"

    # Hash for comparison
    if result.tuning_config_hash:
        payload["hash"] = result.tuning_config_hash

    # Validation status
    if result.tuning_validation_status:
        payload["validation_status"] = result.tuning_validation_status.lower()

    # Clauses breakdown
    clauses: dict[str, Any] = {}
    if "indexes" in tuning_applied:
        clauses["indexes"] = tuning_applied["indexes"]
    if "statistics" in tuning_applied:
        clauses["statistics"] = tuning_applied["statistics"]
    if "configuration" in tuning_applied:
        clauses["configuration"] = tuning_applied["configuration"]

    if clauses:
        payload["clauses"] = clauses

    return payload


def _compute_timing_stats(times_ms: list[float]) -> dict[str, Any]:
    """Compute timing statistics from a list of query times in milliseconds."""
    if not times_ms:
        return {
            "total_ms": 0,
            "avg_ms": 0,
            "min_ms": 0,
            "max_ms": 0,
        }

    total_ms = sum(times_ms)
    avg_ms = total_ms / len(times_ms)
    min_ms = min(times_ms)
    max_ms = max(times_ms)

    stats: dict[str, Any] = {
        "total_ms": _round_duration_ms_for_export(total_ms),
        "avg_ms": _round_duration_ms_for_export(avg_ms),
        "min_ms": _round_duration_ms_for_export(min_ms),
        "max_ms": _round_duration_ms_for_export(max_ms),
    }

    # Compute geometric mean
    if all(t > 0 for t in times_ms):
        try:
            geo_mean = statistics.geometric_mean(times_ms)
            stats["geometric_mean_ms"] = _round_duration_ms_for_export(geo_mean)
        except (statistics.StatisticsError, ValueError):
            pass

    # Compute percentiles and stdev if we have enough samples
    if len(times_ms) >= 3:
        try:
            stdev = statistics.stdev(times_ms)
            stats["stdev_ms"] = _round_duration_ms_for_export(stdev)
        except statistics.StatisticsError:
            pass

    if len(times_ms) >= 10:
        sorted_times = sorted(times_ms)
        n = len(sorted_times)

        # p90
        p90_idx = int(n * 0.90)
        stats["p90_ms"] = _round_duration_ms_for_export(sorted_times[min(p90_idx, n - 1)])

        # p95
        p95_idx = int(n * 0.95)
        stats["p95_ms"] = _round_duration_ms_for_export(sorted_times[min(p95_idx, n - 1)])

        # p99
        p99_idx = int(n * 0.99)
        stats["p99_ms"] = _round_duration_ms_for_export(sorted_times[min(p99_idx, n - 1)])

    return stats


def _build_tpc_metrics(result: BenchmarkResults) -> dict[str, Any] | None:
    """Build TPC metrics block if available."""
    # Official TPC composite metrics are suppressed for unofficial compliance classes
    compliance_class = getattr(result, "compliance_class", None)
    _unofficial_classes = {"unofficial_nonstandard", "unofficial_subscale"}
    if compliance_class in _unofficial_classes:
        return {"suppressed": True, "reason": f"compliance_class={compliance_class}"}

    metrics: dict[str, Any] = {}

    if result.power_at_size is not None:
        metrics["power_at_size"] = result.power_at_size
    if result.throughput_at_size is not None:
        metrics["throughput_at_size"] = result.throughput_at_size
    if result.qph_at_size is not None:
        # Output with benchmark-specific key name based on benchmark_name
        benchmark_id = normalize_benchmark_id(result.benchmark_name or "")
        if benchmark_id == "tpcds":
            metrics["qphds_at_size"] = result.qph_at_size
        else:
            metrics["qphh_at_size"] = result.qph_at_size
    # Note: geometric_mean_ms is in summary.timing (computed from query times),
    # not here. TPC metrics block contains only TPC-specific metrics.

    return metrics if metrics else None


def _build_tuning_summary(result: BenchmarkResults) -> dict[str, Any] | None:
    """Build tuning summary for platform block."""
    if not result.tunings_applied:
        return None

    summary: dict[str, Any] = {}

    # Determine source
    if result.tuning_source_file:
        summary["source"] = "yaml"
    else:
        summary["source"] = "auto"

    # Add hash for comparison
    if result.tuning_config_hash:
        summary["hash"] = result.tuning_config_hash

    # Count clauses applied
    clauses_count = 0
    tuning = result.tunings_applied or {}
    for key in ("indexes", "statistics", "configuration"):
        if key in tuning:
            val = tuning[key]
            if isinstance(val, (list, dict)):
                clauses_count += len(val)

    if clauses_count > 0:
        summary["clauses_applied"] = clauses_count

    return summary if summary else None


def _build_environment_block(result: BenchmarkResults) -> dict[str, Any]:
    """Build environment block with legacy flat keys plus normalized metadata."""
    return build_environment_payload(
        system_profile=getattr(result, "system_profile", None),
        execution_environment=getattr(result, "execution_environment", None),
    )


def _build_tables_block(table_statistics: dict[str, Any] | None) -> dict[str, Any]:
    """Build compact tables block."""
    if not table_statistics:
        return {}

    tables: dict[str, Any] = {}
    for table_name in sorted(table_statistics.keys()):
        stats = table_statistics[table_name]
        if isinstance(stats, dict):
            entry: dict[str, Any] = {}
            if "rows" in stats:
                entry["rows"] = stats["rows"]
            elif "rows_loaded" in stats:
                entry["rows"] = stats["rows_loaded"]
            if "load_time_ms" in stats and stats["load_time_ms"] is not None:
                entry["load_ms"] = round(stats["load_time_ms"], 1)
            elif "load_ms" in stats and stats["load_ms"] is not None:
                entry["load_ms"] = round(stats["load_ms"], 1)
            if entry:
                tables[table_name] = entry
        elif isinstance(stats, int):
            # Simple row count
            tables[table_name] = {"rows": stats}

    return tables


def _extract_table_errors(execution_phases: Any) -> list[dict[str, Any]]:
    """Extract table loading errors from execution phases."""
    errors: list[dict[str, Any]] = []

    if execution_phases is None:
        return errors

    # Handle dataclass or dict
    if is_dataclass(execution_phases):
        phases = asdict(execution_phases)
    elif isinstance(execution_phases, dict):
        phases = execution_phases
    else:
        return errors

    setup = phases.get("setup", {})
    if not setup:
        return errors

    data_loading = setup.get("data_loading", {})
    if not data_loading:
        return errors

    per_table = data_loading.get("per_table_stats", {})
    for table_name, stats in (per_table or {}).items():
        if isinstance(stats, dict):
            error_type = stats.get("error_type")
            error_msg = stats.get("error_message")
            if error_type or error_msg:
                errors.append(
                    {
                        "phase": "data_loading",
                        "table": table_name,
                        "type": error_type or "LoadError",
                        "message": error_msg or "Table loading failed",
                    }
                )

    return errors


def _extract_platform_config(platform_info: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant platform configuration, excluding version and variant."""
    if not platform_info:
        return {}

    exclude_keys = {
        "version",
        "variant",
        "name",
        "platform",
        "adapter_name",
        "adapter_version",
        "platform_version",
        "client_library_version",
        "client_version",
        "platform_name",
        "platform_type",
    }
    config: dict[str, Any] = {}

    def extract_recursive(d: dict[str, Any]) -> None:
        """Recursively extract config, flattening nested 'configuration' keys."""
        for key, value in d.items():
            if key.lower() in exclude_keys or value is None:
                continue
            # Skip empty values
            if isinstance(value, str) and not value:
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            # Flatten nested configuration
            if key == "configuration" and isinstance(value, dict):
                extract_recursive(value)
            else:
                config[key] = value

    extract_recursive(platform_info)
    return config
