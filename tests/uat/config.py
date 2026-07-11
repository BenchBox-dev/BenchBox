"""YAML config schema for the UAT framework."""

from __future__ import annotations

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


@dataclass(frozen=True)
class PreflightConfig:
    free_space_min_gib: float = 5.0
    free_space_path: str | None = None
    docker_required: bool = False
    noisy_neighbor_warn_load: float = 8.0
    local_platforms_check: bool = False


@dataclass(frozen=True)
class CleanupConfig:
    preserve_datagen: bool = True
    prune_databases: bool = True
    docker_manage_platforms: bool = False
    docker_platform_switch: str = "off"
    docker_project_prefix: str = "benchbox-uat"
    docker_start_timeout_s: int = 300
    docker_fixed_container_name_policy: str = "fail"


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
        uat-disk-gate-always-on). The sole opt-out is an explicit
        `preflight.free_space_min_gib: 0`, which callers must pair with a
        loud warning (`disk_gate_disabled_warning`) since it turns the gate
        off entirely.
        """
        return self.preflight.free_space_min_gib > 0


DISK_GATE_DISABLED_WARNING_PREFIX = "[disk-gate] DISABLED by config"


def disk_gate_disabled_warning(config: UATConfig) -> str | None:
    """Return the loud opt-out warning when `disk_gate_enabled` is False."""
    if config.disk_gate_enabled:
        return None
    return (
        f"{DISK_GATE_DISABLED_WARNING_PREFIX}: preflight.free_space_min_gib=0 -- "
        "the free-space floor and per-cell disk watch will NOT run for this sweep"
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
    if coerced < 0:
        raise ConfigError(f"`{section}.{key}` must be >= 0")
    return coerced


def _require_bool(payload: dict[str, Any], key: str, *, default: bool, section: str) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise ConfigError(f"`{section}.{key}` must be a bool, got {type(value).__name__}={value!r}")
    return value


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
    rungs_raw = payload.get("rungs", [0.01])
    if isinstance(rungs_raw, (str, bytes)) or not isinstance(rungs_raw, (list, tuple)):
        raise ConfigError("`scales.rungs` must be a list of numbers")
    try:
        rungs = tuple(float(value) for value in rungs_raw)
    except (TypeError, ValueError) as exc:
        raise ConfigError("`scales.rungs` must be a list of numbers") from exc
    if not rungs:
        raise ConfigError("`scales.rungs` must be non-empty")
    override = payload.get("override")
    try:
        override_value = float(override) if override is not None else None
    except (TypeError, ValueError) as exc:
        raise ConfigError("`scales.override` must be a number") from exc
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
    phases_arg = str(payload.get("phases_arg", "load,power"))
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
    _reject_unknown_fields(
        payload,
        frozenset({"benchmark_runs_dir_template", "logs_dir_template", "submissions_dir_template"}),
        "output",
    )
    return OutputConfig(
        benchmark_runs_dir_template=str(
            payload.get(
                "benchmark_runs_dir_template",
                "~/Developer/benchmark_runs",
            )
        ),
        logs_dir_template=str(
            payload.get(
                "logs_dir_template",
                "~/Developer/benchmark_runs/logs/uat_{date}_{time}",
            )
        ),
        submissions_dir_template=str(
            payload.get(
                "submissions_dir_template",
                "~/Developer/benchmark_runs/submissions/{name}",
            )
        ),
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
    )


def _validate_validate(payload: dict[str, Any] | None) -> ValidateConfig:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ConfigError("`validate:` must be a mapping")
    _reject_unknown_fields(payload, frozenset({"validator_clean_rate_floor"}), "validate")
    return ValidateConfig(
        validator_clean_rate_floor=_require_nonnegative_float(
            payload,
            "validator_clean_rate_floor",
            default=0.80,
            section="validate",
        )
    )


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
