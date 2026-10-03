from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.input_validation import validate_sql_identifier

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import TuningColumn

try:
    from benchbox.core.tuning.interface import TuningType
except ImportError:
    TuningType = None


_REFERENCED_TABLE_RE = re.compile(
    r"\bREFERENCES\s+(?P<table>\"(?:[^\"]|\"\")*\"|[A-Za-z_][A-Za-z0-9_$]*)\s*\(",
    re.IGNORECASE,
)


class SortedIngestionMixin:
    platform_name: str
    logger: logging.Logger

    def get_sorted_ingestion_capability(self) -> dict[str, Any]:
        cloud_method_matrix = {
            "snowflake": ["ctas"],
            "databricks": ["ctas", "z_order", "liquid_clustering"],
            "bigquery": ["ctas"],
            "redshift": ["ctas", "vacuum_sort"],
            "athena": ["ctas"],
            "azure synapse": ["ctas"],
            "clickhouse cloud": [],
        }

        platform_key = self.platform_name.strip().lower()
        methods = cloud_method_matrix.get(platform_key, ["ctas"])
        is_cloud = platform_key in cloud_method_matrix
        return {
            "platform": self.platform_name,
            "is_cloud_platform": is_cloud,
            "supports_sorted_ingestion": bool(methods),
            "supported_methods": methods,
        }

    def resolve_sorted_ingestion_strategy(self) -> tuple[str, str]:
        capability = self.get_sorted_ingestion_capability()
        supported_methods = capability["supported_methods"]

        effective_config = self.get_effective_tuning_configuration()
        platform_optimizations = getattr(effective_config, "platform_optimizations", None)

        mode = getattr(platform_optimizations, "sorted_ingestion_mode", "off")
        method = getattr(platform_optimizations, "sorted_ingestion_method", "auto")

        if mode == "off":
            return "off", "auto"

        if method != "auto" and method not in supported_methods:
            raise ValueError(
                f"Sorted ingestion method '{method}' is not supported for platform '{self.platform_name}'."
            )

        if not supported_methods:
            if mode == "force":
                raise ValueError(f"Sorted ingestion mode 'force' is not supported for platform '{self.platform_name}'.")
            return "off", "none"

        resolved_method = method if method != "auto" else supported_methods[0]
        return mode, resolved_method

    def get_sorted_ingestion_metadata(self) -> dict[str, Any]:
        effective_config = self.get_effective_tuning_configuration()
        platform_optimizations = getattr(effective_config, "platform_optimizations", None)
        configured_mode = getattr(platform_optimizations, "sorted_ingestion_mode", "off")
        configured_method = getattr(platform_optimizations, "sorted_ingestion_method", "auto")

        resolved_mode: str | None = None
        resolved_method: str | None = None
        resolution_error: str | None = None
        try:
            resolved_mode, resolved_method = self.resolve_sorted_ingestion_strategy()
        except Exception as exc:  # pragma: no cover - defensive metadata path
            resolution_error = str(exc)

        applied_tables = getattr(self, "_sorted_ingestion_applied_tables", [])
        total_apply_seconds = getattr(self, "_sorted_ingestion_total_apply_seconds", 0.0)
        unique_tables = sorted(set(applied_tables))
        return {
            "configured_mode": configured_mode,
            "configured_method": configured_method,
            "resolved_mode": resolved_mode,
            "resolved_method": resolved_method,
            "capability": self.get_sorted_ingestion_capability(),
            "applied_tables": unique_tables,
            "applied_table_count": len(unique_tables),
            "total_apply_seconds": total_apply_seconds,
            "resolution_error": resolution_error,
        }

    def apply_ctas_sort(self, table_name: str, tuning_config: Any, connection: Any) -> bool:
        sort_columns = self._resolve_ctas_sort_columns(table_name, tuning_config)
        if sort_columns is None:
            return False

        validated_table = validate_sql_identifier(table_name, "table name")
        sorted_columns = sorted(sort_columns, key=lambda column: column.order)
        for column in sorted_columns:
            validate_sql_identifier(column.name, "sort column")
        intent_statement = self._sorted_ingestion_intent(validated_table, sorted_columns)
        try:
            ctas_sort_sql = self._build_ctas_sort_sql(validated_table, sorted_columns)
        except Exception as exc:
            self._record_sorted_ingestion_failure(intent_statement, validated_table, exc)
            raise

        if ctas_sort_sql is None:
            reason = f"{self.platform_name} does not support CTAS sort"
            self._record_sorted_ingestion_skip(validated_table, sorted_columns, reason)
            self.logger.debug(f"{reason} for {table_name}; skipping")
            return False

        statements = ctas_sort_sql if isinstance(ctas_sort_sql, list) else [ctas_sort_sql]
        constraint_preserving = self._requires_constraint_preserving_ctas_sort
        if constraint_preserving:
            statements = self._build_fk_safe_ctas_sort_sql(validated_table, sorted_columns)
        return self._execute_ctas_sort(
            table_name,
            validated_table,
            sorted_columns,
            statements,
            connection,
            atomic=constraint_preserving,
        )

    @property
    def _requires_constraint_preserving_ctas_sort(self) -> bool:
        platform_key = getattr(self, "platform_name", "").strip().lower()
        return platform_key in ("duckdb", "motherduck")

    def _build_fk_safe_ctas_sort_sql(
        self, validated_table: str, sorted_columns: list[TuningColumn]
    ) -> list[str] | None:
        temp_table = f"{validated_table}__ctas_sort"
        order_by = ", ".join(f'"{col.name}"' for col in sorted_columns)
        return [
            f'CREATE TEMP TABLE "{temp_table}" AS SELECT * FROM "{validated_table}" ORDER BY {order_by};',
            f'DELETE FROM "{validated_table}";',
            f'INSERT INTO "{validated_table}" SELECT * FROM "{temp_table}";',
            f'DROP TABLE "{temp_table}";',
        ]

    def _resolve_ctas_sort_columns(self, table_name: str, tuning_config: Any) -> list | None:
        if not tuning_config:
            self.logger.debug(f"No tuning config provided for {table_name}; skipping CTAS sort")
            return None

        table_tunings = getattr(tuning_config, "table_tunings", None)
        if not table_tunings:
            self.logger.debug(f"No table tunings configured for {table_name}; skipping CTAS sort")
            return None

        table_tuning = None
        for configured_name, configured_tuning in table_tunings.items():
            if configured_name.lower() == table_name.lower():
                table_tuning = configured_tuning
                break

        if not table_tuning:
            self.logger.debug(f"Table {table_name} not present in tuning config; skipping CTAS sort")
            return None

        if TuningType is None:
            self.logger.debug("TuningType unavailable; skipping CTAS sort")
            return None

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if not sort_columns:
            self.logger.debug(f"No sort columns for {table_name}; skipping CTAS sort")
            return None

        return sort_columns

    def _execute_ctas_sort(
        self,
        table_name: str,
        validated_table: str,
        sorted_columns: list,
        statements: list[str],
        connection: Any,
        *,
        atomic: bool = False,
    ) -> bool:
        apply_start = mono_time()
        if not hasattr(self, "_sorted_ingestion_applied_tables"):
            self._sorted_ingestion_applied_tables = []
        if not hasattr(self, "_sorted_ingestion_total_apply_seconds"):
            self._sorted_ingestion_total_apply_seconds = 0.0
        if self.dry_run_mode:
            for statement in statements:
                self.capture_sql(statement, "ctas_sort", validated_table)
            self._sorted_ingestion_applied_tables.append(validated_table)
            return True

        ledger_statement = "\n".join(statements)
        transaction_started = False
        try:
            if atomic:
                if self._connection_has_active_transaction(connection):
                    reason = "connection already has an active transaction owned by the caller"
                    self._record_sorted_ingestion_skip(validated_table, sorted_columns, reason)
                    self.logger.info("Skipping constraint-preserving CTAS sort for %s: %s", table_name, reason)
                    return False
                self._execute_sql_statement(connection, "BEGIN TRANSACTION;")
                transaction_started = True
            if atomic and self._has_populated_fk_dependents(connection, validated_table):
                self._rollback_transaction(connection)
                transaction_started = False
                reason = "populated foreign-key dependents prevent an in-place rewrite"
                self._record_sorted_ingestion_skip(validated_table, sorted_columns, reason)
                self.logger.info(
                    "Skipping constraint-preserving CTAS sort for %s because %s",
                    table_name,
                    reason,
                )
                return False
            for statement in statements:
                self._execute_sql_statement(connection, statement)
            if atomic:
                commit_method = getattr(connection, "commit", None)
                if callable(commit_method):
                    commit_method()
                else:
                    self._execute_sql_statement(connection, "COMMIT;")
                transaction_started = False
        except Exception as exc:
            rollback_error: Exception | None = None
            if transaction_started:
                try:
                    self._rollback_transaction(connection)
                except Exception as cleanup_error:  # pragma: no cover - defensive cleanup path
                    rollback_error = cleanup_error
                    self.logger.warning(
                        f"Failed to roll back constraint-preserving CTAS sort for {table_name}: {cleanup_error}"
                    )
            if rollback_error is not None:
                unsafe_error = RuntimeError(
                    f"Constraint-preserving CTAS sort for {table_name} failed and could not be rolled back: "
                    f"{rollback_error}"
                )
                self._record_sorted_ingestion_failure(ledger_statement, validated_table, unsafe_error)
                raise unsafe_error from exc
            self._record_sorted_ingestion_failure(ledger_statement, validated_table, exc)
            if atomic:
                self.logger.warning(
                    "Constraint-preserving CTAS sort for %s failed safely and was rolled back: %s", table_name, exc
                )
                return False
            raise
        self._sorted_ingestion_applied_tables.append(validated_table)
        self._sorted_ingestion_total_apply_seconds += elapsed_seconds(apply_start)
        sorted_col_names = ", ".join(column.name for column in sorted_columns)
        self.log_verbose(f"Applied CTAS sorting to {table_name}: {sorted_col_names}")
        return True

    def _has_populated_fk_dependents(self, connection: Any, validated_table: str) -> bool:
        execute_method = getattr(connection, "execute", None)
        if not callable(execute_method):
            return False

        metadata = execute_method(
            "SELECT table_name, constraint_column_names, constraint_text "
            "FROM duckdb_constraints() WHERE constraint_type = 'FOREIGN KEY';"
        )
        rows = metadata.fetchall()
        for row in rows:
            child_table, child_columns, constraint_text = row
            child_name = validate_sql_identifier(str(child_table), "referencing table")
            referenced_table = self._referenced_table_from_constraint(str(constraint_text or ""))
            if referenced_table is None:
                if child_name.lower() != validated_table.lower():
                    continue
            elif referenced_table.lower() != validated_table.lower():
                continue
            validated_columns = [validate_sql_identifier(str(column), "foreign key column") for column in child_columns]
            if not validated_columns:
                continue
            non_null_predicate = " AND ".join(f'"{column}" IS NOT NULL' for column in validated_columns)
            dependent = execute_method(f'SELECT 1 FROM "{child_name}" WHERE {non_null_predicate} LIMIT 1;')
            if dependent.fetchone() is not None:
                return True
        return False

    @staticmethod
    def _referenced_table_from_constraint(constraint_text: str) -> str | None:
        match = _REFERENCED_TABLE_RE.search(constraint_text)
        if match is None:
            return None
        table = match.group("table")
        if table.startswith('"') and table.endswith('"'):
            table = table[1:-1].replace('""', '"')
        return validate_sql_identifier(table, "referenced table")

    @staticmethod
    def _connection_has_active_transaction(connection: Any) -> bool:
        tracked_state = getattr(connection, "transaction_active", None)
        if isinstance(tracked_state, bool):
            return tracked_state

        module_name = (type(connection).__module__ or "").lower()
        if "duckdb" not in module_name:
            return False
        execute_method = getattr(connection, "execute", None)
        if not callable(execute_method):
            return True
        try:
            first = execute_method("SELECT txid_current();").fetchone()
            second = execute_method("SELECT txid_current();").fetchone()
        except Exception:
            return True
        return bool(first and second and first[0] == second[0])

    def _record_sorted_ingestion_failure(self, statement: str, table: str, error: Exception) -> None:
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None:
            return
        from benchbox.core.tuning.applied_ledger import PHASE_POST_LOAD, STATEMENT_FAILED

        ledger.record(
            statement,
            PHASE_POST_LOAD,
            status=STATEMENT_FAILED,
            mechanism="sorted_ingestion",
            table=table,
            error=error,
        )

    def _record_sorted_ingestion_skip(self, table: str, sorted_columns: list, reason: str) -> None:
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None:
            return
        ledger.record_dropped(self._sorted_ingestion_intent(table, sorted_columns), reason)

    @staticmethod
    def _sorted_ingestion_intent(table: str, sorted_columns: list) -> str:
        columns = ", ".join(column.name for column in sorted_columns)
        return f"sorted_ingestion {table} ORDER BY {columns}"

    def _rollback_transaction(self, connection: Any) -> None:
        rollback_method = getattr(connection, "rollback", None)
        if callable(rollback_method):
            rollback_method()
        else:
            self._execute_sql_statement(connection, "ROLLBACK;")

    @staticmethod
    def _execute_sql_statement(connection: Any, statement: str) -> None:
        execute_method = getattr(connection, "execute", None)
        if callable(execute_method):
            execute_method(statement)
            return

        cursor_method = getattr(connection, "cursor", None)
        if callable(cursor_method):
            cursor = cursor_method()
            try:
                cursor.execute(statement)
            finally:
                close_method = getattr(cursor, "close", None)
                if callable(close_method):
                    close_method()
            return

        raise TypeError("Connection must provide execute() or cursor().execute() for CTAS sort")

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[TuningColumn]) -> str | list[str] | None:
        return None
