"""TPC-DS One Big Table benchmark implementation."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Union

from benchbox.core.base_benchmark import BaseBenchmark
from benchbox.core.tpcds.generator import TPCDSDataGenerator
from benchbox.core.tpcds_obt.etl.transformer import SUPPORTED_CHANNELS, TPCDSOBTTransformer
from benchbox.core.tpcds_obt.queries import TPCDSOBTQueryManager
from benchbox.utils.scale_factor import format_scale_factor

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Doris/MySQL derived-table alias injection
# ---------------------------------------------------------------------------

_FROM_SUBQUERY_RE = re.compile(r"\bFROM\s*\(", re.IGNORECASE)

# SQL keywords that can legally follow a closing ')' when a derived table
# has NO alias.  Their presence means we need to inject one.
_NO_ALIAS_KEYWORDS = frozenset(
    {
        "where",
        "on",
        "having",
        "group",
        "order",
        "limit",
        "union",
        "intersect",
        "except",
        "join",
        "left",
        "right",
        "inner",
        "outer",
        "full",
        "cross",
        "with",
        "select",
    }
)


def _add_derived_table_aliases(sql: str) -> str:
    """Inject AS _t{n} after every unaliased FROM (...) derived table.

    Required for Doris/MySQL: every derived table must have its own alias
    (error 1248: 'Every derived table must have its own alias').
    """
    parts: list[str] = []
    scan_pos = 0
    counter = 0

    for m in _FROM_SUBQUERY_RE.finditer(sql):
        open_paren = m.end() - 1  # position of '(' in "FROM ("
        if open_paren < scan_pos:
            # This match was already consumed as part of a nested subquery.
            continue

        # Append SQL up to and including "FROM ("
        parts.append(sql[scan_pos : m.end()])
        scan_pos = m.end()

        # Walk forward to find the matching closing ')'
        depth = 1
        i = scan_pos
        while i < len(sql) and depth > 0:
            if sql[i] == "(":
                depth += 1
            elif sql[i] == ")":
                depth -= 1
            i += 1
        # i is now one past the closing ')'

        parts.append(sql[scan_pos:i])
        scan_pos = i

        # Peek at what follows, ignoring whitespace
        j = scan_pos
        while j < len(sql) and sql[j] in " \t\n\r":
            j += 1

        peek = sql[j : j + 60].lower()

        # Already aliased when next token is AS or a bare non-keyword identifier
        if peek.startswith("as ") or peek.startswith("as\n") or peek.startswith("as\t"):
            continue

        # Check the first word after the closing paren
        word_match = re.match(r"(\w+)", peek)
        if word_match:
            next_word = word_match.group(1)
            if next_word not in _NO_ALIAS_KEYWORDS:
                continue  # bare identifier alias already present

        # Need to inject an alias: either a keyword or punctuation follows
        counter += 1
        parts.append(f" AS _t{counter}")

    parts.append(sql[scan_pos:])
    return "".join(parts)


# ---------------------------------------------------------------------------

# Exhaustive mapping of the two supported OBT output formats.
# Using a dict (rather than a ternary) ensures an unknown format gets None
# instead of silently falling through to "parquet".
_ALTERNATE_FORMAT: dict[str, str] = {"parquet": "dat", "dat": "parquet"}


class TPCDSOBTBenchmark(BaseBenchmark):
    """Transforms TPC-DS data into a single OBT table and executes adapted queries.

    Architecture:
        - Source data: Uses standard TPC-DS data from `benchmark_runs/datagen/tpcds_sf{N}/`
        - Output data: OBT-specific output stored in `benchmark_runs/datagen/tpcds_obt_sf{N}/`

    This ensures TPC-DS base data is generated once and reused across benchmarks,
    while OBT-specific transformations are stored separately.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        tpcds_source_dir: Union[str, Path] | None = None,
        parallel: int = 1,
        force_regenerate: bool = False,
        dimension_mode: str = "full",
        channels: list[str] | None = None,
        output_format: str = "parquet",
        **kwargs: Any,
    ) -> None:
        """Initialize TPC-DS OBT benchmark.

        Args:
            scale_factor: Scale factor for the benchmark (minimum 1.0).
            output_dir: Directory for OBT-specific output. Defaults to
                benchmark_runs/datagen/tpcds_obt_sf{N}/.
            tpcds_source_dir: Directory containing TPC-DS source data. Defaults to
                benchmark_runs/datagen/tpcds_sf{N}/. If data doesn't exist, it will
                be generated there.
            parallel: Number of parallel processes for data generation.
            force_regenerate: Force data regeneration even if valid data exists.
            dimension_mode: OBT dimension mode ('full' or 'minimal').
            channels: Sales channels to include ('store', 'web', 'catalog').
            output_format: Output format for OBT data ('parquet', 'dat').
            **kwargs: Additional arguments including compression options
                (compress_data, compression_type, compression_level).
        """
        super().__init__(scale_factor=scale_factor, **kwargs)

        if scale_factor < 1.0:
            raise ValueError("TPC-DS-OBT requires scale_factor >= 1.0 to align with TPC-DS generation.")

        self._name = "TPC-DS One Big Table Benchmark"
        self._version = "0.1"
        self._description = (
            "TPC-DS benchmark adapted to a single wide One Big Table with sales + returns merged across channels."
        )

        # Determine standard paths using scale factor formatting
        sf_str = format_scale_factor(scale_factor)
        default_base = Path.cwd() / "benchmark_runs" / "datagen"

        # OBT output directory (for transformed OBT table)
        if output_dir:
            self.output_dir = Path(output_dir)
        else:
            self.output_dir = default_base / f"tpcds_obt_{sf_str}"

        # TPC-DS source directory (for base TPC-DS data)
        if tpcds_source_dir:
            self.tpcds_source_dir = Path(tpcds_source_dir)
        else:
            self.tpcds_source_dir = default_base / f"tpcds_{sf_str}"

        self.parallel = parallel
        self.force_regenerate = force_regenerate
        self.dimension_mode = dimension_mode
        self.channels = channels or list(SUPPORTED_CHANNELS)
        self.output_format = output_format

        # Store compression options for data generator
        self._compression_kwargs = {
            k: v for k, v in kwargs.items() if k in ("compress_data", "compression_type", "compression_level")
        }

        self._data_generator: TPCDSDataGenerator | None = None
        self._obt_transformer: TPCDSOBTTransformer | None = None
        self._query_manager: TPCDSOBTQueryManager | None = None
        self.tables: dict[str, Path] = {}
        self.manifest: Path | None = None

    @property
    def data_generator(self) -> TPCDSDataGenerator:
        """Lazy-load TPC-DS data generator.

        The generator writes to tpcds_source_dir (standard TPC-DS location),
        not the OBT output_dir.
        """
        if self._data_generator is None:
            self._data_generator = TPCDSDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=self.tpcds_source_dir,  # Generate in TPC-DS source dir
                parallel=self.parallel,
                force_regenerate=self.force_regenerate,
                **self._compression_kwargs,
            )
        return self._data_generator

    @property
    def obt_transformer(self) -> TPCDSOBTTransformer:
        """Lazy-load OBT transformer."""
        if self._obt_transformer is None:
            self._obt_transformer = TPCDSOBTTransformer()
        return self._obt_transformer

    @property
    def query_manager(self) -> TPCDSOBTQueryManager:
        """Lazy-load query manager."""
        if self._query_manager is None:
            self._query_manager = TPCDSOBTQueryManager()
        return self._query_manager

    def generate_data(
        self,
        tables: list[str] | None = None,
        output_format: str | None = None,
    ) -> dict[str, Any]:
        """Generate TPC-DS data and transform it into the single OBT table.

        Args:
            tables: Ignored - OBT always emits a single table.
            output_format: Override the instance's output_format for this run;
                defaults to self.output_format when None.

        Data flow:
            1. Generate TPC-DS base data in tpcds_source_dir (e.g., tpcds_sf1/)
            2. Transform source data into OBT format
            3. Write OBT output to output_dir (e.g., tpcds_obt_sf1/)
        """
        if tables is not None:
            logger.warning("TPC-DS-OBT ignores table selection and always emits a single OBT table.")

        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        obt_output_format = output_format or self.output_format

        # Check for existing OBT output
        if not self.force_regenerate and self._existing_obt(obt_output_format):
            logger.info("Reusing existing OBT output at %s", self.tables.get("tpcds_sales_returns_obt"))
            return {"table": self.tables.get("tpcds_sales_returns_obt"), "manifest": self.manifest}

        # Generate TPC-DS base data in the source directory
        logger.info(
            "Generating base TPC-DS data (scale factor %s) in %s...",
            self.scale_factor,
            self.tpcds_source_dir,
        )
        self.data_generator.generate()

        # Transform from source directory to OBT output directory
        logger.info(
            "Transforming TPC-DS data from %s into OBT at %s...",
            self.tpcds_source_dir,
            self.output_dir,
        )
        result = self.obt_transformer.transform(
            tpcds_dir=self.tpcds_source_dir,  # Read from TPC-DS source
            output_dir=self.output_dir,  # Write to OBT output
            mode=self.dimension_mode,
            channels=self.channels,
            output_format=obt_output_format,
            scale_factor=self.scale_factor,
        )

        self.tables["tpcds_sales_returns_obt"] = Path(result["table"])
        self.manifest = Path(result["manifest"])

        return result

    def _existing_obt(self, output_format: str) -> bool:
        """Check for an existing generated OBT table.

        Returns True when a matching artifact and manifest both exist.
        When the requested format is absent but the alternate format is
        present, logs an INFO message and returns False so the caller
        regenerates.  The two messages are intentionally different in tone:
        - parquet requested / .dat found: labels the .dat "stale" (parquet
          is the preferred format going forward) and asks the user to delete
          it manually to reclaim disk space.
        - dat requested / .parquet found: notes that the format switch was
          explicit, so the existing .parquet is superseded - not "stale".
        """
        existing_path = self.output_dir / f"tpcds_sales_returns_obt.{output_format}"
        manifest_path = self.output_dir / "tpcds_sales_returns_obt_manifest.json"
        if existing_path.exists() and manifest_path.exists():
            self.tables["tpcds_sales_returns_obt"] = existing_path
            self.manifest = manifest_path
            return True
        # Log a hint when a stale alternate-format artifact is on disk
        other_format = _ALTERNATE_FORMAT.get(output_format)
        if other_format is None:
            return False
        other_path = self.output_dir / f"tpcds_sales_returns_obt.{other_format}"
        if other_path.exists():
            if output_format == "parquet":
                logger.info(
                    "Found stale .dat output at %s. Regenerating as parquet. "
                    "Delete the .dat manually to reclaim disk space.",
                    other_path,
                )
            else:
                logger.info(
                    "Found existing .parquet output at %s. Regenerating as dat "
                    "because --benchmark-option output_format=dat was specified.",
                    other_path,
                )
        return False

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: dict[str, Any] | None = None,
        seed: int | None = None,
        scale_factor: float | None = None,
        dialect: str | None = None,
        **kwargs: Any,
    ) -> str:
        """Get the SQL text for a specific OBT query.

        Args:
            query_id: The ID of the query to retrieve.
            params: Optional parameters for query customization.
            seed: Random seed (accepted for API compatibility, not used by OBT queries).
            scale_factor: Scale factor (accepted for API compatibility, not used by OBT queries).
            dialect: Target SQL dialect (accepted for API compatibility, not used by OBT queries).
            **kwargs: Additional parameters for API compatibility.

        Returns:
            The SQL text of the query.
        """
        # OBT queries don't use seed/scale_factor for parameterization like TPC-DS/TPC-H
        # They use a static query set. We accept these params for API compatibility.
        sql = self.query_manager.get_query(query_id, params)
        if dialect:
            sql = self.translate_query_text(sql, dialect)
        return sql

    def get_all_queries(self) -> dict[str, str]:
        """Get all available OBT queries."""
        return {str(k): v for k, v in self.query_manager.get_queries().items()}

    def translate_query_text(self, query_text: str, target_dialect: str) -> str:
        """Apply dialect-specific rewrites to a single OBT query.

        OBT query conversion emits DuckDB SQL.  Route non-DuckDB targets through
        the shared translation pipeline so Spark-family engines receive their
        native identifier quoting (for example aliases with spaces use
        backticks instead of DuckDB double quotes).
        """
        target = target_dialect.lower()
        if target not in {"duckdb", "standard", "ansi"}:
            from benchbox.utils.dialect_utils import translate_sql_query

            query_text = translate_sql_query(
                query_text,
                target_dialect=target,
                source_dialect="duckdb",
                identify=True,
            )

        if target in {"doris", "starrocks"}:
            query_text = _add_derived_table_aliases(query_text)
        return query_text

    def get_queries(self, dialect: str | None = None) -> dict[str, str]:
        """Get all OBT benchmark queries.

        Args:
            dialect: Target SQL dialect.  When provided, applies per-dialect
                rewrites (e.g. derived-table aliases for Doris/MySQL).

        Returns:
            Dictionary mapping query IDs to SQL text.
        """
        queries = {str(k): v for k, v in self.query_manager.get_queries().items()}
        if dialect:
            queries = {qid: self.translate_query_text(sql, dialect) for qid, sql in queries.items()}
        return queries

    def supports_dataframe_mode(self) -> bool:
        """TPC-DS-OBT supports DataFrame execution mode."""
        return True

    def get_dataframe_queries(self) -> list[Any]:
        """Get DataFrame query implementations for TPC-DS-OBT."""
        from benchbox.core.tpcds_obt.dataframe_queries import get_dataframe_queries

        return get_dataframe_queries()

    def execute_query(
        self,
        query_id: Union[int, str],
        connection: Any,
        params: Mapping[str, Any] | None = None,
    ) -> list[tuple[Any, ...]]:
        """Execute an OBT query on the given connection."""
        query = self.get_query(query_id)
        cursor = connection.cursor() if hasattr(connection, "cursor") else connection
        cursor.execute(query, params or {})
        return cursor.fetchall()

    def get_schema(self) -> dict[str, Any]:
        """Return schema metadata for the single OBT table."""
        from benchbox.core.tpcds_obt import schema

        table = schema.get_obt_table(self.dimension_mode)
        return {table.name: table}

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Generate DDL for creating the OBT table.

        Args:
            dialect: Target SQL dialect for the DDL.
            tuning_config: Optional tuning configuration (accepted for API compatibility,
                not currently used by OBT benchmark).

        Returns:
            DDL SQL string for creating the OBT table.
        """
        from benchbox.core.tpcds_obt import schema
        from benchbox.utils.dialect_utils import translate_sql_query

        # Note: tuning_config is accepted for API compatibility but OBT uses a fixed schema
        ddl = schema.get_obt_table(self.dimension_mode).get_create_table_sql()
        target = dialect.lower() if dialect else "duckdb"
        if target not in {"duckdb", "postgres", "ansi", "standard"}:
            ddl = translate_sql_query(ddl, target_dialect=target, source_dialect="postgres", identify=True)
        return ddl


# ---------------------------------------------------------------------------
# Register benchmark-specific CLI option specs
# ---------------------------------------------------------------------------

from benchbox.cli.benchmark_hooks import (  # noqa: E402
    BenchmarkHookRegistry,
    BenchmarkOptionSpec,
    parse_str_list,
)

BenchmarkHookRegistry.register_option_specs(
    "tpcds_obt",
    BenchmarkOptionSpec(
        name="tpcds_source_dir",
        help="Directory containing TPC-DS source data",
        aliases=("tpcds-source-dir",),
    ),
    BenchmarkOptionSpec(
        name="dimension_mode",
        default="full",
        help="OBT dimension mode",
        choices=("full", "minimal"),
        aliases=("dimension-mode",),
    ),
    BenchmarkOptionSpec(
        name="channels",
        parser=parse_str_list,
        help="Sales channels to include (store,web,catalog)",
    ),
    BenchmarkOptionSpec(
        name="output_format",
        default="parquet",
        help="Output format for OBT data",
        choices=("dat", "parquet"),
        aliases=("output-format",),
    ),
    BenchmarkOptionSpec(
        name="force_regenerate",
        parser=lambda v: v.strip().lower() in ("true", "1", "yes"),
        help="Force data regeneration",
        aliases=("force-regenerate",),
    ),
)
