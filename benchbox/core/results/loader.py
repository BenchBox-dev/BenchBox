"""Result file loading and discovery utilities for schema v2.0.

This module provides functionality to load and reconstruct BenchmarkResults
from exported JSON files, enabling result re-export and analysis without
re-running benchmarks.

IMPORTANT: Only schema v2.0 files are supported. Legacy v1.x files are rejected.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from benchbox.core.results.models import (
    BenchmarkResults,
    ExecutionPhases,
    MigrationPhase,
    NativeComparison,
    NativeComparisonEntry,
    SetupPhase,
)
from benchbox.core.results.query_normalizer import normalize_query_id
from benchbox.core.results.query_plan_models import QueryPlanDAG
from benchbox.core.results.schema_policy import LOADER_SCHEMA_POLICY, is_loader_supported_result_schema

logger = logging.getLogger(__name__)


class ResultLoadError(Exception):
    """Raised when a result file cannot be loaded or parsed."""


class UnsupportedSchemaError(ResultLoadError):
    """Raised when the result file has an unsupported schema version."""


def find_latest_result(
    directory: Path | str,
    benchmark: str | None = None,
    platform: str | None = None,
) -> Path | None:
    """Find the most recent result file in a directory.

    Args:
        directory: Directory to search for result files.
        benchmark: Optional benchmark name filter (e.g., "tpch", "tpcds").
        platform: Optional platform name filter (e.g., "duckdb", "databricks").

    Returns:
        Path to most recent result file, or None if no results found.

    Note:
        Only v2.0 schema files are considered. Companion files (.plans.json,
        .tuning.json) are excluded from the search.
    """
    directory_path = Path(directory) if isinstance(directory, str) else directory

    if not directory_path.exists() or not directory_path.is_dir():
        return None

    # Find all JSON files, excluding companion files
    result_files = [
        f
        for f in directory_path.glob("*.json")
        if not f.name.endswith(".plans.json") and not f.name.endswith(".tuning.json")
    ]

    if not result_files:
        return None

    candidates: list[tuple[Path, datetime]] = []
    for filepath in result_files:
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            # Only consider files accepted by the runtime loader policy.
            if not is_loader_supported_result_schema(data):
                continue

            # Extract metadata for filtering (v2.0 format)
            file_benchmark = data.get("benchmark", {}).get("id", "")
            file_platform = data.get("platform", {}).get("name", "")
            file_timestamp = data.get("run", {}).get("timestamp", "")

            # Apply filters
            if benchmark and benchmark.lower() not in file_benchmark.lower():
                continue
            if platform and platform.lower() not in file_platform.lower():
                continue

            # Parse timestamp for sorting
            try:
                timestamp_dt = datetime.fromisoformat(file_timestamp)
            except (ValueError, TypeError):
                timestamp_dt = datetime.fromtimestamp(filepath.stat().st_mtime)

            candidates.append((filepath, timestamp_dt))

        except (json.JSONDecodeError, OSError):
            continue

    if not candidates:
        return None

    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]


def load_result_file(filepath: Path | str) -> tuple[BenchmarkResults, dict[str, Any]]:
    """Load a result JSON file and reconstruct BenchmarkResults.

    Args:
        filepath: Path to result JSON file.

    Returns:
        Tuple of (BenchmarkResults object, raw JSON dict).

    Raises:
        ResultLoadError: If file cannot be loaded or parsed.
        UnsupportedSchemaError: If schema version is not v2.0.
        FileNotFoundError: If file does not exist.

    Note:
        Only schema v2.0 files are supported. Legacy v1.x files will raise
        UnsupportedSchemaError.
    """
    filepath_obj = Path(filepath) if isinstance(filepath, str) else filepath

    if not filepath_obj.exists():
        raise FileNotFoundError(f"Result file not found: {filepath}")

    try:
        with open(filepath_obj, encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise ResultLoadError(f"Invalid JSON in result file: {e}") from e
    except OSError as e:
        raise ResultLoadError(f"Failed to read result file: {e}") from e

    # Check schema version through the named runtime loader policy.
    version_decision = LOADER_SCHEMA_POLICY.evaluate(data.get("version"))
    if not version_decision.accepted:
        raise UnsupportedSchemaError(version_decision.error_message())

    # Load companion files if they exist
    plans_data, plans_load_error = _load_companion_file(filepath_obj, ".plans.json")
    tuning_data, _tuning_load_error = _load_companion_file(filepath_obj, ".tuning.json")

    # Reconstruct BenchmarkResults
    try:
        result = reconstruct_benchmark_results(data, plans_data, tuning_data)
    except Exception as e:
        raise ResultLoadError(f"Failed to reconstruct BenchmarkResults: {e}") from e

    # Surface a plans-companion load failure so consumers can distinguish "no
    # plans were captured" from "a .plans.json exists but could not be read"
    # (qpc-05 / F4.3). Attached as an attribute rather than swallowed at DEBUG.
    result.plans_load_error = plans_load_error

    return result, data


def _load_companion_file(main_file: Path, suffix: str) -> tuple[dict[str, Any] | None, str | None]:
    """Load a companion file if it exists.

    Returns ``(data, error)``:
      - ``(dict, None)`` when the companion loaded successfully;
      - ``(None, None)`` when no companion file exists (the common case);
      - ``(None, "<reason>")`` when the companion EXISTS but could not be read
        or parsed.

    The exists-but-unreadable case is a user-actionable problem (a corrupt or
    unreadable ``.plans.json``), so it is logged at WARNING and returned as an
    error string rather than swallowed at DEBUG and reported downstream as "no
    plans captured" (qpc-05 / F4.3).

    Path arithmetic: an exact basename suffix swap (``name[:-len(".json")] +
    suffix``) rather than ``Path.with_suffix()`` chained twice or a path-wide
    ``str.replace(".json", suffix)`` -- both of those break on a scale-factor
    filename like ``result_sf0.1.json`` -- ``with_suffix("")`` leaves
    ``result_sf0.1``, whose OWN suffix is then read as ``.1`` (stripped by
    the second ``with_suffix()`` call, corrupting the basename to
    ``result_sf0.plans.json``); ``str.replace`` operates on the full path
    string and rewrites the FIRST ``.json`` it finds anywhere, including one
    that happens to appear in a parent directory name.
    """
    name = main_file.name
    companion_name = name[: -len(".json")] + suffix if name.endswith(".json") else name + suffix
    companion_path = main_file.with_name(companion_name)

    if not companion_path.exists():
        return None, None

    try:
        with open(companion_path, encoding="utf-8") as f:
            return json.load(f), None
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Companion file %s exists but could not be loaded: %s", companion_path, e)
        return None, f"{companion_path.name}: {e}"


def reconstruct_benchmark_results(
    data: dict[str, Any],
    plans_data: dict[str, Any] | None = None,
    tuning_data: dict[str, Any] | None = None,
) -> BenchmarkResults:
    """Reconstruct a BenchmarkResults object from v2.0 JSON schema.

    This function reverses the transformation performed by build_result_payload()
    in the schema module, mapping JSON keys back to BenchmarkResults dataclass
    attributes.

    Args:
        data: Result data in v2.0 JSON format.
        plans_data: Optional plans companion file data.
        tuning_data: Optional tuning companion file data.

    Returns:
        Fully reconstructed BenchmarkResults object.

    Raises:
        KeyError: If required fields are missing.
        ValueError: If data cannot be parsed correctly.
    """
    run_section = data.get("run", {})
    benchmark_section = data.get("benchmark", {})
    platform_section = data.get("platform", {})
    summary_section = data.get("summary", {})
    execution_section = data.get("execution", {})

    timestamp = _parse_timestamp(run_section.get("timestamp", ""))
    query_results = _reconstruct_query_results(data.get("queries", []), data.get("errors", []), plans_data)

    timing = _extract_timing_metrics(summary_section)
    tpc = _extract_tpc_metrics(summary_section)
    platform_info = _extract_platform_info(platform_section)
    tuning = _extract_tuning_info(platform_section, tuning_data)
    environment_section = data.get("environment", {})
    system_profile = _extract_system_profile(environment_section)
    execution_environment = _extract_execution_environment(environment_section)
    cost_summary = _extract_cost_summary(data.get("cost", {}), data.get("normalized_cost"))
    plans_captured, plan_failures = _extract_plans_info(plans_data)

    queries_counts = summary_section.get("queries", {})
    tables_section = data.get("tables", {})
    table_statistics = {
        name: {"rows": stats.get("rows"), "load_time_ms": stats.get("load_ms")}
        for name, stats in tables_section.items()
    }

    execution_phases = _reconstruct_execution_phases(data.get("phases", {}))
    native_comparison = _reconstruct_native_comparison(data.get("comparisons", {}))

    return BenchmarkResults(
        benchmark_name=benchmark_section.get("name", "Unknown"),
        platform=platform_section.get("name", "Unknown"),
        scale_factor=benchmark_section.get("scale_factor", 1.0),
        execution_id=run_section.get("id", ""),
        timestamp=timestamp,
        duration_seconds=run_section.get("total_duration_ms", 0) / 1000.0,
        total_queries=queries_counts.get("total", 0),
        successful_queries=queries_counts.get("passed", 0),
        failed_queries=queries_counts.get("failed", 0),
        query_results=query_results,
        total_execution_time=timing["total_execution_time"],
        average_query_time=timing["average_query_time"],
        data_loading_time=timing["data_loading_time"],
        total_rows_loaded=timing["total_rows_loaded"],
        table_statistics=table_statistics,
        power_at_size=tpc["power_at_size"],
        throughput_at_size=tpc["throughput_at_size"],
        qph_at_size=tpc["qph_at_size"],
        geometric_mean_execution_time=tpc["geometric_mean_execution_time"],
        test_execution_type=benchmark_section.get("mode", "standard"),
        validation_status=summary_section.get("validation", "NOT_RUN"),
        execution_metadata=_extract_execution_metadata(execution_section),
        execution_environment=execution_environment,
        platform_deployment=platform_section.get("deployment"),
        platform_cloud=platform_section.get("cloud"),
        platform_compute=platform_section.get("compute"),
        platform_storage=platform_section.get("storage"),
        platform_raw_config=platform_section.get("raw_config"),
        platform_raw_metadata=platform_section.get("raw_metadata"),
        system_profile=system_profile,
        query_subset=run_section.get("query_subset"),
        platform_info=platform_info,
        tunings_applied=tuning["tunings_applied"],
        tuning_source_file=tuning["tuning_source_file"],
        tuning_config_hash=tuning["tuning_config_hash"],
        tuning_validation_status=tuning["tuning_validation_status"],
        query_plans_captured=plans_captured,
        plan_capture_failures=plan_failures,
        cost_summary=cost_summary,
        execution_phases=execution_phases,
        native_comparison=native_comparison,
        _benchmark_id_override=benchmark_section.get("id"),
        compliance_class=benchmark_section.get("compliance_class"),
        dataset_version=benchmark_section.get("dataset_version"),
        manifest_hash=benchmark_section.get("manifest_hash"),
        data_archive_hash=benchmark_section.get("data_archive_hash"),
    )


def _extract_execution_metadata(execution_section: dict[str, Any]) -> dict[str, Any] | None:
    """Preserve execution metadata that is not otherwise reconstructed."""
    metadata: dict[str, Any] = {}
    translation = execution_section.get("translation")
    if isinstance(translation, dict):
        metadata["translation"] = translation
    return metadata or None


def _parse_timestamp(timestamp_str: str) -> datetime:
    """Parse an ISO-format timestamp string, falling back to now()."""
    try:
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, TypeError):
        return datetime.now()


def _extract_timing_metrics(summary_section: dict[str, Any]) -> dict[str, Any]:
    """Extract timing and data loading metrics from the summary section."""
    timing = summary_section.get("timing", {})
    data_section = summary_section.get("data", {})
    return {
        "total_execution_time": timing.get("total_ms", 0.0) / 1000.0,
        "average_query_time": timing.get("avg_ms", 0.0) / 1000.0,
        "data_loading_time": data_section.get("load_time_ms", 0.0) / 1000.0,
        "total_rows_loaded": data_section.get("rows_loaded", 0),
    }


def _extract_tpc_metrics(summary_section: dict[str, Any]) -> dict[str, Any]:
    """Extract TPC benchmark metrics from the summary section."""
    tpc = summary_section.get("tpc_metrics", {})
    timing = summary_section.get("timing", {})
    geometric_mean_ms = timing.get("geometric_mean_ms")
    return {
        "power_at_size": tpc.get("power_at_size"),
        "throughput_at_size": tpc.get("throughput_at_size"),
        "qph_at_size": tpc.get("qphh_at_size") or tpc.get("qphds_at_size"),
        "geometric_mean_execution_time": geometric_mean_ms / 1000.0 if geometric_mean_ms else None,
    }


def _extract_platform_info(platform_section: dict[str, Any]) -> dict[str, Any]:
    """Extract and reconstruct platform info dictionary."""
    info: dict[str, Any] = {
        "name": platform_section.get("name"),
        "version": platform_section.get("version"),
        "variant": platform_section.get("variant"),
    }
    if platform_section.get("config"):
        info.update(platform_section["config"])
    return info


def _extract_tuning_info(platform_section: dict[str, Any], tuning_data: dict[str, Any] | None) -> dict[str, Any]:
    """Extract tuning configuration from platform section and companion data."""
    tunings_applied = None
    tuning_source_file = None
    tuning_config_hash = None
    tuning_validation_status = None

    tuning_summary = platform_section.get("tuning", {})
    if tuning_summary:
        tuning_source_file = "yaml" if tuning_summary.get("source") == "yaml" else None
        tuning_config_hash = tuning_summary.get("hash")

    if tuning_data:
        tunings_applied = tuning_data.get("clauses", {})
        tuning_source_file = tuning_data.get("source_file")
        tuning_config_hash = tuning_data.get("hash")
        tuning_validation_status = tuning_data.get("validation_status")

    return {
        "tunings_applied": tunings_applied,
        "tuning_source_file": tuning_source_file,
        "tuning_config_hash": tuning_config_hash,
        "tuning_validation_status": tuning_validation_status,
    }


def _extract_system_profile(environment_section: dict[str, Any]) -> dict[str, Any]:
    """Reconstruct system profile from environment section."""
    profile: dict[str, Any] = {}
    if not environment_section:
        return profile

    source = dict(environment_section)
    client_host = environment_section.get("client_host")
    if isinstance(client_host, dict):
        source.update({key: value for key, value in client_host.items() if value is not None})

    _env_field_map = {
        "arch": "architecture",
        "cpu_count": "cpu_count",
        "memory_gb": "memory_gb",
        "python": "python_version",
        "machine_id": "machine_id",
    }

    if source.get("os"):
        os_parts = source["os"].split(" ", 1)
        profile["os_type"] = os_parts[0]
        profile["os_release"] = os_parts[1] if len(os_parts) > 1 else ""

    for env_key, profile_key in _env_field_map.items():
        if source.get(env_key):
            profile[profile_key] = source[env_key]

    return profile


def _extract_execution_environment(environment_section: dict[str, Any]) -> dict[str, Any] | None:
    """Extract normalized execution-environment metadata from the environment section."""
    if not isinstance(environment_section, dict):
        return None

    normalized = {
        key: environment_section[key]
        for key in ("client_host", "platform_runtime", "container")
        if isinstance(environment_section.get(key), dict)
    }
    return normalized or None


def _extract_cost_summary(
    cost_section: dict[str, Any],
    normalized_cost_section: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Extract cost summary from cost section.

    Preserves the ``normalized_cost`` block when present so a re-export round-
    trips ``cost.total_usd`` correctly for bundles that have one. Legacy
    bundles without a normalized_cost block still round-trip their direct
    total via the schema-side missing-vs-rejected distinction.
    """
    if not cost_section:
        return None
    summary: dict[str, Any] = {
        "total_cost": cost_section.get("total_usd"),
        "cost_model": cost_section.get("model", "estimated"),
    }
    if isinstance(normalized_cost_section, dict):
        summary["normalized_cost"] = normalized_cost_section
    return summary


