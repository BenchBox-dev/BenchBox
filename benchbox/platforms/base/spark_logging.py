from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def suppress_window_exec_warning(spark: Any) -> None:
    try:
        jvm = spark.sparkContext._jvm
        log_manager = jvm.org.apache.logging.log4j.LogManager
        jvm.org.apache.logging.log4j.core.config.Configurator.setLevel(
            log_manager.getLogger("org.apache.spark.sql.execution.window.WindowExec"),
            jvm.org.apache.logging.log4j.Level.ERROR,
        )
    except Exception as e:
        logger.debug("WindowExec warning suppression failed (warnings may still appear): %s", e)


__all__ = ["suppress_window_exec_warning"]
