"""Shared helpers for real PySpark + Delta Lake live integration tests.

These helpers start a local PySpark session with the Delta Lake extension
using the repository's own JDK compatibility logic
(:func:`benchbox.platforms.spark._ensure_compatible_java`), so the tests
work on machines whose default Java is too new for Spark.

The suites using these helpers are marked ``live_integration`` and are
excluded from the default test selection.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def delta_live_skip_reason() -> str | None:
    """Return a skip reason when the live Delta runtime is unavailable, else None."""
    try:
        import delta  # noqa: F401
        import pyspark  # noqa: F401
    except ImportError as exc:
        return f"PySpark + Delta Lake runtime not installed: {exc}"

    try:
        from benchbox.platforms.spark import _ensure_compatible_java

        _ensure_compatible_java()
    except Exception as exc:
        return f"No compatible Java for PySpark: {exc}"

    return None


def make_delta_spark_session(warehouse_dir: Path | str, app_name: str = "benchbox-delta-live") -> Any:
    """Create a local PySpark session with Delta Lake support.

    Args:
        warehouse_dir: Directory used as the Spark SQL warehouse.
        app_name: Spark application name.

    Returns:
        A running ``SparkSession`` with the Delta extension configured.
    """
    from benchbox.platforms.spark import _ensure_compatible_java

    _ensure_compatible_java()

    from delta import configure_spark_with_delta_pip
    from pyspark.sql import SparkSession

    builder = (
        SparkSession.builder.appName(app_name)
        .master("local[2]")
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension")
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
        .config("spark.sql.warehouse.dir", str(warehouse_dir))
    )
    spark = configure_spark_with_delta_pip(builder).getOrCreate()
    spark.sparkContext.setLogLevel("ERROR")
    return spark
