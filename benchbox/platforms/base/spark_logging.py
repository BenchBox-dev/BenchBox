"""Shared Spark runtime logging utilities.

Used by both the standalone SparkAdapter (platforms/spark.py) and the
PySpark session manager (platforms/pyspark/session.py) so that neither
has to import from the other.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def suppress_window_exec_warning(spark: Any) -> None:
    """Suppress Spark's WindowExec 'No Partition Defined' warning via JVM gateway.

    Standard TPC-DS queries (Q44, Q49) use OVER (ORDER BY ...) without PARTITION BY
    per-spec. This produces ~100+ non-actionable warnings per run. Must be called
    *after* setLogLevel() because setLogLevel resets all log4j2 loggers.
    """
    try:
        jvm = spark.sparkContext._jvm
        log_manager = jvm.org.apache.logging.log4j.LogManager
        jvm.org.apache.logging.log4j.core.config.Configurator.setLevel(
            log_manager.getLogger("org.apache.spark.sql.execution.window.WindowExec"),
            jvm.org.apache.logging.log4j.Level.ERROR,
        )
    except Exception as e:
        # Non-critical - worst case the warnings still appear.
        logger.debug("WindowExec warning suppression failed (warnings may still appear): %s", e)


__all__ = ["suppress_window_exec_warning"]
