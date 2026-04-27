"""DataFrame tuning configuration loader.

This module provides the DataFrameTuningLoader class for loading, saving,
and managing DataFrame tuning configurations from YAML/JSON files.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from benchbox.core.dataframe.tuning.interface import (
    DataFrameTuningConfiguration,
    TuningMetadata,
)

logger = logging.getLogger(__name__)


class DataFrameTuningLoadError(Exception):
    """Raised when a tuning configuration cannot be loaded."""


class DataFrameTuningSaveError(Exception):
    """Raised when a tuning configuration cannot be saved."""


class DataFrameTuningLoader:
    """Loader for DataFrame tuning configurations.

    This class handles loading and saving DataFrame tuning configurations
    from YAML and JSON files, with support for templates and merging.

    Example:
        >>> loader = DataFrameTuningLoader()
        >>> config = loader.load_config("path/to/config.yaml", platform="polars")
        >>> emit(config.execution.streaming_mode)
        True
    """

    def load_config(
        self,
        path: Path | str,
        platform: str | None = None,
    ) -> DataFrameTuningConfiguration:
        """Load a tuning configuration from a file.

        Args:
            path: Path to the YAML or JSON configuration file
            platform: Optional platform name for validation

        Returns:
            The loaded DataFrameTuningConfiguration

        Raises:
            DataFrameTuningLoadError: If the file cannot be loaded or parsed
            FileNotFoundError: If the file does not exist
        """
        path = Path(path)

        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        try:
            data = self._load_file(path)
        except Exception as e:
            raise DataFrameTuningLoadError(f"Failed to parse {path}: {e}") from e

        try:
            config = DataFrameTuningConfiguration.from_dict(data)
        except Exception as e:
            raise DataFrameTuningLoadError(f"Invalid configuration in {path}: {e}") from e

        # Log platform validation warnings if platform specified
        if platform:
            enabled = config.get_enabled_settings()

            for setting in enabled:
                if not setting.is_compatible_with_platform(platform):
                    logger.warning(f"Setting '{setting.value}' is not supported on platform '{platform}'")

        return config

    def _load_file(self, path: Path) -> dict[str, Any]:
        """Load data from a YAML or JSON file.

        Args:
            path: Path to the file

        Returns:
            Parsed dictionary data

        Raises:
            ValueError: If the file format is not supported
        """
        suffix = path.suffix.lower()

        with open(path, encoding="utf-8") as f:
            if suffix in {".yaml", ".yml"}:
                data = yaml.safe_load(f)
            elif suffix == ".json":
                data = json.load(f)
            else:
                raise ValueError(f"Unsupported file format: {suffix}. Use .yaml, .yml, or .json")

        return data or {}

    def save_config(
        self,
        config: DataFrameTuningConfiguration,
        path: Path | str,
        platform: str | None = None,
        description: str | None = None,
        include_defaults: bool = False,
    ) -> None:
        """Save a tuning configuration to a file.

        Args:
            config: The configuration to save
            path: Path to save the file (extension determines format)
            platform: Optional platform name to include in metadata
            description: Optional description to include in metadata
            include_defaults: If True, include all settings even if at defaults

        Raises:
            DataFrameTuningSaveError: If the file cannot be saved
        """
        path = Path(path)

        # Update metadata
        if config.metadata is None:
            config.metadata = TuningMetadata()

        config.metadata.platform = platform or config.metadata.platform
        config.metadata.description = description or config.metadata.description
        config.metadata.created = datetime.now().strftime("%Y-%m-%d")
        config.metadata.generated_by = "benchbox"

        # Serialize
        data = config.to_full_dict() if include_defaults else config.to_dict()

        try:
            self._save_file(data, path)
        except Exception as e:
            raise DataFrameTuningSaveError(f"Failed to save to {path}: {e}") from e

    def _save_file(self, data: dict[str, Any], path: Path) -> None:
        """Save data to a YAML or JSON file.

        Args:
            data: Data to save
            path: Path to the file

        Raises:
            ValueError: If the file format is not supported
        """
        suffix = path.suffix.lower()

        # Ensure parent directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            if suffix in {".yaml", ".yml"}:
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
            elif suffix == ".json":
                json.dump(data, f, indent=2)
            else:
                raise ValueError(f"Unsupported file format: {suffix}. Use .yaml, .yml, or .json")

    def get_template(self, platform: str) -> DataFrameTuningConfiguration:
        """Get a platform-specific template with recommended settings.

        This returns a configuration with sensible defaults for the specified
        platform, optimized for general-purpose workloads.

        Args:
            platform: The DataFrame platform name (e.g., 'polars', 'pandas')

        Returns:
            A DataFrameTuningConfiguration with recommended settings
        """
        from benchbox.core.dataframe.tuning.interface import (
            DataTypeConfiguration,
            ExecutionConfiguration,
            GPUConfiguration,
            IOConfiguration,
            MemoryConfiguration,
            ParallelismConfiguration,
        )

        platform_lower = platform.lower()
        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        # Base configuration
        config = DataFrameTuningConfiguration(
            metadata=TuningMetadata(
                platform=platform_lower,
                description=f"Default template for {platform_lower}",
                generated_by="benchbox-template",
            )
        )

        # Platform-specific settings
        if platform_lower == "polars":
            config.execution = ExecutionConfiguration(
                streaming_mode=False,  # Default to in-memory for speed
                engine_affinity="in-memory",
                lazy_evaluation=True,
            )
            config.memory = MemoryConfiguration(
                rechunk_after_filter=True,
            )
            config.data_types = DataTypeConfiguration(
                enable_string_cache=False,  # Only enable when needed
            )

        elif platform_lower == "pandas":
            config.data_types = DataTypeConfiguration(
                dtype_backend="numpy_nullable",  # Modern nullable types
                enable_string_cache=False,
            )
            config.io = IOConfiguration(
                memory_map=False,
                pre_buffer=True,
            )

        elif platform_lower == "dask":
            config.parallelism = ParallelismConfiguration(
                threads_per_worker=2,  # Balance memory/CPU
            )
            config.memory = MemoryConfiguration(
                spill_to_disk=True,  # Enable for large datasets
            )
            config.data_types = DataTypeConfiguration(
                dtype_backend="pyarrow",  # Better Dask integration
            )

        elif platform_lower == "modin":
            config.execution = ExecutionConfiguration(
                engine_affinity="ray",  # Recommended backend
            )
            config.data_types = DataTypeConfiguration(
                dtype_backend="numpy_nullable",
            )

        elif platform_lower == "cudf":
            config.gpu = GPUConfiguration(
                enabled=True,
                device_id=0,
                spill_to_host=True,  # Fallback for large data
            )

        return config

    def get_optimized_template(self, platform: str) -> DataFrameTuningConfiguration:
        """Get a performance-optimized template for the platform.

        This returns a configuration tuned for maximum performance,
        potentially trading off memory efficiency.

        Args:
            platform: The DataFrame platform name

        Returns:
            A performance-optimized DataFrameTuningConfiguration
        """
        from benchbox.core.dataframe.tuning.interface import (
            DataTypeConfiguration,
            ExecutionConfiguration,
            GPUConfiguration,
            ParallelismConfiguration,
        )

        platform_lower = platform.lower()
        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        config = self.get_template(platform)
        config.metadata.description = f"Performance-optimized template for {platform_lower}"

        if platform_lower == "polars":
            # Use streaming only for very large datasets
            config.execution = ExecutionConfiguration(
                streaming_mode=False,
                engine_affinity="in-memory",
                lazy_evaluation=True,
            )
            config.data_types = DataTypeConfiguration(
                enable_string_cache=True,  # Faster categoricals
            )

        elif platform_lower == "pandas":
            config.data_types = DataTypeConfiguration(
                dtype_backend="pyarrow",  # Faster operations
                enable_string_cache=True,
                auto_categorize_strings=True,
                categorical_threshold=0.3,
            )
            config.io.memory_map = True  # Faster file reads

        elif platform_lower == "dask":
            config.parallelism = ParallelismConfiguration(
                threads_per_worker=4,  # More parallelism
            )
            config.data_types = DataTypeConfiguration(
                dtype_backend="pyarrow",
            )

        elif platform_lower == "cudf":
            config.gpu = GPUConfiguration(
                enabled=True,
                device_id=0,
                spill_to_host=False,  # Keep everything on GPU
                pool_type="pool",  # Faster allocations
            )

        return config

    def get_memory_constrained_template(self, platform: str) -> DataFrameTuningConfiguration:
        """Get a memory-efficient template for the platform.

        This returns a configuration optimized for low memory environments,
        potentially trading off performance.

        Args:
            platform: The DataFrame platform name

        Returns:
            A memory-efficient DataFrameTuningConfiguration
        """
        from benchbox.core.dataframe.tuning.interface import (
            DataTypeConfiguration,
            ExecutionConfiguration,
            GPUConfiguration,
            MemoryConfiguration,
            ParallelismConfiguration,
        )

        platform_lower = platform.lower()
        if platform_lower.endswith("-df"):
            platform_lower = platform_lower[:-3]

        config = self.get_template(platform)
        config.metadata.description = f"Memory-constrained template for {platform_lower}"

        if platform_lower == "polars":
            config.execution = ExecutionConfiguration(
                streaming_mode=True,  # Process in chunks
                engine_affinity="streaming",
                lazy_evaluation=True,
            )
            config.memory = MemoryConfiguration(
                chunk_size=100_000,  # Smaller chunks
                rechunk_after_filter=False,  # Save memory
            )

        elif platform_lower == "pandas":
            config.memory = MemoryConfiguration(
                chunk_size=50_000,  # Small chunks
            )
            config.data_types = DataTypeConfiguration(
                dtype_backend="pyarrow",  # More efficient memory
                auto_categorize_strings=True,
                categorical_threshold=0.5,
            )

        elif platform_lower == "dask":
            config.parallelism = ParallelismConfiguration(
                worker_count=2,  # Fewer workers
                threads_per_worker=1,
            )
            config.memory = MemoryConfiguration(
                memory_limit="2GB",
                spill_to_disk=True,
                chunk_size=100_000,
            )

        elif platform_lower == "cudf":
            config.gpu = GPUConfiguration(
                enabled=True,
                device_id=0,
                spill_to_host=True,  # Use host memory when needed
            )

        return config

    def merge_configs(
        self,
        base: DataFrameTuningConfiguration,
        override: DataFrameTuningConfiguration,
        platform: str | None = None,
        validate: bool = True,
    ) -> DataFrameTuningConfiguration:
        """Merge two configurations with override precedence.

        Values from the override configuration take precedence over base
        values. Only non-default values from override are applied.

        Args:
            base: The base configuration
            override: The configuration with values to override
            platform: Optional platform name for validation
            validate: Whether to validate the merged configuration (default: True)

        Returns:
            A new merged DataFrameTuningConfiguration

        Raises:
            ValueError: If validate=True and the merged configuration is invalid
        """
        # Start with base as a dictionary
        base_dict = base.to_full_dict()

        # Get override values (only non-defaults)
        override_dict = override.to_dict()

        # Deep merge
        merged = self._deep_merge(base_dict, override_dict)

        # Create the merged configuration (this validates field-level constraints
        # via __post_init__ in each sub-configuration)
        merged_config = DataFrameTuningConfiguration.from_dict(merged)

        # Optionally validate platform compatibility
        if validate and platform:
            from benchbox.core.dataframe.tuning.validation import (
                ValidationLevel,
                validate_dataframe_tuning,
            )

            issues = validate_dataframe_tuning(merged_config, platform)
            errors = [i for i in issues if i.level == ValidationLevel.ERROR]
            if errors:
                error_msgs = "; ".join(i.message for i in errors)
                raise ValueError(f"Merged configuration validation failed: {error_msgs}")

            # Log warnings
            for issue in issues:
                if issue.level == ValidationLevel.WARNING:
                    logger.warning(f"Merged config: {issue}")

        return merged_config

    def _deep_merge(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Deep merge two dictionaries.

        Args:
            base: Base dictionary
            override: Dictionary with override values

        Returns:
            Merged dictionary
        """
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result


# Module-level convenience functions
_default_loader = DataFrameTuningLoader()


def load_dataframe_tuning(path: Path | str, platform: str | None = None) -> DataFrameTuningConfiguration:
    """Load a DataFrame tuning configuration from a file.

    Convenience function that uses the default loader.

    Args:
        path: Path to the configuration file
        platform: Optional platform name for validation

    Returns:
        The loaded DataFrameTuningConfiguration
    """
    return _default_loader.load_config(path, platform)


def save_dataframe_tuning(
    config: DataFrameTuningConfiguration,
    path: Path | str,
    platform: str | None = None,
    description: str | None = None,
) -> None:
    """Save a DataFrame tuning configuration to a file.

    Convenience function that uses the default loader.

    Args:
        config: The configuration to save
        path: Path to save the file
        platform: Optional platform name for metadata
        description: Optional description for metadata
    """
    _default_loader.save_config(config, path, platform, description)
