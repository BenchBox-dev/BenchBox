# Copyright 2026 Joe Harris / BenchBox Project
#
# Licensed under the MIT License. See LICENSE file in the project root for details.

"""Live PostgreSQL execution coverage for the SCD Type 2 write-primitives ops.

The three portable SCD2 operations (merge_scd_type2_basic / _no_change /
_new_keys_only) are expressed as standard UPDATE + INSERT and are NOT in the
PostgreSQL per-operation skip list, but until now no test, CI job, or UAT cell
executed them against a real PostgreSQL server -- they only avoided the skip
list. This module runs the full surface (population SQL, operation SQL,
validation queries, cleanup) against a live PostgreSQL instance and asserts each
op validates green and restores the seed exactly, closing audit finding C.

Setup:
    make test-docker-up-postgresql   # PostgreSQL reachable at localhost:5432

The test skips cleanly when no PostgreSQL service is reachable.

Protocol note: the SCD2 write SQL is multi-statement (UPDATE then INSERT in one
string) and the stage population is three INSERTs in one string. psycopg3 sends
these via the simple query protocol (no bound params, text format -- see
psycopg Cursor._execute_send), which is what allows multiple statements per
execute(); a bound-parameter/extended-protocol path would reject them.
"""

from __future__ import annotations

import os

import pytest

from benchbox.write_primitives import WritePrimitives

from .conftest import skip_unless_docker_service

pytestmark = [
    pytest.mark.integration,
    pytest.mark.docker_integration,
    pytest.mark.live_integration,
    pytest.mark.live_postgresql,
]

SCD2_OPS = (
    "merge_scd_type2_basic",
    "merge_scd_type2_no_change",
    "merge_scd_type2_new_keys_only",
)

# pytest.ini's default -n auto runs this module's parametrized tests across
# several pytest-xdist worker processes concurrently. A schema name shared by
# every worker means one worker's `DROP SCHEMA ... CASCADE` can race another
# worker's in-flight use of the same schema (#1154 review); suffixing with the
# worker id gives each worker its own isolated schema.
_SCHEMA_NAME = f"scd2_wp_test_{os.environ.get('PYTEST_XDIST_WORKER', 'master')}"


@pytest.fixture
def pg_scd2_env(temp_dir):
    """Seed a 50-customer PostgreSQL fixture and set up the SCD2 staging tables.

    Mirrors the DuckDB SCD2 fixture but against a live PostgreSQL connection. The
    connection is autocommit so each staging DDL/DML lands immediately, matching
    the harness's expectation of a plain execute()-and-fetch connection.
    """
    skip_unless_docker_service("localhost", 5432, platform="PostgreSQL")
    psycopg = pytest.importorskip("psycopg")

    conn = psycopg.connect(
        "host=localhost port=5432 user=benchbox password=benchbox dbname=benchbox_test",
        autocommit=True,
        connect_timeout=5,
    )
    # Isolate in a dedicated, worker-scoped schema so the generic table names
    # (customer, orders, lineitem, scd2_ops_*) cannot collide with any other
    # test sharing the benchbox_test database, and so concurrent xdist
    # workers each get their own schema instead of racing DROP/CREATE against
    # a name every worker shares (#1154 review).
    conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA_NAME} CASCADE")
    conn.execute(f"CREATE SCHEMA {_SCHEMA_NAME}")
    conn.execute(f"SET search_path TO {_SCHEMA_NAME}")
    conn.execute(
        "CREATE TABLE orders (o_orderkey INTEGER PRIMARY KEY, o_custkey INTEGER, "
        "o_orderstatus CHAR(1), o_totalprice DECIMAL(15,2), o_orderdate DATE, "
        "o_orderpriority CHAR(15), o_clerk CHAR(15), o_shippriority INTEGER, o_comment VARCHAR(79))"
    )
    conn.execute(
        "CREATE TABLE lineitem (l_orderkey INTEGER, l_partkey INTEGER, l_suppkey INTEGER, "
        "l_linenumber INTEGER, l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), "
        "l_discount DECIMAL(15,2), l_tax DECIMAL(15,2), l_returnflag CHAR(1), l_linestatus CHAR(1), "
        "l_shipdate DATE, l_commitdate DATE, l_receiptdate DATE, l_shipinstruct CHAR(25), "
        "l_shipmode CHAR(10), l_comment VARCHAR(44))"
    )
    conn.execute(
        "CREATE TABLE customer (c_custkey INTEGER PRIMARY KEY, c_name VARCHAR(25), "
        "c_address VARCHAR(40), c_nationkey INTEGER, c_phone VARCHAR(15), c_acctbal DECIMAL(15,2), "
        "c_mktsegment VARCHAR(10), c_comment VARCHAR(117))"
    )
    conn.execute("INSERT INTO orders VALUES (1, 1, 'O', 10.0, DATE '2024-01-01', '1-URGENT', 'C#1', 0, 'o')")
    conn.execute(
        "INSERT INTO lineitem VALUES (1, 1, 1, 1, 1.0, 1.0, 0.0, 0.0, 'N', 'O', "
        "DATE '2024-01-02', DATE '2024-01-01', DATE '2024-01-03', 'NONE', 'TRUCK', 'c')"
    )
    # 50 customers so the change batch ranges (1-20 changed, 21-40 unchanged,
    # offset-by-max new) all populate. generate_series is the PostgreSQL analogue
    # of DuckDB's range().
    conn.execute(
        "INSERT INTO customer "
        "SELECT i, 'Customer#' || CAST(i AS VARCHAR), 'Addr ' || CAST(i AS VARCHAR), "
        "(i % 25), '555-' || CAST(i AS VARCHAR), (i * 10.0), "
        "CASE WHEN i % 2 = 0 THEN 'BUILDING' ELSE 'AUTOMOBILE' END, "
        "'comment ' || CAST(i AS VARCHAR) "
        "FROM generate_series(1, 50) AS t(i)"
    )

    write_bench = WritePrimitives(scale_factor=0.01, output_dir=temp_dir, quiet=True)
    # WritePrimitives.setup() (the public wrapper) doesn't accept a dialect
    # kwarg and always forwards the implementation's "standard" default, which
    # clobbers any dialect pre-set directly on _impl -- call the
    # implementation itself so the postgres BYTEA sketch-column mapping is
    # actually applied (#1154 review).
    write_bench._impl.setup(conn, force=True, dialect="postgres")
    yield write_bench, conn
    conn.execute(f"DROP SCHEMA IF EXISTS {_SCHEMA_NAME} CASCADE")
    conn.close()


