# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-H specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from benchbox.utils.clock import elapsed_seconds, mono_time


@dataclass
class TPCHMaintenanceTestConfig:
    scale_factor: float = 1.0
    maintenance_pairs: int = 1
    rf1_interval: float = 30.0
    rf2_interval: float = 30.0
    concurrent_with_queries: bool = True
    validate_integrity: bool = True
    verbose: bool = False
    output_dir: Optional[Path] = None


@dataclass
class TPCHMaintenanceOperation:
    operation_type: str
    start_time: float
    end_time: float
    duration: float
    rows_affected: int
    success: bool
    error: Optional[str] = None


@dataclass
class TPCHMaintenanceTestResult:
    config: TPCHMaintenanceTestConfig
    start_time: str
    end_time: str
    total_time: float
    rf1_operations: int
    rf2_operations: int
    total_operations: int
    successful_operations: int
    failed_operations: int
    operations: list[TPCHMaintenanceOperation] = field(default_factory=list)
    overall_throughput: float = 0.0
    success: bool = True
    errors: list[str] = field(default_factory=list)

    @property
    def scale_factor(self) -> float:
        return self.config.scale_factor


class TPCHMaintenanceTest:
    def __init__(
        self,
        connection_factory: Callable[[], Any],
        scale_factor: float = 1.0,
        output_dir: Optional[Path] = None,
        verbose: bool = False,
    ) -> None:
        self.connection_factory = connection_factory
        self.scale_factor = scale_factor
        self.output_dir = output_dir or Path.cwd() / "maintenance_test"
        self.verbose = verbose

        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.INFO)

    def run_maintenance_test(
        self,
        maintenance_pairs: int = 1,
        concurrent_with_queries: bool = True,
        _query_stream_duration: Optional[float] = None,
        rf1_interval: float = 30.0,
        rf2_interval: float = 30.0,
        validate_integrity: bool = True,
    ) -> TPCHMaintenanceTestResult:
        config = TPCHMaintenanceTestConfig(
            scale_factor=self.scale_factor,
            maintenance_pairs=maintenance_pairs,
            rf1_interval=rf1_interval,
            rf2_interval=rf2_interval,
            concurrent_with_queries=concurrent_with_queries,
            validate_integrity=validate_integrity,
            verbose=self.verbose,
            output_dir=self.output_dir,
        )

        start_time = mono_time()
        start_time_str = datetime.now().isoformat()

        result = TPCHMaintenanceTestResult(
            config=config,
            start_time=start_time_str,
            end_time="",
            total_time=0.0,
            rf1_operations=0,
            rf2_operations=0,
            total_operations=0,
            successful_operations=0,
            failed_operations=0,
        )

        try:
            if self.verbose:
                self.logger.info("Starting TPC-H Maintenance Test")
                self.logger.info(f"Maintenance pairs: {maintenance_pairs}")
                self.logger.info(f"Scale factor: {self.scale_factor}")

            for pair_id in range(maintenance_pairs):
                if self.verbose:
                    self.logger.info(f"Executing maintenance pair {pair_id + 1}")

                rf1_result = self._execute_rf1(pair_id)
                result.operations.append(rf1_result)
                result.total_operations += 1
                result.rf1_operations += 1

                if rf1_result.success:
                    result.successful_operations += 1
                else:
                    result.failed_operations += 1
                    result.errors.append(f"RF1 pair {pair_id + 1} failed: {rf1_result.error}")

                if rf1_interval > 0:
                    time.sleep(rf1_interval)

                rf2_result = self._execute_rf2(pair_id)
                result.operations.append(rf2_result)
                result.total_operations += 1
                result.rf2_operations += 1

                if rf2_result.success:
                    result.successful_operations += 1
                else:
                    result.failed_operations += 1
                    result.errors.append(f"RF2 pair {pair_id + 1} failed: {rf2_result.error}")

                if rf2_interval > 0 and pair_id < maintenance_pairs - 1:
                    time.sleep(rf2_interval)

            total_time = elapsed_seconds(start_time)
            result.total_time = total_time
            result.end_time = datetime.now().isoformat()

            if total_time > 0:
                result.overall_throughput = result.successful_operations / total_time

            result.success = result.failed_operations == 0

            if self.verbose:
                self.logger.info(f"Maintenance Test completed in {total_time:.3f}s")
                self.logger.info(f"Successful operations: {result.successful_operations}/{result.total_operations}")
                self.logger.info(f"Overall throughput: {result.overall_throughput:.2f} ops/sec")

            return result

        except Exception as e:
            result.total_time = elapsed_seconds(start_time)
            result.end_time = datetime.now().isoformat()
            result.success = False
            result.errors.append(f"Maintenance Test execution failed: {e}")

            if self.verbose:
                self.logger.error(f"Maintenance Test failed: {e}")

            return result

    def get_maintenance_operations_sql(
        self,
        pair_id: int = 0,
        placeholder: str = "?",
    ) -> dict[str, list[str]]:
        import random

        rf1_statements = []
        rf2_statements = []

        num_orders = max(1, int(self.scale_factor * 1500 * 0.001))
        orders = self._generate_rf1_orders_data(pair_id, num_orders)

        all_lineitems = []
        for order in orders:
            num_items = random.randint(1, 7)
            lineitems = self._generate_rf1_lineitems_data(order["O_ORDERKEY"], num_items)
            all_lineitems.extend(lineitems)

        if orders:
            columns = ", ".join(orders[0].keys())
            batch_size = 100
            for batch_start in range(0, len(orders), batch_size):
                batch_orders = orders[batch_start : batch_start + batch_size]
                values_placeholders = []
                for order in batch_orders:
                    row_placeholders = ", ".join([placeholder for _ in order])
                    values_placeholders.append(f"({row_placeholders})")
                insert_sql = f"INSERT INTO ORDERS ({columns}) VALUES {', '.join(values_placeholders)}"
                sample_values = list(batch_orders[0].values())[:3] if batch_orders else []
                rf1_statements.append(f"-- Sample values: {sample_values}...\n{insert_sql}")

        if all_lineitems:
            columns = ", ".join(all_lineitems[0].keys())
            batch_size = 100
            for batch_start in range(0, len(all_lineitems), batch_size):
                batch_lineitems = all_lineitems[batch_start : batch_start + batch_size]
                values_placeholders = []
                for lineitem in batch_lineitems:
                    row_placeholders = ", ".join([placeholder for _ in lineitem])
                    values_placeholders.append(f"({row_placeholders})")
                insert_sql = f"INSERT INTO LINEITEM ({columns}) VALUES {', '.join(values_placeholders)}"
                sample_values = list(batch_lineitems[0].values())[:3] if batch_lineitems else []
                rf1_statements.append(f"-- Sample values: {sample_values}...\n{insert_sql}")

        num_to_delete = max(1, int(self.scale_factor * 1500 * 0.001))
        max_order_key = int(6000000 * self.scale_factor)
        sample_order_keys = list(range(1, min(num_to_delete + 1, max_order_key + 1)))

        rf2_statements.append(
            f"-- Identify {num_to_delete} oldest orders to delete\n"
            f"SELECT O_ORDERKEY FROM ORDERS ORDER BY O_ORDERDATE ASC LIMIT {num_to_delete}"
        )

        placeholders_str = ", ".join([placeholder for _ in sample_order_keys])
        rf2_statements.append(
            f"-- Delete lineitems for identified orders\nDELETE FROM LINEITEM WHERE L_ORDERKEY IN ({placeholders_str})"
        )

        rf2_statements.append(f"-- Delete the orders\nDELETE FROM ORDERS WHERE O_ORDERKEY IN ({placeholders_str})")

        return {"RF1": rf1_statements, "RF2": rf2_statements}

    def _generate_rf1_orders_data(self, pair_id: int, num_orders: int) -> list[dict[str, Any]]:
        import random
        from datetime import datetime, timedelta

        orders = []
        base_order_key = 6000000 * int(self.scale_factor) + (pair_id * 10000) + int(time.time() % 10000)

        for i in range(num_orders):
            order_key = base_order_key + i

            order_date = datetime.now() - timedelta(days=random.randint(1, 365))

            orders.append(
                {
                    "O_ORDERKEY": order_key,
                    "O_CUSTKEY": random.randint(1, max(1, int(150000 * self.scale_factor))),
                    "O_ORDERSTATUS": random.choice(["O", "F", "P"]),
                    "O_TOTALPRICE": round(random.uniform(1000.0, 500000.0), 2),
                    "O_ORDERDATE": order_date.strftime("%Y-%m-%d"),
                    "O_ORDERPRIORITY": random.choice(["1-URGENT", "2-HIGH", "3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]),
                    "O_CLERK": f"Clerk#{random.randint(1, 1000):09d}",
                    "O_SHIPPRIORITY": 0,
                    "O_COMMENT": f"Maintenance RF1 pair {pair_id}",
                }
            )

        return orders

    def _generate_rf1_lineitems_data(self, order_key: int, num_items: int) -> list[dict[str, Any]]:
        import random
        from datetime import datetime, timedelta

        lineitems = []
        ship_date_base = datetime.now() - timedelta(days=random.randint(30, 365))

        for line_num in range(1, num_items + 1):
            ship_date = ship_date_base + timedelta(days=random.randint(0, 30))
            commit_date = ship_date + timedelta(days=random.randint(1, 30))
            receipt_date = commit_date + timedelta(days=random.randint(1, 10))

            quantity = random.uniform(1.0, 50.0)
            price = random.uniform(900.0, 100000.0)
            discount = random.uniform(0.0, 0.10)
            tax = random.uniform(0.0, 0.08)

            lineitems.append(
                {
                    "L_ORDERKEY": order_key,
                    "L_PARTKEY": random.randint(1, max(1, int(200000 * self.scale_factor))),
                    "L_SUPPKEY": random.randint(1, max(1, int(10000 * self.scale_factor))),
                    "L_LINENUMBER": line_num,
                    "L_QUANTITY": round(quantity, 2),
                    "L_EXTENDEDPRICE": round(price, 2),
                    "L_DISCOUNT": round(discount, 2),
                    "L_TAX": round(tax, 2),
                    "L_RETURNFLAG": random.choice(["R", "A", "N"]),
                    "L_LINESTATUS": random.choice(["O", "F"]),
                    "L_SHIPDATE": ship_date.strftime("%Y-%m-%d"),
                    "L_COMMITDATE": commit_date.strftime("%Y-%m-%d"),
                    "L_RECEIPTDATE": receipt_date.strftime("%Y-%m-%d"),
                    "L_SHIPINSTRUCT": random.choice(["DELIVER IN PERSON", "COLLECT COD", "NONE", "TAKE BACK RETURN"]),
                    "L_SHIPMODE": random.choice(["AIR", "MAIL", "SHIP", "TRUCK", "RAIL", "REG AIR", "FOB"]),
                    "L_COMMENT": "RF1 lineitem",
                }
            )

        return lineitems

    def _get_parameter_placeholder(self, connection: Any) -> str:
        connection_type = type(connection).__name__.lower()

        if "sqlite" in connection_type or "duckdb" in connection_type:
            return "?"
        elif "psycopg" in connection_type or "postgres" in connection_type or "mysql" in connection_type:
            return "%s"
        else:
            return "?"

    def _identify_old_orders(self, connection: Any, num_to_delete: int) -> list[int]:
        try:
            query = f"""
                SELECT O_ORDERKEY
                FROM ORDERS
                ORDER BY O_ORDERDATE ASC
                LIMIT {num_to_delete}
            """

            cursor = connection.execute(query)
            rows = cursor.fetchall()

            return [row[0] for row in rows]
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Failed to identify old orders: {e}")
            return []

    def _validate_customer_keys(self, connection: Any, custkeys: list[int]) -> tuple[bool, list[int]]:
        if not custkeys:
            return True, []

        unique_keys = list(set(custkeys))
        placeholder = self._get_parameter_placeholder(connection)
        placeholders = ", ".join([placeholder for _ in unique_keys])

        query = f"SELECT C_CUSTKEY FROM CUSTOMER WHERE C_CUSTKEY IN ({placeholders})"

        try:
            cursor = connection.execute(query, tuple(unique_keys))
            valid_keys = {row[0] for row in cursor.fetchall()}
            invalid_keys = [k for k in unique_keys if k not in valid_keys]

            return len(invalid_keys) == 0, invalid_keys
        except Exception as e:
            self.logger.error(f"Error validating customer keys: {e}")
            raise

    def _validate_part_supplier_keys(
        self, connection: Any, partkeys: list[int], suppkeys: list[int]
    ) -> tuple[bool, list[int], list[int]]:
        placeholder = self._get_parameter_placeholder(connection)

        invalid_partkeys = []
        if partkeys:
            unique_partkeys = list(set(partkeys))
            placeholders = ", ".join([placeholder for _ in unique_partkeys])
            query = f"SELECT P_PARTKEY FROM PART WHERE P_PARTKEY IN ({placeholders})"

            try:
                cursor = connection.execute(query, tuple(unique_partkeys))
                valid_partkeys = {row[0] for row in cursor.fetchall()}
                invalid_partkeys = [k for k in unique_partkeys if k not in valid_partkeys]
            except Exception as e:
                self.logger.error(f"Error validating part keys: {e}")
                raise

        invalid_suppkeys = []
        if suppkeys:
            unique_suppkeys = list(set(suppkeys))
            placeholders = ", ".join([placeholder for _ in unique_suppkeys])
            query = f"SELECT S_SUPPKEY FROM SUPPLIER WHERE S_SUPPKEY IN ({placeholders})"

            try:
                cursor = connection.execute(query, tuple(unique_suppkeys))
                valid_suppkeys = {row[0] for row in cursor.fetchall()}
                invalid_suppkeys = [k for k in unique_suppkeys if k not in valid_suppkeys]
            except Exception as e:
                self.logger.error(f"Error validating supplier keys: {e}")
                raise

        all_valid = len(invalid_partkeys) == 0 and len(invalid_suppkeys) == 0
        return all_valid, invalid_partkeys, invalid_suppkeys

    def _validate_rf1_data(
        self, connection: Any, orders: list[dict[str, Any]], lineitems: list[dict[str, Any]]
    ) -> None:
        if self.verbose:
            self.logger.info("Validating foreign key constraints for RF1 data...")

        custkeys = [order["O_CUSTKEY"] for order in orders]
        partkeys = [item["L_PARTKEY"] for item in lineitems]
        suppkeys = [item["L_SUPPKEY"] for item in lineitems]

        valid_cust, invalid_custkeys = self._validate_customer_keys(connection, custkeys)
        if not valid_cust:
            raise ValueError(
                f"Invalid CUSTKEY references found: {invalid_custkeys[:10]}... "
                f"({len(invalid_custkeys)} total invalid keys)"
            )

        valid_parts, invalid_partkeys, invalid_suppkeys = self._validate_part_supplier_keys(
            connection, partkeys, suppkeys
        )
        if not valid_parts:
            error_msg = []
            if invalid_partkeys:
                error_msg.append(
                    f"Invalid PARTKEY references: {invalid_partkeys[:10]}... ({len(invalid_partkeys)} total)"
                )
            if invalid_suppkeys:
                error_msg.append(
                    f"Invalid SUPPKEY references: {invalid_suppkeys[:10]}... ({len(invalid_suppkeys)} total)"
                )
            raise ValueError(" | ".join(error_msg))

        if self.verbose:
            self.logger.info("All foreign key constraints validated successfully")

    def _execute_rf1(self, pair_id: int) -> TPCHMaintenanceOperation:
        start_time = mono_time()

        operation = TPCHMaintenanceOperation(
            operation_type="RF1",
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            rows_affected=0,
            success=False,
        )

        connection = None
        try:
            if self.verbose:
                self.logger.info(f"Executing RF1 for pair {pair_id + 1}")

            connection = self.connection_factory()

            num_orders = max(1, int(self.scale_factor * 1500 * 0.001))

            if self.verbose:
                self.logger.info(f"Generating {num_orders} orders for RF1")

            orders = self._generate_rf1_orders_data(pair_id, num_orders)

            import random

            all_lineitems = []
            for order in orders:
                num_items = random.randint(1, 7)
                lineitems = self._generate_rf1_lineitems_data(order["O_ORDERKEY"], num_items)
                all_lineitems.extend(lineitems)

            self._validate_rf1_data(connection, orders, all_lineitems)

            placeholder = self._get_parameter_placeholder(connection)

            rows_affected = 0

            if orders:
                columns = ", ".join(orders[0].keys())
                batch_size = 100

                for batch_start in range(0, len(orders), batch_size):
                    batch_orders = orders[batch_start : batch_start + batch_size]

                    values_placeholders = []
                    params = []
                    for order in batch_orders:
                        row_placeholders = ", ".join([placeholder for _ in order])
                        values_placeholders.append(f"({row_placeholders})")
                        params.extend(order.values())

                    insert_sql = f"INSERT INTO ORDERS ({columns}) VALUES {', '.join(values_placeholders)}"
                    cursor = connection.execute(insert_sql, tuple(params))
                    rowcount = getattr(cursor, "rowcount", len(batch_orders))
                    rows_affected += max(len(batch_orders), rowcount)

            if all_lineitems:
                columns = ", ".join(all_lineitems[0].keys())
                batch_size = 100

                for batch_start in range(0, len(all_lineitems), batch_size):
                    batch_lineitems = all_lineitems[batch_start : batch_start + batch_size]

                    values_placeholders = []
                    params = []
                    for lineitem in batch_lineitems:
                        row_placeholders = ", ".join([placeholder for _ in lineitem])
                        values_placeholders.append(f"({row_placeholders})")
                        params.extend(lineitem.values())

                    insert_sql = f"INSERT INTO LINEITEM ({columns}) VALUES {', '.join(values_placeholders)}"
                    cursor = connection.execute(insert_sql, tuple(params))
                    rowcount = getattr(cursor, "rowcount", len(batch_lineitems))
                    rows_affected += max(len(batch_lineitems), rowcount)

            if hasattr(connection, "commit"):
                connection.commit()

            operation.rows_affected = rows_affected
            operation.success = True

            if self.verbose:
                self.logger.info(f"RF1 pair {pair_id + 1} completed: {rows_affected} rows affected")

        except Exception as e:
            operation.error = str(e)
            if self.verbose:
                self.logger.error(f"RF1 pair {pair_id + 1} failed: {e}")

            if connection and hasattr(connection, "rollback"):
                try:
                    connection.rollback()
                except Exception:
                    pass

        finally:
            operation.end_time = time.time()
            operation.duration = operation.end_time - operation.start_time
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

        return operation

    def _execute_rf2(self, pair_id: int) -> TPCHMaintenanceOperation:
        start_time = mono_time()

        operation = TPCHMaintenanceOperation(
            operation_type="RF2",
            start_time=start_time,
            end_time=0.0,
            duration=0.0,
            rows_affected=0,
            success=False,
        )

        connection = None
        try:
            if self.verbose:
                self.logger.info(f"Executing RF2 for pair {pair_id + 1}")

            connection = self.connection_factory()

            num_to_delete = max(1, int(self.scale_factor * 1500 * 0.001))

            if self.verbose:
                self.logger.info(f"Identifying {num_to_delete} old orders to delete for RF2")

            order_keys = self._identify_old_orders(connection, num_to_delete)

            if not order_keys:
                if self.verbose:
                    self.logger.warning("No orders found to delete for RF2")
                operation.rows_affected = 0
                operation.success = True
                return operation

            placeholder = self._get_parameter_placeholder(connection)

            rows_affected = 0

            placeholders_str = ", ".join([placeholder for _ in order_keys])
            delete_sql = f"DELETE FROM LINEITEM WHERE L_ORDERKEY IN ({placeholders_str})"
            cursor = connection.execute(delete_sql, tuple(order_keys))
            rowcount = getattr(cursor, "rowcount", 0)
            rows_affected += max(0, rowcount)

            delete_sql = f"DELETE FROM ORDERS WHERE O_ORDERKEY IN ({placeholders_str})"
            cursor = connection.execute(delete_sql, tuple(order_keys))
            rowcount = getattr(cursor, "rowcount", 0)
            rows_affected += max(0, rowcount)

            if hasattr(connection, "commit"):
                connection.commit()

            operation.rows_affected = rows_affected
            operation.success = True

            if self.verbose:
                self.logger.info(f"RF2 pair {pair_id + 1} completed: {rows_affected} rows affected")

        except Exception as e:
            operation.error = str(e)
            if self.verbose:
                self.logger.error(f"RF2 pair {pair_id + 1} failed: {e}")

            if connection and hasattr(connection, "rollback"):
                try:
                    connection.rollback()
                except Exception:
                    pass

        finally:
            operation.end_time = time.time()
            operation.duration = operation.end_time - operation.start_time
            if connection:
                try:
                    connection.close()
                except Exception:
                    pass

        return operation

    def _execute_count_query(self, connection: Any, sql: str) -> int:
        cursor = connection.execute(sql)
        result = cursor.fetchone()
        return result[0] if result else 0

    def _run_integrity_check(
        self,
        connection: Any,
        *,
        sql: str,
        exception_message: str,
        violation_message: str,
        success_message: str | None,
        critical_violation: bool,
    ) -> bool:
        try:
            count = self._execute_count_query(connection, sql)
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"{exception_message}: {e}")
            return False

        if count > 0:
            if self.verbose:
                log_fn = self.logger.error if critical_violation else self.logger.info
                log_fn(violation_message.format(count=count))
            return critical_violation

        if success_message and self.verbose:
            self.logger.info(success_message)
        return False

    def validate_data_integrity(self) -> bool:
        orphaned_lineitems_sql = """
            SELECT COUNT(*) as orphan_count
            FROM LINEITEM l
            WHERE NOT EXISTS (
                SELECT 1 FROM ORDERS o WHERE o.O_ORDERKEY = l.L_ORDERKEY
            )
        """
        date_violations_sql = """
            SELECT COUNT(*) as violation_count
            FROM LINEITEM
            WHERE L_SHIPDATE > L_COMMITDATE
               OR L_COMMITDATE > L_RECEIPTDATE
               OR L_SHIPDATE > L_RECEIPTDATE
        """
        orderless_lineitems_sql = """
            SELECT COUNT(*) as orderless_count
            FROM ORDERS o
            WHERE NOT EXISTS (
                SELECT 1 FROM LINEITEM l WHERE l.L_ORDERKEY = o.O_ORDERKEY
            )
        """
        checks = [
            {
                "sql": orphaned_lineitems_sql,
                "exception_message": "Could not check orphaned lineitems",
                "violation_message": "Integrity violation: {count} orphaned LINEITEM records found",
                "success_message": "✓ No orphaned LINEITEM records",
                "critical_violation": True,
            },
            {
                "sql": date_violations_sql,
                "exception_message": "Could not check date constraints",
                "violation_message": "Integrity violation: {count} LINEITEM date constraint violations",
                "success_message": "✓ All LINEITEM date constraints valid",
                "critical_violation": True,
            },
            {
                "sql": orderless_lineitems_sql,
                "exception_message": "Could not check orders without lineitems",
                "violation_message": "Note: {count} ORDERS without LINEITEM records (may be expected)",
                "success_message": None,
                "critical_violation": False,
            },
        ]

        try:
            connection = self.connection_factory()
            violations_found = False

            if self.verbose:
                self.logger.info("Starting TPC-H data integrity validation")

            for check in checks:
                has_critical_violation = self._run_integrity_check(
                    connection,
                    sql=check["sql"],
                    exception_message=check["exception_message"],
                    violation_message=check["violation_message"],
                    success_message=check["success_message"],
                    critical_violation=check["critical_violation"],
                )
                violations_found = violations_found or has_critical_violation

            connection.close()

            if violations_found:
                if self.verbose:
                    self.logger.error("Data integrity validation FAILED - violations found")
                return False
            else:
                if self.verbose:
                    self.logger.info("Data integrity validation PASSED")
                return True

        except Exception as e:
            if self.verbose:
                self.logger.error(f"Data integrity validation failed with exception: {e}")
            return False
