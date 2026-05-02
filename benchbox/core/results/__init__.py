"""Enhanced results system with execution metadata and anonymization.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from .anonymization import AnonymizationConfig, AnonymizationManager
from .builder import (
    BenchmarkInfoInput,
    ResultBuilder,
    build_benchmark_results,
    normalize_benchmark_id,
)
from .database import (
    PerformanceTrend,
    PlatformRanking,
    RankingConfig,
    ResultDatabase,
    StoredQuery,
    StoredResult,
)
from .display import (
    display_benchmark_list,
    display_configuration_summary,
    display_platform_list,
    display_results,
    display_verbose_config_feedback,
    print_completion_message,
    print_dry_run_summary,
    print_phase_header,
)
from .environment import (
    ClientHostEnvironment,
    ContainerEnvironment,
    NormalizedExecutionEnvironment,
    PlatformCloudMetadata,
    PlatformComputeMetadata,
    PlatformDeploymentMetadata,
    PlatformRuntimeEnvironment,
    PlatformStorageMetadata,
)
from .metrics import TimingStatsCalculator, TPCMetricsCalculator
from .platform_info import (
    PlatformInfoInput,
    build_platform_info,
    format_platform_display_name,
)
from .query_normalizer import (
    QueryResultInput,
    format_query_id,
    normalize_query_id,
    normalize_query_result,
    normalize_query_results,
)
from .timing import QueryTiming, TimingAnalyzer, TimingCollector

__all__ = [
    # Anonymization
    "AnonymizationConfig",
    "AnonymizationManager",
    # Builder
    "BenchmarkInfoInput",
    "ResultBuilder",
    "build_benchmark_results",
    "normalize_benchmark_id",
    # Database
    "PerformanceTrend",
    "PlatformRanking",
    "QueryTiming",
    "RankingConfig",
    "ResultDatabase",
    "StoredQuery",
    "StoredResult",
    # Display
    "display_benchmark_list",
    "display_configuration_summary",
    "display_platform_list",
    "display_results",
    "display_verbose_config_feedback",
    "print_completion_message",
    "print_dry_run_summary",
    "print_phase_header",
    # Environment
    "ClientHostEnvironment",
    "ContainerEnvironment",
    "NormalizedExecutionEnvironment",
    "PlatformCloudMetadata",
    "PlatformComputeMetadata",
    "PlatformDeploymentMetadata",
    "PlatformRuntimeEnvironment",
    "PlatformStorageMetadata",
    # Metrics
    "TPCMetricsCalculator",
    "TimingStatsCalculator",
    # Platform Info
    "PlatformInfoInput",
    "build_platform_info",
    "format_platform_display_name",
    # Query Normalizer
    "QueryResultInput",
    "format_query_id",
    "normalize_query_id",
    "normalize_query_result",
    "normalize_query_results",
    # Timing
    "TimingAnalyzer",
    "TimingCollector",
]
