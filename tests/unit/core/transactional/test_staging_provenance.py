"""Unit tests for the shared staging provenance manifest.

TODO transactional-staging-reuse-ignores-provenance-20260805: before this
manifest existed, `is_setup()` decided readiness with a bare
`SELECT COUNT(*)` on the staging tables. A staging set left over from a
scale-0.01 run satisfied `is_setup` for a scale-1.0 run against the SAME
physical database: setup() was skipped, the benchmark executed against the
wrong data volume, and the run reported a PASS with meaningless timings --
a silent wrong-results bug, not a hygiene issue.

These tests exercise the fix directly against a real (in-memory) DuckDB
connection -- the manifest read/write path is SQL executed through
`connection.execute`, so a mock would only prove the mock's own scripted
behavior, not that the manifest round-trips through a real engine.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark
from benchbox.core.write_primitives.benchmark import WritePrimitivesBenchmark

pytestmark = [pytest.mark.unit, pytest.mark.fast, pytest.mark.duckdb, pytest.mark.database]


def _minimal_tpch_conn() -> duckdb.DuckDBPyConnection:
    """A tiny in-memory DuckDB database with orders/lineitem/customer populated.

    Deliberately minimal (a handful of rows) -- these tests exercise
    provenance bookkeeping, not TPC-H data-generation fidelity.
    """
    conn = duckdb.connect(":memory:")
    conn.execute("""
        CREATE TABLE orders (
            o_orderkey INTEGER, o_custkey INTEGER, o_orderstatus VARCHAR,
            o_totalprice DECIMAL(15,2), o_orderdate DATE, o_orderpriority VARCHAR,
            o_clerk VARCHAR, o_shippriority INTEGER, o_comment VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE lineitem (
            l_orderkey INTEGER, l_partkey INTEGER, l_suppkey INTEGER, l_linenumber INTEGER,
            l_quantity DECIMAL(15,2), l_extendedprice DECIMAL(15,2), l_discount DECIMAL(15,2),
            l_tax DECIMAL(15,2), l_returnflag VARCHAR, l_linestatus VARCHAR,
            l_shipdate DATE, l_commitdate DATE, l_receiptdate DATE,
            l_shipinstruct VARCHAR, l_shipmode VARCHAR, l_comment VARCHAR
        )
    """)
    conn.execute("""
        CREATE TABLE customer (
            c_custkey INTEGER, c_name VARCHAR, c_address VARCHAR, c_nationkey INTEGER,
            c_phone VARCHAR, c_acctbal DECIMAL(15,2), c_mktsegment VARCHAR, c_comment VARCHAR
        )
    """)
    conn.execute("""
        INSERT INTO orders VALUES
        (1, 100, 'O', 150.50, '2024-01-01', '1-URGENT', 'Clerk#001', 0, 'o1'),
        (2, 101, 'O', 250.75, '2024-01-02', '2-HIGH', 'Clerk#002', 0, 'o2'),
        (3, 102, 'O', 350.00, '2024-01-03', '3-MEDIUM', 'Clerk#003', 0, 'o3')
    """)
    conn.execute("""
        INSERT INTO lineitem VALUES
        (1, 1001, 201, 1, 10.0, 100.0, 0.05, 0.01, 'N', 'O',
         '2024-01-15', '2024-01-10', '2024-01-20', 'NONE', 'TRUCK', 'l1'),
        (2, 1002, 202, 1, 20.0, 200.0, 0.05, 0.01, 'N', 'O',
         '2024-01-16', '2024-01-11', '2024-01-21', 'NONE', 'MAIL', 'l2'),
        (3, 1003, 203, 1, 15.0, 150.0, 0.10, 0.02, 'N', 'O',
         '2024-01-17', '2024-01-12', '2024-01-22', 'NONE', 'SHIP', 'l3')
    """)
    conn.execute("""
        INSERT INTO customer VALUES
        (100, 'Customer#100', '123 Main St', 1, '555-1234', 1000.00, 'AUTOMOBILE', 'c1'),
        (101, 'Customer#101', '456 Oak Ave', 1, '555-5678', 2000.00, 'BUILDING', 'c2'),
        (102, 'Customer#102', '789 Pine Rd', 1, '555-9999', 3000.00, 'MACHINERY', 'c3')
    """)
    return conn


@pytest.fixture
def loaded_tpch_conn():
    conn = _minimal_tpch_conn()
    yield conn
    conn.close()


class TestTransactionPrimitivesStagingProvenance:
    """TransactionPrimitivesBenchmark.is_setup() via the shared manifest."""

    def test_no_manifest_is_not_setup(self, tmp_path: Path, loaded_tpch_conn):
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        assert bench.is_setup(loaded_tpch_conn) is False

    def test_matching_manifest_skips_rebuild(self, tmp_path: Path, loaded_tpch_conn):
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        bench.setup(loaded_tpch_conn, force=False)
        assert bench.is_setup(loaded_tpch_conn) is True

        # A second instance at the SAME scale/spec, reusing the same physical
        # database, must also see the manifest as current -- this is the
        # intentional-reuse path the fix must not disable.
        same_scale_bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        assert same_scale_bench.is_setup(loaded_tpch_conn) is True

    def test_scale_mismatch_forces_rebuild(self, tmp_path: Path, loaded_tpch_conn):
        """The exact bug: staging tables from a scale-0.01 run must not satisfy
        is_setup() for a scale-1.0 run against the same physical database."""
        small = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        small.setup(loaded_tpch_conn, force=False)
        assert small.is_setup(loaded_tpch_conn) is True

        large = TransactionPrimitivesBenchmark(scale_factor=1.0, output_dir=tmp_path)
        assert large.is_setup(loaded_tpch_conn) is False

    def test_legacy_populated_unmanifested_database_forces_rebuild(self, tmp_path: Path, loaded_tpch_conn):
        """A database populated by pre-manifest code (staging tables present
        and non-empty, but `benchbox_staging_manifest` never written) must be
        treated as NOT set up -- defaulting a missing manifest to "probably
        fine" would just reinstate the bug this manifest exists to close."""
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)

        loaded_tpch_conn.execute("CREATE TABLE txn_orders AS SELECT * FROM orders")
        loaded_tpch_conn.execute("CREATE TABLE txn_lineitem AS SELECT * FROM lineitem")
        loaded_tpch_conn.execute("CREATE TABLE txn_customer AS SELECT * FROM customer")

        assert bench.is_setup(loaded_tpch_conn) is False

        # And it self-heals: running setup() writes the manifest, after which
        # is_setup() reports True for this same benchmark/scale.
        bench.setup(loaded_tpch_conn, force=False)
        assert bench.is_setup(loaded_tpch_conn) is True


