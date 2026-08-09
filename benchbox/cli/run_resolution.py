"""Typed request and resolved-plan contracts for ``benchbox run``.

The Click command still exposes compatibility attributes while the run pipeline
is migrated incrementally.  These frozen models identify which values are user
intent and which values are derived, and give every dispatch path one stable
snapshot to use for configuration and execution metadata.
"""

from __future__ import annotations

import os
import types
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Callable, Mapping

from benchbox.cli.composite_params import CompressionConfig

if TYPE_CHECKING:
    from benchbox.cli.tuning_resolver import TuningResolution
    from benchbox.core.dataframe.tuning.interface import DataFrameTuningConfiguration
    from benchbox.core.tuning.interface import UnifiedTuningConfiguration


@dataclass(frozen=True)
class RunRequest:
    """User intent for a run, before registry and tuning resolution.

    ``exact_replay`` is false when a historical preference omitted information
    needed to reproduce the original run.  Compatibility defaults remain
    explicit in ``compatibility_notes`` rather than being presented as an exact
    replay.
    """

    platform: str | None
    benchmark: str | None
    scale: float
    phases: tuple[str, ...]
    queries: str | None
    tuning: str
    table_mode: str
    output: str | None
    mode: str | None
    seed: int | None
    compression_enabled: bool
    compression_type: str
    compression_level: int | None
    iterations: int | None = None
    concurrency: int = 1
    non_replayable_options: tuple[str, ...] = ()
    exact_replay: bool = True
    compatibility_notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResolvedRunPlan:
    """Immutable snapshot of all execution-significant derived run state.

    Runtime outputs (result status, timings, and artifacts) intentionally do not
    belong here.  Mutable configuration payloads are retained by reference for
    compatibility, but the plan's selection of those payloads cannot be
    reassigned after resolution.
    """

    request: RunRequest
    platform_key: str | None
    benchmark: str | None
    scale: float
    phases: tuple[str, ...]
    queries: tuple[str, ...] | None
    test_execution_type: str
    execution_mode: str
    resolved_mode: str | None
    table_mode: str
    tuning_resolution: TuningResolution
    canonical_tuning_mode: str | None
    tuning_enabled: bool
    tuning_config_file: str | None
    use_auto_tuning: bool
    loaded_unified_config: UnifiedTuningConfiguration | None
    data_organization: Mapping[str, Any] | None
    dataframe_tuning_config: DataFrameTuningConfiguration | None
    compression_enabled: bool
    compression_type: str
    compression_level: int | None
    iterations: int | None
    concurrency: int
    seed: int | None
    non_replayable_options: tuple[str, ...]


_NON_REPLAYABLE_OPTION_NAMES = frozenset(
    {
        "analyze_plans",
        "benchmark_options",
        "capture_plans",
        "force",
        "global_cache",
        "ignore_memory_warnings",
        "no_monitoring",
        "normalize_plan_literals",
        "official",
        "plan_config",
        "platform_options",
        "presort",
        "show_plans",
        "sorted_ingestion_method",
        "sorted_ingestion_mode",
        "stats_per_table_timing",
        "stats_reset",
        "strict_translation",
        "table_format",
        "validation",
    }
)