def _current_state(conn):
    return conn.execute(
        "SELECT COUNT(*), "
        "SUM(CASE WHEN is_current THEN 1 ELSE 0 END), "
        "SUM(CASE WHEN NOT is_current THEN 1 ELSE 0 END) "
        "FROM scd2_ops_dim_customer"
    ).fetchone()


class TestWritePrimitivesSCD2PostgreSQL:
    """End-to-end SCD Type 2 ops against a live PostgreSQL server."""

    def test_setup_seeds_dimension_and_stage(self, pg_scd2_env):
        _, conn = pg_scd2_env
        total, current, closed = _current_state(conn)
        assert (total, current, closed) == (50, 50, 0)
        stage = dict(
            conn.execute("SELECT change_type, COUNT(*) FROM scd2_ops_stage_customer GROUP BY change_type").fetchall()
        )
        assert stage == {"changed": 20, "unchanged": 20, "new": 20}
        # The || / CAST(... AS VARCHAR) fingerprint agrees between dim and the
        # unchanged stage rows on PostgreSQL (setup portability).
        agree = conn.execute(
            "SELECT COUNT(*) FROM scd2_ops_stage_customer s "
            "JOIN scd2_ops_dim_customer d USING (c_custkey) "
            "WHERE s.change_type = 'unchanged' AND s.row_hash = d.row_hash"
        ).fetchone()[0]
        assert agree == 20

    @pytest.mark.parametrize("op_id", SCD2_OPS)
    def test_scd2_op_not_skipped_on_postgres(self, pg_scd2_env, op_id):
        """The three SCD2 ops are runnable (not skipped) on PostgreSQL."""
        write_bench, conn = pg_scd2_env
        op = write_bench.get_operation(op_id)
        effective_sql, skip_reason = write_bench._impl._get_effective_write_sql(
            op, platform_key="postgres", connection=conn
        )
        assert skip_reason is None
        assert effective_sql is not None

    @pytest.mark.parametrize("op_id", SCD2_OPS)
    def test_scd2_op_executes_validates_and_restores_seed(self, pg_scd2_env, op_id):
        """Each op runs green and its cleanup restores the pristine seed."""
        write_bench, conn = pg_scd2_env
        before = _current_state(conn)
        result = write_bench.execute_operation(op_id, conn, platform_key="postgres")
        assert result.success is True, result.error
        assert result.validation_passed is True, result.error
        assert result.cleanup_success is True
        # cleanup restores the seed, so each op is independently repeatable.
        assert _current_state(conn) == before == (50, 50, 0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
