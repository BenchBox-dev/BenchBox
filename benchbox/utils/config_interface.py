"""Lightweight configuration interface for core utilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional


class ConfigInterface(ABC):
    """Abstract interface for configuration providers."""

    @abstractmethod
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key."""

    @abstractmethod
    def set(self, key: str, value: Any) -> None:
        """Set configuration value by key."""


class SimpleConfigProvider(ConfigInterface):
    """Simple in-memory configuration provider with defaults."""

    def __init__(self, defaults: Optional[dict] = None):
        """Initialize with optional default values."""
        self._config = defaults.copy() if defaults else {}
        self._setup_defaults()

    def _setup_defaults(self):
        """Set up default configuration values."""
        default_config = {
            # Power run defaults
            "execution.power_run.iterations": 4,
            "execution.power_run.warm_up_iterations": 0,
            "execution.power_run.timeout_per_iteration_minutes": 60,
            "execution.power_run.concurrent_streams": 1,
            # Throughput test defaults
            "execution.throughput_test.duration_minutes": 60,
            "execution.throughput_test.concurrent_streams": 4,
            "execution.throughput_test.warm_up_minutes": 5,
            # General execution defaults
            "execution.timeout_minutes": 120,
            "execution.memory_limit_gb": 8,
            "execution.enable_profiling": False,
        }

        # Only set defaults that aren't already configured
        for key, value in default_config.items():
            if key not in self._config:
                self._config[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set configuration value by key."""
        self._config[key] = value

    def update(self, config_dict: dict) -> None:
        """Update configuration with dictionary values."""
        self._config.update(config_dict)


def get_default_config_provider() -> ConfigInterface:
    """Get default configuration provider."""
    return SimpleConfigProvider()


# Registered by whichever layer owns user configuration. utils sits at the
# bottom of the layering contract (utils < core < platforms < cli), so it must
# not reach up for a richer provider -- the richer layer pushes one down. This
# module previously imported benchbox.cli.config directly, which is the
# violation .importlinter carried as an ignore entry.
_config_provider: ConfigInterface | None = None


def set_config_provider(provider: ConfigInterface | None) -> None:
    """Register the process-wide configuration provider.

    Called by the CLI during startup to make its ConfigManager the source for
    utils-level consumers. Passing None restores the built-in defaults, which
    is what test teardown wants.
    """
    global _config_provider
    _config_provider = provider


def get_config_provider() -> ConfigInterface:
    """Return the registered provider, or the built-in defaults.

    Falling back rather than raising keeps library and MCP callers working
    without a CLI: they get SimpleConfigProvider's documented defaults.
    """
    return _config_provider if _config_provider is not None else get_default_config_provider()