def _active_non_replayable_options(state: types.SimpleNamespace) -> tuple[str, ...]:
    """Identify active execution controls that quick restart does not serialize.

    Platform option values are deliberately excluded because option payloads may
    contain credentials. Force regeneration is likewise never replayed
    implicitly. The remaining controls require a future typed persistence
    contract before they can safely be advertised as exact replay inputs.
    """
    checks = {
        "analyze_plans": getattr(state, "analyze_plans", None) is not None,
        "benchmark_options": bool(getattr(state, "benchmark_option_pairs", ())),
        "capture_plans": bool(getattr(state, "capture_plans", False)),
        "force": bool(getattr(getattr(state, "force_config", None) or getattr(state, "force", None), "any", False)),
        "global_cache": bool(getattr(state, "global_cache", False)),
        "ignore_memory_warnings": bool(getattr(state, "ignore_memory_warnings", False)),
        "no_monitoring": bool(getattr(state, "no_monitoring", False)),
        "normalize_plan_literals": bool(getattr(state, "normalize_plan_literals", False)),
        "official": bool(getattr(state, "official", False)),
        "plan_config": bool(getattr(state, "plan_config", None)),
        "platform_options": bool(getattr(state, "platform_option_pairs", ())),
        "presort": getattr(state, "presort", None) is not None,
        "show_plans": bool(getattr(state, "show_plans", False)),
        "sorted_ingestion_method": getattr(state, "sorted_ingestion_method", None) is not None,
        "sorted_ingestion_mode": getattr(state, "sorted_ingestion_mode", None) is not None,
        "stats_per_table_timing": bool(getattr(state, "stats_per_table_timing", False)),
        "stats_reset": getattr(state, "stats_reset", None) is not None,
        "strict_translation": bool(getattr(state, "strict_translation", False)),
        "table_format": getattr(state, "table_format", None) is not None,
        "validation": getattr(state, "validation", None) is not None,
    }
    return tuple(name for name, active in checks.items() if active)


def _saved_non_replayable_options(saved: Mapping[str, Any]) -> tuple[str, ...]:
    raw = saved.get("non_replayable_options", ())
    if not isinstance(raw, (list, tuple)) or any(not isinstance(name, str) for name in raw):
        raise ValueError("Saved quick-restart non_replayable_options must be a list of names")
    unknown = set(raw) - _NON_REPLAYABLE_OPTION_NAMES
    if unknown:
        raise ValueError(f"Saved quick-restart contains unknown non-replayable options: {sorted(unknown)}")
    return tuple(sorted(set(raw)))


def current_run_request(state: types.SimpleNamespace) -> RunRequest:
    """Capture user intent without including fields derived by the resolver."""
    phases = state.phases if isinstance(state.phases, (list, tuple)) else str(state.phases).split(",")
    compression = getattr(state, "comp_config", None) or state.compression or CompressionConfig()
    return RunRequest(
        platform=state.platform,
        benchmark=state.benchmark,
        scale=float(state.scale),
        phases=tuple(str(phase).strip() for phase in phases if str(phase).strip()),
        queries=state.queries,
        tuning=state.tuning,
        table_mode=state.table_mode,
        output=state.output,
        mode=state.mode,
        seed=state.seed,
        compression_enabled=bool(compression.enabled),
        compression_type=compression.type,
        compression_level=compression.level,
        iterations=getattr(state, "iterations", None),
        # Click leaves the hidden --concurrency option as None when callers
        # use the normal CLI surface; the canonical plan treats that as the
        # single-stream default rather than passing None through int().
        concurrency=int(getattr(state, "concurrency", None) or 1),
        non_replayable_options=_active_non_replayable_options(state),
    )


def capture_resolved_run_plan(
    state: types.SimpleNamespace,
    *,
    canonical_tuning_mode: str | None,
) -> ResolvedRunPlan:
    """Take one immutable snapshot after all run-resolution stages succeed."""
    request = getattr(state, "run_request", None) or current_run_request(state)
    organization = (
        MappingProxyType(dict(state.data_organization_payload)) if state.data_organization_payload is not None else None
    )
    return ResolvedRunPlan(
        request=request,
        platform_key=state.platform_key,
        benchmark=state.benchmark,
        scale=state.scale,
        phases=tuple(state.phases_to_run),
        queries=tuple(state.queries_to_run) if state.queries_to_run is not None else None,
        test_execution_type=state.test_execution_type,
        execution_mode=state.execution_mode,
        resolved_mode=state.resolved_mode,
        table_mode=state.table_mode,
        tuning_resolution=state.tuning_resolution,
        canonical_tuning_mode=canonical_tuning_mode,
        tuning_enabled=state.tuning_enabled,
        tuning_config_file=state.tuning_config_file,
        use_auto_tuning=state.use_auto_tuning,
        loaded_unified_config=state.loaded_unified_config,
        data_organization=organization,
        dataframe_tuning_config=state.df_tuning_config,
        compression_enabled=state.compress_data,
        compression_type=state.compression_type,
        compression_level=state.compression_level,
        iterations=request.iterations,
        concurrency=request.concurrency,
        seed=state.seed,
        non_replayable_options=request.non_replayable_options,
    )


