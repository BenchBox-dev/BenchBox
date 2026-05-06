"""YAML config schema for the UAT framework.

The schema is the source of truth for what a UAT config can express.
See `_project/specs/uat-framework.md` Section 3.

W3 introduces only the minimal fields the single-cell runner needs;
W4 expands schema coverage to the remaining sections (matrix filters,
ladder rules, cleanup, validate, package, explorer_smoke, report).
This split mirrors the spec's W2/W3/W4 staging.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

VALID_PHASES: tuple[str, ...] = (
    "preflight",
    "enumerate",
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


@dataclass(frozen=True)
class OutputConfig:
    benchmark_runs_dir_template: str = "~/Developer/benchmark_runs"
    logs_dir_template: str = "~/Developer/benchmark_runs/logs/uat_{date}"
    submissions_dir_template: str = "~/Developer/benchmark_runs/submissions/{name}"


@dataclass(frozen=True)
class UATConfig:
    """Root config object.

    Only fields needed by the W3 runner are required; W4 adds the rest
    (matrix filters, ladder, cleanup, validate, package, explorer_smoke,
    report). Defaults match the spec.
    """

    name: str
    description: str = ""
    phases: tuple[str, ...] = ("preflight", "enumerate", "execute", "report")
    dry_run: bool = False
    execute: ExecuteConfig = field(default_factory=ExecuteConfig)
    output: OutputConfig = field(default_factory=OutputConfig)
    # Raw YAML preserved so W4 can layer additional sections without
    # losing the source data.
    raw: dict[str, Any] = field(default_factory=dict)


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


def _require_positive_int(raw: dict[str, Any], key: str, *, default: int) -> int:
    """Coerce raw[key] to int. Reject floats and non-numeric strings."""
    value = raw.get(key, default)
    if isinstance(value, bool):
        raise ConfigError(f"`execute.{key}` must be an int, got bool")
    if isinstance(value, int):
        coerced = value
    elif isinstance(value, str) and value.lstrip("-").isdigit():
        coerced = int(value)
    else:
        raise ConfigError(f"`execute.{key}` must be an int, got {type(value).__name__}={value!r}")
    if coerced <= 0:
        raise ConfigError(f"`execute.{key}` must be > 0")
    return coerced


def _validate_execute(raw: dict[str, Any]) -> ExecuteConfig:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("`execute:` must be a mapping")
    if raw.get("parallel_platforms") is True:
        raise ConfigError(
            "`execute.parallel_platforms: true` is forbidden — UAT W3 line 222: "
            "concurrent platform runs contaminate timings"
        )
    timeout = _require_positive_int(raw, "per_cell_timeout_s", default=600)
    early_after = _require_positive_int(raw, "early_stop_after_s", default=180)
    extra_args_raw = raw.get("extra_args", ())
    if extra_args_raw is None:
        extra_args = ()
    elif isinstance(extra_args_raw, (list, tuple)) and all(isinstance(entry, str) for entry in extra_args_raw):
        extra_args = tuple(extra_args_raw)
    else:
        raise ConfigError("`execute.extra_args` must be a list of strings")
    return ExecuteConfig(
        per_cell_timeout_s=timeout,
        early_stop_after_s=early_after,
        early_stop_on_failure=bool(raw.get("early_stop_on_failure", True)),
        phases_arg=str(raw.get("phases_arg", "load,power")),
        compression=raw.get("compression"),
        extra_args=extra_args,
        skip_unreachable=bool(raw.get("skip_unreachable", True)),
        parallel_platforms=False,
    )


def _validate_output(raw: dict[str, Any]) -> OutputConfig:
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigError("`output:` must be a mapping")
    return OutputConfig(
        benchmark_runs_dir_template=str(
            raw.get(
                "benchmark_runs_dir_template",
                "~/Developer/benchmark_runs",
            )
        ),
        logs_dir_template=str(
            raw.get(
                "logs_dir_template",
                "~/Developer/benchmark_runs/logs/uat_{date}",
            )
        ),
        submissions_dir_template=str(
            raw.get(
                "submissions_dir_template",
                "~/Developer/benchmark_runs/submissions/{name}",
            )
        ),
    )


def load_config(path: str | Path) -> UATConfig:
    """Load and validate a UAT YAML config.

    Validates the W3-relevant subset (identity, phases, execute, output).
    W4 will extend this validator to cover platforms/benchmarks/scales/
    cleanup/validate/package/explorer_smoke/report.
    """
    import yaml  # late import — keeps W2 import-free of yaml.

    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file not found: {p}")
    with p.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping, got {type(raw).__name__}")
    return validate_config(raw)


def validate_config(raw: dict[str, Any]) -> UATConfig:
    """Validate an already-parsed YAML mapping. Public for tests."""
    name = raw.get("name")
    if not name or not isinstance(name, str):
        raise ConfigError("`name:` is required and must be a non-empty string")
    phases = _validate_phases(raw.get("phases") or ["preflight", "enumerate", "execute", "report"])
    execute = _validate_execute(raw.get("execute") or {})
    output = _validate_output(raw.get("output") or {})
    return UATConfig(
        name=name,
        description=str(raw.get("description", "")),
        phases=phases,
        dry_run=bool(raw.get("dry_run", False)),
        execute=execute,
        output=output,
        raw=raw,
    )


def apply_stress_overrides(
    config: UATConfig,
    *,
    platform: str | None = None,
    benchmark: str | None = None,
    scale: float | None = None,
) -> UATConfig:
    """Apply the closed env-var override set documented in the spec (Section 4).

    Only PLATFORM, BENCHMARK, SCALE are recognised. The override mutates
    `raw` (which W4's matrix filters will read) and clears any conflicting
    YAML defaults. Returns a new `UATConfig`; the input is unchanged.
    """
    new_raw = dict(config.raw)
    if platform is not None:
        platforms = dict(new_raw.get("platforms") or {})
        platforms["groups"] = []
        platforms["include"] = [platform]
        new_raw["platforms"] = platforms
    if benchmark is not None:
        benchmarks = dict(new_raw.get("benchmarks") or {})
        benchmarks["groups"] = []
        benchmarks["include"] = [benchmark]
        new_raw["benchmarks"] = benchmarks
    if scale is not None:
        scales = dict(new_raw.get("scales") or {})
        scales.pop("rungs", None)
        scales["override"] = float(scale)
        new_raw["scales"] = scales
    return replace(config, raw=new_raw)
