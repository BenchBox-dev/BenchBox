"""Shared mixin for simple benchmarks with common run_benchmark and _load_data patterns.

Extracts duplicated query-iteration and table-loading logic from AMPLab, ClickBench, and SSB
benchmarks into a reusable mixin.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from benchbox.core.connection import DatabaseConnection
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


class SimpleBenchmarkMixin:
    """Mixin providing shared run_benchmark and _load_data for simple benchmarks.

    Consuming classes must provide:
    - ``_benchmark_label``: str - human-readable benchmark name for result dicts (e.g. "AMPLab")
    - ``_table_load_order``: list[str] - ordered table names for _load_data
    - ``query_manager`` with ``get_all_queries()`` returning dict[str, str]
    - ``get_query(query_id, *, params=None)`` returning str
    - ``execute_query(query_id, connection, params=None)`` returning results
    - ``get_create_tables_sql()`` returning str
    - ``tables``: dict[str, Any] - mapping of table name to data file path
    - ``scale_factor``: float
    - ``_get_table_schema()`` returning dict[str, dict] with "columns" key per table
    """

    _benchmark_label: str
    _table_load_order: list[str]

    def run_benchmark(self, connection: Any, queries: list[str] | None = None, iterations: int = 1) -> dict[str, Any]:
        """Run the complete benchmark with shared query-iteration logic.

        Args:
            connection: Database connection to use
            queries: Optional list of query IDs to run. If None, runs all.
            iterations: Number of times to run each query

        Returns:
            Dictionary containing benchmark results with per-query timings
        """
        if queries is None:
            queries = list(self.query_manager.get_all_queries().keys())

        results: dict[str, Any] = {
            "benchmark": self._benchmark_label,
            "scale_factor": self.scale_factor,
            "iterations": iterations,
            "queries": {},
        }

        for query_id in queries:
            query_results: dict[str, Any] = {
                "query_id": query_id,
                "iterations": [],
                "avg_time": 0,
                "min_time": float("inf"),
                "max_time": 0,
                "sql_text": self.get_query(query_id),
            }

            for i in range(iterations):
                start_time = mono_time()
                try:
                    result = self.execute_query(query_id, connection)
                    execution_time = elapsed_seconds(start_time)

                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": execution_time,
                            "rows": len(result) if result else 0,
                            "success": True,
                        }
                    )

                    query_results["min_time"] = min(query_results["min_time"], execution_time)
                    query_results["max_time"] = max(query_results["max_time"], execution_time)

                except Exception as e:
                    query_results["iterations"].append(
                        {
                            "iteration": i + 1,
                            "time": 0,
                            "error": str(e),
                            "success": False,
                        }
                    )

            # Calculate average time for successful iterations
            iterations_list: list[dict[str, Any]] = query_results["iterations"]
            successful_iterations = [iter_result for iter_result in iterations_list if iter_result["success"]]
            if successful_iterations:
                successful_times = [iter_result["time"] for iter_result in successful_iterations]
                successful_rows = [iter_result.get("rows", 0) for iter_result in successful_iterations]
                query_results["avg_time"] = sum(successful_times) / len(successful_times)
                query_results["rows_returned"] = (
                    int(sum(successful_rows) / len(successful_rows)) if successful_rows else 0
                )

            results["queries"][query_id] = query_results

        return results

    def _load_data(self, connection: DatabaseConnection) -> None:
        """Load benchmark data into the database.

        Creates the schema, then loads each table in ``_table_load_order`` from
        generated CSV files using INSERT statements.

        Args:
            connection: DatabaseConnection wrapper for database operations

        Raises:
            ValueError: If data hasn't been generated yet
            Exception: If data loading fails
        """
        label = self._benchmark_label

        if not self.tables:
            raise ValueError("No data has been generated. Call generate_data() first.")

        logger.info("Loading %s data into database...", label)

        # Create database schema first
        try:
            schema_sql = self.get_create_tables_sql()
            if ";" in schema_sql:
                statements = [stmt.strip() for stmt in schema_sql.split(";") if stmt.strip()]
                for statement in statements:
                    connection.execute(statement)
            else:
                connection.execute(schema_sql)
            connection.commit()
            logger.info("Created %s database schema", label)
        except Exception as e:
            logger.error("Failed to create database schema: %s", e)
            raise

        total_rows = 0
        loaded_tables = 0

        for table_name in self._table_load_order:
            if table_name not in self.tables:
                logger.warning("Skipping %s - no data file found", table_name)
                continue

            data_file = Path(self.tables[table_name])
            if not data_file.exists():
                logger.warning("Skipping %s - data file does not exist: %s", table_name, data_file)
                continue

            try:
                logger.info("Loading data for %s...", table_name.upper())
                rows_loaded = self._load_table_data(connection, table_name, data_file)

                total_rows += rows_loaded
                loaded_tables += 1
                logger.info("Loaded %s rows into %s", f"{rows_loaded:,}", table_name.upper())

            except Exception as e:
                logger.error("Failed to load data for %s: %s", table_name, e)
                raise

        try:
            connection.commit()
            logger.info("Successfully loaded %s total rows across %d tables", f"{total_rows:,}", loaded_tables)
        except Exception as e:
            logger.error("Failed to commit data loading transaction: %s", e)
            raise

    def _load_table_data(self, connection: DatabaseConnection, table_name: str, data_file: Path) -> int:
        """Load data into a database table using simple INSERT statements.

        Args:
            connection: DatabaseConnection wrapper
            table_name: Name of the table to load data into
            data_file: Path to the data file

        Returns:
            Number of rows loaded
        """
        table_schema = self._get_table_schema()[table_name]
        num_columns = len(table_schema["columns"])

        placeholders = ", ".join(["?" for _ in range(num_columns)])
        insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

        rows_loaded = 0

        with open(data_file, newline="", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")

            for row in reader:
                if len(row) != num_columns:
                    continue  # Skip malformed rows

                connection.execute(insert_sql, row)
                rows_loaded += 1

        return rows_loaded