def parse_saved_phases(value: object) -> tuple[str, ...]:
    """Validate and normalize the historical ``phases`` preference."""
    if isinstance(value, str):
        phases = tuple(part.strip() for part in value.split(",") if part.strip())
    elif isinstance(value, (list, tuple)):
        phases = tuple(str(part).strip() for part in value if str(part).strip())
    else:
        raise ValueError("Saved quick-restart phases must be a string or list")
    if not phases:
        raise ValueError("Saved quick-restart phases cannot be empty")
    return phases


def _saved_compression(
    current: RunRequest,
    saved: Mapping[str, Any],
    explicit_fields: frozenset[str],
) -> tuple[bool, str, int | None]:
    if "compression" in explicit_fields:
        return current.compression_enabled, current.compression_type, current.compression_level

    raw_enabled = saved.get("compress_data", True)
    if not isinstance(raw_enabled, bool):
        raise ValueError("Saved quick-restart compress_data must be a boolean")
    compression_type = str(saved.get("compression_type", "zstd" if raw_enabled else "none"))
    compression_level = saved.get("compression_level")
    if compression_level is not None:
        try:
            compression_level = int(compression_level)
        except (TypeError, ValueError) as exc:
            raise ValueError("Saved quick-restart compression level must be an integer") from exc
    if not raw_enabled:
        compression_type = "none"
        compression_level = None
    elif compression_type == "none":
        raise ValueError("Saved quick-restart compression cannot be enabled with type none")
    if compression_type not in {"none", "gzip", "zstd"}:
        raise ValueError(f"Saved quick-restart compression type is invalid: {compression_type}")
    if compression_level is not None:
        valid_level = (compression_type == "gzip" and 1 <= compression_level <= 9) or (
            compression_type == "zstd" and 1 <= compression_level <= 22
        )
        if not valid_level:
            raise ValueError(
                f"Saved quick-restart compression level {compression_level} is invalid for {compression_type}"
            )
    return raw_enabled, compression_type, compression_level


def _saved_concurrency(
    current: RunRequest,
    saved: Mapping[str, Any],
    explicit_fields: frozenset[str],
) -> int:
    raw_concurrency = current.concurrency if "concurrency" in explicit_fields else saved.get("concurrency", 1)
    if raw_concurrency is None:
        raw_concurrency = 1
    try:
        concurrency = int(raw_concurrency)
    except (TypeError, ValueError) as exc:
        raise ValueError("Saved quick-restart concurrency must be an integer") from exc
    if concurrency < 1:
        raise ValueError("Saved quick-restart concurrency must be at least one")
    return concurrency


def _saved_iterations(
    current: RunRequest,
    saved: Mapping[str, Any],
    explicit_fields: frozenset[str],
) -> int | None:
    raw_iterations = current.iterations if "iterations" in explicit_fields else saved.get("iterations")
    if raw_iterations is None:
        return None
    if isinstance(raw_iterations, bool) or (isinstance(raw_iterations, float) and not raw_iterations.is_integer()):
        raise ValueError("Saved quick-restart iterations must be an integer")
    try:
        iterations = int(raw_iterations)
    except (TypeError, ValueError) as exc:
        raise ValueError("Saved quick-restart iterations must be an integer") from exc
    if iterations < 1:
        raise ValueError("Saved quick-restart iterations must be at least one")
    return iterations


def _validate_replay_schema(saved: Mapping[str, Any]) -> None:
    version = saved.get("replay_schema_version")
    if version is not None and (isinstance(version, bool) or version != 1):
        raise ValueError(f"Saved quick-restart replay schema is unsupported: {version!r}")


