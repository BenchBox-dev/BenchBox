# Copyright 2026 Joe Harris / BenchBox Project

from .session import (
    PYSPARK_AVAILABLE,
    PYSPARK_VERSION,
    SUPPORTED_JAVA_VERSIONS,
    JavaVersionError,
    SparkConfigurationError,
    SparkSessionError,
    SparkSessionManager,
    SparkUnavailableError,
    detect_java_version,
    ensure_compatible_java,
    find_supported_java_home,
    get_effective_java_home,
    get_java_skip_reason,
    is_java_compatible,
)
from .sql_adapter import PySparkSQLAdapter

__all__ = [
    "PYSPARK_AVAILABLE",
    "PYSPARK_VERSION",
    "SUPPORTED_JAVA_VERSIONS",
    "detect_java_version",
    "find_supported_java_home",
    "is_java_compatible",
    "ensure_compatible_java",
    "get_java_skip_reason",
    "get_effective_java_home",
    "SparkSessionManager",
    "SparkSessionError",
    "SparkUnavailableError",
    "SparkConfigurationError",
    "JavaVersionError",
    "PySparkSQLAdapter",
]
