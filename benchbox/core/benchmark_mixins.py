"""Shared benchmark mixins for common data generation and loading behavior.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any, Optional, Union

from benchbox.utils.clock import elapsed_seconds, mono_time


class DataGenerationMixin:
    """Shared data generation and CSV loading flow for table-based benchmarks."""

    tables: dict[str, Any]
    data_generator: Any

    def _get_table_schema(self) -> dict[str, Any]:
        """Return benchmark table schema mapping used for validation and loading."""
        raise NotImplementedError

    def _get_data_loading_batch_size(self) -> int | None:
        """Return batch size for executemany inserts, or None to load all rows at once."""
        return None

    def generate_data(self, tables: Optional[list[str]] = None, output_format: str = "csv") -> dict[str, Any]:
        """Generate benchmark data files for the requested tables."""
        if output_format != "csv":
            raise ValueError(f"Unsupported output format: {output_format}")

        table_schema = self._get_table_schema()

        if tables is None:
            tables = list(table_schema.keys())

        invalid_tables = set(tables) - set(table_schema.keys())
        if invalid_tables:
            raise ValueError(f"Invalid table names: {invalid_tables}")

        self.tables = self.data_generator.generate_data(tables)
        return self.tables

    def load_data_to_database(self, connection: Any, tables: Optional[list[str]] = None) -> None:
        """Load generated CSV data into a database connection."""
        if not self.tables:
            raise ValueError("No data generated. Call generate_data() first.")

        if tables is None:
            tables = list(self.tables.keys())

        self._execute_schema_sql(connection)

        table_schema = self._get_table_schema()
        batch_size = self._get_data_loading_batch_size()

        for table_name in tables:
            if table_name not in self.tables or table_name not in table_schema:
                continue
            self._load_single_table(connection, table_name, table_schema[table_name], batch_size)

        if hasattr(connection, "commit"):
            connection.commit()

    def _execute_schema_sql(self, connection: Any) -> None:
        """Execute CREATE TABLE statements against the connection."""
        schema_sql = self.get_create_tables_sql()
        if hasattr(connection, "executescript"):
            connection.executescript(schema_sql)
        else:
            cursor = connection.cursor()
            for statement in schema_sql.split(";"):
                if statement.strip():
                    cursor.execute(statement)

    def _load_single_table(self, connection: Any, table_name: str, table_def: dict, batch_size: int | None) -> None:
        """Load a single table's CSV data into the database."""
        import csv

        file_path = self.tables[table_name]

        with open(file_path, encoding="utf-8") as handle:
            reader = csv.reader(handle, delimiter="|")

            columns = [col["name"] for col in table_def["columns"]]
            placeholders = ",".join(["?" for _ in columns])
            insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

            if hasattr(connection, "executemany"):
                if batch_size:
                    batch = []
                    for row in reader:
                        batch.append(row)
                        if len(batch) >= batch_size:
                            connection.executemany(insert_sql, batch)
                            batch = []
                    if batch:
                        connection.executemany(insert_sql, batch)
                else:
                    connection.executemany(insert_sql, list(reader))
            else:
                cursor = connection.cursor()
                for row in reader:
                    cursor.execute(insert_sql, row)


class QueryCategoryFacadeMixin:
    """Shared facade delegation for query category accessors."""

    _impl: Any

    def get_queries_by_category(self, category: str) -> dict[str, str]:
        """Delegate query-category lookup to the benchmark implementation."""
        return self._impl.get_queries_by_category(category)

    def get_query_categories(self) -> list[str]:
        """Delegate query-category listing to the benchmark implementation."""
        return self._impl.get_query_categories()


class OperationCategoryFacadeMixin:
    """Shared facade delegation for operation category accessors."""

    _impl: Any

    def get_operations_by_category(self, category: str) -> dict[str, Any]:
        """Delegate operation-category lookup to the benchmark implementation."""
        return self._impl.get_operations_by_category(category)

    def get_operation_categories(self) -> list[str]:
        """Delegate operation-category listing to the benchmark implementation."""
        return self._impl.get_operation_categories()


class QueryFacadeMixin:
    """Shared facade delegation for basic query retrieval methods."""

    _impl: Any

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Delegate query listing to the benchmark implementation."""
        return self._impl.get_queries(dialect=dialect)

    def get_query(
        self,
        query_id: Union[int, str],
        *,
        params: Optional[dict[str, Any]] = None,
        **kwargs: Any,
    ) -> str:
        """Delegate query retrieval while preserving params/kwargs compatibility."""
        if params is None:
            return self._impl.get_query(query_id, **kwargs)
        return self._impl.get_query(query_id, params=params, **kwargs)


class CursorValidationQueryExecutionMixin:
    """Shared DBAPI cursor execute flow with row-count validation and query stats.

    Consuming classes must provide:
    - log_verbose(msg: str) -> None
    - log_very_verbose(msg: str) -> None
    - _build_query_result_with_validation(**kwargs) -> dict[str, Any]
    """

    _REQUIRED_METHODS = ("log_verbose", "log_very_verbose", "_build_query_result_with_validation")

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        # Skip enforcement on intermediate mixins that aren't concrete adapters.
        # Concrete adapters will be checked when they are defined.
        if cls.__name__.endswith(("Mixin", "Base")):
            return
        for method_name in CursorValidationQueryExecutionMixin._REQUIRED_METHODS:
            # Walk the MRO excluding this mixin and the class itself to verify
            # that some other parent provides the method (not a local stub).
            providers = [
                c
                for c in cls.__mro__
                if c not in (cls, CursorValidationQueryExecutionMixin, object) and method_name in c.__dict__
            ]
            if not providers:
                raise TypeError(
                    f"{cls.__name__} uses CursorValidationQueryExecutionMixin but does not "
                    f"inherit a concrete implementation of {method_name}(). "
                    f"Ensure a parent class (e.g. PlatformAdapter) provides it."
                )

    def _build_query_stats(self, execution_time: float) -> dict[str, Any]:
        """Build default query stats payload for cursor-based adapters."""
        return {"execution_time_seconds": execution_time}

    def _attach_query_stats(self, result_dict: dict[str, Any], query_stats: dict[str, Any]) -> None:
        """Attach platform query stats and resource usage to result payload.

        Both keys share the same dict for schema backward compatibility: downstream
        consumers read from either key depending on context (result schema uses
        query_statistics, telemetry pipelines use resource_usage).
        """
        result_dict["query_statistics"] = query_stats
        result_dict["resource_usage"] = query_stats

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
        """Execute query via DBAPI cursor with optional row-count validation."""
        start_time = mono_time()
        cursor = connection.cursor()

        try:
            cursor.execute(query)
            result = cursor.fetchall()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0
            query_stats = self._build_query_stats(execution_time)

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

                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=result[0] if result else None,
                validation_result=validation_result,
            )
            self._attach_query_stats(result_dict, query_stats)
            return result_dict

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            return {
                "query_id": query_id,
                "status": "FAILED",
                "execution_time_seconds": execution_time,
                "rows_returned": 0,
                "error": str(e),
                "error_type": type(e).__name__,
            }
        finally:
            cursor.close()
