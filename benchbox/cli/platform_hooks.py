"""Platform-specific CLI option and configuration registry.

Provides a lightweight extension mechanism for platform adapters to expose
command-line hooks without requiring changes to the core CLI implementation.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any, Callable

from benchbox.core.platform_registry import PlatformInfo, PlatformRegistry
from benchbox.core.schemas import DatabaseConfig


class PlatformOptionError(ValueError):
    """Raised when parsing or registering platform options fails."""


def _identity(value: str) -> Any:
    return value


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise PlatformOptionError(f"Invalid boolean value '{value}'")


@dataclass(frozen=True)
class PlatformOptionSpec:
    """Describe a platform-specific CLI option."""

    name: str
    parser: Callable[[str], Any] = _identity
    default: Any = None
    help: str = ""
    choices: Iterable[Any] | None = None
    aliases: tuple[str, ...] = field(default_factory=tuple)

    def parse(self, raw: str) -> Any:
        value = self.parser(raw)
        if self.choices and value not in self.choices:
            allowed = ", ".join(sorted(str(choice) for choice in self.choices))
            raise PlatformOptionError(f"Invalid value '{value}' for option '{self.name}'. Allowed values: {allowed}")
        return value


class PlatformHookRegistry:
    """Registry for CLI platform hooks (options and database config builders)."""

    _option_specs: dict[str, dict[str, PlatformOptionSpec]] = {}
    _alias_index: dict[str, dict[str, str]] = {}
    _config_builders: dict[
        str,
        Callable[[str, dict[str, Any], dict[str, Any], PlatformInfo | None], DatabaseConfig],
    ] = {}

    @classmethod
    def register_option_specs(cls, platform: str, *specs: PlatformOptionSpec) -> None:
        """Register option specifications for a platform.

        Args:
            platform: Platform identifier (e.g., "clickhouse")
            specs: Option specifications to register
        """
        platform = platform.lower()
        option_map = cls._option_specs.setdefault(platform, {})
        alias_map = cls._alias_index.setdefault(platform, {})

        for spec in specs:
            name = spec.name.lower()
            if name in option_map:
                # Allow re-registration - just skip silently
                # This handles cases where modules are re-imported during complex import chains
                # or pytest collection. The first registration wins.
                continue
            option_map[name] = spec

            for alias in spec.aliases:
                key = alias.lower()
                if key in alias_map:
                    raise PlatformOptionError(
                        f"Alias '{alias}' already used for option '{alias_map[key]}' on platform '{platform}'"
                    )
                alias_map[key] = name

    @classmethod
    def list_option_specs(cls, platform: str) -> dict[str, PlatformOptionSpec]:
        return cls._option_specs.get(platform.lower(), {}).copy()

    @classmethod
    def get_default_options(cls, platform: str) -> dict[str, Any]:
        specs = cls._option_specs.get(platform.lower(), {})
        defaults: dict[str, Any] = {}
        for name, spec in specs.items():
            defaults[name] = spec.default
        return defaults

    @classmethod
    def parse_options(cls, platform: str, provided: Iterable[tuple[str, str]]) -> dict[str, Any]:
        platform = platform.lower()
        specs = cls._option_specs.get(platform, {})
        if not specs and any(True for _ in provided):
            raise PlatformOptionError(f"Platform '{platform}' does not accept platform-specific options")

        resolved: dict[str, Any] = {}
        for key, raw in provided:
            canonical = cls._resolve_option_name(platform, key)
            if canonical not in specs:
                available = sorted(specs.keys())
                options_str = ", ".join(available) if available else "(none)"
                raise PlatformOptionError(
                    f"Unknown platform option '{key}' for platform '{platform}'. Available: {options_str}"
                )
            if canonical in resolved:
                raise PlatformOptionError(f"Duplicate platform option '{canonical}' provided")
            spec = specs[canonical]
            resolved[canonical] = spec.parse(raw)

        defaults = cls.get_default_options(platform)
        defaults.update(resolved)
        return {name: value for name, value in defaults.items() if value is not None}

    @classmethod
    def describe_options(cls, platform: str) -> list[str]:
        specs = cls._option_specs.get(platform.lower(), {})
        lines: list[str] = []
        for name, spec in sorted(specs.items()):
            aliases = f" (aliases: {', '.join(spec.aliases)})" if spec.aliases else ""
            default = f" [default: {spec.default}]" if spec.default is not None else ""
            lines.append(f"{name}{aliases}{default} - {spec.help or 'No description provided'}")
        return lines

    @classmethod
    def register_config_builder(
        cls,
        platform: str,
        builder: Callable[[str, dict[str, Any], dict[str, Any], PlatformInfo | None], DatabaseConfig],
    ) -> None:
        cls._config_builders[platform.lower()] = builder

    @classmethod
    def build_database_config(
        cls,
        platform: str,
        options: dict[str, Any],
        runtime_overrides: dict[str, Any] | None = None,
    ) -> DatabaseConfig:
        platform = platform.lower()
        overrides = runtime_overrides or {}
        info = PlatformRegistry.get_platform_info(platform)

        custom_builder = cls._config_builders.get(platform)
        builder = custom_builder or cls._default_builder
        config = builder(platform, options, overrides, info)

        # Custom builders already return merged options that preserve the
        # saved-creds contract; only the default builder needs this backfill.
        if custom_builder is None:
            config.options.update(options)
        config.options.update(overrides)

        return config

    @classmethod
    def _default_builder(
        cls,
        platform: str,
        options: dict[str, Any],
        overrides: dict[str, Any],
        info: PlatformInfo | None,
    ) -> DatabaseConfig:
        name = info.display_name if info else platform.title()
        driver_package = info.driver_package if info else None
        driver_version = overrides.get("driver_version") or options.get("driver_version")
        auto_install = overrides.get("driver_auto_install")
        if auto_install is None:
            auto_install = options.get("driver_auto_install", False)
        # Extract execution_mode from overrides for --mode flag support
        execution_mode = overrides.get("execution_mode") or options.get("execution_mode")
        return DatabaseConfig(
            type=platform,
            name=name,
            options={},
            driver_package=driver_package,
            driver_version=driver_version,
            driver_auto_install=bool(auto_install),
            execution_mode=execution_mode,
        )

    @classmethod
    def _resolve_option_name(cls, platform: str, option: str) -> str:
        option = option.lower()
        specs = cls._option_specs.get(platform, {})
        if option in specs:
            return option
        alias_map = cls._alias_index.get(platform, {})
        if option in alias_map:
            return alias_map[option]
        return option


__all__ = [
    "PlatformHookRegistry",
    "PlatformOptionError",
    "PlatformOptionSpec",
]
