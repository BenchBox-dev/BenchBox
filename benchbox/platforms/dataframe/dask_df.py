"""Dask DataFrame adapter for Pandas-family benchmarking.

This module provides the DaskDataFrameAdapter that implements the
PandasFamilyAdapter interface for Dask.

Dask is a parallel computing library that enables:
- Lazy evaluation with task graph optimization
- Out-of-core processing for datasets larger than memory
- Distributed computing across clusters
- Pandas-like API with .compute() to materialize results

Usage:
    from benchbox.platforms.dataframe.dask_df import DaskDataFrameAdapter

    adapter = DaskDataFrameAdapter()
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
import re
import shutil
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    import dask.dataframe as dd
    from dask.distributed import Client, LocalCluster

    DASK_AVAILABLE = True
except ImportError:
    dd = None  # type: ignore[assignment]
    Client = None  # type: ignore[assignment,misc]
    LocalCluster = None  # type: ignore[assignment,misc]
    DASK_AVAILABLE = False

# Import pandas for type conversions
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    PANDAS_AVAILABLE = False

from benchbox.core.dataframe.profiling import QueryExecutionProfile
from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe._result_helpers import build_failure_result_dict
from benchbox.platforms.dataframe.pandas_family import (
    PandasFamilyAdapter,
)
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN, has_trailing_delimiter

logger = logging.getLogger(__name__)

# Type alias for Dask DataFrame (when available)
DaskDF = dd.DataFrame if DASK_AVAILABLE else Any

_RESOURCE_ENVELOPE_PATTERNS = (
    "exit 137",
    "exit code 137",
    "returncode 137",
    "returned non-zero exit status 137",
    "sigkill",
    "signal 9",
    "killedworker",
    "worker was killed",
    "worker died",
    "exceeded memory",
    "memory budget",
    "memoryerror",
)
_DEFAULT_LOCAL_MEMORY_LIMIT = "2GB"
_DEFAULT_LOCAL_WORKER_CAP = 2
_DEFAULT_LOCAL_THREADS_PER_WORKER_CAP = 2
_GUARDED_TPCH_Q10_NAME = "returned item reporting"
_RESOURCE_ENVELOPE_SKIP_QUERY_IDS = frozenset({"Q10"})


class DaskResourceEnvelopeError(RuntimeError):
    """Raised when Dask reports a local resource-envelope failure."""


def _cap_default_memory_limit(memory_limit: str) -> str:
    """Cap implicit local worker memory while preserving explicit user limits."""
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*(gib|gb)\s*$", memory_limit, re.IGNORECASE)
    if match is None:
        return memory_limit

    value = float(match.group(1))
    if value < 1:
        return "1GB"
    if value > 2:
        return _DEFAULT_LOCAL_MEMORY_LIMIT
    return memory_limit


class DaskDataFrameAdapter(PandasFamilyAdapter[DaskDF]):
    """Dask adapter for Pandas-family DataFrame benchmarking.

    This adapter provides lazy, distributed DataFrame operations
    using Dask. Unlike other Pandas-family adapters, Dask uses
    lazy evaluation - operations build a task graph that is only
    executed when .compute() is called.

    Features:
    - Lazy evaluation with task graph optimization
    - Out-of-core support for datasets larger than memory
    - Distributed computing with optional cluster
    - Pandas-like API

    Attributes:
        n_workers: Number of worker processes
        threads_per_worker: Threads per worker process
        use_distributed: Use distributed scheduler
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        n_workers: int | None = None,
        threads_per_worker: int | None = None,
        use_distributed: bool = True,
        scheduler_address: str | None = None,
        memory_limit: str | None = None,
        spill_directory: str | Path | None = None,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the Dask adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            n_workers: Number of worker processes (default: CPU count)
            threads_per_worker: Threads per worker (default: conservative local envelope)
            use_distributed: Use distributed scheduler (default: local resource envelope)
            scheduler_address: Connect to existing scheduler (e.g., 'tcp://...')
            memory_limit: Memory limit per local worker (e.g., '4GB')
            spill_directory: Directory for Dask spill files. Explicit directories are not deleted by close().
            tuning_config: Optional tuning configuration for performance optimization

        Raises:
            ImportError: If Dask is not installed
        """
        if not DASK_AVAILABLE:
            raise ImportError("Dask not installed. Install with: pip install dask[distributed]")

        if not PANDAS_AVAILABLE:
            raise ImportError("Pandas not installed. Dask requires Pandas.")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # Default values (may be overridden by tuning config)
        self.n_workers = n_workers
        self.threads_per_worker = threads_per_worker if threads_per_worker is not None else 1
        self.use_distributed = use_distributed
        self.scheduler_address = scheduler_address
        self._memory_limit: str | None = memory_limit
        self._spill_to_disk = False
        self._configured_spill_directory = Path(spill_directory).expanduser() if spill_directory else None
        self._spill_directory: Path | None = None
        self._owns_spill_directory = False
        self._n_workers_configured = n_workers is not None
        self._threads_per_worker_configured = threads_per_worker is not None
        self._memory_limit_configured = memory_limit is not None

        self._client: Client | None = None
        self._cluster: LocalCluster | None = None

        # Validate and apply tuning configuration (before setting up cluster)
        self._validate_and_apply_tuning()
        self._apply_local_resource_envelope_defaults()

        if use_distributed or scheduler_address:
            self._setup_distributed()

    def _apply_tuning(self) -> None:
        """Apply Dask-specific tuning configuration.

        This method applies tuning settings from the configuration to the Dask
        runtime environment. Settings include:
        - worker_count for distributed computing
        - threads_per_worker for thread-based parallelism
        - memory_limit per worker
        - spill_to_disk for out-of-core computation
        """
        config = self._tuning_config

        # Apply worker count setting
        if config.parallelism.worker_count is not None:
            self.n_workers = config.parallelism.worker_count
            self._n_workers_configured = True
            self._log_verbose(f"Set n_workers={self.n_workers} from tuning configuration")

        # Apply threads per worker setting
        if config.parallelism.threads_per_worker is not None:
            self.threads_per_worker = config.parallelism.threads_per_worker
            self._threads_per_worker_configured = True
            self._log_verbose(f"Set threads_per_worker={self.threads_per_worker} from tuning configuration")

        # Apply memory limit setting
        if config.memory.memory_limit is not None:
            self._memory_limit = config.memory.memory_limit
            self._memory_limit_configured = True
            self._log_verbose(f"Set memory_limit={self._memory_limit} from tuning configuration")

        # Apply spill to disk setting
        if config.memory.spill_to_disk:
            self._spill_to_disk = True
            self._log_verbose("Enabled spill to disk from tuning configuration")

        spill_directory = getattr(config.memory, "spill_directory", None)
        if spill_directory is not None:
            self._configured_spill_directory = Path(spill_directory).expanduser()

    def _apply_local_resource_envelope_defaults(self) -> None:
        """Apply conservative defaults for local distributed Dask runs."""
        if not self.use_distributed or self.scheduler_address:
            return

        from benchbox.core.dataframe.tuning import get_smart_defaults

        defaults = get_smart_defaults("dask")

        if not self._n_workers_configured and defaults.parallelism.worker_count is not None:
            self.n_workers = min(defaults.parallelism.worker_count, _DEFAULT_LOCAL_WORKER_CAP)

        if not self._threads_per_worker_configured and defaults.parallelism.threads_per_worker is not None:
            self.threads_per_worker = min(
                defaults.parallelism.threads_per_worker,
                _DEFAULT_LOCAL_THREADS_PER_WORKER_CAP,
            )

        if not self._memory_limit_configured and defaults.memory.memory_limit is not None:
            self._memory_limit = _cap_default_memory_limit(defaults.memory.memory_limit)

        if defaults.memory.spill_to_disk:
            self._spill_to_disk = True

    def _configure_spill_to_disk(self) -> None:
        """Configure Dask spill thresholds and local directory."""
        if not self._spill_to_disk:
            return

        import dask

        self._resolve_spill_directory()
        dask.config.set(
            {
                "distributed.worker.memory.spill": True,
                "distributed.worker.memory.target": 0.6,
                "distributed.worker.memory.pause": 0.8,
            }
        )

    def _resolve_spill_directory(self) -> Path:
        """Return the Dask spill directory, creating an owned temp dir if needed."""
        spill_directory = getattr(self, "_spill_directory", None)
        if spill_directory is not None:
            return spill_directory

        configured_spill_directory = getattr(self, "_configured_spill_directory", None)
        if configured_spill_directory is not None:
            configured_spill_directory.mkdir(parents=True, exist_ok=True)
            self._spill_directory = configured_spill_directory
            return self._spill_directory

        parent = Path(self.working_dir) / ".benchbox-dask-spill"
        parent.mkdir(parents=True, exist_ok=True)
        self._spill_directory = Path(tempfile.mkdtemp(prefix="run-", dir=parent))
        self._owns_spill_directory = True
        return self._spill_directory

    def _setup_distributed(self) -> None:
        """Set up the Dask distributed scheduler."""
        try:
            if self.scheduler_address:
                # Connect to existing scheduler
                self._client = Client(self.scheduler_address)
                if self.verbose:
                    logger.info(f"Connected to Dask scheduler at {self.scheduler_address}")
            else:
                self._configure_spill_to_disk()

                # Create local cluster with tuning settings
                cluster_kwargs: dict[str, Any] = {
                    "n_workers": self.n_workers,
                    "threads_per_worker": self.threads_per_worker,
                    "silence_logs": logging.INFO if self.verbose else logging.ERROR,
                }

                # Apply memory limit from tuning configuration
                if self._memory_limit is not None:
                    cluster_kwargs["memory_limit"] = self._memory_limit

                if self._spill_directory is not None:
                    cluster_kwargs["local_directory"] = str(self._spill_directory)

                self._cluster = LocalCluster(**cluster_kwargs)
                self._client = Client(self._cluster)
                if self.verbose:
                    logger.info(
                        f"Dask local cluster started: "
                        f"{self._cluster.scheduler.address}, "
                        f"{len(self._cluster.workers)} workers"
                    )
                    if self._memory_limit:
                        logger.info(f"Memory limit per worker: {self._memory_limit}")
                    if self._spill_directory:
                        logger.info(f"Dask spill directory: {self._spill_directory}")
                    if hasattr(self._cluster, "dashboard_link"):
                        logger.info(f"Dashboard: {self._cluster.dashboard_link}")
        except Exception as e:
            self._cleanup_owned_spill_directory()
            raise DaskResourceEnvelopeError(
                f"Could not set up Dask distributed resource envelope. Original error: {type(e).__name__}: {e}"
            ) from e

    def __del__(self) -> None:
        """Clean up distributed resources."""
        self.close()

    def close(self) -> None:
        """Close the Dask client and cluster."""
        if not hasattr(self, "_client"):
            return
        if self._client is not None:
            try:
                self._client.close()
            except Exception as e:
                logger.debug(f"Failed to close Dask client: {e}")
            self._client = None

        if self._cluster is not None:
            try:
                self._cluster.close()
            except Exception as e:
                logger.debug(f"Failed to close Dask cluster: {e}")
            self._cluster = None

        self._cleanup_owned_spill_directory()

    def _cleanup_owned_spill_directory(self) -> None:
        """Remove only spill directories created by this adapter instance."""
        if not getattr(self, "_owns_spill_directory", False):
            return

        spill_directory = getattr(self, "_spill_directory", None)
        if spill_directory is None:
            return

        try:
            shutil.rmtree(spill_directory, ignore_errors=True)
            parent = spill_directory.parent
            if parent.name == ".benchbox-dask-spill":
                try:
                    parent.rmdir()
                except OSError:
                    pass
        finally:
            self._spill_directory = None
            self._owns_spill_directory = False

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "Dask"

    def execute_query(self, ctx: Any, query: Any, query_id: str | None = None) -> dict[str, Any]:
        """Execute a query, guarding known parent-killing Dask graphs."""
        qid = str(query_id or getattr(query, "query_id", "unknown"))
        diagnostic = self._guarded_resource_query_diagnostic(query, qid)
        if diagnostic is not None:
            logger.error("Query %s failed: %s", qid, diagnostic)
            return build_failure_result_dict(
                query_id=qid,
                execution_time_seconds=0.0,
                error_message=diagnostic,
            )

        return super().execute_query(ctx, query, query_id=query_id)

    def execute_query_profiled(
        self,
        ctx: Any,
        query: Any,
        query_id: str | None = None,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], QueryExecutionProfile]:
        """Execute a profiled query, guarding known parent-killing Dask graphs."""
        qid = str(query_id or getattr(query, "query_id", "unknown"))
        diagnostic = self._guarded_resource_query_diagnostic(query, qid)
        if diagnostic is not None:
            logger.error("Query %s failed: %s", qid, diagnostic)
            return (
                build_failure_result_dict(
                    query_id=qid,
                    execution_time_seconds=0.0,
                    error_message=diagnostic,
                ),
                QueryExecutionProfile(
                    query_id=qid,
                    execution_time_ms=0.0,
                    platform=self.platform_name,
                    lazy_evaluation=True,
                    metrics={"resource_envelope_guarded": True},
                ),
            )

        return super().execute_query_profiled(ctx, query, query_id=query_id, **kwargs)

    def _guarded_resource_query_diagnostic(self, query: Any, query_id: str) -> str | None:
        """Return a diagnostic when a known Dask graph can kill the parent process."""
        query_name = str(getattr(query, "query_name", "")).strip().lower()
        if query_id.strip().upper() != "Q10" or query_name != _GUARDED_TPCH_Q10_NAME:
            return None

        return (
            "Dask resource-envelope failure before query execution: TPC-H Q10 Returned Item Reporting "
            "is guarded because this Pandas-family Dask graph has been observed to terminate the parent "
            f"benchmark process with exit 137 on local runs. Envelope: {self._resource_envelope_settings()}. "
            "The query was not executed to preserve process stability; use a query subset excluding Q10 "
            "or another DataFrame platform when Q10 coverage is required."
        )

    def _collect_skip_query_ids(self, benchmark_instance: Any | None) -> set[str]:
        """Add Dask resource-envelope skips to benchmark-provided skip lists.

        The TPC-H Q10 OOM that motivated this guard is specific to the local
        single-machine cluster envelope. When the user provides an external
        ``scheduler_address`` or explicitly requests a distributed cluster,
        Q10 should run normally — skipping it for those runs would lose
        legitimate full-suite coverage.
        """
        skip_query_ids = super()._collect_skip_query_ids(benchmark_instance)
        self._resource_envelope_skip_query_ids: set[str] = set()
        if self._is_tpch_benchmark(benchmark_instance) and self._is_local_envelope():
            self._resource_envelope_skip_query_ids = set(_RESOURCE_ENVELOPE_SKIP_QUERY_IDS)
            skip_query_ids |= self._resource_envelope_skip_query_ids
            logger.warning(
                "Skipping TPC-H Q10 for dask-df local envelope: %s. "
                "Pass --platform-option scheduler_address=tcp://... to run Q10 on an external cluster.",
                self._tpch_q10_resource_envelope_diagnostic(),
            )
        return skip_query_ids

    def _is_local_envelope(self) -> bool:
        """Return True only for runs that use the constrained local single-machine cluster.

        Treat any external scheduler or explicit distributed cluster request as
        out-of-envelope: those runs have provisioned their own resources and
        must not lose Q10 coverage to the local-OOM guard.
        """
        if getattr(self, "scheduler_address", None):
            return False
        if getattr(self, "use_distributed", False):
            return False
        return True

    def _build_skipped_results(self, filtered_skip_query_ids: set[str]) -> list[dict[str, Any]]:
        """Build skipped results, preserving Dask resource-envelope skip reasons."""
        results = super()._build_skipped_results(filtered_skip_query_ids)
        resource_skip_query_ids = getattr(self, "_resource_envelope_skip_query_ids", set())
        for result in results:
            query_id = str(result.get("query_id", "")).strip().upper()
            if query_id in resource_skip_query_ids:
                result["error"] = self._tpch_q10_resource_envelope_diagnostic()
                result["dask_resource_envelope_guarded"] = True
        return results

    @staticmethod
    def _is_tpch_benchmark(benchmark_instance: Any | None) -> bool:
        """Return whether a benchmark instance is the TPC-H benchmark."""
        if benchmark_instance is None:
            return False
        benchmark_type = type(benchmark_instance)
        benchmark_name = str(
            getattr(benchmark_instance, "name", "") or getattr(benchmark_instance, "_name", "")
        ).lower()
        return (
            benchmark_type.__name__ == "TPCHBenchmark"
            or benchmark_type.__module__.startswith("benchbox.core.tpch")
            or "tpc-h" in benchmark_name
        )

    def _tpch_q10_resource_envelope_diagnostic(self) -> str:
        """Return the stable diagnostic for the guarded TPC-H Q10 path."""
        return (
            "Dask resource-envelope guard: TPC-H Q10 Returned Item Reporting is skipped because this "
            "Pandas-family Dask graph has been observed to terminate the parent benchmark process with "
            f"exit 137 on local runs. Envelope: {self._resource_envelope_settings()}. Use another "
            "DataFrame platform when Q10 coverage is required."
        )

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
    ) -> DaskDF:
        """Read a CSV file into a Dask DataFrame.

        This creates a lazy DataFrame - the actual reading happens
        when .compute() is called.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            header: Row to use as header (None for no header)
            names: Column names (if header is None)
            null_marker: When not None, enables trailing-delimiter probing (TPC-style rows end with a spurious delimiter).

        Returns:
            Dask DataFrame (lazy)
        """
        read_kwargs: dict[str, Any] = {
            "sep": delimiter,
            "header": header if header is not None else "infer",
            "on_bad_lines": "skip",
        }

        # Dask uses header='infer' for first row as header
        if header is None:
            read_kwargs["header"] = None

        # Add column names if provided
        if names:
            read_kwargs["names"] = names

        # Trailing-delimiter probing only for TPC-style sources (null_marker is not None).
        if null_marker is not None and names and has_trailing_delimiter(path, delimiter, names):
            extended_names = names + [TRAILING_DUMMY_COLUMN]
            read_kwargs["names"] = extended_names

        df = dd.read_csv(path, **read_kwargs)

        # Drop trailing column if present (lazy operation)
        if TRAILING_DUMMY_COLUMN in df.columns:
            df = df.drop(columns=[TRAILING_DUMMY_COLUMN])

        return df

    def read_parquet(self, path: Path) -> DaskDF:
        """Read a Parquet file into a Dask DataFrame.

        This creates a lazy DataFrame - the actual reading happens
        when .compute() is called.

        Args:
            path: Path to the Parquet file

        Returns:
            Dask DataFrame (lazy)
        """
        # Dask can read Parquet files efficiently with partition pruning
        return dd.read_parquet(path)

    def to_datetime(self, series: Any) -> Any:
        """Convert a Series to datetime type.

        For Dask, this uses pandas' to_datetime which works
        with Dask Series.

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

    def concat(self, dfs: list[DaskDF]) -> DaskDF:
        """Concatenate multiple DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame (lazy)
        """
        if len(dfs) == 1:
            return dfs[0]
        return dd.concat(dfs, ignore_index=True)

    def get_row_count(self, df: DaskDF) -> int:
        """Get the number of rows in a DataFrame.

        Note: This triggers computation for lazy DataFrames.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """
        # For Dask, len() triggers computation
        return self._run_with_resource_diagnostics("row count", lambda: len(df))

    def _get_first_row(self, df: DaskDF) -> tuple | None:
        """Get the first row of a Dask DataFrame.

        Note: This triggers computation to get the first row.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None if empty
        """
        # Compute just the first row to avoid loading entire dataset
        head_df = self._run_with_resource_diagnostics("first row", lambda: df.head(1))
        if len(head_df) == 0:
            return None

        return tuple(head_df.iloc[0])

    # =========================================================================
    # Dask-Specific Methods
    # =========================================================================

    def compute(self, df: DaskDF) -> Any:
        """Materialize a lazy Dask DataFrame.

        Triggers computation of the task graph and returns
        a Pandas DataFrame.

        Args:
            df: Dask DataFrame (lazy)

        Returns:
            Pandas DataFrame (materialized)
        """
        return self._run_with_resource_diagnostics("compute", df.compute)

    def persist(self, df: DaskDF) -> DaskDF:
        """Persist a Dask DataFrame in memory.

        Triggers computation but keeps result as Dask DataFrame
        distributed across workers.

        Args:
            df: Dask DataFrame

        Returns:
            Persisted Dask DataFrame
        """
        return self._run_with_resource_diagnostics("persist", df.persist)

    def _run_with_resource_diagnostics(self, operation: str, func: Any) -> Any:
        """Run a Dask operation and classify resource-envelope failures."""
        try:
            return func()
        except Exception as exc:
            diagnostic = self._resource_envelope_diagnostic(operation, exc)
            if diagnostic is not None:
                raise DaskResourceEnvelopeError(diagnostic) from exc
            raise

    def _resource_envelope_diagnostic(self, operation: str, exc: Exception) -> str | None:
        """Return a user-facing diagnostic for Dask worker/process kills."""
        error_text = f"{type(exc).__name__}: {exc}"
        normalized = error_text.lower()

        if not any(pattern in normalized for pattern in _RESOURCE_ENVELOPE_PATTERNS):
            return None

        envelope = self._resource_envelope_settings()
        return (
            f"Dask resource-envelope failure during {operation}: worker or subprocess was killed "
            f"by the operating system/resource manager. Envelope: {envelope}. "
            f"Original error: {error_text}"
        )

    def _resource_envelope_settings(self) -> str:
        """Return the Dask resource envelope used in diagnostics."""
        return (
            f"use_distributed={self.use_distributed}, "
            f"n_workers={self.n_workers}, "
            f"threads_per_worker={self.threads_per_worker}, "
            f"memory_limit={getattr(self, '_memory_limit', None) or 'unbounded'}, "
            f"spill_to_disk={getattr(self, '_spill_to_disk', False)}, "
            "spill_directory="
            f"{getattr(self, '_spill_directory', None) or getattr(self, '_configured_spill_directory', None) or 'default'}"
        )

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "n_workers": self.n_workers,
            "threads_per_worker": self.threads_per_worker,
            "use_distributed": self.use_distributed,
            "memory_limit": getattr(self, "_memory_limit", None),
            "spill_to_disk": getattr(self, "_spill_to_disk", False),
            "spill_directory": str(self._spill_directory) if getattr(self, "_spill_directory", None) else None,
            "working_dir": str(self.working_dir),
        }

        if DASK_AVAILABLE:
            import dask

            info["version"] = dask.__version__

        if self._client is not None:
            try:
                info["scheduler_address"] = self._client.scheduler.address  # type: ignore[union-attr]
                info["n_active_workers"] = len(self._client.scheduler_info()["workers"])
            except Exception as e:
                logger.debug(f"Failed to get scheduler info: {e}")

        return info

    def _merge_frames(
        self,
        left: DaskDF,
        right: DaskDF,
        *,
        on: str | list[str] | None,
        left_on: str | list[str] | None,
        right_on: str | list[str] | None,
        how: str,
    ) -> DaskDF:
        """Use Dask's lazy merge implementation."""
        return dd.merge(
            left,
            right,
            on=on,
            left_on=left_on,
            right_on=right_on,
            how=how,
        )

    def groupby_agg(
        self,
        df: DaskDF,
        by: str | list[str],
        agg_spec: dict[str, Any],
        as_index: bool = False,
    ) -> DaskDF:
        """Perform grouped aggregation with Dask-specific handling.

        Dask differences from Pandas:
        - Does not support as_index parameter in groupby()
        - Uses reset_index() to achieve same result as as_index=False
        - Does not support 'nunique' in agg() - must handle separately

        Note: This is a lazy operation.

        Args:
            df: Input DataFrame
            by: Column(s) to group by
            agg_spec: Aggregation specification. Supports:
                - Named aggs: {"sum_qty": ("qty", "sum"), "avg_price": ("price", "mean")}
                - Direct aggs: {"qty": "sum", "price": "mean"}
            as_index: Whether to use group columns as index (ignored for Dask, always False behavior)

        Returns:
            Aggregated DataFrame (lazy)
        """
        by_list = [by] if isinstance(by, str) else list(by)

        # Check for nunique aggregations (not supported in Dask agg)
        nunique_aggs = {}
        regular_aggs = {}

        for name, spec in agg_spec.items():
            if isinstance(spec, tuple) and len(spec) >= 2 and spec[1] == "nunique":
                nunique_aggs[name] = spec
            elif spec == "nunique":
                nunique_aggs[name] = (name, "nunique")
            else:
                regular_aggs[name] = spec

        if nunique_aggs:
            return self._groupby_agg_with_nunique(df, by_list, regular_aggs, nunique_aggs)

        # Detect if this is named aggregation (tuples) or direct style
        # Named: {"sum_qty": ("qty", "sum")} -> use **agg_spec
        # Direct: {"qty": "sum"} -> use agg(dict) without unpacking
        is_named_agg = any(isinstance(v, tuple) for v in regular_aggs.values())

        # Standard case: groupby().agg().reset_index()
        # Keep if/else for clarity: **aggs vs aggs is a subtle but important API difference
        if is_named_agg:  # noqa: SIM108
            result = df.groupby(by_list).agg(**regular_aggs)
        else:
            result = df.groupby(by_list).agg(regular_aggs)

        # Reset index to match as_index=False behavior
        if not as_index:
            result = result.reset_index()

        return result

    def _groupby_agg_with_nunique(
        self,
        df: DaskDF,
        by: list[str],
        regular_aggs: dict[str, Any],
        nunique_aggs: dict[str, tuple[str, str]],
    ) -> DaskDF:
        """Handle groupby with nunique aggregations separately.

        Dask does not support 'nunique' in .agg(). We compute nunique
        separately and merge the results.

        Args:
            df: Input DataFrame
            by: Group by columns
            regular_aggs: Standard aggregations
            nunique_aggs: Nunique aggregations to handle separately

        Returns:
            Combined aggregation result
        """
        # Compute regular aggregations if any
        if regular_aggs:
            result = df.groupby(by).agg(**regular_aggs).reset_index()
        else:
            # No regular aggs, just create a frame with group keys
            # Dask reset_index() doesn't support 'name' parameter
            size_result = df.groupby(by).size().reset_index()
            # Rename the size column (default name is 0 or 'size') and drop it
            size_cols = [c for c in size_result.columns if c not in by]
            result = size_result.drop(columns=size_cols) if size_cols else size_result

        # Add nunique columns separately
        for col_name, (source_col, _) in nunique_aggs.items():
            # Dask reset_index() doesn't support 'name' parameter
            nunique_result = df.groupby(by)[source_col].nunique().reset_index()
            # Rename the nunique column (will be named after source_col)
            nunique_result = nunique_result.rename(columns={source_col: col_name})
            result = result.merge(nunique_result, on=by)

        return result

    def groupby_size(
        self,
        df: DaskDF,
        by: str | list[str],
        name: str = "size",
    ) -> DaskDF:
        """Group by columns and count rows per group (Dask-specific).

        Dask doesn't support reset_index(name='...'), so we use a different approach.

        Args:
            df: Input DataFrame
            by: Column(s) to group by
            name: Name for the count column (default 'size')

        Returns:
            DataFrame with group columns and count column
        """
        by_list = [by] if isinstance(by, str) else list(by)
        # size() returns a Series, reset_index() makes it a DataFrame with default column name
        result = df.groupby(by_list).size().reset_index()
        # Rename the count column (it will be named after a number or 'size')
        # The count column is the last one that's not in by_list
        count_col = [c for c in result.columns if c not in by_list][0]
        if count_col != name:
            result = result.rename(columns={count_col: name})
        return result

    def repartition(self, df: DaskDF, npartitions: int) -> DaskDF:
        """Repartition a Dask DataFrame.

        Args:
            df: Dask DataFrame
            npartitions: Target number of partitions

        Returns:
            Repartitioned DataFrame
        """
        return df.repartition(npartitions=npartitions)

    def get_npartitions(self, df: DaskDF) -> int:
        """Get the number of partitions in a Dask DataFrame.

        Args:
            df: Dask DataFrame

        Returns:
            Number of partitions
        """
        return df.npartitions
