"""cuDF DataFrame adapter for Pandas-family benchmarking.

This module provides the CuDFDataFrameAdapter that implements the
PandasFamilyAdapter interface for NVIDIA cuDF.

cuDF is a GPU DataFrame library that provides Pandas-like API with
massive performance improvements through GPU acceleration:
- Same Pandas API (df['column'], df[mask], .agg())
- GPU-accelerated operations with CUDA
- Integration with RAPIDS ecosystem

Usage:
    from benchbox.platforms.dataframe.cudf_df import CuDFDataFrameAdapter

    adapter = CuDFDataFrameAdapter()
    ctx = adapter.create_context()

    # Load data
    adapter.load_table(ctx, "orders", [Path("orders.parquet")])

    # Execute query
    result = adapter.execute_query(ctx, query)

Note:
    cuDF requires an NVIDIA GPU with CUDA support.
    Install with: pip install cudf-cu12 (for CUDA 12.x)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    import cudf

    CUDF_AVAILABLE = True
except ImportError:
    cudf = None  # type: ignore[assignment]
    CUDF_AVAILABLE = False

# Import pandas for type conversions and CPU fallback
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    PANDAS_AVAILABLE = False

from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe.pandas_family import (
    PandasFamilyAdapter,
)
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN, has_trailing_delimiter

logger = logging.getLogger(__name__)

# Type alias for cuDF DataFrame (when available)
CuDFDF = cudf.DataFrame if CUDF_AVAILABLE else Any


class CuDFDataFrameAdapter(PandasFamilyAdapter[CuDFDF]):
    """cuDF adapter for Pandas-family DataFrame benchmarking.

    This adapter provides GPU-accelerated DataFrame operations
    using NVIDIA cuDF.

    Features:
    - GPU-accelerated operations with CUDA
    - Same API as Pandas (eager evaluation)
    - Automatic GPU memory management
    - Integration with RAPIDS ML/graph libraries

    Attributes:
        device_id: CUDA device ID to use
        spill_to_host: Enable GPU memory spilling to host
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        device_id: int = 0,
        spill_to_host: bool = True,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the cuDF adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            device_id: CUDA device ID to use (default: 0)
            spill_to_host: Enable GPU memory spilling to host RAM
            tuning_config: Optional tuning configuration for performance optimization

        Raises:
            ImportError: If cuDF is not installed
        """
        if not CUDF_AVAILABLE:
            raise ImportError("cuDF not installed. Install with: pip install cudf-cu12 (for CUDA 12.x)")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # Default values (may be overridden by tuning config)
        self.device_id = device_id
        self.spill_to_host = spill_to_host
        self._pool_type = "default"

        # Validate and apply tuning configuration (before configuring GPU)
        self._validate_and_apply_tuning()

        # Configure GPU after tuning settings are applied
        self._configure_gpu()

    def _apply_tuning(self) -> None:
        """Apply cuDF-specific tuning configuration.

        This method applies tuning settings from the configuration to the cuDF
        runtime environment. Settings include:
        - device_id for GPU device selection
        - spill_to_host for GPU memory management
        - pool_type for memory allocator configuration
        """
        config = self._tuning_config

        # Apply GPU settings if enabled
        if config.gpu.enabled:
            # Apply device_id setting
            if config.gpu.device_id is not None:
                self.device_id = config.gpu.device_id
                self._log_verbose(f"Set device_id={self.device_id} from tuning configuration")

            # Apply spill_to_host setting
            self.spill_to_host = config.gpu.spill_to_host
            self._log_verbose(f"Set spill_to_host={self.spill_to_host} from tuning configuration")

            # Apply pool_type setting
            self._pool_type = config.gpu.pool_type
            self._log_verbose(f"Set pool_type={self._pool_type} from tuning configuration")

    def _configure_gpu(self) -> None:
        """Configure GPU settings for cuDF."""
        try:
            import rmm

            # Configure RMM (RAPIDS Memory Manager) based on pool_type
            rmm_kwargs: dict[str, Any] = {
                "devices": self.device_id,
            }

            # Set pool allocator based on pool_type from tuning configuration
            if self._pool_type == "pool":
                rmm_kwargs["pool_allocator"] = True
            elif self._pool_type == "managed":
                rmm_kwargs["managed_memory"] = True
            elif self._pool_type == "cuda":
                # Use default CUDA allocator (no pooling)
                rmm_kwargs["pool_allocator"] = False
            else:
                # Default: use pool allocator for performance
                rmm_kwargs["pool_allocator"] = True

            rmm.reinitialize(**rmm_kwargs)

            if self.verbose:
                # Log GPU information
                import cupy

                device = cupy.cuda.Device(self.device_id)
                mem_info = device.mem_info
                logger.info(
                    f"cuDF using GPU {self.device_id}: "
                    f"{mem_info[1] / 1e9:.1f}GB total, "
                    f"{mem_info[0] / 1e9:.1f}GB free, "
                    f"pool_type={self._pool_type}"
                )
        except Exception as e:
            if self.verbose:
                logger.warning(f"Could not configure GPU: {e}")

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "cuDF"

    # =========================================================================
    # Data Loading Methods
    # =========================================================================

    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        header: int | None = 0,
        names: list[str] | None = None,
        null_marker: str | None = None,
        column_types: list[str] | None = None,  # noqa: ARG002 - accepted for signature parity; cuDF infers types
    ) -> CuDFDF:
        """Read a CSV file into a cuDF DataFrame.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            header: Row to use as header (None for no header)
            names: Column names (if header is None)
            null_marker: When not None, enables trailing-delimiter probing (TPC-style rows end with a spurious delimiter).

        Returns:
            cuDF DataFrame with the file contents
        """
        read_kwargs: dict[str, Any] = {
            "sep": delimiter,
        }

        # cuDF uses header=-1 for no header (different from Pandas)
        if header is None:
            read_kwargs["header"] = None
        else:
            read_kwargs["header"] = header

        # Add column names if provided
        if names:
            read_kwargs["names"] = names

        # Trailing-delimiter probing only for TPC-style sources (null_marker is not None).
        if null_marker is not None and names and has_trailing_delimiter(path, delimiter, names):
            extended_names = names + [TRAILING_DUMMY_COLUMN]
            read_kwargs["names"] = extended_names

        df = cudf.read_csv(path, **read_kwargs)

        # Drop trailing column if present
        if TRAILING_DUMMY_COLUMN in df.columns:
            df = df.drop(columns=[TRAILING_DUMMY_COLUMN])

        return df

    def read_parquet(self, path: Path) -> CuDFDF:
        """Read a Parquet file into a cuDF DataFrame.

        Args:
            path: Path to the Parquet file

        Returns:
            cuDF DataFrame with the file contents
        """
        return cudf.read_parquet(path)

    def to_datetime(self, series: Any) -> Any:
        """Convert a Series to datetime type.

        Args:
            series: The Series to convert

        Returns:
            Datetime Series
        """
        return cudf.to_datetime(series)

    def timedelta_days(self, days: int) -> timedelta:
        """Create a timedelta representing the given number of days.

        Note: cuDF operations use pandas Timedelta which is compatible.

        Args:
            days: Number of days

        Returns:
            Pandas Timedelta object
        """
        if PANDAS_AVAILABLE:
            return pd.Timedelta(days=days)
        # Fallback to standard library timedelta
        return timedelta(days=days)

    def concat(self, dfs: list[CuDFDF]) -> CuDFDF:
        """Concatenate multiple DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        if len(dfs) == 1:
            return dfs[0]
        return cudf.concat(dfs, ignore_index=True)

    def get_row_count(self, df: CuDFDF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """
        return len(df)

    def _get_first_row(self, df: CuDFDF) -> tuple | None:
        """Get the first row of a cuDF DataFrame.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None if empty
        """
        if len(df) == 0:
            return None

        # Convert to pandas for reliable row extraction
        return tuple(df.head(1).to_pandas().iloc[0])

    # =========================================================================
    # cuDF-Specific Helper Methods
    # =========================================================================

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "device_id": self.device_id,
            "spill_to_host": self.spill_to_host,
            "working_dir": str(self.working_dir),
        }

        if CUDF_AVAILABLE:
            info["version"] = cudf.__version__

            # Get GPU information if available
            try:
                import cupy

                device = cupy.cuda.Device(self.device_id)
                mem_info = device.mem_info
                info["gpu_name"] = cupy.cuda.runtime.getDeviceProperties(self.device_id)["name"]
                info["gpu_memory_total_gb"] = round(mem_info[1] / 1e9, 2)
                info["gpu_memory_free_gb"] = round(mem_info[0] / 1e9, 2)
            except Exception:
                pass

        return info

    def _merge_frames(
        self,
        left: CuDFDF,
        right: CuDFDF,
        *,
        on: str | list[str] | None,
        left_on: str | list[str] | None,
        right_on: str | list[str] | None,
        how: str,
    ) -> CuDFDF:
        """Use cuDF's merge implementation."""
        return cudf.merge(
            left,
            right,
            on=on,
            left_on=left_on,
            right_on=right_on,
            how=how,
        )

    def to_pandas(self, df: CuDFDF) -> Any:
        """Convert cuDF DataFrame to Pandas DataFrame.

        This transfers data from GPU to CPU memory.

        Args:
            df: cuDF DataFrame

        Returns:
            Pandas DataFrame
        """
        return df.to_pandas()

    def from_pandas(self, df: Any) -> CuDFDF:
        """Convert Pandas DataFrame to cuDF DataFrame.

        This transfers data from CPU to GPU memory.

        Args:
            df: Pandas DataFrame

        Returns:
            cuDF DataFrame
        """
        return cudf.from_pandas(df)

    def get_gpu_memory_usage(self) -> dict[str, float]:
        """Get current GPU memory usage.

        Returns:
            Dictionary with memory usage in GB
        """
        try:
            import cupy

            device = cupy.cuda.Device(self.device_id)
            mem_info = device.mem_info
            return {
                "free_gb": round(mem_info[0] / 1e9, 2),
                "total_gb": round(mem_info[1] / 1e9, 2),
                "used_gb": round((mem_info[1] - mem_info[0]) / 1e9, 2),
            }
        except Exception:
            return {"free_gb": 0.0, "total_gb": 0.0, "used_gb": 0.0}
