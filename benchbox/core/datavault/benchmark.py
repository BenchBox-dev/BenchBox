"""Data Vault benchmark implementation.

This module provides the main DataVaultBenchmark class that implements
a Data Vault 2.0 benchmark based on TPC-H source data.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional, Union

from benchbox.core.base_benchmark import BaseBenchmark

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

    from benchbox.utils.cloud_storage import DatabricksPath

PathLike = Union[Path, "CloudPath", "DatabricksPath"]

from benchbox.core.datavault.schema import (
    TABLES,
    TABLES_BY_NAME,
    get_create_all_tables_sql,
    get_table_loading_order,
)
from benchbox.utils.scale_factor import format_scale_factor

logger = logging.getLogger(__name__)


class DataVaultBenchmark(BaseBenchmark):
    """Data Vault 2.0 benchmark implementation using TPC-H source data.

    This benchmark transforms TPC-H's 8 tables into 21 Data Vault tables:
    - 7 Hub tables (business entities)
    - 6 Link tables (relationships)
    - 8 Satellite tables (descriptive attributes)

    The benchmark provides 22 queries adapted from TPC-H to work with
    the Hub-Link-Satellite data model.

    Attributes:
        scale_factor: Size multiplier for the benchmark data (1.0 = ~1GB)
        output_dir: Directory for generated data files
        parallel: Number of parallel workers for data generation
        hash_algorithm: Algorithm for hash keys ('md5' or 'sha256')
        record_source: Source system identifier for audit columns
    """

    # Canonical source of truth for supported hash algorithms.
    # All enforcement layers (BenchmarkOptionSpec.choices, transformer validator,
    # HashAlgorithm Literal) must stay in sync with this tuple.
    SUPPORTED_HASH_ALGORITHMS = ("md5", "sha256")

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        parallel: int = 1,
        force_regenerate: bool = False,
        hash_algorithm: str = "md5",
        record_source: str = "TPCH",
        compress_data: bool = False,
        compression_type: str = "none",
        compression_level: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        """Initialize the Data Vault benchmark.

        Args:
            scale_factor: Size multiplier for TPC-H source data
            output_dir: Directory for generated Data Vault files
            parallel: Number of parallel workers (for TPC-H generation)
            force_regenerate: Whether to regenerate data even if it exists
            hash_algorithm: Hash algorithm for keys ('md5' or 'sha256')
            record_source: Source identifier for RECORD_SOURCE columns
            compress_data: Whether to compress generated data files
            compression_type: Type of compression ('none', 'gzip', 'zstd')
            compression_level: Compression level (algorithm-specific)
            **kwargs: Additional configuration passed to BaseBenchmark

        Raises:
            ValueError: If hash_algorithm is not supported
        """
        # Validate hash algorithm before proceeding
        if hash_algorithm not in self.SUPPORTED_HASH_ALGORITHMS:
            raise ValueError(
                f"Unsupported hash algorithm: '{hash_algorithm}'. "
                f"Supported algorithms: {self.SUPPORTED_HASH_ALGORITHMS}."
            )

        super().__init__(scale_factor=scale_factor, output_dir=output_dir, **kwargs)

        self._name = "Data Vault Benchmark"
        self._version = "1.0"
        self._description = (
            "Data Vault 2.0 benchmark based on TPC-H source data. "
            "Transforms 8 TPC-H tables into 21 Data Vault tables (7 Hubs, 6 Links, 8 Satellites)."
        )

        self.parallel = parallel
        self.force_regenerate = force_regenerate
        self.hash_algorithm = hash_algorithm
        self.record_source = record_source

        # Compression settings
        self.compress_data = compress_data
        self.compression_type = compression_type
        self.compression_level = compression_level

        # Set output_dir from parameter if provided, otherwise use default
        # (BaseBenchmark doesn't handle output_dir, so we set it explicitly)
        if output_dir is not None:
            self.output_dir = Path(output_dir) if isinstance(output_dir, str) else output_dir
        elif not hasattr(self, "output_dir") or self.output_dir is None:
            sf_str = format_scale_factor(self.scale_factor)
            self.output_dir = Path.cwd() / "benchmark_runs" / "datagen" / f"{self._get_benchmark_name()}_{sf_str}"

        # Lazy-loaded components
        self._tpch_generator: Optional[Any] = None
        self._etl_transformer: Optional[Any] = None
        self._query_manager: Optional[Any] = None

        # TPC-H source directory (standard tpch_sf{sf} location)
        self._tpch_source_dir: Optional[PathLike] = None

    @property
    def tpch_source_dir(self) -> PathLike:
        """Get the TPC-H source data directory.

        Data Vault uses the standard TPC-H datagen location as its source,
        which allows sharing TPC-H data between TPC-H and Data Vault benchmarks.

        Returns:
            Path to tpch_sf{sf} directory (e.g., benchmark_runs/datagen/tpch_sf1)
        """
        if self._tpch_source_dir is None:
            sf_str = format_scale_factor(self.scale_factor)
            # Use the same parent directory as output_dir but with tpch prefix
            if self.output_dir is not None:
                parent = self.output_dir.parent
            else:
                parent = Path.cwd() / "benchmark_runs" / "datagen"
            self._tpch_source_dir = parent / f"tpch_{sf_str}"
        result = self._tpch_source_dir
        assert result is not None  # Set above if None
        return result

    @property
    def tpch_generator(self) -> Any:
        """Lazy-load the TPC-H data generator.

        The generator is configured to output to the standard TPC-H location
        (tpch_sf{sf}) rather than the Data Vault directory, enabling data
        sharing and proper compression support.
        """
        if self._tpch_generator is None:
            from benchbox.core.tpch.generator import TPCHDataGenerator

            self._tpch_generator = TPCHDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=self.tpch_source_dir,
                parallel=self.parallel,
                # Pass compression settings so TPC-H data matches expectations
                compress_data=self.compress_data,
                compression_type=self.compression_type,
                compression_level=self.compression_level,
            )
        return self._tpch_generator

    @property
    def etl_transformer(self) -> Any:
        """Lazy-load the ETL transformer."""
        if self._etl_transformer is None:
            from benchbox.core.datavault.etl.transformer import DataVaultETLTransformer

            self._etl_transformer = DataVaultETLTransformer(
                scale_factor=self.scale_factor,
                hash_algorithm=self.hash_algorithm,
                record_source=self.record_source,
                compress_data=self.compress_data,
                compression_type=self.compression_type,
                compression_level=self.compression_level,
            )
        return self._etl_transformer

    @property
    def query_manager(self) -> Any:
        """Lazy-load the query manager."""
        if self._query_manager is None:
            from benchbox.core.datavault.queries import DataVaultQueryManager

            self._query_manager = DataVaultQueryManager()
        return self._query_manager

    def _check_existing_manifest(self) -> Optional[dict[str, Path]]:
        """Check if valid data already exists based on manifest.

        Returns:
            Dictionary of table paths if valid manifest exists, None otherwise.
        """
        from benchbox.utils.datagen_manifest import MANIFEST_FILENAME, get_table_files, load_manifest

        manifest_path = self.output_dir / MANIFEST_FILENAME
        if not manifest_path.exists():
            return None

        try:
            manifest = load_manifest(manifest_path)

            # Verify benchmark and scale factor match
            if manifest.get("benchmark", "").lower() != "datavault":
                logger.debug("Manifest benchmark mismatch, regenerating")
                return None

            if float(manifest.get("scale_factor", 0)) != float(self.scale_factor):
                logger.debug("Manifest scale factor mismatch, regenerating")
                return None

            # Reconstruct file paths from manifest
            tables = manifest.get("tables", {})
            file_paths: dict[str, Path] = {}

            for table_name in tables:
                entries = get_table_files(manifest, table_name)
                if entries:
                    # Use first entry's path
                    rel_path = entries[0].get("path", "")
                    full_path = self.output_dir / rel_path
                    if full_path.exists():
                        file_paths[table_name] = full_path
                    else:
                        logger.debug(f"File {full_path} from manifest does not exist")
                        return None

            # Verify we have all 21 tables
            if len(file_paths) < 21:
                logger.debug(f"Only found {len(file_paths)} tables in manifest, expected 21")
                return None

            return file_paths

        except Exception as e:
            logger.debug(f"Error reading manifest: {e}")
            return None

    def generate_data(
        self,
        tables: Optional[list[str]] = None,
        output_format: str = "tbl",
    ) -> dict[str, Any]:
        """Generate Data Vault benchmark data from TPC-H source.

        This method:
        1. Checks if valid data already exists (unless force_regenerate is True)
        2. Generates TPC-H source data using dbgen
        3. Transforms it to Data Vault format using DuckDB

        Args:
            tables: Optional list of specific tables to generate.
                    If None, generates all 21 Data Vault tables.
            output_format: Output file format ('tbl' for pipe-delimited, 'csv' for comma)

        Returns:
            Dictionary mapping table names to file paths
        """
        if self.output_dir is None:
            raise ValueError("output_dir must be set before generating data")

        # Ensure output directory exists before generation
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if valid data already exists (skip if force_regenerate)
        if not self.force_regenerate:
            existing_files = self._check_existing_manifest()
            if existing_files:
                logger.info(
                    f"Valid Data Vault data found at scale factor {self.scale_factor} "
                    f"({len(existing_files)} tables). Skipping regeneration."
                )
                self.tables = existing_files
                return existing_files

        if self.force_regenerate:
            logger.info("Force regeneration requested")

        logger.info(f"Generating Data Vault data at scale factor {self.scale_factor}")

        # Step 1: Generate TPC-H source data to standard tpch_sf{sf} location
        logger.info("Step 1/2: Generating TPC-H source data...")
        logger.info(f"  TPC-H source directory: {self.tpch_source_dir}")
        tpch_files = self.tpch_generator.generate()
        logger.info(f"Generated {len(tpch_files)} TPC-H source files")

        # Step 2: Transform to Data Vault (source: tpch_sf{sf}, output: datavault_sf{sf})
        logger.info("Step 2/2: Transforming to Data Vault format...")
        dv_files = self.etl_transformer.transform(
            tpch_dir=self.tpch_source_dir,
            output_dir=self.output_dir,
            tables=tables,
            output_format=output_format,
        )
        logger.info(f"Generated {len(dv_files)} Data Vault tables")

        # Persist mapping for downstream consumers (loaders, manifests)
        self.tables = dv_files
        return dv_files

    def get_query(self, query_id: Union[int, str]) -> str:
        """Get the SQL text for a specific Data Vault query.

        Args:
            query_id: Query identifier (1-22)

        Returns:
            SQL query text adapted for Data Vault schema

        Raises:
            ValueError: If query_id is not valid
        """
        return self.query_manager.get_query(query_id)

    def get_all_queries(self) -> dict[str, str]:
        """Get all available Data Vault queries.

        Returns:
            Dictionary mapping query IDs (1-22) to SQL text
        """
        return self.query_manager.get_all_queries()

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all Data Vault benchmark queries.

        This is an alias for get_all_queries() that matches the standard
        benchmark interface expected by the platform adapters.

        Args:
            dialect: Optional SQL dialect for translation (not yet implemented)

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        # Convert keys to strings for consistency with other benchmarks
        return {str(k): v for k, v in self.query_manager.get_all_queries().items()}

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Optional[Mapping[str, Any]] = None,
    ) -> list[tuple[Any, ...]]:
        """Execute a Data Vault query on the given connection.

        Args:
            query_id: Query identifier (1-22)
            connection: Database connection to use
            params: Optional query parameters

        Returns:
            Query results as list of tuples
        """
        query = self.get_query(query_id)
        cursor = connection.cursor() if hasattr(connection, "cursor") else connection
        cursor.execute(query)
        return cursor.fetchall()

    def get_schema(self) -> dict[str, Any]:
        """Get the Data Vault schema definition.

        Returns:
            Dictionary mapping table names to Table objects
        """
        return TABLES_BY_NAME.copy()

    def get_create_tables_sql(
        self,
        dialect: str = "duckdb",
        tuning_config: Optional[Any] = None,
    ) -> str:
        """Generate SQL DDL for creating all Data Vault tables.

        Args:
            dialect: Target SQL dialect (for future dialect translation)
            tuning_config: Optional tuning configuration

        Returns:
            SQL DDL statements for all 21 tables
        """
        from benchbox.utils.dialect_utils import translate_sql_query

        enable_pk = True
        enable_fk = True

        if tuning_config is not None:
            enable_pk = getattr(tuning_config.primary_keys, "enabled", True)
            enable_fk = getattr(tuning_config.foreign_keys, "enabled", True)

        ddl = get_create_all_tables_sql(
            enable_primary_keys=enable_pk,
            enable_foreign_keys=enable_fk,
        )

        # Translate DDL for non-DuckDB dialects using SQLGlot to keep portability
        target = dialect.lower() if dialect else "duckdb"
        if target not in {"duckdb", "postgres", "ansi", "standard"}:
            statements = [stmt.strip() for stmt in ddl.split(";\n") if stmt.strip()]
            translated = [
                translate_sql_query(stmt, target_dialect=target, source_dialect="postgres", identify=True)
                for stmt in statements
            ]
            ddl = ";\n\n".join(translated) + ";"

        return ddl

    def get_table_loading_order(self, available_tables: Optional[list[str]] = None) -> list[str]:
        """Get table names in proper loading order.

        Data Vault tables must be loaded in order:
        1. Hubs (no dependencies)
        2. Links (depend on Hubs)
        3. Satellites (depend on Hubs/Links)

        Args:
            available_tables: Optional list of table names that are actually available.
                            If provided, only these tables are included in the order.

        Returns:
            List of table names in loading order
        """
        full_order = get_table_loading_order()
        if available_tables is None:
            return full_order
        # Filter to only include available tables, preserving order
        available_set = set(available_tables)
        return [t for t in full_order if t in available_set]

    def get_table_count(self) -> int:
        """Get the total number of Data Vault tables.

        Returns:
            Number of tables (21)
        """
        return len(TABLES)

    def supports_dataframe_mode(self) -> bool:
        """Data Vault supports DataFrame execution mode."""
        return True

    def get_dataframe_queries(self) -> list[Any]:
        """Get DataFrame query implementations for Data Vault."""
        from benchbox.core.datavault.dataframe_queries import DATAVAULT_DATAFRAME_QUERIES

        return DATAVAULT_DATAFRAME_QUERIES.get_all_queries()

    def _get_benchmark_name(self) -> str:
        """Override base naming to use datavault identifier for paths."""
        return "datavault"

    def cleanup(self) -> None:
        """Clean up any resources used by the benchmark."""
        if self._tpch_generator is not None and hasattr(self._tpch_generator, "cleanup"):
            self._tpch_generator.cleanup()  # type: ignore[call-non-callable]
        super().cleanup()


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.cli.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
)

BenchmarkHookRegistry.register_option_specs(
    "datavault",
    BenchmarkOptionSpec(
        name="hash_algorithm",
        default="md5",
        help="Hash algorithm for hub/link keys",
        choices=DataVaultBenchmark.SUPPORTED_HASH_ALGORITHMS,
        aliases=("hash-algorithm",),
    ),
    BenchmarkOptionSpec(
        name="record_source",
        default="TPCH",
        help="Record source identifier for audit columns",
        aliases=("record-source",),
    ),
    BenchmarkOptionSpec(
        name="force_regenerate",
        parser=lambda v: v.strip().lower() in ("true", "1", "yes"),
        help="Force data regeneration",
        aliases=("force-regenerate",),
    ),
)
