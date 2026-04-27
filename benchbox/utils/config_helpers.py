"""Configuration Helper Utilities for BenchBox.

This module provides helper functions and classes for working with BenchBox
configuration settings, especially for power run and concurrent query features.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union

# Import handled locally to avoid circular imports


@dataclass
class PowerRunSettings:
    """Power run configuration settings."""

    iterations: int
    warm_up_iterations: int
    timeout_per_iteration_minutes: int
    fail_fast: bool
    collect_metrics: bool

    @classmethod
    def from_config_manager(cls, config_manager: Any) -> "PowerRunSettings":
        """Create settings from config manager."""
        return cls(
            iterations=config_manager.get("execution.power_run.iterations", 4),
            warm_up_iterations=config_manager.get("execution.power_run.warm_up_iterations", 0),
            timeout_per_iteration_minutes=config_manager.get("execution.power_run.timeout_per_iteration_minutes", 60),
            fail_fast=config_manager.get("execution.power_run.fail_fast", False),
            collect_metrics=config_manager.get("execution.power_run.collect_metrics", True),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "iterations": self.iterations,
            "warm_up_iterations": self.warm_up_iterations,
            "timeout_per_iteration_minutes": self.timeout_per_iteration_minutes,
            "fail_fast": self.fail_fast,
            "collect_metrics": self.collect_metrics,
        }

    def apply_to_config_manager(self, config_manager: Any) -> None:
        """Apply settings to config manager."""
        config_manager.set("execution.power_run.iterations", self.iterations)
        config_manager.set("execution.power_run.warm_up_iterations", self.warm_up_iterations)
        config_manager.set(
            "execution.power_run.timeout_per_iteration_minutes",
            self.timeout_per_iteration_minutes,
        )
        config_manager.set("execution.power_run.fail_fast", self.fail_fast)
        config_manager.set("execution.power_run.collect_metrics", self.collect_metrics)


@dataclass
class ConcurrentQueriesSettings:
    """Concurrent queries configuration settings."""

    enabled: bool
    max_concurrent: int
    query_timeout_seconds: int
    stream_timeout_seconds: int
    retry_failed_queries: bool
    max_retries: int

    @classmethod
    def from_config_manager(cls, config_manager: Any) -> "ConcurrentQueriesSettings":
        """Create settings from config manager."""
        return cls(
            enabled=config_manager.get("execution.concurrent_queries.enabled", False),
            max_concurrent=config_manager.get("execution.concurrent_queries.max_concurrent", 2),
            query_timeout_seconds=config_manager.get("execution.concurrent_queries.query_timeout_seconds", 300),
            stream_timeout_seconds=config_manager.get("execution.concurrent_queries.stream_timeout_seconds", 3600),
            retry_failed_queries=config_manager.get("execution.concurrent_queries.retry_failed_queries", True),
            max_retries=config_manager.get("execution.concurrent_queries.max_retries", 3),
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "enabled": self.enabled,
            "max_concurrent": self.max_concurrent,
            "query_timeout_seconds": self.query_timeout_seconds,
            "stream_timeout_seconds": self.stream_timeout_seconds,
            "retry_failed_queries": self.retry_failed_queries,
            "max_retries": self.max_retries,
        }

    def apply_to_config_manager(self, config_manager: Any) -> None:
        """Apply settings to config manager."""
        config_manager.set("execution.concurrent_queries.enabled", self.enabled)
        config_manager.set("execution.concurrent_queries.max_concurrent", self.max_concurrent)
        config_manager.set(
            "execution.concurrent_queries.query_timeout_seconds",
            self.query_timeout_seconds,
        )
        config_manager.set(
            "execution.concurrent_queries.stream_timeout_seconds",
            self.stream_timeout_seconds,
        )
        config_manager.set(
            "execution.concurrent_queries.retry_failed_queries",
            self.retry_failed_queries,
        )
        config_manager.set("execution.concurrent_queries.max_retries", self.max_retries)


class ExecutionConfigHelper:
    """Helper class for execution configuration management."""

    def __init__(self, config_manager: Optional[Any] = None):
        """Initialize with optional config manager."""
        if config_manager is None:
            from benchbox.utils.config_interface import create_cli_config_adapter

            self.config_manager = create_cli_config_adapter()
        else:
            self.config_manager = config_manager

    def get_power_run_settings(self) -> PowerRunSettings:
        """Get current power run settings."""
        return PowerRunSettings.from_config_manager(self.config_manager)

    def get_concurrent_queries_settings(self) -> ConcurrentQueriesSettings:
        """Get current concurrent queries settings."""
        return ConcurrentQueriesSettings.from_config_manager(self.config_manager)

    def update_power_run_settings(self, settings: PowerRunSettings) -> None:
        """Update power run settings."""
        settings.apply_to_config_manager(self.config_manager)

    def update_concurrent_queries_settings(self, settings: ConcurrentQueriesSettings) -> None:
        """Update concurrent queries settings."""
        settings.apply_to_config_manager(self.config_manager)

    def enable_power_run_iterations(self, iterations: int = 3, warm_up_iterations: int = 1) -> None:
        """Enable power run iterations with specified counts."""
        settings = self.get_power_run_settings()
        settings.iterations = iterations
        settings.warm_up_iterations = warm_up_iterations
        self.update_power_run_settings(settings)

    def enable_concurrent_queries(self, max_concurrent: int = 2) -> None:
        """Enable concurrent queries with specified concurrency."""
        settings = self.get_concurrent_queries_settings()
        settings.enabled = True
        settings.max_concurrent = max_concurrent
        self.update_concurrent_queries_settings(settings)

    def disable_concurrent_queries(self) -> None:
        """Disable concurrent queries."""
        settings = self.get_concurrent_queries_settings()
        settings.enabled = False
        self.update_concurrent_queries_settings(settings)

    def optimize_for_system(self, cpu_cores: int, memory_gb: float) -> None:
        """Optimize execution settings based on system resources.

        Args:
            cpu_cores: Number of CPU cores available
            memory_gb: Amount of memory available in GB
        """
        # Optimize power run settings based on memory
        power_settings = self.get_power_run_settings()
        if memory_gb < 8:
            # Low memory systems - use longer timeouts
            power_settings.timeout_per_iteration_minutes = 120
        elif memory_gb > 16:
            # High memory systems - use shorter timeouts
            power_settings.timeout_per_iteration_minutes = 45

        # Optimize concurrent query settings based on CPU cores
        concurrent_settings = self.get_concurrent_queries_settings()
        concurrent_settings.max_concurrent = min(8, max(2, cpu_cores // 4))

        # Adjust timeouts based on available resources
        if memory_gb < 8:
            concurrent_settings.query_timeout_seconds = 600
            concurrent_settings.stream_timeout_seconds = 7200
        elif memory_gb > 16:
            concurrent_settings.query_timeout_seconds = 180
            concurrent_settings.stream_timeout_seconds = 1800

        self.update_power_run_settings(power_settings)
        self.update_concurrent_queries_settings(concurrent_settings)

    def create_performance_profile(self, profile_name: str) -> dict[str, Any]:
        """Create a performance testing profile.

        Args:
            profile_name: Name of the performance profile

        Returns:
            Dictionary containing the performance profile configuration
        """
        profiles = {
            "quick": {
                "power_run": PowerRunSettings(
                    iterations=1,
                    warm_up_iterations=0,
                    timeout_per_iteration_minutes=30,
                    fail_fast=True,
                    collect_metrics=True,
                ),
                "concurrent_queries": ConcurrentQueriesSettings(
                    enabled=False,
                    max_concurrent=2,
                    query_timeout_seconds=180,
                    stream_timeout_seconds=1800,
                    retry_failed_queries=False,
                    max_retries=1,
                ),
            },
            "standard": {
                "power_run": PowerRunSettings(
                    iterations=3,
                    warm_up_iterations=1,
                    timeout_per_iteration_minutes=60,
                    fail_fast=False,
                    collect_metrics=True,
                ),
                "concurrent_queries": ConcurrentQueriesSettings(
                    enabled=True,
                    max_concurrent=2,
                    query_timeout_seconds=300,
                    stream_timeout_seconds=3600,
                    retry_failed_queries=True,
                    max_retries=3,
                ),
            },
            "thorough": {
                "power_run": PowerRunSettings(
                    iterations=5,
                    warm_up_iterations=2,
                    timeout_per_iteration_minutes=120,
                    fail_fast=False,
                    collect_metrics=True,
                ),
                "concurrent_queries": ConcurrentQueriesSettings(
                    enabled=True,
                    max_concurrent=4,
                    query_timeout_seconds=600,
                    stream_timeout_seconds=7200,
                    retry_failed_queries=True,
                    max_retries=5,
                ),
            },
            "stress": {
                "power_run": PowerRunSettings(
                    iterations=10,
                    warm_up_iterations=3,
                    timeout_per_iteration_minutes=180,
                    fail_fast=False,
                    collect_metrics=True,
                ),
                "concurrent_queries": ConcurrentQueriesSettings(
                    enabled=True,
                    max_concurrent=8,
                    query_timeout_seconds=900,
                    stream_timeout_seconds=10800,
                    retry_failed_queries=True,
                    max_retries=10,
                ),
            },
        }

        if profile_name not in profiles:
            raise ValueError(f"Unknown performance profile: {profile_name}. Available: {list(profiles.keys())}")

        profile = profiles[profile_name]
        return {
            "name": profile_name,
            "power_run": profile["power_run"].to_dict(),
            "concurrent_queries": profile["concurrent_queries"].to_dict(),
        }

    def apply_performance_profile(self, profile_name: str) -> None:
        """Apply a performance testing profile.

        Args:
            profile_name: Name of the performance profile to apply
        """
        profile = self.create_performance_profile(profile_name)

        power_settings = PowerRunSettings(**profile["power_run"])
        concurrent_settings = ConcurrentQueriesSettings(**profile["concurrent_queries"])

        self.update_power_run_settings(power_settings)
        self.update_concurrent_queries_settings(concurrent_settings)

    def save_config(self) -> None:
        """Save current configuration to file."""
        self.config_manager.save_config()

    def validate_execution_config(self) -> bool:
        """Validate execution configuration settings."""
        return self.config_manager.validate_config()

    def get_execution_summary(self) -> dict[str, Any]:
        """Get a summary of current execution configuration."""
        power_settings = self.get_power_run_settings()
        concurrent_settings = self.get_concurrent_queries_settings()

        return {
            "power_run": {
                "enabled": power_settings.iterations > 1 or power_settings.warm_up_iterations > 0,
                "total_iterations": power_settings.iterations + power_settings.warm_up_iterations,
                "estimated_duration_minutes": (power_settings.iterations + power_settings.warm_up_iterations)
                * power_settings.timeout_per_iteration_minutes,
                "settings": power_settings.to_dict(),
            },
            "concurrent_queries": {
                "enabled": concurrent_settings.enabled,
                "max_streams": concurrent_settings.max_concurrent,
                "estimated_stream_duration_minutes": concurrent_settings.stream_timeout_seconds / 60,
                "settings": concurrent_settings.to_dict(),
            },
            "general": {
                "max_workers": self.config_manager.get("execution.max_workers", 4),
                "memory_limit_gb": self.config_manager.get("execution.memory_limit_gb", 0),
                "parallel_queries": self.config_manager.get("execution.parallel_queries", False),
            },
        }


def create_sample_execution_config(output_path: Union[str, Path]) -> None:
    """Create a sample execution configuration file.

    Args:
        output_path: Path where to save the sample configuration
    """
    output_path = Path(output_path)

    sample_config = {
        "_description": "Sample BenchBox execution configuration with power run and concurrent query settings",
        "execution": {
            "parallel_queries": False,
            "max_workers": 4,
            "memory_limit_gb": 8,
            "verbose": True,
            "power_run": {
                "iterations": 3,
                "warm_up_iterations": 1,
                "timeout_per_iteration_minutes": 60,
                "fail_fast": False,
                "collect_metrics": True,
                "_description": "Power run configuration for iterative performance testing",
            },
            "concurrent_queries": {
                "enabled": True,
                "max_concurrent": 2,
                "query_timeout_seconds": 300,
                "stream_timeout_seconds": 3600,
                "retry_failed_queries": True,
                "max_retries": 3,
                "_description": "Concurrent query configuration for throughput testing",
            },
        },
        "_profiles": {
            "quick": "Fast testing with minimal iterations",
            "standard": "Balanced testing with moderate iterations",
            "thorough": "Comprehensive testing with multiple iterations",
            "stress": "Stress testing with maximum iterations and concurrency",
        },
    }

    import yaml

    with open(output_path, "w", encoding="utf-8") as f:
        yaml.dump(sample_config, f, default_flow_style=False, sort_keys=False)
