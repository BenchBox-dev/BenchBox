"""Cloud Spark shared infrastructure for managed Spark platforms.

This module provides shared infrastructure that enables 80%+ code reuse
across managed cloud Spark platforms:

- AWS: EMR, EMR Serverless, Glue, Athena (Spark)
- GCP: Dataproc, Dataproc Serverless
- Azure: Synapse Spark, Fabric Spark
- Databricks: Already uses Databricks Connect (separate implementation)
- Snowflake: Snowpark (separate implementation)

Components:
    CloudSparkStaging: Unified cloud storage upload API for S3, GCS, Azure, DBFS
    CloudSparkSessionManager: Remote Spark session lifecycle management
    SparkConfigOptimizer: Benchmark-specific Spark configuration optimization
    SparkExternalTableMixin: Shared --table-mode external flow for managed Spark adapters

Usage:
    from benchbox.platforms.base.cloud_spark import (
        CloudSparkStaging,
        CloudSparkSessionManager,
        SparkConfigOptimizer,
    )

    # Upload data to cloud storage
    staging = CloudSparkStaging.from_uri("s3://my-bucket/data")
    staging.upload_tables(tables, source_dir)

    # Get optimized Spark config for TPC-H
    config = SparkConfigOptimizer.for_tpch(scale_factor=10)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from benchbox.platforms.base.cloud_spark.config import SparkConfigOptimizer
from benchbox.platforms.base.cloud_spark.external_tables import SparkExternalTableMixin
from benchbox.platforms.base.cloud_spark.mixins import (
    CloudSparkConfigMixin,
    SparkDDLGeneratorMixin,
    SparkTableFormat,
    SparkTuningMixin,
)
from benchbox.platforms.base.cloud_spark.session import CloudSparkSessionManager
from benchbox.platforms.base.cloud_spark.staging import CloudSparkStaging

__all__ = [
    "CloudSparkConfigMixin",
    "CloudSparkStaging",
    "CloudSparkSessionManager",
    "SparkConfigOptimizer",
    "SparkDDLGeneratorMixin",
    "SparkExternalTableMixin",
    "SparkTableFormat",
    "SparkTuningMixin",
]
