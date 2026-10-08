from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable


class BenchmarkOptionError(ValueError):
    pass


def _identity(value: str) -> Any:
    return value


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise BenchmarkOptionError(f"Invalid boolean value '{value}'")


def parse_int(value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise BenchmarkOptionError(f"Invalid integer value '{value}'") from None


def parse_int_list(value: str) -> list[int]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise BenchmarkOptionError(f"Empty list value '{value}'")
    try:
        return [int(p) for p in parts]
    except ValueError:
        raise BenchmarkOptionError(f"Invalid integer list '{value}' - expected comma-separated integers") from None


def parse_str_list(value: str) -> list[str]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    if not parts:
        raise BenchmarkOptionError(f"Empty list value '{value}'")
    return parts


def parse_enum_list(enum_cls: type[Enum]) -> Callable[[str], list[Enum]]:
    valid_values = {member.value: member for member in enum_cls}

    def _parser(value: str) -> list[Enum]:
        parts = [p.strip().lower() for p in value.split(",") if p.strip()]
        if not parts:
            raise BenchmarkOptionError(f"Empty list value '{value}'")
        result = []
        for part in parts:
            if part not in valid_values:
                allowed = ", ".join(sorted(valid_values.keys()))
                raise BenchmarkOptionError(f"Invalid value '{part}' for {enum_cls.__name__}. Allowed: {allowed}")
            result.append(valid_values[part])
        return result

    return _parser


def parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.strip())
    except ValueError:
        raise BenchmarkOptionError(
            f"Invalid datetime '{value}' - expected ISO format (e.g. 2019-02-01T00:00:00)"
        ) from None


@dataclass(frozen=True)
class BenchmarkOptionSpec:
    name: str
    parser: Callable[[str], Any] = _identity
    default: Any = None
    help: str = ""
    choices: Iterable[Any] | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def parse(self, raw: str) -> Any:
        value = self.parser(raw)
        if self.choices:
            candidates = value if isinstance(value, list) else [value]
            for candidate in candidates:
                if candidate not in self.choices:
                    allowed = ", ".join(sorted(str(choice) for choice in self.choices))
                    raise BenchmarkOptionError(
                        f"Invalid value '{candidate}' for option '{self.name}'. Allowed values: {allowed}"
                    )
        return value


class BenchmarkHookRegistry:
    _option_specs: dict[str, dict[str, BenchmarkOptionSpec]] = {}
    _alias_index: dict[str, dict[str, str]] = {}
    _validated_benchmarks: set[str] = set()

    @classmethod
    def register_option_specs(
        cls,
        benchmark: str,
        *specs: BenchmarkOptionSpec,
        benchmark_class: type[Any] | None = None,
    ) -> None:
        benchmark = benchmark.lower()
        option_map = cls._option_specs.setdefault(benchmark, {})
        alias_map = cls._alias_index.setdefault(benchmark, {})

        if benchmark_class is not None:
            cls._validate_specs_against_constructor(benchmark, specs, benchmark_class)
            cls._validated_benchmarks.add(benchmark)

        for spec in specs:
            name = spec.name.lower()
            if name in option_map:
                continue
            option_map[name] = spec

            for alias in spec.aliases:
                key = alias.lower()
                if key in alias_map:
                    raise BenchmarkOptionError(
                        f"Alias '{alias}' already used for option '{alias_map[key]}' on benchmark '{benchmark}'"
                    )
                alias_map[key] = name

    @staticmethod
    def _validate_specs_against_constructor(
        benchmark: str,
        specs: tuple[BenchmarkOptionSpec, ...],
        benchmark_class: type[Any],
    ) -> None:
        try:
            parameters = inspect.signature(benchmark_class).parameters
        except (TypeError, ValueError) as exc:
            raise BenchmarkOptionError(
                f"Cannot validate benchmark options for benchmark '{benchmark}': "
                f"constructor signature of {benchmark_class.__name__} is unavailable. "
                f"Declare an inspectable constructor instead of relying on "
                f"unverifiable option forwarding."
            ) from exc
        explicit = {
            name
            for name, parameter in parameters.items()
            if parameter.kind
            in (
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            )
        }
        for spec in specs:
            if spec.name.lower() not in explicit:
                raise BenchmarkOptionError(
                    f"Benchmark option '{spec.name}' for benchmark '{benchmark}' "
                    f"does not match any constructor parameter of "
                    f"{benchmark_class.__name__}. Add an explicit constructor "
                    f"parameter - a bare **kwargs must not silently swallow "
                    f"misrouted options."
                )

    @classmethod
    def list_option_specs(cls, benchmark: str) -> dict[str, BenchmarkOptionSpec]:
        return cls._option_specs.get(benchmark.lower(), {}).copy()

    @classmethod
    def get_default_options(cls, benchmark: str) -> dict[str, Any]:
        specs = cls._option_specs.get(benchmark.lower(), {})
        defaults: dict[str, Any] = {}
        for name, spec in specs.items():
            defaults[name] = spec.default
        return defaults

    @classmethod
    def parse_options(cls, benchmark: str, provided: Iterable[tuple[str, str]]) -> dict[str, Any]:
        benchmark = benchmark.lower()
        specs = cls._option_specs.get(benchmark, {})
        provided = list(provided)
        if not specs and provided:
            raise BenchmarkOptionError(f"Benchmark '{benchmark}' does not accept benchmark-specific options")

        resolved: dict[str, Any] = {}
        for key, raw in provided:
            canonical = cls._resolve_option_name(benchmark, key)
            if canonical not in specs:
                available = sorted(specs.keys())
                options_str = ", ".join(available) if available else "(none)"
                raise BenchmarkOptionError(
                    f"Unknown benchmark option '{key}' for benchmark '{benchmark}'. Available: {options_str}"
                )
            if canonical in resolved:
                raise BenchmarkOptionError(f"Duplicate benchmark option '{canonical}' provided")
            spec = specs[canonical]
            resolved[canonical] = spec.parse(raw)

        return resolved

    @classmethod
    def describe_options(cls, benchmark: str) -> list[str]:
        specs = cls._option_specs.get(benchmark.lower(), {})
        lines: list[str] = []
        for name, spec in sorted(specs.items()):
            aliases = f" (aliases: {', '.join(spec.aliases)})" if spec.aliases else ""
            default = f" [default: {spec.default}]" if spec.default is not None else ""
            lines.append(f"{name}{aliases}{default} - {spec.help or 'No description provided'}")
        return lines

    @classmethod
    def has_specs(cls, benchmark: str) -> bool:
        return bool(cls._option_specs.get(benchmark.lower()))

    @classmethod
    def _resolve_option_name(cls, benchmark: str, option: str) -> str:
        option = option.lower()
        specs = cls._option_specs.get(benchmark, {})
        if option in specs:
            return option
        alias_map = cls._alias_index.get(benchmark, {})
        if option in alias_map:
            return alias_map[option]
        return option


__all__ = [
    "BenchmarkHookRegistry",
    "BenchmarkOptionError",
    "BenchmarkOptionSpec",
    "parse_bool",
    "parse_datetime",
    "parse_enum_list",
    "parse_int",
    "parse_int_list",
    "parse_str_list",
]
