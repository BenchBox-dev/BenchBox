"""Input validation schemas for BenchBox MCP server.

Provides Pydantic models for validating and sanitizing tool inputs
to ensure type safety, prevent invalid inputs, and protect against
malicious payloads.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

logger = logging.getLogger(__name__)

# Validation constants
MAX_QUERY_IDS = 100  # Maximum number of query IDs per request (DoS protection)
MAX_QUERY_ID_LENGTH = 64  # Maximum length of a single query ID
QUERY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric with dash/underscore
PLATFORM_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric platform names
BENCHMARK_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")  # Alphanumeric benchmark names
FILENAME_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")  # Safe filename characters
PLATFORM_OPTION_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
MEMORY_LIMIT_PATTERN = re.compile(r"^(?:[1-9]\d{0,5}(?:\.\d{1,2})?)(?:B|KB|MB|GB|TB)$", re.IGNORECASE)
IDENTIFIER_LIST_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(?:,[a-zA-Z_][a-zA-Z0-9_]*)*$")
CLICKHOUSE_PROFILE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

# Server-owned ClickHouse connection profiles, as JSON:
#   {"analytics": {"port": 9440, "secure": true}}
# Only the operator sets this; MCP callers may name a profile but never describe
# a destination or a transport policy.
MCP_CLICKHOUSE_PROFILE_ENV = "BENCHBOX_MCP_CLICKHOUSE_PROFILES"

MAX_PLATFORM_OPTIONS = 16
MAX_PLATFORM_OPTION_VALUE_LENGTH = 256
MAX_MEMORY_LIMIT_BYTES = 1 << 40

# Scale factor limits
MIN_SCALE_FACTOR = 0.001
MAX_SCALE_FACTOR = 10000  # 10TB scale factor is extreme but possible


class MCPValidationError(ValueError):
    """Raised when MCP input validation fails.

    This is distinct from pydantic.ValidationError to avoid confusion
    and provide clearer error handling in MCP tool implementations.
    """


@dataclass(frozen=True, slots=True)
class MCPPlatformOptionSpec:
    """Bounded, non-secret option accepted by the MCP benchmark surface."""

    kind: Literal["bool", "int", "float", "string"]
    choices: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None

    def parse(self, name: str, value: object) -> bool | int | float | str:
        """Validate and normalize one JSON option value without echoing it."""
        if self.kind == "bool":
            if not isinstance(value, bool):
                raise MCPValidationError(f"Platform option '{name}' must be a boolean")
            return value
        if self.kind == "int":
            if isinstance(value, bool) or not isinstance(value, int):
                raise MCPValidationError(f"Platform option '{name}' must be an integer")
            normalized: int | float | str = value
        elif self.kind == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise MCPValidationError(f"Platform option '{name}' must be a number")
            normalized = float(value)
            if not math.isfinite(normalized):
                raise MCPValidationError(f"Platform option '{name}' must be finite")
        else:
            if not isinstance(value, str):
                raise MCPValidationError(f"Platform option '{name}' must be a string")
            normalized = value.strip()
            if not normalized or len(normalized) > MAX_PLATFORM_OPTION_VALUE_LENGTH:
                raise MCPValidationError(f"Platform option '{name}' has an invalid length")

        if self.choices and normalized not in self.choices:
            raise MCPValidationError(f"Platform option '{name}' has an unsupported value")
        if self.minimum is not None and normalized < self.minimum:
            raise MCPValidationError(f"Platform option '{name}' is below the permitted minimum")
        if self.maximum is not None and normalized > self.maximum:
            raise MCPValidationError(f"Platform option '{name}' exceeds the permitted maximum")
        return normalized


_MCP_OPTION = MCPPlatformOptionSpec


@dataclass(frozen=True, slots=True)
class MCPPlatformOptionContract:
    """Review metadata for one accepted MCP option.

    The contract is deliberately separate from the Pydantic-like value spec:
    bounds validate syntax, while this record documents the effective consumer,
    security class, compatibility aliases, and rejected alternatives.  The
    validator requires both records to agree so a new allow-listed option
    cannot bypass the review matrix accidentally.
    """

    consumer: str
    security_class: Literal["execution", "resource", "device", "layout", "connection"]
    aliases: tuple[str, ...] = ()
    rejected_alternatives: tuple[str, ...] = ()


# This is deliberately narrower than the CLI registry.  MCP callers cannot
# change credentials, destinations, filesystem locations, package installation,
# or other tenant-owned connection state through request arguments.
MCP_PLATFORM_OPTION_ALLOWLIST: dict[str, dict[str, MCPPlatformOptionSpec]] = {
    "clickhouse": {
        "connection_profile": _MCP_OPTION("string"),
        "deployment_mode": _MCP_OPTION("string", choices=("local", "server")),
    },
    "clickhouse-server": {
        "connection_profile": _MCP_OPTION("string"),
    },
    "cudf": {
        "device_id": _MCP_OPTION("int", minimum=0, maximum=255),
        "spill_to_host": _MCP_OPTION("bool"),
    },
    "dask": {
        "memory_limit": _MCP_OPTION("string"),
        "n_workers": _MCP_OPTION("int", minimum=1, maximum=256),
        "threads_per_worker": _MCP_OPTION("int", minimum=1, maximum=256),
        "use_distributed": _MCP_OPTION("bool"),
    },
    "datafusion": {
        "batch_size": _MCP_OPTION("int", minimum=1, maximum=1_000_000),
        "memory_limit": _MCP_OPTION("string"),
        "parquet_pushdown": _MCP_OPTION("bool"),
        "repartition_joins": _MCP_OPTION("bool"),
        "target_partitions": _MCP_OPTION("int", minimum=1, maximum=1_024),
    },
    "duckdb": {
        "memory_limit": _MCP_OPTION("string"),
        "threads": _MCP_OPTION("int", minimum=1, maximum=256),
    },
    "firebolt": {
        "disable_result_cache": _MCP_OPTION("bool"),
        "strict_validation": _MCP_OPTION("bool"),
    },
    "databricks": {
        "databricks_clustering_strategy": _MCP_OPTION(
            "string", choices=("z_order", "liquid_clustering", "liquid_clustering_auto", "none")
        ),
        "liquid_clustering_columns": _MCP_OPTION("string"),
    },
    "modin": {"engine": _MCP_OPTION("string", choices=("ray", "dask"))},
    "pandas": {"dtype_backend": _MCP_OPTION("string", choices=("numpy_nullable", "pyarrow"))},
    "polars": {
        "n_rows": _MCP_OPTION("int", minimum=1, maximum=10_000_000),
        "rechunk": _MCP_OPTION("bool"),
        "streaming": _MCP_OPTION("bool"),
    },
    "spark": {"adaptive_enabled": _MCP_OPTION("bool")},
    "sqlite": {
        "check_same_thread": _MCP_OPTION("bool"),
        "timeout": _MCP_OPTION("float", minimum=0, maximum=300),
    },
    "velox": {
        "adaptive_enabled": _MCP_OPTION("bool"),
        "deployment": _MCP_OPTION("string", choices=("local", "remote")),
        "driver_memory": _MCP_OPTION("string"),
        "offheap_size": _MCP_OPTION("string"),
        "shuffle_partitions": _MCP_OPTION("int", minimum=1, maximum=1_024),
    },
}


def _contract(
    consumer: str,
    security_class: Literal["execution", "resource", "device", "layout", "connection"],
    *,
    aliases: tuple[str, ...] = (),
    rejected_alternatives: tuple[str, ...] = (),
) -> MCPPlatformOptionContract:
    return MCPPlatformOptionContract(
        consumer=consumer,
        security_class=security_class,
        aliases=aliases,
        rejected_alternatives=rejected_alternatives,
    )


_CLICKHOUSE_PROFILE_CONTRACT = _contract(
    "ClickHouseAdapter.from_config(port, secure) resolved from server configuration",
    "connection",
    rejected_alternatives=(
        "caller-supplied port",
        "caller-supplied secure/TLS policy",
        "arbitrary destination selection",
        "transport downgrade",
    ),
)


# Canonical option-to-consumer matrix.  Keep this map explicit instead of
# deriving it from the allow-list: an accepted option must have a reviewed
# consumer and security classification before it can cross the MCP boundary.
MCP_PLATFORM_OPTION_CONTRACT: dict[str, dict[str, MCPPlatformOptionContract]] = {
    "clickhouse": {
        "connection_profile": _CLICKHOUSE_PROFILE_CONTRACT,
        "deployment_mode": _contract("ClickHouseAdapter.from_config(deployment_mode)", "execution"),
    },
    "clickhouse-server": {
        "connection_profile": _CLICKHOUSE_PROFILE_CONTRACT,
    },
    "cudf": {
        "device_id": _contract("cuDF runtime device selection", "device"),
        "spill_to_host": _contract("cuDF memory policy", "resource"),
    },
    "dask": {
        "memory_limit": _contract("Dask worker resource envelope", "resource"),
        "n_workers": _contract("Dask LocalCluster worker count", "resource"),
        "threads_per_worker": _contract("Dask LocalCluster thread count", "resource"),
        "use_distributed": _contract("Dask execution-mode selector", "execution"),
    },
    "datafusion": {
        "batch_size": _contract("DataFusion execution configuration", "resource"),
        "memory_limit": _contract("DataFusion memory policy", "resource"),
        "parquet_pushdown": _contract("DataFusion parquet execution options", "execution"),
        "repartition_joins": _contract("DataFusion join execution options", "execution"),
        "target_partitions": _contract("DataFusion partition configuration", "resource"),
    },
    "duckdb": {
        "memory_limit": _contract("DuckDB thread/memory adapter settings", "resource"),
        "threads": _contract(
            "DuckDBAdapter.thread_limit",
            "resource",
            aliases=("thread_limit",),
        ),
    },
    "firebolt": {
        "disable_result_cache": _contract("Firebolt query execution options", "execution"),
        "strict_validation": _contract("Firebolt validation options", "execution"),
    },
    "databricks": {
        "databricks_clustering_strategy": _contract(
            "Databricks PlatformOptimizationConfiguration clustering strategy", "layout"
        ),
        "liquid_clustering_columns": _contract(
            "Databricks PlatformOptimizationConfiguration clustering columns", "layout"
        ),
    },
    "modin": {"engine": _contract("Modin dataframe backend selector", "execution")},
    "pandas": {"dtype_backend": _contract("pandas dataframe dtype backend", "execution")},
    "polars": {
        "n_rows": _contract("Polars input row limit", "resource"),
        "rechunk": _contract("Polars dataframe memory layout", "resource"),
        "streaming": _contract("Polars dataframe execution mode", "execution"),
    },
    "spark": {"adaptive_enabled": _contract("Spark adaptive execution setting", "execution")},
    "sqlite": {
        "check_same_thread": _contract("SQLite connection safety setting", "execution"),
        "timeout": _contract("SQLite connection timeout", "resource"),
    },
    "velox": {
        "adaptive_enabled": _contract("Velox execution options", "execution"),
        "deployment": _contract("Velox local/remote deployment selector", "connection"),
        "driver_memory": _contract("Velox driver resource envelope", "resource"),
        "offheap_size": _contract("Velox off-heap resource envelope", "resource"),
        "shuffle_partitions": _contract("Velox shuffle resource envelope", "resource"),
    },
}


def _load_clickhouse_connection_profiles() -> dict[str, dict[str, object]]:
    """Return the operator-defined ClickHouse connection profiles.

    Profiles are the only supported way to reach a non-default ClickHouse port
    or a non-default TLS setting from MCP.  The mapping is read from server
    process configuration, never from request arguments, so a caller can name a
    reviewed destination but can never describe one.  A malformed registry
    yields no profiles rather than a partially trusted one.
    """
    raw = os.environ.get(MCP_CLICKHOUSE_PROFILE_ENV, "").strip()
    if not raw:
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("Ignoring malformed %s: value is not valid JSON", MCP_CLICKHOUSE_PROFILE_ENV)
        return {}
    if not isinstance(decoded, dict):
        logger.error("Ignoring malformed %s: value is not a JSON object", MCP_CLICKHOUSE_PROFILE_ENV)
        return {}

    profiles: dict[str, dict[str, object]] = {}
    for name, entry in decoded.items():
        if not isinstance(name, str) or not CLICKHOUSE_PROFILE_NAME_PATTERN.fullmatch(name):
            logger.error("Ignoring a %s entry whose profile name is not snake_case", MCP_CLICKHOUSE_PROFILE_ENV)
            continue
        if not isinstance(entry, Mapping):
            logger.error("Ignoring %s profile '%s': value is not an object", MCP_CLICKHOUSE_PROFILE_ENV, name)
            continue
        unknown = set(entry) - {"port", "secure"}
        if unknown:
            # Fail closed rather than silently dropping operator intent: a
            # profile carrying hosts, credentials, or paths is a policy error.
            logger.error(
                "Ignoring %s profile '%s': only 'port' and 'secure' are supported", MCP_CLICKHOUSE_PROFILE_ENV, name
            )
            continue
        port = entry.get("port")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65_535:
            logger.error(
                "Ignoring %s profile '%s': 'port' must be an integer in 1-65535", MCP_CLICKHOUSE_PROFILE_ENV, name
            )
            continue
        secure = entry.get("secure", False)
        if not isinstance(secure, bool):
            logger.error("Ignoring %s profile '%s': 'secure' must be a boolean", MCP_CLICKHOUSE_PROFILE_ENV, name)
            continue
        profiles[name] = {"port": port, "secure": secure}
    return profiles


def resolve_clickhouse_connection_profile(name: str) -> dict[str, object]:
    """Resolve a named profile to its server-owned connection settings.

    Raises:
        MCPValidationError: If no such profile is configured on this server.
    """
    profile = _load_clickhouse_connection_profiles().get(name)
    if profile is None:
        # Deliberately does not echo the requested name or list configured
        # profiles: that would turn a validation error into a probe oracle.
        raise MCPValidationError("Platform option 'connection_profile' is not configured on this server")
    return dict(profile)


def _validate_clickhouse_options(platform: str, normalized: Mapping[str, object]) -> None:
    """Fail closed on ClickHouse connection intent that MCP must not grant."""
    profile = normalized.get("connection_profile")
    if profile is None:
        return
    if not CLICKHOUSE_PROFILE_NAME_PATTERN.fullmatch(str(profile)):
        raise MCPValidationError("Platform option 'connection_profile' must be a lowercase snake_case profile name")
    if platform == "clickhouse" and normalized.get("deployment_mode") != "server":
        # Local mode runs chDB in-process.  Accepting a connection profile there
        # would hand local runs a network path they do not otherwise have.
        raise MCPValidationError("Platform option 'connection_profile' requires deployment_mode='server'")
    # Existence is checked at admission so an unknown profile is rejected before
    # a durable job is persisted.  The resolved port/TLS values are deliberately
    # NOT merged into the normalized request: only the profile name is persisted,
    # so a retry re-resolves from current server configuration.
    resolve_clickhouse_connection_profile(str(profile))


def _memory_size_bytes(value: str) -> float | None:
    """Return a bounded memory-size string in bytes, or None if it is not one."""
    if not MEMORY_LIMIT_PATTERN.fullmatch(value):
        return None
    number, unit = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([A-Za-z]+)", value).groups()  # type: ignore[union-attr]
    multipliers = {"B": 1, "KB": 1 << 10, "MB": 1 << 20, "GB": 1 << 30, "TB": 1 << 40}
    return float(number) * multipliers[unit.upper()]


def _validate_memory_limit(name: str, value: str) -> str:
    """Validate a bounded memory-size option without accepting paths or expressions."""
    size = _memory_size_bytes(value)
    if size is None:
        raise MCPValidationError(f"Platform option '{name}' must use a bounded memory size")
    if size > MAX_MEMORY_LIMIT_BYTES:
        raise MCPValidationError(f"Platform option '{name}' exceeds the permitted memory limit")
    return value


@dataclass(frozen=True, slots=True)
class DaskResourceEnvelope:
    """Server-owned aggregate ceiling for one MCP-requested Dask cluster.

    Dask's per-field maxima bound each knob in isolation, but the pressure a
    request actually puts on the host is the *product* of the worker count and
    the per-worker thread and memory limits.  This record is the aggregate
    budget that product must fit inside.
    """

    max_workers: int
    max_total_threads: int
    max_total_memory_bytes: float


# Effective adapter defaults for fields the request leaves unset.  These mirror
# the conservative local caps in benchbox/platforms/dataframe/dask_df.py, so an
# omitted field can never contribute more than the adapter would actually apply.
_DASK_DEFAULT_WORKERS = 2
_DASK_DEFAULT_THREADS_PER_WORKER = 2
_DASK_DEFAULT_MEMORY_PER_WORKER_BYTES = float(2 << 30)

# Server-owned aggregate budget.  Deliberately far below the per-field maxima:
# n_workers=256 x threads_per_worker=256 would otherwise admit a 65,536-thread
# cluster advertising 256 TB of memory from a single request.
MCP_DASK_MAX_WORKERS_ENV = "BENCHBOX_MCP_DASK_MAX_WORKERS"
MCP_DASK_MAX_TOTAL_THREADS_ENV = "BENCHBOX_MCP_DASK_MAX_TOTAL_THREADS"
MCP_DASK_MAX_TOTAL_MEMORY_ENV = "BENCHBOX_MCP_DASK_MAX_TOTAL_MEMORY"
_DASK_DEFAULT_MAX_WORKERS = 16
_DASK_DEFAULT_MAX_TOTAL_THREADS = 64
_DASK_DEFAULT_MAX_TOTAL_MEMORY = "64GB"
# A units slip or an extra digit ("999999TB") is syntactically valid, so the
# memory override needs the same out-of-range guard the integer budgets have --
# otherwise a typo silently disables the aggregate memory ceiling entirely.
_DASK_MAX_TOTAL_MEMORY_CEILING_BYTES = float(16 << 40)


def _envelope_int(env_name: str, default: int, *, maximum: int) -> int:
    """Read one operator-supplied integer budget, falling back when unusable."""
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.error("Ignoring malformed %s: value is not an integer", env_name)
        return default
    if not 1 <= value <= maximum:
        logger.error("Ignoring out-of-range %s: value must be in 1-%d", env_name, maximum)
        return default
    return value


def load_dask_resource_envelope() -> DaskResourceEnvelope:
    """Return the server-owned aggregate Dask budget for this process."""
    raw_memory = os.environ.get(MCP_DASK_MAX_TOTAL_MEMORY_ENV, "").strip()
    memory_bytes = _memory_size_bytes(raw_memory) if raw_memory else None
    if raw_memory and memory_bytes is None:
        logger.error("Ignoring malformed %s: value is not a bounded memory size", MCP_DASK_MAX_TOTAL_MEMORY_ENV)
    if memory_bytes is not None and memory_bytes > _DASK_MAX_TOTAL_MEMORY_CEILING_BYTES:
        logger.error(
            "Ignoring out-of-range %s: value must not exceed %dTB",
            MCP_DASK_MAX_TOTAL_MEMORY_ENV,
            int(_DASK_MAX_TOTAL_MEMORY_CEILING_BYTES) >> 40,
        )
        memory_bytes = None
    if memory_bytes is None:
        memory_bytes = _memory_size_bytes(_DASK_DEFAULT_MAX_TOTAL_MEMORY)
    assert memory_bytes is not None
    return DaskResourceEnvelope(
        max_workers=_envelope_int(MCP_DASK_MAX_WORKERS_ENV, _DASK_DEFAULT_MAX_WORKERS, maximum=256),
        max_total_threads=_envelope_int(
            MCP_DASK_MAX_TOTAL_THREADS_ENV, _DASK_DEFAULT_MAX_TOTAL_THREADS, maximum=65_536
        ),
        max_total_memory_bytes=memory_bytes,
    )


def _validate_dask_options(normalized: Mapping[str, object]) -> None:
    """Reject a Dask request whose aggregate footprint exceeds the host budget.

    Runs before adapter construction: ``DaskDataFrameAdapter.__init__`` builds
    the ``LocalCluster`` itself, so a guard placed any later would have to start
    the oversized cluster to discover it was oversized.
    """
    envelope = load_dask_resource_envelope()

    workers = normalized.get("n_workers", _DASK_DEFAULT_WORKERS)
    threads_per_worker = normalized.get("threads_per_worker", _DASK_DEFAULT_THREADS_PER_WORKER)
    assert isinstance(workers, int) and isinstance(threads_per_worker, int)

    if workers > envelope.max_workers:
        raise MCPValidationError("Dask 'n_workers' exceeds the server's worker budget")

    total_threads = workers * threads_per_worker
    if total_threads > envelope.max_total_threads:
        # The product, not either field alone, is the CPU pressure on the host.
        raise MCPValidationError("Dask 'n_workers' x 'threads_per_worker' exceeds the server's total thread budget")

    memory_limit = normalized.get("memory_limit")
    per_worker_bytes = (
        _memory_size_bytes(str(memory_limit)) if memory_limit is not None else _DASK_DEFAULT_MEMORY_PER_WORKER_BYTES
    )
    assert per_worker_bytes is not None  # already bounded by _validate_memory_limit
    if workers * per_worker_bytes > envelope.max_total_memory_bytes:
        # memory_limit is per worker, so the advertised total scales with n_workers.
        raise MCPValidationError("Dask 'n_workers' x 'memory_limit' exceeds the server's total memory budget")


def validate_platform_options(platform: str, options: Mapping[str, object] | None) -> dict[str, object]:
    """Return canonical, bounded MCP platform options or fail closed."""
    # An omitted request and an empty one must validate identically.  Returning
    # early for None would skip the cross-field policy, so a request that names
    # no options at all would escape the server's resource envelope and run on
    # adapter defaults that may exceed it.
    if options is None:
        options = {}
    if not isinstance(options, Mapping):
        raise MCPValidationError("platform_options must be an object")
    if len(options) > MAX_PLATFORM_OPTIONS:
        raise MCPValidationError(f"Too many platform options (maximum {MAX_PLATFORM_OPTIONS})")

    platform_name = validate_platform_name(platform)
    # A "-df" request falls back to the base platform's records, so the policy
    # key must fall back with it: resolving the fallback once keeps the value
    # specs, the contract matrix, and the cross-field rules on the same platform.
    policy_name = platform_name
    if platform_name not in MCP_PLATFORM_OPTION_ALLOWLIST and platform_name.endswith("-df"):
        policy_name = platform_name[:-3]
    specs = MCP_PLATFORM_OPTION_ALLOWLIST.get(policy_name) or {}
    contracts = MCP_PLATFORM_OPTION_CONTRACT.get(policy_name) or {}
    normalized: dict[str, object] = {}
    for raw_name, raw_value in options.items():
        if not isinstance(raw_name, str) or not PLATFORM_OPTION_NAME_PATTERN.fullmatch(raw_name):
            raise MCPValidationError("Platform option names must use lowercase snake_case")
        name = raw_name.lower()
        spec = specs.get(name)
        contract = contracts.get(name)
        if spec is None or contract is None:
            raise MCPValidationError(f"Platform option '{name}' is not authorized for MCP")
        parsed = spec.parse(name, raw_value)
        if spec.kind == "string" and name in {"memory_limit", "driver_memory", "offheap_size"}:
            parsed = _validate_memory_limit(name, parsed)  # type: ignore[arg-type]
        if name == "liquid_clustering_columns" and not IDENTIFIER_LIST_PATTERN.fullmatch(str(parsed)):
            raise MCPValidationError(f"Platform option '{name}' contains invalid identifiers")
        normalized[name] = parsed

    # Cross-field policy runs after every value is bounded, so it sees the whole
    # request.  Every admission path (synchronous run_benchmark, durable
    # start_benchmark, and durable worker replay) reaches this one function, so a
    # rejected combination can never be persisted or reintroduced by a retry.
    _validate_cross_field_policy(policy_name, normalized)
    return normalized


def _validate_cross_field_policy(platform_name: str, normalized: Mapping[str, object]) -> None:
    """Apply per-platform rules that individual value bounds cannot express."""
    if platform_name in {"clickhouse", "clickhouse-server"}:
        _validate_clickhouse_options(platform_name, normalized)
    elif platform_name == "dask":
        _validate_dask_options(normalized)
    elif platform_name == "databricks":
        # Building the intent is the validation: contradictory layout requests
        # only reveal themselves once both fields are resolved together.
        build_databricks_clustering_intent(normalized)


def build_databricks_clustering_intent(normalized: Mapping[str, object]):
    """Translate normalized MCP clustering options into effective tuning.

    Returns ``None`` when the request carries no clustering intent.  Both the
    admission gate and adapter preparation call this, so a combination that is
    rejected at admission cannot be reconstructed later by a durable replay, and
    the object the resolver consumes is the one that was validated.

    Raises:
        MCPValidationError: If the requested layout fields contradict each other.
    """
    strategy = normalized.get("databricks_clustering_strategy")
    columns = normalized.get("liquid_clustering_columns")
    if strategy is None and columns is None:
        return None

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration

    tuning_config = UnifiedTuningConfiguration()
    platform_optimizations = tuning_config.platform_optimizations

    if strategy is not None:
        strategy = str(strategy).lower()
        platform_optimizations.databricks_clustering_strategy = strategy
        platform_optimizations.liquid_clustering_enabled = strategy in {
            "liquid_clustering",
            "liquid_clustering_auto",
        }
        platform_optimizations.physical_rendering_id = None
    if columns is not None:
        parsed_columns = [column.strip() for column in str(columns).split(",") if column.strip()]
        platform_optimizations.liquid_clustering_columns = parsed_columns
        platform_optimizations.liquid_clustering_enabled = bool(parsed_columns)
        if parsed_columns and strategy is None:
            platform_optimizations.databricks_clustering_strategy = "liquid_clustering"

    try:
        platform_optimizations.__post_init__()
    except ValueError as exc:
        # Surface layout conflicts as a structured validation error at admission
        # instead of an execution failure discovered by a worker.  The message
        # is generated from allow-listed option names, not from caller text.
        raise MCPValidationError(f"Databricks clustering options conflict: {exc}") from exc
    return tuning_config


def validate_query_id(query_id: str) -> str:
    """Validate a single query ID.

    Args:
        query_id: Query ID to validate

    Returns:
        Sanitized query ID

    Raises:
        MCPValidationError: If query ID is invalid
    """
    query_id = query_id.strip()

    if not query_id:
        raise MCPValidationError("Query ID cannot be empty")

    if len(query_id) > MAX_QUERY_ID_LENGTH:
        raise MCPValidationError(f"Query ID too long (max {MAX_QUERY_ID_LENGTH} chars): {query_id[:20]}...")

    if not QUERY_ID_PATTERN.match(query_id):
        raise MCPValidationError(f"Query ID contains invalid characters: {query_id}")

    return query_id


def validate_query_list(queries: str | None) -> list[str] | None:
    """Validate and parse a comma-separated query list.

    Args:
        queries: Comma-separated query IDs (e.g., "1,3,6")

    Returns:
        List of validated query IDs, or None if input is None/empty

    Raises:
        MCPValidationError: If any query ID is invalid or list is too long
    """
    if not queries:
        return None

    query_list = [q.strip() for q in queries.split(",") if q.strip()]

    if not query_list:
        return None

    if len(query_list) > MAX_QUERY_IDS:
        raise MCPValidationError(f"Too many query IDs (max {MAX_QUERY_IDS}): got {len(query_list)}")

    return [validate_query_id(q) for q in query_list]


def validate_platform_name(platform: str) -> str:
    """Validate a platform name.

    Args:
        platform: Platform name to validate

    Returns:
        Lowercased, sanitized platform name

    Raises:
        MCPValidationError: If platform name is invalid
    """
    platform = platform.strip().lower()

    if not platform:
        raise MCPValidationError("Platform name cannot be empty")

    if len(platform) > 50:
        raise MCPValidationError(f"Platform name too long (max 50 chars): {platform[:20]}...")

    if not PLATFORM_PATTERN.match(platform):
        raise MCPValidationError(f"Platform name contains invalid characters: {platform}")

    return platform


def validate_benchmark_name(benchmark: str) -> str:
    """Validate a benchmark name.

    Args:
        benchmark: Benchmark name to validate

    Returns:
        Lowercased, sanitized benchmark name

    Raises:
        MCPValidationError: If benchmark name is invalid
    """
    benchmark = benchmark.strip().lower()

    if not benchmark:
        raise MCPValidationError("Benchmark name cannot be empty")

    if len(benchmark) > 50:
        raise MCPValidationError(f"Benchmark name too long (max 50 chars): {benchmark[:20]}...")

    if not BENCHMARK_PATTERN.match(benchmark):
        raise MCPValidationError(f"Benchmark name contains invalid characters: {benchmark}")

    return benchmark


def validate_filename(filename: str) -> str:
    """Validate a result filename.

    Prevents path traversal attacks and other malicious filenames.

    Args:
        filename: Filename to validate

    Returns:
        Sanitized filename

    Raises:
        MCPValidationError: If filename is invalid or potentially malicious
    """
    filename = filename.strip()

    if not filename:
        raise MCPValidationError("Filename cannot be empty")

    if len(filename) > 255:
        raise MCPValidationError(f"Filename too long (max 255 chars): {filename[:20]}...")

    # Check for path traversal attempts
    if ".." in filename or "/" in filename or "\\" in filename:
        raise MCPValidationError(f"Filename cannot contain path components: {filename}")

    # Only allow safe characters
    if not FILENAME_PATTERN.match(filename):
        raise MCPValidationError(f"Filename contains invalid characters: {filename}")

    return filename


MODE_CHOICES = ("sql", "dataframe", "data_only")


def validate_mode(mode: str | None) -> str | None:
    """Validate execution mode value.

    Args:
        mode: Execution mode to validate ('sql', 'dataframe', or 'data_only')

    Returns:
        Lowercased, validated mode or None if input is None

    Raises:
        MCPValidationError: If mode is invalid
    """
    if mode is None:
        return None
    mode_lower = mode.strip().lower()
    # Normalize aliases
    if mode_lower in ("datagen", "generate"):
        mode_lower = "data_only"
    if mode_lower not in MODE_CHOICES:
        raise MCPValidationError(f"Invalid mode: {mode}. Must be 'sql', 'dataframe', or 'data_only'")
    return mode_lower


def validate_scale_factor(scale_factor: float) -> float:
    """Validate a scale factor.

    Args:
        scale_factor: Scale factor to validate

    Returns:
        Validated scale factor

    Raises:
        MCPValidationError: If scale factor is out of valid range
    """
    if scale_factor <= 0:
        raise MCPValidationError(f"Scale factor must be positive: {scale_factor}")

    if scale_factor < MIN_SCALE_FACTOR:
        raise MCPValidationError(f"Scale factor too small (min {MIN_SCALE_FACTOR}): {scale_factor}")

    if scale_factor > MAX_SCALE_FACTOR:
        raise MCPValidationError(f"Scale factor too large (max {MAX_SCALE_FACTOR}): {scale_factor}")

    return scale_factor
