"""Workload execution helpers for ClickHouse."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.cloud_storage import get_cloud_path_info, is_cloud_path
from benchbox.utils.printing import emit
from benchbox.utils.sql_parsing import find_matching_parenthesis

from .query_transformer import ClickHouseQueryTransformer

logger = logging.getLogger(__name__)


class ClickHouseWorkloadMixin:
    """Provide schema management and workload execution utilities."""

    def create_schema(self, benchmark, connection: Any) -> float:
        """Create schema using ClickHouse-optimized table definitions."""
        start_time = mono_time()

        # Get constraint settings from tuning configuration
        enable_primary_keys, enable_foreign_keys = self._get_constraint_configuration()
        self._log_constraint_configuration(enable_primary_keys, enable_foreign_keys)

        try:
            # Get schema SQL directly from benchmark to avoid sqlglot translation issues.
            # We ask for the DuckDB dialect because most BenchBox schemas emit identical
            # DDL for "duckdb" and "clickhouse", and the few that differ (e.g.
            # transaction_primitives / write_primitives drop inline PRIMARY KEY when
            # dialect="clickhouse") would lose the PK info that
            # `_extract_primary_key_columns` later uses to derive ORDER BY. Known
            # DuckDB-only DDL syntax (Nullable() NOT NULL, FLOAT[N] vector columns)
            # is rewritten in `_optimize_table_definition` below.
            effective_config = self.get_effective_tuning_configuration()
            schema_sql = benchmark.get_create_tables_sql(
                dialect="duckdb",
                tuning_config=effective_config,
            )
            nullable_columns_by_table = self._get_nullable_columns_by_table(benchmark)

            # Physical table_tunings (partitioning/sorting/clustering columns)
            # render only when tuning is actually enabled -- matching the same
            # `self.tuning_enabled` gate DataLoader/apply_ctas_sort use
            # elsewhere, and per ADR-3 baseline policy (notuning = platform
            # defaults + engine-mandatory only, no tuned rendering).
            table_tunings = None
            if self.tuning_enabled and effective_config is not None:
                table_tunings = effective_config.table_tunings

            # Split schema into individual statements and execute
            statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]

            for statement in statements:
                # Optimize table definitions for ClickHouse
                table_name = self._extract_table_name(statement)
                nullable_columns = nullable_columns_by_table.get(table_name.lower(), set()) if table_name else set()
                statement = self._optimize_table_definition(
                    statement,
                    table_tunings,
                    nullable_columns=nullable_columns,
                )
                connection.execute(statement)
                self.logger.debug(f"Executed schema statement: {statement[:100]}...")

            self.logger.info(f"Schema created (PKs: {enable_primary_keys}, FKs: {enable_foreign_keys})")

        except Exception as e:
            self.logger.error(f"Schema creation failed: {e}")
            raise

        return elapsed_seconds(start_time)

    def _optimize_table_definition(
        self,
        statement: str,
        table_tunings: dict[str, Any] | None = None,
        *,
        nullable_columns: set[str] | None = None,
    ) -> str:
        """Optimize table definition for ClickHouse.

        Args:
            statement: A single CREATE TABLE statement.
            table_tunings: Optional mapping of table_name -> TableTuning, from
                the effective tuning configuration, present only when tuning
                is enabled (see create_schema). When a matching, non-empty
                TableTuning exists for this statement's table, tuned
                PARTITION BY/ORDER BY clauses are rendered via
                core.tuning.generators.clickhouse.ClickHouseDDLGenerator --
                the same generator dry-run preview uses (ADR-3 single
                renderer) -- instead of the engine-mandatory PK/tuple()
                fallback below.
            nullable_columns: Lowercase source-schema column names whose values
                may be NULL. Columns used by resolved MergeTree keys are
                intentionally excluded before wrapping.
        """
        if not statement.upper().startswith("CREATE TABLE"):
            return statement

        # Transform SQL for ClickHouse compatibility
        # ClickHouse doesn't like "NOT NULL" on already non-nullable types
        # Replace "Nullable(Type) NOT NULL" patterns
        import re

        # [^)]+  would stop at the first ) inside Nullable(Decimal(38, 0)) NOT NULL;
        # use an alternation that allows one level of nested parens.
        statement = re.sub(
            r"Nullable\((?:[^()]+|\([^)]*\))+\)\s+NOT\s+NULL",
            lambda m: m.group(0).replace(" NOT NULL", ""),
            statement,
            flags=re.IGNORECASE,
        )

        # Schema generators emit DuckDB-style fixed-size float arrays
        # (FLOAT[N], DOUBLE[N]) for embedding columns. ClickHouse rejects the
        # `[N]` syntax (SYNTAX_ERROR Code 62) and uses Array(Float32/Float64)
        # without a compile-time dimension. Rewrite in-place so the
        # vector_search benchmark's CREATE TABLE parses on ClickHouse.
        statement = re.sub(r"\bFLOAT\s*\[\s*\d+\s*\]", "Array(Float32)", statement, flags=re.IGNORECASE)
        statement = re.sub(r"\bDOUBLE\s*\[\s*\d+\s*\]", "Array(Float64)", statement, flags=re.IGNORECASE)

        tuning_clauses = self._resolve_tuned_ddl_clauses(statement, table_tunings)
        if nullable_columns:
            key_columns = self._resolve_key_columns(statement, tuning_clauses, nullable_columns)
            statement = self._apply_nullable_column_types(statement, nullable_columns - key_columns)

        # Include ClickHouse MergeTree engine and ORDER BY clause if not present
        statement_upper = statement.upper()

        # Include ENGINE if not present
        if "ENGINE" not in statement_upper:
            if statement.endswith(";"):
                statement = statement[:-1] + " ENGINE = MergeTree();"
            else:
                statement = statement + " ENGINE = MergeTree()"

        # Include PARTITION BY if not present and the tuned generator produced one.
        statement_upper = statement.upper()
        if "PARTITION BY" not in statement_upper and tuning_clauses is not None and tuning_clauses.partition_by:
            partition_clause = f" PARTITION BY ({tuning_clauses.partition_by})"
            if statement.endswith(";"):
                statement = statement[:-1] + partition_clause + ";"
            else:
                statement = statement + partition_clause

        # Include ORDER BY if not present
        statement_upper = statement.upper()
        if "ORDER BY" not in statement_upper:
            if tuning_clauses is not None and tuning_clauses.sort_by:
                # Tuned rendering: ORDER BY (sort + clustering columns), via
                # the shared ClickHouseDDLGenerator.
                order_by_clause = f" ORDER BY ({tuning_clauses.sort_by})"
            else:
                # Engine-mandatory baseline: MergeTree requires ORDER BY.
                # Extract primary key columns if any exist in the statement.
                pk_columns = self._extract_primary_key_columns(statement)
                if pk_columns:
                    # Use primary key columns for ORDER BY to satisfy ClickHouse requirement
                    order_by_clause = f" ORDER BY ({', '.join(pk_columns)})"
                else:
                    # Use tuple() for tables without primary keys
                    order_by_clause = " ORDER BY tuple()"

            if statement.endswith(";"):
                statement = statement[:-1] + order_by_clause + ";"
            else:
                statement = statement + order_by_clause

        return statement

    @staticmethod
    def _extract_table_name(statement: str) -> str | None:
        """Extract an unquoted table name from a CREATE TABLE statement."""
        import re

        match = re.search(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+([A-Za-z_]\w*)", statement, re.IGNORECASE)
        return match.group(1) if match else None

    @staticmethod
    def _get_nullable_columns_by_table(benchmark: Any) -> dict[str, set[str]]:
        """Return source-nullable, non-primary-key columns by table.

        BenchBox schemas use several shapes: dict/list columns (TPC-DS and
        vector search), dict-of-column-specs (NYC Taxi and TSBS), and table
        objects (Data Vault). Schema metadata treats an omitted ``nullable``
        flag as nullable; explicit ``False`` is the non-null contract.
        """
        schema_getter = getattr(benchmark, "get_schema", None)
        if not callable(schema_getter):
            return {}
        schema = schema_getter()
        if not isinstance(schema, dict):
            return {}

        nullable_by_table: dict[str, set[str]] = {}
        for table_name, table_schema in schema.items():
            if isinstance(table_schema, dict):
                columns = table_schema.get("columns")
                table_primary_keys = {str(name).lower() for name in table_schema.get("primary_key", [])}
            else:
                columns = getattr(table_schema, "columns", None)
                table_primary_keys = set()

            if isinstance(columns, dict):
                column_items = [(name, spec) for name, spec in columns.items()]
            elif isinstance(columns, (list, tuple)):
                column_items = []
                for column in columns:
                    name = column.get("name") if isinstance(column, dict) else getattr(column, "name", None)
                    column_items.append((name, column))
            else:
                continue

            nullable_columns: set[str] = set()
            for raw_name, column in column_items:
                if not isinstance(raw_name, str):
                    continue
                if isinstance(column, dict):
                    is_nullable = column.get("nullable", True)
                    is_primary_key = column.get("primary_key", False)
                else:
                    is_nullable = getattr(column, "nullable", True)
                    is_primary_key = getattr(column, "primary_key", False)
                column_name = raw_name.lower()
                if bool(is_nullable) and not bool(is_primary_key) and column_name not in table_primary_keys:
                    nullable_columns.add(column_name)

            if nullable_columns:
                nullable_by_table[str(table_name).lower()] = nullable_columns

        return nullable_by_table

    def _resolve_key_columns(self, statement: str, tuning_clauses: Any, nullable_columns: set[str]) -> set[str]:
        """Return nullable candidates referenced by PK/partition/order keys."""
        import re

        key_columns = {name.lower() for name in self._extract_primary_key_columns(statement)}
        if tuning_clauses is None:
            return key_columns

        key_expressions = [
            value
            for value in (
                tuning_clauses.partition_by,
                tuning_clauses.sort_by,
                tuning_clauses.order_by,
                tuning_clauses.cluster_by,
                tuning_clauses.primary_key,
            )
            if value
        ]
        for column_name in nullable_columns:
            identifier = re.compile(
                rf"(?<![A-Za-z0-9_]){re.escape(column_name)}(?![A-Za-z0-9_])",
                re.IGNORECASE,
            )
            if any(identifier.search(expression) for expression in key_expressions):
                key_columns.add(column_name)
        return key_columns

    @classmethod
    def _apply_nullable_column_types(cls, statement: str, nullable_columns: set[str]) -> str:
        """Wrap selected CREATE TABLE column types with ``Nullable(...)``.

        The scanner splits only on top-level commas, so nested type commas
        such as ``DECIMAL(10,2)`` cannot consume the next column. Edits are
        confined to selected type spans; every other byte remains unchanged.
        """
        import re

        if not nullable_columns:
            return statement

        create_match = re.search(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+[A-Za-z_]\w*\s*\(", statement, re.IGNORECASE)
        if create_match is None:
            return statement
        open_index = statement.find("(", create_match.start())
        close_index = find_matching_parenthesis(statement, open_index)
        body = statement[open_index + 1 : close_index]
        edits: list[tuple[int, int, str]] = []

        for start, end in cls._top_level_column_spans(body):
            segment = body[start:end]
            name_match = re.match(r'^\s*(?:"(?P<quoted>[^"]+)"|(?P<plain>[A-Za-z_]\w*))\s+', segment)
            if name_match is None:
                continue
            column_name = (name_match.group("quoted") or name_match.group("plain")).lower()
            if column_name not in nullable_columns:
                continue

            type_start = name_match.end()
            type_end = cls._column_type_end(segment, type_start)
            data_type = segment[type_start:type_end].rstrip()
            if not data_type or data_type.upper().startswith("NULLABLE("):
                continue
            suffix = segment[type_end:]
            if re.search(r"\bNOT\s+NULL\b", suffix, re.IGNORECASE):
                raise ValueError(f"source-nullable column {column_name!r} is declared NOT NULL")
            replacement_end = type_start + len(data_type)
            edits.append((start + type_start, start + replacement_end, f"Nullable({data_type})"))

        for start, end, replacement in reversed(edits):
            body = body[:start] + replacement + body[end:]
        return statement[: open_index + 1] + body + statement[close_index:]

    @staticmethod
    def _top_level_column_spans(body: str) -> list[tuple[int, int]]:
        """Return comma-delimited spans while respecting nested SQL syntax."""
        spans: list[tuple[int, int]] = []
        start = 0
        depth = 0
        quote: str | None = None
        index = 0
        while index < len(body):
            char = body[index]
            if quote is not None:
                if char == quote:
                    if index + 1 < len(body) and body[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif char == "," and depth == 0:
                spans.append((start, index))
                start = index + 1
            index += 1
        spans.append((start, len(body)))
        return spans

    @staticmethod
    def _column_type_end(segment: str, type_start: int) -> int:
        """Locate the end of a type expression before column constraints."""
        import re

        constraint = re.compile(
            r"(?:NOT\s+NULL|NULL|PRIMARY\s+KEY|REFERENCES|DEFAULT|UNIQUE|CHECK|COLLATE|GENERATED|CONSTRAINT)\b",
            re.IGNORECASE,
        )
        depth = 0
        quote: str | None = None
        index = type_start
        while index < len(segment):
            char = segment[index]
            if quote is not None:
                if char == quote:
                    if index + 1 < len(segment) and segment[index + 1] == quote:
                        index += 2
                        continue
                    quote = None
            elif char in {"'", '"'}:
                quote = char
            elif char in "([":
                depth += 1
            elif char in ")]":
                depth -= 1
            elif char.isspace() and depth == 0:
                next_token = segment[index:].lstrip()
                if constraint.match(next_token):
                    return index
            index += 1
        return len(segment.rstrip())

    def _resolve_tuned_ddl_clauses(self, statement: str, table_tunings: dict[str, Any] | None):
        """Resolve tuned PARTITION BY/ORDER BY clauses for this statement's table, if any.

        Returns None when tuning is not enabled, no table_tuning is
        configured for this table, or the configured table_tuning has no
        partitioning/sorting/clustering columns -- callers fall back to the
        engine-mandatory baseline in that case.
        """
        if not table_tunings:
            return None

        import re

        match = re.search(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+(\w+)", statement, re.IGNORECASE)
        if not match:
            return None
        table_name = match.group(1)

        # Benchmark table names are lowercase while shipped tuning templates
        # key tables uppercase (e.g. "LINEITEM") -- same case-insensitive
        # lookup pattern as core/dryrun.py's _extract_ddl_preview.
        table_tuning = None
        for configured_name, configured_tuning in table_tunings.items():
            if str(configured_name).upper() == table_name.upper():
                table_tuning = configured_tuning
                break

        if table_tuning is None or not table_tuning.has_any_tuning():
            return None

        from benchbox.core.tuning.ddl_generator import get_ddl_generator

        generator = get_ddl_generator("clickhouse")
        clauses = generator.generate_tuning_clauses(table_tuning)
        if clauses.is_empty():
            return None
        self._normalize_tuning_clause_identifiers(statement, clauses)
        return clauses

    @classmethod
    def _normalize_tuning_clause_identifiers(cls, statement: str, tuning_clauses: Any) -> None:
        """Match tuning-template identifier case to the emitted DDL columns."""
        import re

        column_names = cls._ddl_column_name_map(statement)
        if not column_names:
            return

        identifier = re.compile(r"[A-Za-z_]\w*")
        for attribute in ("partition_by", "sort_by", "order_by", "cluster_by", "primary_key"):
            expression = getattr(tuning_clauses, attribute, None)
            if expression:
                setattr(
                    tuning_clauses,
                    attribute,
                    identifier.sub(lambda match: column_names.get(match.group(0).lower(), match.group(0)), expression),
                )

    @classmethod
    def _ddl_column_name_map(cls, statement: str) -> dict[str, str]:
        """Return lowercase-to-emitted names for CREATE TABLE columns."""
        import re

        create_match = re.search(r"CREATE TABLE(?:\s+IF NOT EXISTS)?\s+[A-Za-z_]\w*\s*\(", statement, re.IGNORECASE)
        if create_match is None:
            return {}
        open_index = statement.find("(", create_match.start())
        close_index = find_matching_parenthesis(statement, open_index)
        body = statement[open_index + 1 : close_index]
        names: dict[str, str] = {}
        for start, end in cls._top_level_column_spans(body):
            segment = body[start:end]
            match = re.match(r'^\s*(?:"(?P<quoted>[^"]+)"|(?P<plain>[A-Za-z_]\w*))\s+', segment)
            if match is None:
                continue
            name = match.group("quoted") or match.group("plain")
            if name.upper() not in {"PRIMARY", "FOREIGN", "UNIQUE", "CHECK", "CONSTRAINT"}:
                names[name.lower()] = name
        return names

    def _extract_primary_key_columns(self, statement: str) -> list[str]:
        """Extract primary key column names from a CREATE TABLE statement.

        Args:
            statement: CREATE TABLE SQL statement

        Returns:
            List of primary key column names
        """
        import re

        # Look for PRIMARY KEY constraints in different formats
        pk_columns = []

        # Pattern 1: column_name TYPE PRIMARY KEY
        # (?:\((?:[^()]+|\([^)]*\))*\))? handles one level of nesting e.g. Nullable(Decimal(10,2))
        inline_pk_pattern = r"(\w+)\s+\w+(?:\((?:[^()]+|\([^)]*\))*\))?\s+PRIMARY\s+KEY"
        inline_matches = re.findall(inline_pk_pattern, statement, re.IGNORECASE)
        pk_columns.extend(inline_matches)

        # Pattern 2: PRIMARY KEY (col1, col2, ...)
        composite_pk_pattern = r"PRIMARY\s+KEY\s*\(\s*([^)]+)\s*\)"
        composite_matches = re.findall(composite_pk_pattern, statement, re.IGNORECASE)
        for match in composite_matches:
            # Split by comma and clean up column names
            cols = [col.strip() for col in match.split(",")]
            pk_columns.extend(cols)

        return pk_columns

    def load_data(
        self, benchmark, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data using ClickHouse's optimized CSV import capabilities."""
        from benchbox.platforms.base.data_loading import DataLoader

        # Check if using cloud storage and log
        if is_cloud_path(str(data_dir)):
            path_info = get_cloud_path_info(str(data_dir))
            self.log_verbose(f"Loading data from cloud storage: {path_info['provider']} bucket '{path_info['bucket']}'")
            emit(f"  Loading data from {path_info['provider']} cloud storage")

        # Create ClickHouse-specific handler factory
        def clickhouse_handler_factory(file_path, adapter, benchmark_instance, table_name=None, data_source=None):
            from benchbox.platforms.base.data_loading import (
                ClickHouseNativeHandler,
                DataSource,
                FileFormatRegistry,
                resolve_csv_dialect,
            )

            # Determine the true base extension (handles names like *.tbl.1.zst)
            base_ext = FileFormatRegistry.get_base_data_extension(file_path)

            # Create ClickHouse native handler for supported formats
            if base_ext in (".tbl", ".dat", ".csv"):
                dialect_source = data_source or DataSource(source_type="clickhouse_handler", tables={})
                dialect = resolve_csv_dialect(
                    dialect_source, table_name or file_path.stem, file_path, benchmark_instance
                )
                return ClickHouseNativeHandler(
                    dialect.delimiter,
                    adapter,
                    benchmark_instance,
                    has_header=dialect.has_header,
                )
            elif base_ext == ".parquet":
                # Delimiter is unused for Parquet - file() reads the format natively.
                # We route through ClickHouseNativeHandler so load_table() uses
                # INSERT INTO ... SELECT * FROM file(path, 'Parquet') instead of
                # falling back to the generic row-by-row ParquetHandler.
                return ClickHouseNativeHandler(",", adapter, benchmark_instance)
            return None  # Fall back to generic handler

        loader = DataLoader(
            adapter=self,
            benchmark=benchmark,
            connection=connection,
            data_dir=data_dir,
            handler_factory=clickhouse_handler_factory,
            tuning_config=self.unified_tuning_configuration if self.tuning_enabled else None,
        )
        table_stats, loading_time = loader.load()
        # DataLoader doesn't provide per-table timings yet
        return table_stats, loading_time, None

    def _get_existing_tables(self, connection) -> list[str]:
        """Get list of existing tables in the ClickHouse database.

        Override the base class implementation with ClickHouse-specific query.

        Args:
            connection: ClickHouse connection (server or local)

        Returns:
            List of table names (lowercase for consistency)
        """
        try:
            if self.deployment_mode == "local":
                # For local mode (chdb), use SHOW TABLES
                result = connection.execute("SHOW TABLES")
                if result:
                    # Handle different result formats from chdb
                    tables = []
                    for row in result:
                        if isinstance(row, (list, tuple)):
                            tables.append(str(row[0]).lower())
                        else:
                            tables.append(str(row).lower())
                    return tables
                return []
            else:
                # For server mode, use system.tables query
                result = connection.execute("SELECT name FROM system.tables WHERE database = currentDatabase()")
                return [row[0].lower() for row in result] if result else []
        except Exception as e:
            self.logger.debug(f"Failed to get existing tables: {e}")
            return []

    def get_table_row_count(self, connection: Any, table: str) -> int:
        """Get row count using ClickHouse execute() API.

        Overrides base implementation that uses cursor() - ClickHouseLocalClient
        and ClickHouseCloudClient expose execute() but not cursor().

        Args:
            connection: ClickHouse connection (local, server, or cloud)
            table: Table name

        Returns:
            Row count as integer, or 0 if unable to determine
        """
        try:
            result = connection.execute(f"SELECT COUNT(*) FROM {table}")
            if result:
                row = result[0]
                return int(row[0])
            return 0
        except Exception as e:
            self.logger.debug(f"Failed to get row count for {table}: {e}")
            return 0

    def _get_constraint_configuration(self) -> tuple[bool, bool]:
        """Extract constraint configuration settings from tuning config.

        Override base implementation to ensure ClickHouse always has primary keys enabled,
        since ClickHouse MergeTree engine requires ORDER BY (derived from PRIMARY KEY).

        Returns:
            Tuple of (enable_primary_keys, enable_foreign_keys)
        """
        effective_config = self.get_effective_tuning_configuration()

        # ClickHouse always needs primary keys for MergeTree engine, even in no-tuning mode
        enable_primary_keys = True

        # Foreign keys follow normal tuning configuration
        enable_foreign_keys = effective_config.foreign_keys.enabled if effective_config else False

        return enable_primary_keys, enable_foreign_keys

    def _validate_data_integrity(
        self,
        benchmark: Any,
        connection: Any,
        table_stats: dict[str, int],
    ) -> tuple[str, dict[str, Any]]:
        """Validate data integrity and table accessibility for ClickHouse.

        Override base implementation to use execute() instead of cursor()
        which is not available in ClickHouseLocalClient.

        Args:
            benchmark: Benchmark instance
            connection: ClickHouse connection (server or local)
            table_stats: Dictionary of table names to row counts

        Returns:
            Tuple of (status, details) where status is "PASSED" or "FAILED"
        """
        validation_details: dict[str, Any] = {}

        try:
            execute_fn = getattr(connection, "execute", None)
            if not callable(execute_fn):
                raise TypeError("ClickHouse connection must expose an execute() method")

            accessible_tables = []
            inaccessible_tables = []

            for table_name in table_stats:
                try:
                    # ClickHouseLocalClient and ClickHouse server clients both expose execute().
                    execute_fn(f"SELECT 1 FROM {table_name} LIMIT 1")
                    accessible_tables.append(table_name)
                except Exception as e:
                    self.logger.debug(f"Table {table_name} inaccessible: {e}")
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            else:
                validation_details["accessible_tables"] = accessible_tables
                validation_details["constraints_enabled"] = True
                return "PASSED", validation_details

        except Exception as e:
            validation_details["constraints_enabled"] = False
            validation_details["integrity_error"] = str(e)
            return "FAILED", validation_details

    def execute_query(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute query with detailed timing and profiling."""
        start_time = mono_time()

        try:
            # Apply ClickHouse-specific query transformations for SQL compatibility
            transformer = ClickHouseQueryTransformer(verbose=self.very_verbose)
            transformed_query = transformer.transform(query)
            # Session settings stay generic; analyzer-sensitive query rewrites live in the benchmark.
            transformed_query = transformer.add_query_settings(transformed_query)

            # Log transformations if any were applied
            if transformer.get_transformations_applied() and self.verbose_enabled:
                self.log_verbose(
                    f"Query {query_id}: Applied transformations: {', '.join(transformer.get_transformations_applied())}"
                )

            # Execute the transformed query
            result = connection.execute(transformed_query)

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

            # Validate row count if enabled and benchmark type is provided
            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                # Log validation result
                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

                # If validation failed, mark query as failed
                if not validation_result.is_valid:
                    return {
                        "query_id": query_id,
                        "status": "FAILED",
                        "execution_time_seconds": execution_time,
                        "rows_returned": actual_row_count,
                        "row_count_validation": {
                            "expected": validation_result.expected_row_count,
                            "actual": actual_row_count,
                            "status": "FAILED",
                            "error": validation_result.error_message,
                        },
                        "error": validation_result.error_message,
                        "first_row": result[0] if result else None,
                        "translated_query": None,
                    }

            # Build successful result
            result_dict = {
                "query_id": query_id,
                "status": "SUCCESS",
                "execution_time_seconds": execution_time,
                "rows_returned": actual_row_count,
                "first_row": result[0] if result else None,
                "translated_query": None,  # Translation handled by base adapter
            }

            # Include validation metadata if validation was performed
            if validation_result:
                row_count_validation = {
                    "expected": validation_result.expected_row_count,
                    "actual": actual_row_count,
                    "status": "PASSED" if validation_result.is_valid else "SKIPPED",
                }
                if validation_result.warning_message:
                    row_count_validation["warning"] = validation_result.warning_message
                result_dict["row_count_validation"] = row_count_validation

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            error_type = type(e).__name__
            # Always populate `error` with a non-empty string - some exceptions
            # (e.g. chdb errors raised with no message) yield empty str(e).
            error_message = str(e) or repr(e) or error_type

            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": error_message,
                "error_type": error_type,
            }

        # Plan capture routes through the shared chokepoint, outside the try so a
        # strict-mode PlanCaptureError propagates rather than being swallowed by the
        # broad `except` above. For phase-eligible engines (the default) the
        # chokepoint records the executed query for the isolated post-measurement
        # phase instead of running EXPLAIN inline; otherwise it captures inline.
        # EXPLAIN targets the transformed query (the one that actually ran): the
        # original may not parse under ClickHouse without the compatibility transforms.
        self._merge_plan_capture_into_result(result_dict, connection, transformed_query, query_id)

        return result_dict


__all__ = ["ClickHouseWorkloadMixin"]
