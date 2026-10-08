# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import importlib
from typing import Any

from benchbox.platforms.dataframe.benchmark_mixin import (
    BenchmarkExecutionMixin,
    DataFramePhases,
    DataFrameRunOptions,
)
from benchbox.platforms.dataframe.expression_family import (
    ExpressionFamilyAdapter,
    ExpressionFamilyContext,
)
from benchbox.platforms.dataframe.pandas_family import (
    PandasFamilyAdapter,
    PandasFamilyContext,
)
from benchbox.platforms.dataframe.platform_checker import (
    DATAFRAME_PLATFORMS,
    DataFrameFamily,
    DataFramePlatformChecker,
    PlatformInfo,
    PlatformStatus,
    format_platform_status_table,
    get_installation_suggestion,
    get_platform_error_message,
    require_platform,
)

_LAZY_EXPORTS = {
    "PANDAS_AVAILABLE": ("benchbox.platforms.dataframe.pandas_df", False),
    "PandasDataFrameAdapter": ("benchbox.platforms.dataframe.pandas_df", None),
    "POLARS_AVAILABLE": ("benchbox.platforms.dataframe.polars_df", False),
    "PolarsDataFrameAdapter": ("benchbox.platforms.dataframe.polars_df", None),
    "CUDF_AVAILABLE": ("benchbox.platforms.dataframe.cudf_df", False),
    "CuDFDataFrameAdapter": ("benchbox.platforms.dataframe.cudf_df", None),
    "DASK_AVAILABLE": ("benchbox.platforms.dataframe.dask_df", False),
    "DaskDataFrameAdapter": ("benchbox.platforms.dataframe.dask_df", None),
    "DATAFUSION_DF_AVAILABLE": ("benchbox.platforms.dataframe.datafusion_df", False),
    "DataFusionDataFrameAdapter": ("benchbox.platforms.dataframe.datafusion_df", None),
    "PYSPARK_AVAILABLE": ("benchbox.platforms.dataframe.pyspark_df", False),
    "PYSPARK_VERSION": ("benchbox.platforms.dataframe.pyspark_df", None),
    "PySparkDataFrameAdapter": ("benchbox.platforms.dataframe.pyspark_df", None),
    "LakeSailDataFrameAdapter": ("benchbox.platforms.dataframe.lakesail_df", None),
    "DELTA_SPARK_AVAILABLE": ("benchbox.platforms.dataframe.pyspark_maintenance", False),
    "PYSPARK_DELTA_CAPABILITIES": ("benchbox.platforms.dataframe.pyspark_maintenance", None),
    "PYSPARK_PARQUET_CAPABILITIES": ("benchbox.platforms.dataframe.pyspark_maintenance", None),
    "PySparkMaintenanceOperations": ("benchbox.platforms.dataframe.pyspark_maintenance", None),
    "get_pyspark_maintenance_operations": ("benchbox.platforms.dataframe.pyspark_maintenance", None),
}


def __getattr__(name: str) -> Any:
    if name == "ducklake_maintenance":
        module = importlib.import_module("benchbox.platforms.dataframe.ducklake_maintenance")
        globals()[name] = module
        return module
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_path, default = target
    try:
        module = __import__(module_path, fromlist=[name])
    except (ImportError, OSError):
        value = default
    else:
        value = getattr(module, name, default)
    globals()[name] = value
    return value


__all__ = [
    "BenchmarkExecutionMixin",
    "DataFramePhases",
    "DataFrameRunOptions",
    "ExpressionFamilyAdapter",
    "ExpressionFamilyContext",
    "PandasFamilyAdapter",
    "PandasFamilyContext",
    "PolarsDataFrameAdapter",
    "POLARS_AVAILABLE",
    "PandasDataFrameAdapter",
    "PANDAS_AVAILABLE",
    "CuDFDataFrameAdapter",
    "CUDF_AVAILABLE",
    "DaskDataFrameAdapter",
    "DASK_AVAILABLE",
    "DataFusionDataFrameAdapter",
    "DATAFUSION_DF_AVAILABLE",
    "PySparkDataFrameAdapter",
    "PYSPARK_AVAILABLE",
    "PYSPARK_VERSION",
    "LakeSailDataFrameAdapter",
    "PySparkMaintenanceOperations",
    "get_pyspark_maintenance_operations",
    "PYSPARK_DELTA_CAPABILITIES",
    "PYSPARK_PARQUET_CAPABILITIES",
    "DELTA_SPARK_AVAILABLE",
    "DataFramePlatformChecker",
    "DataFrameFamily",
    "PlatformInfo",
    "PlatformStatus",
    "DATAFRAME_PLATFORMS",
    "format_platform_status_table",
    "get_installation_suggestion",
    "get_platform_error_message",
    "require_platform",
]
