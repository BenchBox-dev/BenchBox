"""YAML config schema for the UAT framework."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_PHASES: tuple[str, ...] = (
    "preflight",
    "execute",
    "validate",
    "package",
    "explorer_smoke",
    "report",
)

VALID_TERMINAL_STATES: tuple[str, ...] = (
    "local-stage",
    "cloud-uploaded",
    "draft-pr",
    "merged-to-published-results",
)

VALID_DOCKER_PLATFORM_SWITCH_MODES: tuple[str, ...] = ("off", "containers", "volumes", "images")
VALID_DOCKER_FIXED_CONTAINER_NAME_POLICIES: tuple[str, ...] = ("fail", "override", "allow")


class ConfigError(ValueError):
    """Raised when a UAT YAML config fails schema validation."""


@dataclass(frozen=True)
class ExecuteConfig:
    per_cell_timeout_s: int = 600
    early_stop_after_s: int = 180
    early_stop_on_failure: bool = True
    phases_arg: str = "load,power"
    compression: str | None = None
    extra_args: tuple[str, ...] = ()
    skip_unreachable: bool = True
    parallel_platforms: bool = False  # reserved; must remain False
    # Per-cell liveness probe: TCP timeout, in seconds, for the fresh
    # reachability probe run before each cell of a platform that WAS
    # reachable when the platform started. 0 disables the probe entirely --
    # the same 0-disables convention as free_space_min_gib /
    # free_memory_min_gib, so every gate this change adds is switched off
    # the same way.
    #
    # This is the mechanism that catches a stack dying at arbitrary latency
    # mid-platform; the post-start readiness check
    # (cleanup.docker_settle_s) covers only immediate crashes. Cost is one
    # loopback TCP connect per cell against multi-minute cells, and zero
    # syscalls for platforms with no reachability endpoint.
    liveness_probe_timeout_s: float = 2.0
    # official/streams/seed drive a real multi-stream throughput cell via
    # `benchbox run-official --streams N` instead of the default `benchbox
    # run` -- see tests.uat.throughput for why `run-official` is the only
    # CLI surface that can request N>1 streams today.
    official: bool = False
    streams: int | None = None
    seed: int | None = None


@dataclass(frozen=True)
class OutputConfig:
    benchmark_runs_dir_template: str = "~/Developer/benchmark_runs"
    logs_dir_template: str = "~/Developer/benchmark_runs/logs/uat_{date}_{time}"
    submissions_dir_template: str = "~/Developer/benchmark_runs/submissions/{name}"
    # Keys that were actually present in the raw YAML `output:` mapping --
    # NOT a value-equality check. A config that explicitly sets a template to
    # a string that happens to equal the schema default must still be
    # treated as explicit (must_preserve "Explicit YAML output templates
    # ALWAYS win"; see tests.uat.phases.execute._resolve_output_base and the
    # uat-operator-provisioning review response, 2026-07-19).
    explicitly_set: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class PreflightConfig:
    free_space_min_gib: float = 5.0
    free_space_path: str | None = None
    docker_required: bool = False
    noisy_neighbor_warn_load: float = 8.0
    local_platforms_check: bool = False
    # Mirrors free_space_min_gib's shape and 0-disables convention (see
    # UATConfig.memory_gate_enabled). Under mocker each Docker-managed
    # platform is its own VM with independent memory sizing; `up --wait`
    # exiting 0 says nothing about host headroom for that VM. Default 2.0
    # GiB is a deliberately modest floor -- roughly one container VM's
    # worth of breathing room -- not a tuned production threshold; the
    # 2026-08-04 postmortem host had 72 MB free of 16 GB when a 1024 MB
    # cgroup-limited container failed to start. See
    # uat-container-readiness-and-memory-headroom-gate w2.
    #
    # CALIBRATION PROVENANCE -- read before retuning this number. The floor
    # is compared against `psutil.virtual_memory().available`
    # (preflight_budget.read_memory_snapshot), but the motivating "72 MB
    # free of 16 GB" observation is a macOS *free*-style figure, and those
    # are NOT the same metric: measured on the 2026-08-05 dev host,
    # `.available` read 6.888 GiB against `.free` 1.076 GiB -- a ~6.4:1
    # spread. So 2.0 GiB-of-`.available` is NOT "the incident value plus
    # margin"; the incident number cannot be converted into an `.available`
    # threshold after the fact, and this floor has deliberately NOT been
    # silently re-derived from it. `.available` is still the correct metric
    # to gate on (a `.free` gate would refuse to start on a perfectly
    # healthy machine -- 1.076 GiB < 2.0 GiB on the host above); what is
    # unproven is the exact value. Treat 2.0 as a placeholder pending a
    # `.available` reading captured during a real memory-starved incident,
    # and record any change against a measured `.available` figure.
    free_memory_min_gib: float = 2.0
    # Calibrated ClickHouse server compose request. This is resolved into
    # CLICKHOUSE_MEMORY_LIMIT for managed starts; it is not a 1 GiB fallback.
    # Operators may override it explicitly for a separately measured rung.
    # SF1's 4 GiB trace failed with a ClickHouse memory-limit error; the
    # lowest envelope justified for the certification path is 8 GiB.
    clickhouse_memory_limit: str = "8g"
    # Host memory kept available in addition to requested VM/container bytes.
    docker_memory_reserve_gib: float = 2.0


@dataclass(frozen=True)
class CleanupConfig:
    preserve_datagen: bool = True
    prune_databases: bool = True
    docker_manage_platforms: bool = False
    docker_platform_switch: str = "off"
    docker_project_prefix: str = "benchbox-uat"
    docker_start_timeout_s: int = 300
    docker_fixed_container_name_policy: str = "fail"
    # Settle window after `up --wait` reports success and before the
    # post-start readiness re-check (compose ps state + TCP probe) runs --
    # see uat-container-readiness-and-memory-headroom-gate w0. NOT a
    # replacement for docker_start_timeout_s: `up --wait` already reported
    # Started/healthy by the time this fires, so raising
    # docker_start_timeout_s would only wait longer on something the engine
    # already declared done. This waits to see whether it STAYS up.
    docker_settle_s: int = 10


@dataclass(frozen=True)
class MatrixFilterConfig:
    groups: tuple[str, ...] | None = None
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    include_was_specified: bool = False

    @property
    def uses_implicit_group_default(self) -> bool:
        """Whether callers should apply their phase-specific default group."""
        return self.groups is None and not self.include_was_specified and not self.include


@dataclass(frozen=True)
class ScalesConfig:
    rungs: tuple[float, ...] = (0.01,)
    override: float | None = None

    @property
    def requested_rungs(self) -> tuple[float, ...]:
        """Return the effective ladder after any one-scale override."""
        return (self.override,) if self.override is not None else self.rungs


@dataclass(frozen=True)
class ValidateConfig:
    validator_clean_rate_floor: float = 0.80


@dataclass(frozen=True)
class PackageConfig:
    submit_terminal_state: str | None = None
    service: str | None = None


@dataclass(frozen=True)
class ExplorerSmokeConfig:
    playwright_browsers: tuple[str, ...] = ("chromium",)


@dataclass(frozen=True)
class ReportConfig:
    matrix_summary_tsv: str = "matrix_summary.tsv"
    cross_scale_coverage_min_pairs: int | None = None


@dataclass(frozen=True)
class CompatibilityConfig:
    release_gate_runtime_envelopes: bool = False


@dataclass(frozen=True)
class UATConfig:
    """Root config object. Defaults match the spec."""

    name: str
    description: str = ""
    phases: tuple[str, ...] = ("preflight", "execute", "report")
    dry_run: bool = False
    platforms: MatrixFilterConfig = field(default_factory=MatrixFilterConfig)
    benchmarks: MatrixFilterConfig = field(default_factory=MatrixFilterConfig)
    scales: ScalesConfig = field(default_factory=ScalesConfig)
    execute: ExecuteConfig = field(default_factory=ExecuteConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    preflight: PreflightConfig = field(default_factory=PreflightConfig)
    cleanup: CleanupConfig = field(default_factory=CleanupConfig)
    validate: ValidateConfig = field(default_factory=ValidateConfig)
    package: PackageConfig = field(default_factory=PackageConfig)
    explorer_smoke: ExplorerSmokeConfig = field(default_factory=ExplorerSmokeConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    compatibility: CompatibilityConfig = field(default_factory=CompatibilityConfig)

    @property
    def disk_gate_enabled(self) -> bool:
        """Whether the free-space floor and per-cell disk watch are active.

        Always-on for every execute-bearing run, decoupled from the
        `phases:` list -- omitting `"preflight"` skips the pre-sweep
        budget report/abort only, not this safety interlock (see
        uat-disk-gate-always-on). Reads the raw configured floor
        (`preflight.free_space_min_gib`), not a budget-resolved value;
        the pre-sweep gate separately resolves max(flat floor, budget
        est_peak) in preflight_budget.check_disk_headroom. The sole
        opt-out is an explicit `preflight.free_space_min_gib: 0`, which
        callers must pair with a loud warning
        (`disk_gate_disabled_warning`) since it turns the gate off
        entirely.
        """
        return self.preflight.free_space_min_gib > 0

    @property
    def memory_gate_enabled(self) -> bool:
        """Whether the free-memory floor is active before starting a Docker-managed platform.

        Mirrors `disk_gate_enabled`'s shape and 0-disables convention:
        gated purely on the configured floor (`preflight.free_memory_min_gib
        > 0`), read directly by `execute.py` at the platform boundary --
        there is no separate orchestrator-level toggle to keep in sync (see
        uat-container-readiness-and-memory-headroom-gate w2). The sole
        opt-out is an explicit `preflight.free_memory_min_gib: 0`.
        """
        return self.preflight.free_memory_min_gib > 0


DISK_GATE_DISABLED_WARNING_PREFIX = "[disk-gate] DISABLED by config"
MEMORY_GATE_DISABLED_WARNING_PREFIX = "[memory-gate] DISABLED by config"


def disk_gate_disabled_warning(config: UATConfig) -> str | None:
    """Return the loud opt-out warning when `disk_gate_enabled` is False."""
    if config.disk_gate_enabled:
        return None
    return (
        f"{DISK_GATE_DISABLED_WARNING_PREFIX}: preflight.free_space_min_gib=0 -- "
        "the free-space floor and per-cell disk watch will NOT run for this sweep"
    )


def memory_gate_disabled_warning(config: UATConfig) -> str | None:
    """Return the loud opt-out warning when `memory_gate_enabled` is False."""
    if config.memory_gate_enabled:
        return None
    return (
        f"{MEMORY_GATE_DISABLED_WARNING_PREFIX}: preflight.free_memory_min_gib=0 -- "
        "the free-memory headroom gate will NOT run before starting Docker-managed platforms"
    )


ROOT_FIELDS = frozenset(
    {
        "name",
        "description",
        "phases",
        "dry_run",
        "platforms",
        "benchmarks",
        "scales",
        "execute",
        "output",
        "preflight",
        "cleanup",
        "validate",
        "package",
        "explorer_smoke",
        "report",
        "compatibility",
    }
)


def _reject_unknown_fields(payload: dict[str, Any], allowed: frozenset[str], section: str) -> None:
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise ConfigError(f"Unknown field(s) in `{section}`: {', '.join(unknown)}")


def _validate_phases(phases: list[str]) -> tuple[str, ...]:
    if not phases:
        raise ConfigError("`phases:` must be a non-empty list of strings")
    out: list[str] = []
    for entry in phases:
        if not isinstance(entry, str):
            raise ConfigError(f"`phases[]` entries must be strings, got {type(entry).__name__}")
        if entry not in VALID_PHASES:
            raise ConfigError(f"Unknown phase {entry!r}; valid: {sorted(VALID_PHASES)}")
        out.append(entry)
    seen: set[str] = set()
    duplicates: list[str] = []
    for entry in out:
        if entry in seen:
            duplicates.append(entry)
        else:
            seen.add(entry)
    if duplicates:
        raise ConfigError(f"`phases:` contains duplicate entries: {sorted(set(duplicates))}")
    # The orchestrator (tests/uat/orchestrator.py) walks `phases:` literally
    # in the order given -- it does not reorder to the canonical pipeline
    # order. A config like `phases: [report, execute]` used to load
    # successfully and silently produce an empty report (report ran before
    # any cell existed). Reject any ordering that is not a subsequence of
    # VALID_PHASES's canonical order.
    canonical_index = {phase: idx for idx, phase in enumerate(VALID_PHASES)}
    indices = [canonical_index[phase] for phase in out]
    if indices != sorted(indices):
        raise ConfigError(
            f"`phases:` entries must follow canonical order {list(VALID_PHASES)}; got {out} "
            "-- the orchestrator walks `phases:` literally, so an out-of-order list "
            "(e.g. `report` before `execute`) silently produces an empty report"
        )
    return tuple(out)


def _require_positive_int(payload: dict[str, Any], key: str, *, default: int, section: str) -> int:
    """Coerce payload[key] to int. Reject floats and non-numeric strings."""
    value = payload.get(key, default)
    if isinstance(value, bool):
        raise ConfigError(f"`{section}.{key}` must be an int, got bool")
    if isinstance(value, int):
        coerced = value
    elif isinstance(value, str) and value.lstrip("-").isdigit():
        coerced = int(value)
    else:
        raise ConfigError(f"`{section}.{key}` must be an int, got {type(value).__name__}={value!r}")
    if coerced <= 0:
        raise ConfigError(f"`{section}.{key}` must be > 0")
    return coerced


def _require_nonnegative_float(payload: dict[str, Any], key: str, *, default: float, section: str) -> float:
    value = payload.get(key, default)
    if isinstance(value, bool):
        raise ConfigError(f"`{section}.{key}` must be a number, got bool")
    try:
        coerced = float(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"`{section}.{key}` must be a number, got {type(value).__name__}={value!r}") from exc
    if not math.isfinite(coerced) or coerced < 0:
        raise ConfigError(f"`{section}.{key}` must be a finite number >= 0")
    return coerced


def _require_bool(payload: dict[str, Any], key: str, *, default: bool, section: str) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"`{section}.{key}` must be a bool, got {type(value).__name__}={value!r}")
    return value


def _require_nonempty_string(payload: dict[str, Any], key: str, *, default: str, section: str) -> str:
    value = payload.get(key, default)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"`{section}.{key}` must be a non-empty string")
    return value.strip()


def _as_string_tuple(value: Any, *, section: str, key: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)) and all(isinstance(entry, str) for entry in value):
        return tuple(value)
    raise ConfigError(f"`{section}.{key}` must be a string or list of strings")


def _validate_matrix_filter(payload: dict[str, Any] | None, *, section: str) -> MatrixFilterConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError(f"`{section}:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"groups", "include", "exclude"}), section)
    groups = None if "groups" not in payload else _as_string_tuple(payload.get("groups"), section=section, key="groups")
    return MatrixFilterConfig(
        groups=groups,
        include=_as_string_tuple(payload.get("include"), section=section, key="include"),
        exclude=_as_string_tuple(payload.get("exclude"), section=section, key="exclude"),
        include_was_specified="include" in payload,
    )


def _validate_scales(payload: dict[str, Any] | None) -> ScalesConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`scales:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"rungs", "override"}), "scales")
    override = payload.get("override")
    if isinstance(override, bool):
        raise ConfigError("`scales.override` must be a number, got bool")
    try:
        override_value = float(override) if override is not None else None
    except (TypeError, ValueError) as exc:
        raise ConfigError("`scales.override` must be a number") from exc

    # Keep the report-facing rung list aligned with the single-scale override.
    # Enumeration already prefers `override`, but report/aggregation consumers
    # read `rungs`; leaving the schema default here makes an override run report
    # against the wrong scale ladder.
    rungs_raw = payload.get("rungs", [override_value] if override_value is not None else [0.01])
    if isinstance(rungs_raw, (str, bytes)) or not isinstance(rungs_raw, (list, tuple)):
        raise ConfigError("`scales.rungs` must be a list of numbers")
    if any(isinstance(value, bool) for value in rungs_raw):
        # bool is an int subclass, so `float(True) == 1.0` would otherwise
        # silently accept `rungs: [true]` as a 1.0 scale rung.
        raise ConfigError("`scales.rungs` entries must be numbers, got bool")
    try:
        rungs = tuple(float(value) for value in rungs_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError("`scales.rungs` must be a list of numbers") from exc
    if not rungs:
        raise ConfigError("`scales.rungs` must be non-empty")
    if "rungs" in payload and override_value is not None:
        raise ConfigError(
            "`scales.rungs` and `scales.override` are mutually exclusive -- "
            "set only one (see _project/specs/uat-framework.md Section 3)"
        )
    return ScalesConfig(rungs=rungs, override=override_value)


def _validate_execute(payload: dict[str, Any]) -> ExecuteConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`execute:` must be a mapping")
    _reject_unknown_fields(
        payload,
        frozenset(
            {
                "per_cell_timeout_s",
                "early_stop_after_s",
                "early_stop_on_failure",
                "phases_arg",
                "compression",
                "extra_args",
                "skip_unreachable",
                "parallel_platforms",
                "liveness_probe_timeout_s",
                "official",
                "streams",
                "seed",
            }
        ),
        "execute",
    )
    parallel_platforms = _require_bool(payload, "parallel_platforms", default=False, section="execute")
    if parallel_platforms:
        raise ConfigError(
            "`execute.parallel_platforms: true` is forbidden — UAT W3 line 222: "
            "concurrent platform runs contaminate timings"
        )
    timeout = _require_positive_int(payload, "per_cell_timeout_s", default=600, section="execute")
    early_after = _require_positive_int(payload, "early_stop_after_s", default=180, section="execute")
    extra_args_raw = payload.get("extra_args", ())
    if extra_args_raw is None:
        extra_args = ()
    elif isinstance(extra_args_raw, (list, tuple)) and all(isinstance(entry, str) for entry in extra_args_raw):
        extra_args = tuple(extra_args_raw)
    else:
        raise ConfigError("`execute.extra_args` must be a list of strings")
    phases_arg_raw = payload.get("phases_arg", "load,power")
    if not isinstance(phases_arg_raw, str):
        raise ConfigError(
            f"`execute.phases_arg` must be a string, got {type(phases_arg_raw).__name__}={phases_arg_raw!r}"
        )
    phases_arg = phases_arg_raw
    official = _require_bool(payload, "official", default=False, section="execute")
    streams = _optional_positive_int(payload, "streams", section="execute")
    seed = _optional_int(payload, "seed", section="execute")
    if streams is not None and not official:
        raise ConfigError("`execute.streams` requires `execute.official: true` — see tests.uat.throughput")
    wants_throughput = "throughput" in {phase.strip().lower() for phase in phases_arg.split(",")}
    if official and wants_throughput and streams is None:
        raise ConfigError(
            "`execute.streams` is required when `execute.official: true` and "
            "`execute.phases_arg` includes `throughput` — `run-official` itself "
            "rejects a throughput phase without --streams"
        )
    return ExecuteConfig(
        per_cell_timeout_s=timeout,
        early_stop_after_s=early_after,
        early_stop_on_failure=_require_bool(payload, "early_stop_on_failure", default=True, section="execute"),
        phases_arg=phases_arg,
        compression=payload.get("compression"),
        extra_args=extra_args,
        skip_unreachable=_require_bool(payload, "skip_unreachable", default=True, section="execute"),
        parallel_platforms=parallel_platforms,
        liveness_probe_timeout_s=_require_nonnegative_float(
            payload,
            "liveness_probe_timeout_s",
            default=2.0,
            section="execute",
        ),
        official=official,
        streams=streams,
        seed=seed,
    )


def _optional_positive_int(payload: dict[str, Any], key: str, *, section: str) -> int | None:
    """Coerce payload[key] to a positive int, or None if absent/null."""
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool):
        raise ConfigError(f"`{section}.{key}` must be an int, got bool")
    if isinstance(value, int):
        coerced = value
    elif isinstance(value, str) and value.lstrip("-").isdigit():
        coerced = int(value)
    else:
        raise ConfigError(f"`{section}.{key}` must be an int, got {type(value).__name__}={value!r}")
    if coerced <= 0:
        raise ConfigError(f"`{section}.{key}` must be > 0")
    return coerced


def _optional_int(payload: dict[str, Any], key: str, *, section: str) -> int | None:
    """Coerce payload[key] to an int (any sign), or None if absent/null."""
    if key not in payload or payload[key] is None:
        return None
    value = payload[key]
    if isinstance(value, bool):
        raise ConfigError(f"`{section}.{key}` must be an int, got bool")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.lstrip("-").isdigit():
        return int(value)
    raise ConfigError(f"`{section}.{key}` must be an int, got {type(value).__name__}={value!r}")


def _validate_output(payload: dict[str, Any]) -> OutputConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`output:` must be a mapping")
    template_keys = ("benchmark_runs_dir_template", "logs_dir_template", "submissions_dir_template")
    _reject_unknown_fields(payload, frozenset(template_keys), "output")
    for key in template_keys:
        if key in payload and not isinstance(payload[key], str):
            # Without this, a non-string value (e.g. a YAML mapping) would
            # silently str()-coerce into a nonsense path fragment instead of
            # failing at load time.
            raise ConfigError(f"`output.{key}` must be a string, got {type(payload[key]).__name__}={payload[key]!r}")
    explicitly_set = frozenset(key for key in template_keys if key in payload)
    return OutputConfig(
        benchmark_runs_dir_template=payload.get(
            "benchmark_runs_dir_template",
            "~/Developer/benchmark_runs",
        ),
        logs_dir_template=payload.get(
            "logs_dir_template",
            "~/Developer/benchmark_runs/logs/uat_{date}_{time}",
        ),
        submissions_dir_template=payload.get(
            "submissions_dir_template",
            "~/Developer/benchmark_runs/submissions/{name}",
        ),
        explicitly_set=explicitly_set,
    )


def _validate_preflight(payload: dict[str, Any] | None) -> PreflightConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`preflight:` must be a mapping")
    _reject_unknown_fields(
        payload,
        frozenset(
            {
                "free_space_min_gib",
                "free_space_path",
                "docker_required",
                "noisy_neighbor_warn_load",
                "local_platforms_check",
                "free_memory_min_gib",
                "clickhouse_memory_limit",
                "docker_memory_reserve_gib",
            }
        ),
        "preflight",
    )
    free_space_path = payload.get("free_space_path")
    if free_space_path is not None and not isinstance(free_space_path, str):
        raise ConfigError("`preflight.free_space_path` must be a string")
    return PreflightConfig(
        free_space_min_gib=_require_nonnegative_float(
            payload,
            "free_space_min_gib",
            default=5.0,
            section="preflight",
        ),
        free_space_path=free_space_path,
        docker_required=_require_bool(payload, "docker_required", default=False, section="preflight"),
        noisy_neighbor_warn_load=_require_nonnegative_float(
            payload,
            "noisy_neighbor_warn_load",
            default=8.0,
            section="preflight",
        ),
        local_platforms_check=_require_bool(payload, "local_platforms_check", default=False, section="preflight"),
        free_memory_min_gib=_require_nonnegative_float(
            payload,
            "free_memory_min_gib",
            default=2.0,
            section="preflight",
        ),
        clickhouse_memory_limit=_require_nonempty_string(
            payload,
            "clickhouse_memory_limit",
            default="8g",
            section="preflight",
        ),
        docker_memory_reserve_gib=_require_nonnegative_float(
            payload,
            "docker_memory_reserve_gib",
            default=2.0,
            section="preflight",
        ),
    )


def _validate_cleanup(payload: dict[str, Any] | None) -> CleanupConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`cleanup:` must be a mapping")
    _reject_unknown_fields(
        payload,
        frozenset(
            {
                "preserve_datagen",
                "prune_databases",
                "docker_manage_platforms",
                "docker_platform_switch",
                "docker_project_prefix",
                "docker_start_timeout_s",
                "docker_fixed_container_name_policy",
                "docker_settle_s",
            }
        ),
        "cleanup",
    )

    preserve_datagen = _require_bool(payload, "preserve_datagen", default=True, section="cleanup")
    if not preserve_datagen:
        raise ConfigError("`cleanup.preserve_datagen: false` is not supported by UAT automation")
    docker_manage_platforms = _require_bool(payload, "docker_manage_platforms", default=False, section="cleanup")
    docker_platform_switch = str(payload.get("docker_platform_switch", "off"))
    if docker_platform_switch not in VALID_DOCKER_PLATFORM_SWITCH_MODES:
        raise ConfigError(
            f"Unknown `cleanup.docker_platform_switch` {docker_platform_switch!r}; "
            f"valid: {sorted(VALID_DOCKER_PLATFORM_SWITCH_MODES)}"
        )
    if not docker_manage_platforms and docker_platform_switch != "off":
        raise ConfigError(
            "`cleanup.docker_platform_switch` must be 'off' when "
            "`cleanup.docker_manage_platforms` is false; otherwise cleanup is a no-op or unsafe"
        )

    docker_project_prefix = str(payload.get("docker_project_prefix", "benchbox-uat")).strip()
    if not docker_project_prefix:
        raise ConfigError("`cleanup.docker_project_prefix` must be a non-empty string")
    docker_fixed_container_name_policy = str(payload.get("docker_fixed_container_name_policy", "fail"))
    if docker_fixed_container_name_policy not in VALID_DOCKER_FIXED_CONTAINER_NAME_POLICIES:
        raise ConfigError(
            "Unknown `cleanup.docker_fixed_container_name_policy` "
            f"{docker_fixed_container_name_policy!r}; valid: {sorted(VALID_DOCKER_FIXED_CONTAINER_NAME_POLICIES)}"
        )

    return CleanupConfig(
        preserve_datagen=preserve_datagen,
        prune_databases=_require_bool(payload, "prune_databases", default=True, section="cleanup"),
        docker_manage_platforms=docker_manage_platforms,
        docker_platform_switch=docker_platform_switch,
        docker_project_prefix=docker_project_prefix,
        docker_start_timeout_s=_require_positive_int(
            payload,
            "docker_start_timeout_s",
            default=300,
            section="cleanup",
        ),
        docker_fixed_container_name_policy=docker_fixed_container_name_policy,
        docker_settle_s=_require_positive_int(
            payload,
            "docker_settle_s",
            default=10,
            section="cleanup",
        ),
    )


def _validate_validate(payload: dict[str, Any] | None) -> ValidateConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`validate:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"validator_clean_rate_floor"}), "validate")
    floor = _require_nonnegative_float(
        payload,
        "validator_clean_rate_floor",
        default=0.80,
        section="validate",
    )
    if floor > 1.0:
        raise ConfigError(f"`validate.validator_clean_rate_floor` must be in [0.0, 1.0], got {floor}")
    return ValidateConfig(validator_clean_rate_floor=floor)


def _validate_package(payload: dict[str, Any] | None) -> PackageConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`package:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"submit_terminal_state", "service"}), "package")
    state = payload.get("submit_terminal_state")
    if state is not None and not isinstance(state, str):
        raise ConfigError("`package.submit_terminal_state` must be a string")
    service = payload.get("service")
    if service is not None and not isinstance(service, str):
        raise ConfigError("`package.service` must be a string")
    return PackageConfig(submit_terminal_state=state, service=service)


def _validate_explorer_smoke(payload: dict[str, Any] | None) -> ExplorerSmokeConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`explorer_smoke:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"playwright_browsers"}), "explorer_smoke")
    return ExplorerSmokeConfig(
        playwright_browsers=_as_string_tuple(
            payload.get("playwright_browsers", ["chromium"]),
            section="explorer_smoke",
            key="playwright_browsers",
        )
    )


def _validate_report(payload: dict[str, Any] | None) -> ReportConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`report:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"matrix_summary_tsv", "cross_scale_coverage_min_pairs"}), "report")
    matrix_summary_tsv = payload.get("matrix_summary_tsv", "matrix_summary.tsv")
    if not isinstance(matrix_summary_tsv, str):
        raise ConfigError("`report.matrix_summary_tsv` must be a string")
    floor = payload.get("cross_scale_coverage_min_pairs")
    if floor is not None:
        if isinstance(floor, bool) or not isinstance(floor, int):
            raise ConfigError("`report.cross_scale_coverage_min_pairs` must be an int or null")
        if floor < 0:
            raise ConfigError("`report.cross_scale_coverage_min_pairs` must be >= 0")
    return ReportConfig(matrix_summary_tsv=matrix_summary_tsv, cross_scale_coverage_min_pairs=floor)


def _validate_compatibility(payload: dict[str, Any] | None) -> CompatibilityConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`compatibility:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"release_gate_runtime_envelopes"}), "compatibility")
    return CompatibilityConfig(
        release_gate_runtime_envelopes=_require_bool(
            payload,
            "release_gate_runtime_envelopes",
            default=False,
            section="compatibility",
        )
    )


def load_config(path: str | Path) -> UATConfig:
    """Load and validate a UAT YAML config."""
    import yaml  # late import — keeps W2 import-free of yaml.

    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        payload = yaml.safe_load(fh) or {}
    if not isinstance(payload, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(payload).__name__}")
    return validate_config(payload)


def validate_config(payload: dict[str, Any]) -> UATConfig:
    """Validate an already-parsed YAML mapping. Public for tests."""
    _reject_unknown_fields(payload, ROOT_FIELDS, "root")
    name = payload.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError("`name:` is required and must be a non-empty string")
    phases = _validate_phases(payload.get("phases") or ["preflight", "execute", "report"])
    platforms = _validate_matrix_filter(payload.get("platforms"), section="platforms")
    benchmarks = _validate_matrix_filter(payload.get("benchmarks"), section="benchmarks")
    scales = _validate_scales(payload.get("scales"))
    execute = _validate_execute(payload.get("execute") or {})
    if execute.official:
        from tests.uat.throughput import TPC_ALLOWED_SCALE_FACTORS

        non_compliant = sorted(rung for rung in scales.rungs if rung not in TPC_ALLOWED_SCALE_FACTORS)
        if non_compliant:
            raise ConfigError(
                f"`scales.rungs` {non_compliant} not TPC-compliant for `execute.official: true` "
                f"(run-official requires one of {sorted(TPC_ALLOWED_SCALE_FACTORS)})"
            )
    output = _validate_output(payload.get("output") or {})
    preflight = _validate_preflight(payload.get("preflight"))
    cleanup = _validate_cleanup(payload.get("cleanup"))
    validate = _validate_validate(payload.get("validate"))
    package = _validate_package(payload.get("package"))
    if "package" in phases:
        # These three checks mirror tests/uat/phases/package.py's
        # `_resolve_state`/`_resolve_service` runtime guard (package.py:55-68)
        # -- moved here so a bad `package:` section is a load-time
        # ConfigError instead of an execute-time PackagePhaseError, but only
        # once the `package` phase is actually enabled. A `package:` section
        # left stale while the phase is not in `phases:` is inert (matches
        # the framework's existing "unused-field is a warning, not an
        # error" leniency for e.g. `preflight.free_space_min_gib` when
        # `preflight` is absent from `phases:`).
        if package.submit_terminal_state is None:
            raise ConfigError("`package.submit_terminal_state` is required when the `package` phase is enabled")
        if package.submit_terminal_state not in VALID_TERMINAL_STATES:
            raise ConfigError(
                f"`package.submit_terminal_state` {package.submit_terminal_state!r} not in "
                f"{sorted(VALID_TERMINAL_STATES)}"
            )
        if package.submit_terminal_state == "cloud-uploaded" and not package.service:
            raise ConfigError("`package.submit_terminal_state: cloud-uploaded` requires `package.service`")
    explorer_smoke = _validate_explorer_smoke(payload.get("explorer_smoke"))
    report = _validate_report(payload.get("report"))
    compatibility = _validate_compatibility(payload.get("compatibility"))
    return UATConfig(
        name=name,
        description=str(payload.get("description", "")),
        phases=phases,
        dry_run=_require_bool(payload, "dry_run", default=False, section="root"),
        platforms=platforms,
        benchmarks=benchmarks,
        scales=scales,
        execute=execute,
        output=output,
        preflight=preflight,
        cleanup=cleanup,
        validate=validate,
        package=package,
        explorer_smoke=explorer_smoke,
        report=report,
        compatibility=compatibility,
    )