def _replay_compatibility_notes(
    current: RunRequest,
    saved: Mapping[str, Any],
    explicit_fields: frozenset[str],
    *,
    compression_enabled: bool,
) -> tuple[str, ...]:
    saved_field_names = {
        "platform": "database",
        "benchmark": "benchmark",
        "scale": "scale",
        "phases": "phases",
        "queries": "queries",
        "tuning": "tuning_mode",
        "table_mode": "table_mode",
        "output": "output",
        "mode": "mode",
        "seed": "seed",
        "compression": "compress_data",
        "iterations": "iterations",
        "concurrency": "concurrency",
    }
    notes = []
    for field in sorted(explicit_fields & saved_field_names.keys()):
        action = "overrides saved" if saved_field_names[field] in saved else "supplies missing saved"
        notes.append(f"current CLI {action} {field}")
    assumed_defaults = (
        ("phases", "phases", "saved run did not record phases; assumed load,power"),
        ("tuning", "tuning_mode", "saved run did not record tuning mode; assumed tuned"),
        ("table_mode", "table_mode", "saved run did not record table mode; assumed native"),
        ("queries", "queries", "saved run did not record a query subset; assumed all queries"),
        ("mode", "mode", "saved run did not record execution mode; used platform default"),
        ("compression", "compress_data", "saved run did not record compression enablement; assumed enabled"),
        ("concurrency", "concurrency", "saved run did not record concurrency; assumed one"),
        ("iterations", "iterations", "saved run did not record power iterations; used the default"),
    )
    notes.extend(
        note
        for field, saved_field, note in assumed_defaults
        if field not in explicit_fields and saved_field not in saved
    )
    if "seed" not in explicit_fields and saved.get("seed") is None:
        notes.append("saved run did not record a seed")
    if "compression" not in explicit_fields and compression_enabled and "compression_type" not in saved:
        notes.append("saved run did not record compression type; assumed zstd")
    if "compression" not in explicit_fields and compression_enabled and "compression_level" not in saved:
        notes.append("saved run did not record compression level; used algorithm default")
    if saved.get("replay_schema_version") != 1:
        notes.append("saved run predates complete execution-option replay accounting")
    active_non_replayable = sorted(set(_saved_non_replayable_options(saved)) | set(current.non_replayable_options))
    notes.extend(f"execution option is not persisted for automatic replay: {name}" for name in active_non_replayable)
    return tuple(notes)


def merge_quick_restart_request(
    current: RunRequest,
    saved: Mapping[str, Any],
    *,
    explicit_fields: frozenset[str],
) -> RunRequest:
    """Merge saved preferences with current command-line intent.

    Explicit current CLI values always win.  Missing historical optional fields
    use documented compatibility defaults.  Required selectors fail closed.
    """

    def choose(field: str, saved_field: str, current_value: Any, default: Any = None) -> Any:
        if field in explicit_fields:
            return current_value
        return saved.get(saved_field, default)

    def required(field: str, saved_field: str, current_value: Any) -> Any:
        if field in explicit_fields:
            return current_value
        if saved_field in saved:
            return saved[saved_field]
        raise ValueError(f"Saved quick-restart configuration is missing: {saved_field}")

    _validate_replay_schema(saved)
    platform = required("platform", "database", current.platform)
    benchmark = required("benchmark", "benchmark", current.benchmark)
    if not isinstance(platform, str) or not platform.strip():
        raise ValueError("Saved quick-restart platform must be a non-empty string")
    if not isinstance(benchmark, str) or not benchmark.strip():
        raise ValueError("Saved quick-restart benchmark must be a non-empty string")

    try:
        scale = float(required("scale", "scale", current.scale))
    except (TypeError, ValueError) as exc:
        raise ValueError("Saved quick-restart scale must be numeric") from exc
    if scale <= 0:
        raise ValueError("Saved quick-restart scale must be positive")

    phases = (
        current.phases if "phases" in explicit_fields else parse_saved_phases(saved.get("phases", ["load", "power"]))
    )
    tuning = str(choose("tuning", "tuning_mode", current.tuning, "tuned") or "tuned")
    table_mode = str(choose("table_mode", "table_mode", current.table_mode, "native") or "native").lower()
    if table_mode not in {"native", "external"}:
        raise ValueError(f"Saved quick-restart table mode is invalid: {table_mode}")

    seed = choose("seed", "seed", current.seed)
    if seed is not None:
        if isinstance(seed, bool) or (isinstance(seed, float) and not seed.is_integer()):
            raise ValueError("Saved quick-restart seed must be an integer")
        try:
            seed = int(seed)
        except (TypeError, ValueError) as exc:
            raise ValueError("Saved quick-restart seed must be an integer") from exc

    iterations = _saved_iterations(current, saved, explicit_fields)

    compression_enabled, compression_type, compression_level = _saved_compression(current, saved, explicit_fields)
    concurrency = _saved_concurrency(current, saved, explicit_fields)

    notes = _replay_compatibility_notes(current, saved, explicit_fields, compression_enabled=compression_enabled)

    raw_queries = current.queries if "queries" in explicit_fields else saved.get("queries")
    if raw_queries is None:
        queries = None
    elif isinstance(raw_queries, str):
        queries = raw_queries
    elif isinstance(raw_queries, (list, tuple)):
        queries = ",".join(str(query).strip() for query in raw_queries if str(query).strip()) or None
    else:
        raise ValueError("Saved quick-restart queries must be a string or list")
    mode = current.mode if "mode" in explicit_fields else saved.get("mode")
    if mode is not None:
        mode = str(mode)

    return RunRequest(
        platform=platform,
        benchmark=benchmark,
        scale=scale,
        phases=phases,
        queries=queries,
        tuning=tuning,
        table_mode=table_mode,
        output=choose("output", "output", current.output),
        mode=mode,
        seed=seed,
        compression_enabled=compression_enabled,
        compression_type=compression_type,
        compression_level=compression_level,
        iterations=iterations,
        concurrency=concurrency,
        non_replayable_options=tuple(
            sorted(set(_saved_non_replayable_options(saved)) | set(current.non_replayable_options))
        ),
        exact_replay=not notes,
        compatibility_notes=notes,
    )


