"""Utility functions for BenchBox.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from .config_helpers import (
    ConcurrentQueriesSettings,
    ExecutionConfigHelper,
    PowerRunSettings,
    create_sample_execution_config,
)
from .formatting import (
    format_bytes,
    format_duration,
    format_memory_usage,
    format_number,
)
from .resource_limits import (
    ResourceLimitExceeded,
    ResourceLimitMonitor,
    ResourceLimitsConfig,
    ResourceUsageSummary,
    ResourceWarning,
    ResourceWarningLevel,
    calculate_safe_memory_limit,
    get_available_memory_mb,
    get_system_memory_mb,
)
from .scale_factor import (
    format_benchmark_name,
    format_data_directory,
    format_scale_factor,
    format_schema_name,
)
from .timeout_manager import (
    TimeoutConfig,
    TimeoutError,
    TimeoutManager,
    get_timeout_manager,
    run_with_timeout,
    timeout,
)

__all__ = [
    # Scale factor utilities
    "format_scale_factor",
    "format_benchmark_name",
    "format_data_directory",
    "format_schema_name",
    # Execution management
    "PowerRunSettings",
    "ConcurrentQueriesSettings",
    "ExecutionConfigHelper",
    "create_sample_execution_config",
    # Formatting
    "format_duration",
    "format_bytes",
    "format_memory_usage",
    "format_number",
    # Resource limits
    "ResourceLimitsConfig",
    "ResourceLimitMonitor",
    "ResourceUsageSummary",
    "ResourceWarning",
    "ResourceWarningLevel",
    "ResourceLimitExceeded",
    "get_system_memory_mb",
    "get_available_memory_mb",
    "calculate_safe_memory_limit",
    # Timeout management
    "TimeoutManager",
    "TimeoutConfig",
    "TimeoutError",
    "get_timeout_manager",
    "run_with_timeout",
    "timeout",
]