def _extract_plans_info(plans_data: dict[str, Any] | None) -> tuple[int, int]:
    """Extract query plan capture counts from companion data."""
    if not plans_data:
        return 0, 0
    return plans_data.get("plans_captured", 0), plans_data.get("capture_failures", 0)


def _reconstruct_query_results(
    queries_list: list[dict[str, Any]],
    errors_list: list[dict[str, Any]],
    plans_data: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct query results from compact v2.0 format.

    Converts from compact format:
        {"id": "Q1", "ms": 632.9, "rows": 100}

    To internal format:
        {"query_id": "Q1", "execution_time_ms": 632.9, "rows_returned": 100, "status": "SUCCESS"}

    When ``plans_data`` (the loaded ``.plans.json`` companion) carries an entry for a
    query ID, rehydrate ``query_plan`` as a real ``QueryPlanDAG`` plus its fingerprint
    fields, so plans survive a load -> show-plan/compare-plans round-trip.

    ``build_plans_payload`` keys its ``queries`` map by the raw, pre-normalization
    query ID (e.g. ``"q1"``), while the compact ``queries`` list here carries the
    already-normalized ID (e.g. ``"1"``) written by ``_build_query_results_section``.
    Normalize both sides for the lookup so the two companion files agree without
    changing the on-disk ``.plans.json`` format. A query ID that ran in more than
    one stream is written under ``"{query_id}#{stream_id}"`` composite keys (see
    ``build_plans_payload``); ``_index_plan_entries``/``_lookup_plan_entry`` below
    resolve those back to the exact stream's entry. A combined run (e.g. power
    then throughput) can have a power row and a throughput row share the same
    query_id AND stream_id (each phase's stream counter starts at its own 0);
    those are disambiguated with a further ``"{query_id}#{stream_id}:{test_type}"``
    key, resolved via the row's own compact ``test_type`` field.

    Current-format bundles write ``status``/``run_type`` on every compact entry
    (including failures, which are ALSO duplicated into ``errors[]`` for the
    legacy fallback below) and use ``iter``/``stream`` 0 for warmup rows / the
    first stream. Legacy bundles predate those per-entry fields entirely: their
    ``queries[]`` entries carry only successful queries (no ``status`` key at
    all) and failures live solely in ``errors[]``. Both shapes must round-trip:
    an entry's own ``status`` (when present) is authoritative; ``errors[]`` is
    only used to (a) attach ``error_type``/``error_message`` detail onto a
    compact entry that already reports non-SUCCESS, and (b) synthesize a
    standalone FAILED row for a query_id that never appears in ``queries[]``
    at all (the legacy shape).
    """
    plan_entries = _index_plan_entries(plans_data)
    results: list[dict[str, Any]] = []

    query_error_by_id: dict[str, dict[str, Any]] = {}
    for error in errors_list:
        if error.get("phase") != "query":
            continue
        qid = error.get("query_id")
        if qid is None:
            continue
        query_error_by_id.setdefault(normalize_query_id(qid), error)

    ids_in_queries_list: set[str] = {normalize_query_id(q["id"]) for q in queries_list if q.get("id") is not None}

    for q in queries_list:
        query_id = q.get("id")
        status = q.get("status", "SUCCESS")
        result: dict[str, Any] = {
            "query_id": query_id,
            "execution_time_ms": q.get("ms"),
            "rows_returned": q.get("rows"),
            "status": status,
        }
        if q.get("iter") is not None:
            result["iteration"] = q["iter"]
        if q.get("stream") is not None:
            result["stream_id"] = q["stream"]
        if q.get("run_type") is not None:
            result["run_type"] = q["run_type"]
        if q.get("test_type"):
            result["test_type"] = q["test_type"]

        if status not in ("SUCCESS", "SKIPPED") and query_id is not None:
            error = query_error_by_id.get(normalize_query_id(query_id))
            if error is not None:
                result["error_type"] = error.get("type")
                result["error_message"] = error.get("message")

        _attach_plan(
            result,
            _lookup_plan_entry(plan_entries, query_id, q.get("stream", 0), q.get("test_type")),
        )
        results.append(result)

    # Legacy fallback: synthesize a FAILED row only for query_ids that never
    # appear in queries[] at all. Current-format bundles duplicate every
    # failure into queries[] too (handled above); re-adding it here would
    # produce a phantom second row for the same failure.
    for error in errors_list:
        if error.get("phase") != "query":
            continue
        qid = error.get("query_id")
        if qid is not None and normalize_query_id(qid) in ids_in_queries_list:
            continue
        results.append(
            {
                "query_id": qid,
                "status": "FAILED",
                "error_type": error.get("type"),
                "error_message": error.get("message"),
            }
        )

    return results


def _attach_plan(result: dict[str, Any], plan_entry: dict[str, Any] | None) -> None:
    """Rehydrate a ``.plans.json`` entry onto a reconstructed query result dict."""
    if not plan_entry:
        return

    plan_dict = plan_entry.get("plan")
    if plan_dict is not None:
        result["query_plan"] = QueryPlanDAG.from_dict(plan_dict)
    if plan_entry.get("fingerprint"):
        result["plan_fingerprint"] = plan_entry["fingerprint"]
    if plan_entry.get("fingerprint_normalized"):
        result["plan_fingerprint_normalized"] = plan_entry["fingerprint_normalized"]
    if plan_entry.get("capture_time_ms") is not None:
        result["plan_capture_time_ms"] = plan_entry["capture_time_ms"]


def _index_plan_entries(plans_data: dict[str, Any] | None) -> dict[str, Any]:
    """Index a ``.plans.json`` ``queries`` map for lookup by normalized query ID.

    A query ID that ran in more than one stream is written under
    ``"{query_id}#{stream_id}"`` composite keys (see ``build_plans_payload``); this
    splits those apart so the reader doesn't need to know the writer's key format.
    Each normalized query ID maps to either a single entry dict (the common
    bare-key, single-stream case) or a ``{stream_id_str: entry}`` dict (the
    multi-stream case) - distinguished in ``_lookup_plan_entry`` by the presence
    of a ``"plan"`` key, which a stream-keyed bucket never has.
    """
    raw_entries: dict[str, Any] = (plans_data or {}).get("queries") or {}
    indexed: dict[str, Any] = {}
    for key, entry in raw_entries.items():
        if "#" in key:
            base_id, _, stream_id = key.rpartition("#")
            bucket = indexed.setdefault(normalize_query_id(base_id), {})
            bucket[stream_id] = entry
        else:
            indexed[normalize_query_id(key)] = entry
    return indexed


def _lookup_plan_entry(
    plan_entries: dict[str, Any], query_id: Any, stream_id: Any, test_type: Any = None
) -> dict[str, Any] | None:
    """Resolve the plan entry for ``query_id``, disambiguating by ``stream_id`` (and,
    for a cross-phase collision, ``test_type``) when needed."""
    if query_id is None:
        return None
    entry = plan_entries.get(normalize_query_id(query_id))
    if entry is None or "plan" in entry:
        return entry
    if test_type:
        qualified = entry.get(f"{stream_id}:{test_type}")
        if qualified is not None:
            return qualified
    return entry.get(str(stream_id))


def iter_query_results(results: Any) -> list[dict[str, Any]]:
    """Return the flattened per-query result dicts for a ``BenchmarkResults`` instance.

    ``query_results`` is the canonical per-query source: ``ResultBuilder`` populates it
    identically for freshly executed results and ``reconstruct_benchmark_results``
    populates it the same way for bundles reloaded from disk (including rehydrated
    ``query_plan``/``plan_fingerprint`` values from the ``.plans.json`` companion).
    ``execution_phases`` is not a reliable per-query source once reconstructed from a
    bundle - only phase-level summaries survive that round-trip - so consumers that
    need per-query plan/fingerprint data should use this accessor instead of walking
    ``execution_phases``.
    """
    return list(getattr(results, "query_results", None) or [])


def _reconstruct_execution_phases(phases_section: dict[str, Any]) -> ExecutionPhases | None:
    """Reconstruct ExecutionPhases from the phases block.

    Only summary-level fields (status, duration_ms) are available for most phases.
    MigrationPhase is reconstructed with full summary fields; per_table_stats
    cannot be recovered (intentionally excluded from serialization).
    """
    if not phases_section:
        return None

    migration = None
    mig = phases_section.get("migration")
    if mig and mig.get("status") != "NOT_RUN":
        migration = MigrationPhase(
            duration_ms=mig.get("duration_ms", 0),
            status=mig.get("status", "UNKNOWN"),
            tables_migrated=mig.get("tables_migrated", 0),
            tables_failed=mig.get("tables_failed", 0),
            storage_before_bytes=mig.get("storage_before_bytes", 0),
            storage_after_bytes=mig.get("storage_after_bytes", 0),
            storage_delta_bytes=mig.get("storage_delta_bytes", 0),
            per_table_stats={},  # Not serialized; summary-level only
        )

    # Only return ExecutionPhases if we have at least one reconstructable phase.
    # Setup sub-phases (data_generation, schema_creation, etc.) are serialized as
    # flat status/duration_ms pairs - insufficient to reconstruct the full dataclass
    # tree, so we provide a minimal SetupPhase shell for round-trip fidelity.
    if migration is None and not any(
        phases_section.get(p, {}).get("status") not in (None, "NOT_RUN") for p in ("power_test", "throughput_test")
    ):
        return None

    return ExecutionPhases(
        setup=SetupPhase(),  # Placeholder; sub-phase detail not recoverable
        migration=migration,
    )


def _reconstruct_native_comparison(comparisons_section: dict[str, Any]) -> NativeComparison | None:
    """Reconstruct NativeComparison from the comparisons block."""
    if not comparisons_section:
        return None

    nd = comparisons_section.get("native_duckdb")
    if not nd:
        return None

    entries = [
        NativeComparisonEntry(
            query_id=q.get("id", ""),
            pg_duckdb_ms=q.get("pg_duckdb_ms", 0.0),
            duckdb_ms=q.get("duckdb_ms", 0.0),
            delta_ms=q.get("delta_ms", 0.0),
        )
        for q in nd.get("queries", [])
    ]

    return NativeComparison(
        generated_at=nd.get("generated_at", ""),
        scale_factor=nd.get("scale_factor", 0.0),
        total_queries=nd.get("total_queries", 0),
        mean_delta_ms=nd.get("mean_delta_ms", 0.0),
        max_delta_ms=nd.get("max_delta_ms", 0.0),
        entries=entries,
    )


__all__ = [
    "find_latest_result",
    "iter_query_results",
    "load_result_file",
    "reconstruct_benchmark_results",
    "ResultLoadError",
    "UnsupportedSchemaError",
]