def apply_run_request(state: types.SimpleNamespace, request: RunRequest) -> None:
    """Apply raw intent only; derived fields remain owned by the resolver."""
    state.platform = request.platform
    state.benchmark = request.benchmark
    state.scale = request.scale
    state.phases = ",".join(request.phases)
    state.queries = request.queries
    state.tuning = request.tuning
    state.table_mode = request.table_mode
    state.output = request.output
    state.mode = request.mode
    state.seed = request.seed
    compression = CompressionConfig(
        enabled=request.compression_enabled,
        type=request.compression_type,
        level=request.compression_level,
    )
    state.compression = compression
    state.comp_config = compression
    state.compression_cli_set = True
    state.no_compression = not compression.enabled
    state.compression_type = compression.type
    state.compression_level = compression.level
    state.iterations = request.iterations
    state.concurrency = request.concurrency
    state.run_request = request


def resolve_quick_restart_atomically(
    state: types.SimpleNamespace,
    last_run: Mapping[str, Any],
    *,
    current_request: RunRequest,
    explicit_fields: frozenset[str],
    resolve: Callable[[types.SimpleNamespace], None],
    data_organization_environment: str,
) -> ResolvedRunPlan:
    """Merge and resolve saved intent, rolling back state and environment on failure."""
    request = merge_quick_restart_request(current_request, last_run, explicit_fields=explicit_fields)
    previous_state = vars(state).copy()
    missing_environment = object()
    previous_data_organization = os.environ.get(data_organization_environment, missing_environment)
    previous_non_interactive = os.environ.get("BENCHBOX_NON_INTERACTIVE", missing_environment)
    try:
        apply_run_request(state, request)
        resolve(state)
    except BaseException:
        vars(state).clear()
        vars(state).update(previous_state)
        if previous_data_organization is missing_environment:
            os.environ.pop(data_organization_environment, None)
        else:
            assert isinstance(previous_data_organization, str)
            os.environ[data_organization_environment] = previous_data_organization
        raise
    finally:
        if previous_non_interactive is missing_environment:
            os.environ.pop("BENCHBOX_NON_INTERACTIVE", None)
        else:
            assert isinstance(previous_non_interactive, str)
            os.environ["BENCHBOX_NON_INTERACTIVE"] = previous_non_interactive
    return state.resolved_run_plan


__all__ = [
    "ResolvedRunPlan",
    "RunRequest",
    "apply_run_request",
    "capture_resolved_run_plan",
    "current_run_request",
    "merge_quick_restart_request",
    "parse_saved_phases",
    "resolve_quick_restart_atomically",
]