class TestWritePrimitivesStagingProvenance:
    """WritePrimitivesBenchmark.is_setup() via the shared manifest."""

    def test_no_manifest_is_not_setup(self, tmp_path: Path, loaded_tpch_conn):
        bench = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        assert bench.is_setup(loaded_tpch_conn) is False

    def test_matching_manifest_skips_rebuild(self, tmp_path: Path, loaded_tpch_conn):
        bench = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        bench.setup(loaded_tpch_conn, force=False)
        assert bench.is_setup(loaded_tpch_conn) is True

        same_scale_bench = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        assert same_scale_bench.is_setup(loaded_tpch_conn) is True

    def test_scale_mismatch_forces_rebuild(self, tmp_path: Path, loaded_tpch_conn):
        small = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        small.setup(loaded_tpch_conn, force=False)
        assert small.is_setup(loaded_tpch_conn) is True

        large = WritePrimitivesBenchmark(scale_factor=1.0, output_dir=tmp_path)
        assert large.is_setup(loaded_tpch_conn) is False

    def test_legacy_populated_unmanifested_database_forces_rebuild(self, tmp_path: Path, loaded_tpch_conn):
        bench = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)

        loaded_tpch_conn.execute("CREATE TABLE update_ops_orders AS SELECT * FROM orders")
        loaded_tpch_conn.execute("CREATE TABLE delete_ops_orders AS SELECT * FROM orders")
        loaded_tpch_conn.execute("CREATE TABLE delete_ops_lineitem AS SELECT * FROM lineitem")
        loaded_tpch_conn.execute("CREATE TABLE merge_ops_target AS SELECT * FROM orders")
        loaded_tpch_conn.execute("CREATE TABLE merge_ops_source AS SELECT * FROM orders")
        loaded_tpch_conn.execute("CREATE TABLE merge_ops_lineitem_target AS SELECT * FROM lineitem")
        loaded_tpch_conn.execute(
            "CREATE TABLE ddl_truncate_target AS SELECT o_orderkey, o_custkey, o_orderdate FROM orders"
        )

        assert bench.is_setup(loaded_tpch_conn) is False

        bench.setup(loaded_tpch_conn, force=False)
        assert bench.is_setup(loaded_tpch_conn) is True


class TestStagingManifestHelpers:
    """Direct coverage of the shared TransactionalBenchmarkBase manifest helpers."""

    def test_source_digest_reflects_row_counts(self, tmp_path: Path, loaded_tpch_conn):
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        digest_before = bench._staging_source_digest(loaded_tpch_conn, ["orders", "lineitem", "customer"])

        loaded_tpch_conn.execute(
            "INSERT INTO orders VALUES (4, 103, 'O', 50.0, '2024-01-04', '3-MEDIUM', 'Clerk#004', 0, 'o4')"
        )
        digest_after = bench._staging_source_digest(loaded_tpch_conn, ["orders", "lineitem", "customer"])

        assert digest_before != digest_after

    def test_manifest_missing_table_does_not_match(self, tmp_path: Path, loaded_tpch_conn):
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        assert bench._staging_manifest_matches(loaded_tpch_conn, ["orders", "lineitem", "customer"]) is False

    def test_write_then_match_round_trips(self, tmp_path: Path, loaded_tpch_conn):
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        bench._write_staging_manifest(loaded_tpch_conn, ["orders", "lineitem", "customer"])
        assert bench._staging_manifest_matches(loaded_tpch_conn, ["orders", "lineitem", "customer"]) is True

    def test_different_spec_version_does_not_match(self, tmp_path: Path, loaded_tpch_conn):
        bench = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=tmp_path)
        bench._write_staging_manifest(loaded_tpch_conn, ["orders", "lineitem", "customer"])

        bench._version = "2.0"
        assert bench._staging_manifest_matches(loaded_tpch_conn, ["orders", "lineitem", "customer"]) is False
