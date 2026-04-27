"""Shared SparkSession management for PySpark-based adapters.

This module provides:
- SparkSessionManager: Singleton lifecycle manager for SparkSession
- Java version detection and compatibility checking
- Automatic JAVA_HOME switching to compatible versions

PySpark 4.x requires Java 17 or 21. This module can automatically detect
and switch to a compatible Java installation on macOS using java_home.

Environment Variables:
- BENCHBOX_JAVA_HOME: Override Java home for BenchBox (highest priority)
- JAVA_HOME: Standard Java home (used if BENCHBOX_JAVA_HOME not set)

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import atexit
import logging
import os
import subprocess
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from benchbox.platforms.base.spark_logging import suppress_window_exec_warning
from benchbox.utils.dependencies import get_package_install_message

try:
    import pyspark
    from pyspark.sql import SparkSession

    PYSPARK_AVAILABLE = True
    PYSPARK_VERSION = pyspark.__version__
except ImportError:
    PYSPARK_AVAILABLE = False
    PYSPARK_VERSION = None  # type: ignore[assignment]
    pyspark = None  # type: ignore[assignment]
    SparkSession = Any  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)

SUPPORTED_JAVA_VERSIONS = frozenset({17, 21})
MAX_SUPPORTED_JAVA_VERSION = 22

# Environment variable for BenchBox-specific Java home override
BENCHBOX_JAVA_HOME_ENV = "BENCHBOX_JAVA_HOME"


class SparkSessionError(RuntimeError):
    """Base class for SparkSession management errors."""


class SparkUnavailableError(SparkSessionError):
    """Raised when PySpark is not installed but required."""


class SparkConfigurationError(SparkSessionError):
    """Raised when new configuration conflicts with existing SparkSession."""


class JavaVersionError(SparkSessionError):
    """Raised when Java version is incompatible with PySpark."""


@dataclass(frozen=True)
class SparkSessionConfig:
    """Normalized SparkSession configuration values."""

    master: str
    app_name: str
    driver_memory: str
    executor_memory: str | None
    shuffle_partitions: int
    enable_aqe: bool
    extra_configs: tuple[tuple[str, str], ...]
    verbose: bool = False  # Control Spark's Java-side log level


def _normalize_extra_configs(extra: Mapping[str, Any] | None) -> tuple[tuple[str, str], ...]:
    if not extra:
        return ()
    normalized: list[tuple[str, str]] = []
    for key, value in extra.items():
        normalized.append((str(key), str(value)))
    normalized.sort(key=lambda item: item[0])
    return tuple(normalized)


# -----------------------------------------------------------------------------
# Java Version Detection and Management (Public API)
# -----------------------------------------------------------------------------


def get_effective_java_home() -> str | None:
    """Return the Java home path that will be used for PySpark.

    Priority order:
    1. BENCHBOX_JAVA_HOME environment variable
    2. JAVA_HOME environment variable
    3. None (system default java will be used)

    Returns:
        Path to Java home directory, or None if not explicitly set.
    """
    return os.environ.get(BENCHBOX_JAVA_HOME_ENV) or os.environ.get("JAVA_HOME")


def detect_java_version(java_home: str | None = None) -> int | None:
    """Detect the major version of a Java installation.

    Args:
        java_home: Path to Java home directory. If None, uses get_effective_java_home()
                   or falls back to system PATH.

    Returns:
        Major version number (e.g., 17, 21, 25) or None if detection fails.
    """
    if java_home is None:
        java_home = get_effective_java_home()

    java_path = Path(java_home, "bin", "java") if java_home else Path("java")

    try:
        result = subprocess.run(
            [str(java_path), "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError, PermissionError):
        return None

    version_line = (result.stderr or result.stdout).splitlines()
    if not version_line:
        return None
    line = version_line[0]
    if '"' not in line:
        return None
    version_str = line.split('"')[1]
    major = version_str.split(".")[0]
    try:
        return int(major)
    except ValueError:
        return None


def find_supported_java_home() -> tuple[str, int] | None:
    """Find a Java installation compatible with PySpark.

    Uses platform-specific helpers to locate Java installations:
    - macOS: /usr/libexec/java_home
    - Linux: Not yet implemented (returns None)
    - Windows: Not yet implemented (returns None)

    Returns:
        Tuple of (java_home_path, major_version) for a compatible installation,
        or None if no compatible Java is found.
    """
    helper = Path("/usr/libexec/java_home")
    if sys.platform != "darwin" or not helper.exists():
        return None

    for version in sorted(SUPPORTED_JAVA_VERSIONS, reverse=True):
        try:
            result = subprocess.run(
                [str(helper), "-v", str(version)],
                capture_output=True,
                text=True,
                timeout=5,
                check=True,
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            continue

        candidate = result.stdout.strip()
        if candidate:
            return candidate, version

    return None


def is_java_compatible(version: int | None = None) -> bool:
    """Check if a Java version is compatible with PySpark 4.x.

    Args:
        version: Java major version to check. If None, detects current version.

    Returns:
        True if the version is compatible (17 or 21), False otherwise.
    """
    if version is None:
        version = detect_java_version()
    return version in SUPPORTED_JAVA_VERSIONS


def ensure_compatible_java() -> tuple[int | None, str | None]:
    """Ensure a compatible Java version is configured for PySpark.

    This function checks the current Java configuration and attempts to
    switch to a compatible version if necessary. It modifies JAVA_HOME
    in the current process if a switch is needed.

    Priority:
    1. If BENCHBOX_JAVA_HOME is set, use it (no auto-switching)
    2. If current JAVA_HOME points to compatible Java, use it
    3. If system default Java is compatible, use it
    4. Attempt to find and switch to a compatible Java installation

    Returns:
        Tuple of (java_version, java_home_path) where:
        - java_version: The major version of the configured Java (e.g., 17, 21),
                        or None if no compatible Java is available
        - java_home_path: The JAVA_HOME path being used, or None if using system default

    Side Effects:
        May set JAVA_HOME environment variable if switching to a compatible version.
    """
    # Check if BENCHBOX_JAVA_HOME is explicitly set - respect user override
    benchbox_java_home = os.environ.get(BENCHBOX_JAVA_HOME_ENV)
    if benchbox_java_home:
        version = detect_java_version(benchbox_java_home)
        if is_java_compatible(version):
            # Ensure JAVA_HOME is also set for subprocess compatibility
            os.environ["JAVA_HOME"] = benchbox_java_home
            return version, benchbox_java_home
        logger.warning(
            "%s=%s points to Java %s which is not compatible with PySpark 4.x",
            BENCHBOX_JAVA_HOME_ENV,
            benchbox_java_home,
            version,
        )
        return version, benchbox_java_home

    # Check current JAVA_HOME
    current_java_home = os.environ.get("JAVA_HOME")
    if current_java_home:
        version = detect_java_version(current_java_home)
        if is_java_compatible(version):
            return version, current_java_home

    # Check system default Java
    version = detect_java_version(None)
    if is_java_compatible(version):
        return version, None

    # Attempt to find and switch to a compatible Java
    alternative = find_supported_java_home()
    if alternative:
        path, version = alternative
        os.environ["JAVA_HOME"] = path
        logger.info("Switching JAVA_HOME to %s (Java %s) for PySpark compatibility", path, version)
        return version, path

    # No compatible Java found
    return detect_java_version(), get_effective_java_home()


def get_java_skip_reason() -> str:
    """Get a human-readable reason for skipping PySpark tests.

    Returns:
        Empty string if Java is compatible, otherwise a skip reason message.
    """
    if not PYSPARK_AVAILABLE:
        return "PySpark not installed"

    version, java_home = ensure_compatible_java()
    if is_java_compatible(version):
        return ""

    if version is None:
        return "Java not found"
    if version >= MAX_SUPPORTED_JAVA_VERSION + 1:
        return f"PySpark 4.x not compatible with Java {version}"
    return f"PySpark 4.x requires Java 17 or 21 (found Java {version})"


# -----------------------------------------------------------------------------
# Internal Helpers (Private)
# -----------------------------------------------------------------------------


def _validate_java_version() -> None:
    """Validate Java version and raise if incompatible.

    Raises:
        JavaVersionError: If no compatible Java version is available.
    """
    version, _ = ensure_compatible_java()

    if is_java_compatible(version):
        return

    if version is None:
        raise JavaVersionError("Unable to determine Java version. PySpark SQL mode requires Java 17 or 21.")

    if version >= MAX_SUPPORTED_JAVA_VERSION + 1:
        raise JavaVersionError(f"Detected Java {version}. PySpark 4.x is not compatible with Java 23 or newer.")

    raise JavaVersionError(f"Detected Java {version}. Please install Java 17 or 21 for PySpark 4.x.")


class SparkSessionManager:
    """Singleton SparkSession lifecycle manager for PySpark adapters."""

    _lock = threading.Lock()
    _session: SparkSession | None = None
    _config: SparkSessionConfig | None = None
    _refcount = 0
    _java_validated = False

    @classmethod
    def get_or_create(
        cls,
        *,
        master: str,
        app_name: str,
        driver_memory: str,
        executor_memory: str | None,
        shuffle_partitions: int,
        enable_aqe: bool,
        extra_configs: Mapping[str, Any] | None = None,
        verbose: bool = False,
    ) -> SparkSession:
        """Return the shared SparkSession, creating it if necessary."""
        if not PYSPARK_AVAILABLE:
            raise SparkUnavailableError(get_package_install_message("pyspark pyarrow", "PySpark is not installed."))

        config = SparkSessionConfig(
            master=master,
            app_name=app_name,
            driver_memory=driver_memory,
            executor_memory=executor_memory,
            shuffle_partitions=shuffle_partitions,
            enable_aqe=enable_aqe,
            extra_configs=_normalize_extra_configs(extra_configs),
            verbose=verbose,
        )

        with cls._lock:
            if cls._session is None:
                logger.debug("Creating SparkSession with config: %s", config)
                if not cls._java_validated:
                    _validate_java_version()
                    cls._java_validated = True
                cls._session = cls._create_session(config)
                cls._config = config
            else:
                cls._ensure_compatible_config(config)

            cls._refcount += 1
            return cls._session

    @classmethod
    def release(cls) -> None:
        """Release a reference to the shared SparkSession."""
        with cls._lock:
            if cls._refcount == 0:
                return
            cls._refcount -= 1
            if cls._refcount == 0:
                cls._stop_session()

    @classmethod
    def close(cls) -> None:
        """Forcefully stop the shared SparkSession (used for shutdown hooks)."""
        with cls._lock:
            cls._refcount = 0
            cls._stop_session()

    @classmethod
    def _ensure_compatible_config(cls, config: SparkSessionConfig) -> None:
        if cls._config == config:
            return
        raise SparkConfigurationError(
            "SparkSession already created with a different configuration. "
            "Ensure all PySpark adapters share the same Spark settings."
        )

    @classmethod
    def _create_session(cls, config: SparkSessionConfig) -> SparkSession:
        # Suppress Spark's Java-side logging before session creation
        # This reduces the noise from hostname resolution, Hadoop native libs, etc.
        cls._configure_spark_logging(config.verbose)

        # Use custom Log4j2 configuration file to suppress startup messages
        # The config files are in the same directory as this module
        log4j_config_name = "log4j2-verbose.properties" if config.verbose else "log4j2-quiet.properties"
        log4j_config_path = Path(__file__).parent / log4j_config_name
        log4j_opts = f"-Dlog4j.configurationFile=file:{log4j_config_path}"

        # Check if user provided extra Java options - merge with our log4j setting
        user_java_opts = dict(config.extra_configs).get("spark.driver.extraJavaOptions", "")
        if user_java_opts:
            log4j_opts = f"{log4j_opts} {user_java_opts}"

        builder = (
            SparkSession.builder.master(config.master)
            .appName(config.app_name)
            .config("spark.driver.memory", config.driver_memory)
            .config("spark.driver.extraJavaOptions", log4j_opts)
            .config("spark.sql.shuffle.partitions", str(config.shuffle_partitions))
            .config("spark.sql.inMemoryColumnarStorage.enabled", "false")
        )

        if config.executor_memory:
            builder = builder.config("spark.executor.memory", config.executor_memory)

        if config.enable_aqe:
            builder = builder.config("spark.sql.adaptive.enabled", "true")
            builder = builder.config("spark.sql.adaptive.coalescePartitions.enabled", "true")
        else:
            builder = builder.config("spark.sql.adaptive.enabled", "false")

        # Apply extra configs, skipping extraJavaOptions since we already merged it
        for key, value in config.extra_configs:
            if key != "spark.driver.extraJavaOptions":
                builder = builder.config(key, value)

        session = builder.getOrCreate()

        # Set SparkContext log level after session is created
        # This controls ongoing Spark logging during execution
        spark_log_level = "WARN" if config.verbose else "ERROR"
        session.sparkContext.setLogLevel(spark_log_level)

        # Suppress WindowExec "No Partition Defined for Window operation" warnings.
        # Standard TPC-DS queries (Q44, Q49) use OVER (ORDER BY ...) without
        # PARTITION BY - per-spec, not fixable. The warning floods output (~100+
        # lines per run) and is not actionable.  Must be set *after* setLogLevel()
        # because setLogLevel resets all log4j2 loggers.
        suppress_window_exec_warning(session)

        logger.info("SparkSession created with master=%s app=%s", config.master, config.app_name)
        return session

    @classmethod
    def _configure_spark_logging(cls, verbose: bool) -> None:
        """Configure Spark's Java-side logging before session creation.

        This suppresses the noisy startup messages from Spark's Log4j logging.
        The messages include hostname warnings, Hadoop native library warnings, etc.

        Args:
            verbose: If True, show WARN level; if False, show only ERROR level.
        """
        # The only reliable way to suppress Spark's startup logging is to
        # configure Log4j before SparkContext initializes. We do this by:
        # 1. Setting the py4j logger level (reduces some noise)
        # 2. The SparkContext.setLogLevel() call after session creation handles the rest
        try:
            # Suppress py4j gateway logging which can be noisy
            import logging

            py4j_logger = logging.getLogger("py4j")
            py4j_logger.setLevel(logging.ERROR if not verbose else logging.WARNING)
        except Exception:
            pass

    @classmethod
    def _stop_session(cls) -> None:
        if cls._session is None:
            return
        try:
            logger.info("Stopping shared SparkSession")
            cls._session.stop()
        finally:
            cls._session = None
            cls._config = None
            cls._java_validated = False


atexit.register(SparkSessionManager.close)


__all__ = [
    # Availability flags
    "PYSPARK_AVAILABLE",
    "PYSPARK_VERSION",
    # Java version detection
    "SUPPORTED_JAVA_VERSIONS",
    "detect_java_version",
    "find_supported_java_home",
    "is_java_compatible",
    "ensure_compatible_java",
    "get_java_skip_reason",
    "get_effective_java_home",
    # Session management
    "SparkSessionManager",
    # Logging utilities (re-exported from base.spark_logging)
    "suppress_window_exec_warning",
    # Exceptions
    "SparkSessionError",
    "SparkUnavailableError",
    "SparkConfigurationError",
    "JavaVersionError",
]
