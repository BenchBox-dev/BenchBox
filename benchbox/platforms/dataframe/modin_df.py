"""Modin DataFrame adapter for Pandas-family benchmarking.

This module provides the ModinDataFrameAdapter that implements the
PandasFamilyAdapter interface for Modin.

Modin is a drop-in replacement for Pandas that enables distributed
and parallelized DataFrame operations:
- Same Pandas API (df['column'], df[mask], .agg())
- Automatic parallelization with Ray or Dask backend
- Out-of-core support for datasets larger than memory

Usage:
    from benchbox.platforms.dataframe.modin_df import ModinDataFrameAdapter

    adapter = ModinDataFrameAdapter()
    ctx = adapter.create_context()

    # Load data
    adapter.load_table(ctx, "orders", [Path("orders.parquet")])

    # Execute query
    result = adapter.execute_query(ctx, query)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

# IMPORTANT: Configure Ray for lightweight local execution BEFORE importing Modin.
# Without this, Ray will:
# 1. Package the entire working directory (233MB+ including .git)
# 2. Spawn multiple workers that each create virtual environments
# 3. Download all dependencies on each worker
# See: https://github.com/ray-project/ray/issues/49783


def _initialize_ray_for_local_execution(num_cpus: int | None = None) -> bool:
    """Initialize Ray for lightweight local benchmarking.

    Must be called BEFORE importing modin.pandas to prevent heavyweight
    cluster setup including working directory packaging.

    Args:
        num_cpus: Number of CPUs to use (defaults to all available)

    Returns:
        True if Ray was initialized, False if already initialized or unavailable
    """
    try:
        import ray
    except ImportError:
        return False

    if ray.is_initialized():
        return False

    # Disable Ray's uv runtime_env hook which causes issues when running under `uv run`:
    # - Spawns workers that try to create their own venvs with uv
    # - Causes VIRTUAL_ENV mismatch warnings
    # - Can lead to Python version mismatches between driver and workers
    # See: https://github.com/ray-project/ray/issues/56583
    # See: https://github.com/ray-project/ray/issues/59639
    #
    # RAY_ENABLE_UV_RUN_RUNTIME_ENV controls whether Ray auto-detects `uv run` in parent
    # processes and sets py_executable="uv run ..." for workers. This causes workers to
    # spawn with `uv run`, creating their own virtual environments and downloading deps.
    # Disabling this makes Ray use the current Python interpreter directly.
    os.environ["RAY_ENABLE_UV_RUN_RUNTIME_ENV"] = "0"
    os.environ.pop("RAY_RUNTIME_ENV_HOOK", None)

    # Initialize Ray with minimal configuration for local execution
    # Key settings to prevent heavyweight setup:
    # - No logging to reduce overhead
    # - local_mode=False (True is deprecated and has issues)
    init_kwargs: dict[str, Any] = {
        "ignore_reinit_error": True,
        "include_dashboard": False,  # Don't need dashboard for benchmarking
        "logging_level": logging.WARNING,  # Reduce Ray's verbose logging
    }

    if num_cpus is not None:
        init_kwargs["num_cpus"] = num_cpus

    ray.init(**init_kwargs)
    return True


# Check if we should use Ray or Dask based on environment
_MODIN_ENGINE = os.environ.get("MODIN_ENGINE", "ray").lower()

# NOTE: We do NOT initialize Ray at module import time. Ray initialization is
# deferred to when the adapter is actually instantiated (in __init__). This
# prevents Ray from starting up just to check if Modin is available (e.g.,
# during `benchbox platforms list`).

try:
    # Import modin.pandas to check availability. Modin handles lazy Ray
    # initialization internally - Ray won't start until DataFrame operations
    # are actually performed.
    import modin.pandas as mpd

    MODIN_AVAILABLE = True
except ImportError:
    mpd = None  # type: ignore[assignment]
    MODIN_AVAILABLE = False

# Import pandas for type conversions (Modin uses pandas internally)
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    PANDAS_AVAILABLE = False

# These imports must come after Ray/Modin initialization above
from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration  # noqa: E402
from benchbox.platforms.dataframe.pandas_df import _pandas_string_columns  # noqa: E402
from benchbox.platforms.dataframe.pandas_family import (  # noqa: E402
    PandasFamilyAdapter,
)
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN, has_trailing_delimiter  # noqa: E402

logger = logging.getLogger(__name__)

# Type alias for Modin DataFrame (when available)
ModinDF = mpd.DataFrame if MODIN_AVAILABLE else Any


class ModinDataFrameAdapter(PandasFamilyAdapter[ModinDF]):
    """Modin adapter for Pandas-family DataFrame benchmarking.

    This adapter provides distributed/parallelized DataFrame operations
    using Modin with the Ray or Dask backend.

    Features:
    - Drop-in Pandas replacement with parallel execution
    - Automatic partitioning across CPU cores
    - Out-of-core support for large datasets
    - Same API as Pandas (eager evaluation)

    Attributes:
        engine: The Modin execution engine ('ray' or 'dask')
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        engine: str = "ray",
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the Modin adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            engine: Modin execution engine ('ray' or 'dask')
            tuning_config: Optional tuning configuration for performance optimization

        Raises:
            ImportError: If Modin is not installed
        """
        if not MODIN_AVAILABLE:
            raise ImportError("Modin not installed. Install with: pip install modin[ray] or pip install modin[dask]")

        if not PANDAS_AVAILABLE:
            raise ImportError("Pandas not installed. Modin requires Pandas.")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # Default value (may be overridden by tuning config)
        self.engine = engine

        # Validate and apply tuning configuration (before configuring engine)
        self._validate_and_apply_tuning()

        # Initialize Ray for local execution if using Ray backend.
        # This must happen BEFORE any Modin DataFrame operations to prevent
        # Modin from auto-initializing Ray with heavyweight defaults.
        if self.engine == "ray":
            _initialize_ray_for_local_execution()

        # Configure the engine after tuning settings are applied
        self._configure_engine()

    def _apply_tuning(self) -> None:
        """Apply Modin-specific tuning configuration.

        This method applies tuning settings from the configuration to the Modin
        runtime environment. Settings include:
        - engine_affinity (ray or dask backend)
        - worker_count for number of partitions
        """
        config = self._tuning_config

        # Apply engine_affinity setting (maps to Modin engine)
        if config.execution.engine_affinity is not None and config.execution.engine_affinity in ("ray", "dask"):
            self.engine = config.execution.engine_affinity
            self._log_verbose(f"Set engine={self.engine} from tuning configuration")

        # Apply worker_count setting (controls Modin partitions)
        if config.parallelism.worker_count is not None:
            os.environ["MODIN_CPUS"] = str(config.parallelism.worker_count)
            self._log_verbose(f"Set MODIN_CPUS={config.parallelism.worker_count} from tuning configuration")

    def _configure_engine(self) -> None:
        """Configure the Modin execution engine."""
        # Set the engine before any Modin operations
        os.environ.setdefault("MODIN_ENGINE", self.engine)

        if self.verbose:
            logger.info(f"Modin engine configured: {self.engine}")

    def close(self) -> None:
        """Clean up Modin resources.

        For Modin with Ray backend, this attempts to shut down Ray gracefully.
        For Dask backend, Dask manages its own cleanup.

        Note: In most cases Modin manages resources automatically, but calling
        close() explicitly can help free memory in long-running processes.
        """
        if self.engine == "ray":
            try:
                import ray

                if ray.is_initialized():
                    # Don't shut down Ray entirely as other code may be using it
                    # Just log that we're done with our adapter
                    logger.debug("Modin adapter closed (Ray remains initialized)")
            except ImportError:
                pass
            except Exception as e:
                logger.debug(f"Failed to check Ray status: {e}")

    def __del__(self) -> None:
        """Clean up resources on garbage collection."""
        # Guard against __del__ being called before __init__ completes
        if hasattr(self, "engine"):
            self.close()

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "Modin"

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
        column_types: list[str] | None = None,
    ) -> ModinDF:
        """Read a CSV file into a Modin DataFrame.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            header: Row to use as header (None for no header)
            names: Column names (if header is None)
            null_marker: When not None, enables trailing-delimiter probing (TPC-style rows end with a spurious delimiter).

        Returns:
            Modin DataFrame with the file contents
        """
        read_kwargs: dict[str, Any] = {
            "sep": delimiter,
            "header": header,
            "on_bad_lines": "skip",
        }

        # Add column names if provided
        string_columns: list[str] = []
        if names:
            read_kwargs["names"] = names
            # Read declared text columns as object and (below) restore '' for empty
            # fields, mirroring the pandas adapter so the empty-string contract holds
            # on Modin's raw-CSV path too.
            string_columns = _pandas_string_columns(names, column_types, set())
            if string_columns:
                read_kwargs["dtype"] = dict.fromkeys(string_columns, "object")

        # Trailing-delimiter probing only for TPC-style sources (null_marker is not None).
        if null_marker is not None and names and has_trailing_delimiter(path, delimiter, names):
            extended_names = names + [TRAILING_DUMMY_COLUMN]
            read_kwargs["names"] = extended_names

        df = mpd.read_csv(path, **read_kwargs)

        # Match the SQL dialect's empty-field semantics (null_marker None -> keep '';
        # '' -> NULL), as the pandas adapter does.
        if null_marker is None and string_columns:
            for column in string_columns:
                if column in df.columns:
                    # Per-column (not df[list]=...) so it works across dask/modin/cudf,
                    # whose multi-column assignment support differs from pandas.
                    df[column] = df[column].fillna("")

        # Drop trailing column if present
        if TRAILING_DUMMY_COLUMN in df.columns:
            df = df.drop(columns=[TRAILING_DUMMY_COLUMN])

        return df

    def read_parquet(self, path: Path) -> ModinDF:
        """Read a Parquet file into a Modin DataFrame.

        Args:
            path: Path to the Parquet file

        Returns:
            Modin DataFrame with the file contents
        """
        return mpd.read_parquet(path)

    def to_datetime(self, series: Any) -> Any:
        """Convert a Series to datetime type.

        Modin uses pandas' to_datetime under the hood.

        Args:
            series: The Series to convert

        Returns:
            Datetime Series
        """
        return pd.to_datetime(series)

    def timedelta_days(self, days: int) -> timedelta:
        """Create a timedelta representing the given number of days.

        Args:
            days: Number of days

        Returns:
            Pandas Timedelta object
        """
        return pd.Timedelta(days=days)

    def concat(self, dfs: list[ModinDF]) -> ModinDF:
        """Concatenate multiple DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        if len(dfs) == 1:
            return dfs[0]
        return mpd.concat(dfs, ignore_index=True)

    def get_row_count(self, df: ModinDF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """
        return len(df)

    def _get_first_row(self, df: ModinDF) -> tuple | None:
        """Get the first row of a Modin DataFrame.

        Uses head(1) to avoid computing len() on the entire DataFrame,
        which can be expensive for distributed DataFrames.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None if empty
        """
        # Use head(1) to avoid full DataFrame computation
        head_df = df.head(1)
        if len(head_df) == 0:
            return None

        return tuple(head_df.iloc[0])

    # =========================================================================
    # Modin-Specific Helper Methods
    # =========================================================================

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "engine": self.engine,
            "working_dir": str(self.working_dir),
        }

        if MODIN_AVAILABLE:
            import modin

            info["version"] = modin.__version__

        if PANDAS_AVAILABLE:
            info["pandas_version"] = pd.__version__

        return info

    def _merge_frames(
        self,
        left: ModinDF,
        right: ModinDF,
        *,
        on: str | list[str] | None,
        left_on: str | list[str] | None,
        right_on: str | list[str] | None,
        how: str,
    ) -> ModinDF:
        """Use Modin's module-level merge implementation."""
        return mpd.merge(
            left,
            right,
            on=on,
            left_on=left_on,
            right_on=right_on,
            how=how,
        )

    def to_pandas(self, df: ModinDF) -> Any:
        """Convert Modin DataFrame to Pandas DataFrame.

        This can be useful for operations that require Pandas-native
        functionality or for final result extraction.

        Args:
            df: Modin DataFrame

        Returns:
            Pandas DataFrame
        """
        # Use _to_pandas() if available (Modin internal), otherwise return as-is
        # Note: Modin's public API uses _to_pandas() despite the underscore prefix
        if hasattr(df, "_to_pandas"):
            try:
                return df._to_pandas()
            except Exception as e:
                logger.debug(f"Failed to convert to pandas via _to_pandas: {e}")
                return df
        return df
