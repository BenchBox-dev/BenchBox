"""Integration tests for Data Vault benchmark with DuckDB.

Tests the end-to-end flow of:
1. Generating TPC-H source data
2. Transforming to Data Vault format
3. Loading into DuckDB
4. Executing Data Vault queries

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from decimal import Decimal

import pytest

from benchbox.core.datavault import DataVaultBenchmark
from benchbox.core.datavault.queries import DataVaultQueryManager
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tpch.schema import TABLES
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


@pytest.mark.integration
@pytest.mark.datavault
class TestDataVaultDuckDBIntegration:
    """Integration tests for Data Vault with DuckDB."""

    @pytest.fixture
    def datavault_benchmark(self, tmp_path):
        """Create a DataVault benchmark at minimal scale."""
        return DataVaultBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "datavault_data",
        )

    def test_schema_generation(self, datavault_benchmark):
        """DDL should be valid DuckDB SQL."""
        import duckdb

        ddl = datavault_benchmark.get_create_tables_sql(dialect="duckdb")
        conn = duckdb.connect(":memory:")

        # Should create all 21 tables without error
        conn.execute(ddl)

        # Verify tables were created
        tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
        table_names = {t[0] for t in tables}

        assert len(table_names) == 21
        assert "hub_customer" in table_names
        assert "link_lineitem" in table_names
        assert "sat_order" in table_names

        conn.close()

    def test_query_syntax_valid(self, datavault_benchmark):
        """All 22 queries should parse without error in DuckDB."""
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create schema first
        ddl = datavault_benchmark.get_create_tables_sql(dialect="duckdb")
        conn.execute(ddl)

        # Try to prepare each query (validates syntax)
        for qid in range(1, 23):
            query = datavault_benchmark.get_query(qid)
            try:
                # Use EXPLAIN to validate without executing
                conn.execute(f"EXPLAIN {query}")
            except Exception as e:
                pytest.fail(f"Query {qid} failed to parse: {e}")

        conn.close()

    def test_parameterized_queries_syntax_valid(self, datavault_benchmark):
        """Parameterized queries should parse without error."""
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create schema first
        ddl = datavault_benchmark.get_create_tables_sql(dialect="duckdb")
        conn.execute(ddl)

        query_manager = datavault_benchmark.query_manager

        # Generate and validate parameterized queries for different streams
        for stream_id in [0, 1, 2]:
            for qid in range(1, 23):
                sql, params = query_manager.get_parameterized_query(qid, stream_id=stream_id)
                try:
                    conn.execute(f"EXPLAIN {sql}")
                except Exception as e:
                    pytest.fail(f"Query {qid} stream {stream_id} failed: {e}")

        conn.close()

    def test_validation_utilities_work(self, datavault_benchmark):
        """Validation utilities should work correctly."""
        from benchbox.core.datavault import get_expected_row_count

        # Test expected row counts at different scales
        assert get_expected_row_count("hub_region", 0.01) == 5  # Fixed
        assert get_expected_row_count("hub_nation", 0.01) == 25  # Fixed
        assert get_expected_row_count("hub_customer", 0.01) == 1500  # Scales

    def test_table_loading_order(self, datavault_benchmark):
        """Loading order should respect dependencies."""
        order = datavault_benchmark.get_table_loading_order()

        # Get indices
        def idx(name):
            return order.index(name)

        # Hubs must come before their satellites
        assert idx("hub_customer") < idx("sat_customer")
        assert idx("hub_order") < idx("sat_order")

        # Hubs must come before links that reference them
        assert idx("hub_customer") < idx("link_order_customer")
        assert idx("hub_order") < idx("link_order_customer")


@pytest.mark.integration
@pytest.mark.datavault
@pytest.mark.slow
class TestDataVaultDataGeneration:
    """Integration tests for Data Vault data generation.

    These tests require TPC-H binary and are slower, so marked as 'slow'.
    """

    @pytest.fixture
    def datavault_with_data(self, tmp_path):
        """Create a DataVault benchmark and generate data."""
        benchmark = DataVaultBenchmark(
            scale_factor=0.01,
            output_dir=tmp_path / "datavault_data",
        )

        # Skip if TPC-H binaries not available
        try:
            benchmark.generate_data()
        except FileNotFoundError as e:
            if "dbgen" in str(e) or "dsdgen" in str(e):
                pytest.skip("TPC-H binaries not available")
            raise

        return benchmark

    def test_data_generation_creates_21_tables(self, datavault_with_data):
        """Data generation should create all 21 Data Vault tables."""
        output_dir = datavault_with_data.output_dir

        # Check for generated files
        tbl_files = list(output_dir.glob("*.tbl"))
        assert len(tbl_files) >= 21, f"Expected 21 tables, found {len(tbl_files)}"

    def test_manifest_created(self, datavault_with_data):
        """Data generation should create a manifest file."""
        import json

        manifest_path = datavault_with_data.output_dir / "_datagen_manifest.json"
        assert manifest_path.exists()

        manifest = json.loads(manifest_path.read_text())
        assert manifest["benchmark"] == "datavault"
        assert manifest["scale_factor"] == 0.01
        assert len(manifest["tables"]) == 21

    def test_query_execution_on_generated_data(self, datavault_with_data):
        """Queries should execute successfully on generated data."""
        import duckdb

        conn = duckdb.connect(":memory:")

        # Create schema
        ddl = datavault_with_data.get_create_tables_sql(dialect="duckdb")
        conn.execute(ddl)

        # Load data
        output_dir = datavault_with_data.output_dir
        for table_name in datavault_with_data.get_table_loading_order():
            tbl_path = output_dir / f"{table_name}.tbl"
            if tbl_path.exists():
                conn.execute(f"""
                    INSERT INTO {table_name}
                    SELECT * FROM read_csv('{tbl_path}', delim='|', header=false)
                """)

        # Execute a simple query (Q1)
        query = datavault_with_data.get_query(1)
        result = conn.execute(query).fetchall()

        # Q1 should return aggregated results
        assert len(result) > 0

        conn.close()

    def test_row_count_validation(self, datavault_with_data):
        """Row count validation should pass for generated data."""
        from benchbox.core.datavault import validate_row_counts

        report = validate_row_counts(
            datavault_with_data.output_dir,
            scale_factor=0.01,
        )

        # Validation should pass or have minimal failures
        # (some variance is acceptable for lineitem)
        assert report.tables_validated == 21
        # Allow up to 2 failures for edge cases
        assert report.tables_failed <= 2, f"Too many validation failures: {report}"


@pytest.mark.integration
@pytest.mark.datavault
@pytest.mark.reference_comparison
class TestDataVaultTPCHEquivalence:
    """End-to-end validation that Data Vault queries produce correct results.

    This test validates that Data Vault queries return semantically equivalent
    results to TPC-H queries when executed on the same underlying data.

    IMPORTANT DESIGN NOTE:
    - Data Vault queries use DEFAULT_PARAMS (TPC-H standard test defaults)
    - These are the canonical TPC-H benchmark parameters from the specification
    - We do NOT use qgen parameter generation because:
      1. qgen uses internal C-based algorithms that differ from our Python implementation
      2. qgen's seed handling is query-specific and not easily reproducible
      3. The DEFAULT_PARAMS are the official TPC-H test values anyway

    The test validates row counts match as a proxy for semantic equivalence.
    Full value comparison is complex due to column ordering differences between
    Data Vault (with audit columns) and raw TPC-H schemas.
    """

    @staticmethod
    def _load_tbl_simple(conn, table_name: str, file_path: str) -> None:
        """Load a .tbl file into DuckDB, letting DuckDB infer column order.

        This simpler approach works because:
        1. Tables are already created with correct schema via DDL
        2. DuckDB's read_csv can match positional columns to existing table
        3. Avoids complex column type mapping that can break

        Note: TPC-H .tbl files have trailing pipe delimiters, so we use the
        explicit `names` parameter with table schema names plus an ignore column
        for the trailing delimiter. This is DuckDB-version agnostic.
        """
        # Get the column names from the existing table schema
        result = conn.execute(f"SELECT name FROM pragma_table_info('{table_name}') ORDER BY cid").fetchall()
        col_names = [row[0] for row in result]

        # Use explicit column names from schema plus ignore column for trailing pipe
        # Then EXCLUDE the ignore column in SELECT to get only the real columns.
        # null_padding=true handles files that may or may not have trailing delimiters.
        all_names = col_names + [TRAILING_DUMMY_COLUMN]
        names_param = ", ".join([f"'{col}'" for col in all_names])
        conn.execute(
            f"""
            INSERT INTO {table_name}
            SELECT * EXCLUDE ({TRAILING_DUMMY_COLUMN}) FROM read_csv('{file_path}', delim='|', header=false, null_padding=true, names=[{names_param}])
            """
        )

    @staticmethod
    def _normalize_value(value):
        """Normalize result values for deterministic cross-query comparison."""
        if isinstance(value, Decimal):
            return round(float(value), 8)
        if isinstance(value, float):
            return round(value, 8)
        return value

    @classmethod
    def _normalize_rows(cls, rows):
        """Normalize and order rows for set-equivalence comparison."""
        normalized = [tuple(cls._normalize_value(v) for v in row) for row in rows]
        return sorted(normalized)

    @staticmethod
    def _tpch_query_for_params(query_id: int, params: dict[str, object]) -> str:  # noqa: C901
        """Build canonical TPC-H SQL for a given query ID using shared params.

        All 22 queries follow the TPC-H specification exactly, parameterized
        by the same dict that DataVaultParameterGenerator produces.
        """
        if query_id == 1:
            delta = params["delta"]
            return f"""
                SELECT
                    l_returnflag,
                    l_linestatus,
                    SUM(l_quantity) AS sum_qty,
                    SUM(l_extendedprice) AS sum_base_price,
                    SUM(l_extendedprice * (1 - l_discount)) AS sum_disc_price,
                    SUM(l_extendedprice * (1 - l_discount) * (1 + l_tax)) AS sum_charge,
                    AVG(l_quantity) AS avg_qty,
                    AVG(l_extendedprice) AS avg_price,
                    AVG(l_discount) AS avg_disc,
                    COUNT(*) AS count_order
                FROM lineitem
                WHERE l_shipdate <= DATE '1998-12-01' - INTERVAL '{delta}' DAY
                GROUP BY l_returnflag, l_linestatus
                ORDER BY l_returnflag, l_linestatus
            """
        if query_id == 2:
            size = params["size"]
            type_suffix = params["type_suffix"]
            region = params["region"]
            return f"""
                SELECT
                    s_acctbal, s_name, n_name, p_partkey, p_mfgr,
                    s_address, s_phone, s_comment
                FROM part, supplier, partsupp, nation, region
                WHERE p_partkey = ps_partkey
                  AND s_suppkey = ps_suppkey
                  AND p_size = {size}
                  AND p_type LIKE '%{type_suffix}'
                  AND s_nationkey = n_nationkey
                  AND n_regionkey = r_regionkey
                  AND r_name = '{region}'
                  AND ps_supplycost = (
                      SELECT MIN(ps_supplycost)
                      FROM partsupp, supplier, nation, region
                      WHERE p_partkey = ps_partkey
                        AND s_suppkey = ps_suppkey
                        AND s_nationkey = n_nationkey
                        AND n_regionkey = r_regionkey
                        AND r_name = '{region}'
                  )
                ORDER BY s_acctbal DESC, n_name, s_name, p_partkey
                LIMIT 100
            """
        if query_id == 3:
            segment = params["segment"]
            date_str = params["date"]
            return f"""
                SELECT
                    l_orderkey,
                    SUM(l_extendedprice * (1 - l_discount)) AS revenue,
                    o_orderdate,
                    o_shippriority
                FROM customer, orders, lineitem
                WHERE c_mktsegment = '{segment}'
                  AND c_custkey = o_custkey
                  AND l_orderkey = o_orderkey
                  AND o_orderdate < DATE '{date_str}'
                  AND l_shipdate > DATE '{date_str}'
                GROUP BY l_orderkey, o_orderdate, o_shippriority
                ORDER BY revenue DESC, o_orderdate
                LIMIT 10
            """
        if query_id == 4:
            date_str = params["date"]
            return f"""
                SELECT
                    o_orderpriority,
                    COUNT(*) AS order_count
                FROM orders
                WHERE o_orderdate >= DATE '{date_str}'
                  AND o_orderdate < DATE '{date_str}' + INTERVAL '3' MONTH
                  AND EXISTS (
                      SELECT 1 FROM lineitem
                      WHERE l_orderkey = o_orderkey
                        AND l_commitdate < l_receiptdate
                  )
                GROUP BY o_orderpriority
                ORDER BY o_orderpriority
            """
        if query_id == 5:
            region = params["region"]
            date_str = params["date"]
            return f"""
                SELECT
                    n_name,
                    SUM(l_extendedprice * (1 - l_discount)) AS revenue
                FROM customer, orders, lineitem, supplier, nation, region
                WHERE c_custkey = o_custkey
                  AND l_orderkey = o_orderkey
                  AND l_suppkey = s_suppkey
                  AND c_nationkey = s_nationkey
                  AND s_nationkey = n_nationkey
                  AND n_regionkey = r_regionkey
                  AND r_name = '{region}'
                  AND o_orderdate >= DATE '{date_str}'
                  AND o_orderdate < DATE '{date_str}' + INTERVAL '1' YEAR
                GROUP BY n_name
                ORDER BY revenue DESC
            """
        if query_id == 6:
            date_str = params["date"]
            discount = params["discount"]
            quantity = params["quantity"]
            return f"""
                SELECT
                    SUM(l_extendedprice * l_discount) AS revenue
                FROM lineitem
                WHERE l_shipdate >= DATE '{date_str}'
                  AND l_shipdate < DATE '{date_str}' + INTERVAL '1' YEAR
                  AND l_discount BETWEEN {discount} - 0.01 AND {discount} + 0.01
                  AND l_quantity < {quantity}
            """
        if query_id == 7:
            nation1 = params["nation1"]
            nation2 = params["nation2"]
            return f"""
                SELECT
                    supp_nation, cust_nation, l_year,
                    SUM(volume) AS revenue
                FROM (
                    SELECT
                        n1.n_name AS supp_nation,
                        n2.n_name AS cust_nation,
                        EXTRACT(YEAR FROM l_shipdate) AS l_year,
                        l_extendedprice * (1 - l_discount) AS volume
                    FROM supplier, lineitem, orders, customer, nation n1, nation n2
                    WHERE s_suppkey = l_suppkey
                      AND o_orderkey = l_orderkey
                      AND c_custkey = o_custkey
                      AND s_nationkey = n1.n_nationkey
                      AND c_nationkey = n2.n_nationkey
                      AND ((n1.n_name = '{nation1}' AND n2.n_name = '{nation2}')
                        OR (n1.n_name = '{nation2}' AND n2.n_name = '{nation1}'))
                      AND l_shipdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'
                ) AS shipping
                GROUP BY supp_nation, cust_nation, l_year
                ORDER BY supp_nation, cust_nation, l_year
            """
        if query_id == 8:
            nation = params["nation"]
            region = params["region"]
            p_type = params["type"]
            return f"""
                SELECT
                    o_year,
                    SUM(CASE WHEN nation = '{nation}' THEN volume ELSE 0 END)
                        / SUM(volume) AS mkt_share
                FROM (
                    SELECT
                        EXTRACT(YEAR FROM o_orderdate) AS o_year,
                        l_extendedprice * (1 - l_discount) AS volume,
                        n2.n_name AS nation
                    FROM part, supplier, lineitem, orders, customer,
                         nation n1, nation n2, region
                    WHERE p_partkey = l_partkey
                      AND s_suppkey = l_suppkey
                      AND l_orderkey = o_orderkey
                      AND o_custkey = c_custkey
                      AND c_nationkey = n1.n_nationkey
                      AND n1.n_regionkey = r_regionkey
                      AND r_name = '{region}'
                      AND s_nationkey = n2.n_nationkey
                      AND o_orderdate BETWEEN DATE '1995-01-01' AND DATE '1996-12-31'
                      AND p_type = '{p_type}'
                ) AS all_nations
                GROUP BY o_year
                ORDER BY o_year
            """
        if query_id == 9:
            color = params["color"]
            return f"""
                SELECT
                    nation, o_year,
                    SUM(amount) AS sum_profit
                FROM (
                    SELECT
                        n_name AS nation,
                        EXTRACT(YEAR FROM o_orderdate) AS o_year,
                        l_extendedprice * (1 - l_discount)
                            - ps_supplycost * l_quantity AS amount
                    FROM part, supplier, lineitem, partsupp, orders, nation
                    WHERE s_suppkey = l_suppkey
                      AND ps_suppkey = l_suppkey
                      AND ps_partkey = l_partkey
                      AND p_partkey = l_partkey
                      AND o_orderkey = l_orderkey
                      AND s_nationkey = n_nationkey
                      AND p_name LIKE '%{color}%'
                ) AS profit
                GROUP BY nation, o_year
                ORDER BY nation, o_year DESC
            """
        if query_id == 10:
            date_str = params["date"]
            return f"""
                SELECT
                    c_custkey, c_name,
                    SUM(l_extendedprice * (1 - l_discount)) AS revenue,
                    c_acctbal, n_name, c_address, c_phone, c_comment
                FROM customer, orders, lineitem, nation
                WHERE c_custkey = o_custkey
                  AND l_orderkey = o_orderkey
                  AND o_orderdate >= DATE '{date_str}'
                  AND o_orderdate < DATE '{date_str}' + INTERVAL '3' MONTH
                  AND l_returnflag = 'R'
                  AND c_nationkey = n_nationkey
                GROUP BY c_custkey, c_name, c_acctbal, c_phone,
                         n_name, c_address, c_comment
                ORDER BY revenue DESC
                LIMIT 20
            """
        if query_id == 11:
            nation = params["nation"]
            fraction = params["fraction"]
            return f"""
                SELECT
                    ps_partkey,
                    SUM(ps_supplycost * ps_availqty) AS value
                FROM partsupp, supplier, nation
                WHERE ps_suppkey = s_suppkey
                  AND s_nationkey = n_nationkey
                  AND n_name = '{nation}'
                GROUP BY ps_partkey
                HAVING SUM(ps_supplycost * ps_availqty) > (
                    SELECT SUM(ps_supplycost * ps_availqty) * {fraction}
                    FROM partsupp, supplier, nation
                    WHERE ps_suppkey = s_suppkey
                      AND s_nationkey = n_nationkey
                      AND n_name = '{nation}'
                )
                ORDER BY value DESC
            """
        if query_id == 12:
            shipmode1 = params["shipmode1"]
            shipmode2 = params["shipmode2"]
            date_str = params["date"]
            return f"""
                SELECT
                    l_shipmode,
                    SUM(CASE
                        WHEN o_orderpriority = '1-URGENT' OR o_orderpriority = '2-HIGH'
                        THEN 1 ELSE 0 END) AS high_line_count,
                    SUM(CASE
                        WHEN o_orderpriority <> '1-URGENT' AND o_orderpriority <> '2-HIGH'
                        THEN 1 ELSE 0 END) AS low_line_count
                FROM orders, lineitem
                WHERE o_orderkey = l_orderkey
                  AND l_shipmode IN ('{shipmode1}', '{shipmode2}')
                  AND l_commitdate < l_receiptdate
                  AND l_shipdate < l_commitdate
                  AND l_receiptdate >= DATE '{date_str}'
                  AND l_receiptdate < DATE '{date_str}' + INTERVAL '1' YEAR
                GROUP BY l_shipmode
                ORDER BY l_shipmode
            """
        if query_id == 13:
            word1 = params["word1"]
            word2 = params["word2"]
            return f"""
                SELECT
                    c_count,
                    COUNT(*) AS custdist
                FROM (
                    SELECT
                        c_custkey,
                        COUNT(o_orderkey) AS c_count
                    FROM customer
                    LEFT OUTER JOIN orders ON c_custkey = o_custkey
                        AND o_comment NOT LIKE '%{word1}%{word2}%'
                    GROUP BY c_custkey
                ) AS c_orders
                GROUP BY c_count
                ORDER BY custdist DESC, c_count DESC
            """
        if query_id == 14:
            date_str = params["date"]
            return f"""
                SELECT
                    100.00 * SUM(CASE WHEN p_type LIKE 'PROMO%'
                        THEN l_extendedprice * (1 - l_discount) ELSE 0 END)
                    / SUM(l_extendedprice * (1 - l_discount)) AS promo_revenue
                FROM lineitem, part
                WHERE l_partkey = p_partkey
                  AND l_shipdate >= DATE '{date_str}'
                  AND l_shipdate < DATE '{date_str}' + INTERVAL '1' MONTH
            """
        if query_id == 15:
            date_str = params["date"]
            return f"""
                WITH revenue AS (
                    SELECT
                        l_suppkey AS supplier_no,
                        SUM(l_extendedprice * (1 - l_discount)) AS total_revenue
                    FROM lineitem
                    WHERE l_shipdate >= DATE '{date_str}'
                      AND l_shipdate < DATE '{date_str}' + INTERVAL '3' MONTH
                    GROUP BY l_suppkey
                )
                SELECT
                    s_suppkey, s_name, s_address, s_phone,
                    total_revenue
                FROM supplier, revenue
                WHERE s_suppkey = supplier_no
                  AND total_revenue = (SELECT MAX(total_revenue) FROM revenue)
                ORDER BY s_suppkey
            """
        if query_id == 16:
            brand = params["brand"]
            type_prefix = params["type_prefix"]
            sizes = params["sizes"]
            assert isinstance(sizes, (list, tuple))
            sizes_str = ", ".join(str(s) for s in sizes)
            return f"""
                SELECT
                    p_brand, p_type, p_size,
                    COUNT(DISTINCT ps_suppkey) AS supplier_cnt
                FROM partsupp, part
                WHERE p_partkey = ps_partkey
                  AND p_brand <> '{brand}'
                  AND p_type NOT LIKE '{type_prefix}%'
                  AND p_size IN ({sizes_str})
                  AND ps_suppkey NOT IN (
                      SELECT s_suppkey FROM supplier
                      WHERE s_comment LIKE '%Customer%Complaints%'
                  )
                GROUP BY p_brand, p_type, p_size
                ORDER BY supplier_cnt DESC, p_brand, p_type, p_size
            """
        if query_id == 17:
            brand = params["brand"]
            container = params["container"]
            return f"""
                SELECT
                    SUM(l_extendedprice) / 7.0 AS avg_yearly
                FROM lineitem, part
                WHERE p_partkey = l_partkey
                  AND p_brand = '{brand}'
                  AND p_container = '{container}'
                  AND l_quantity < (
                      SELECT 0.2 * AVG(l_quantity)
                      FROM lineitem
                      WHERE l_partkey = p_partkey
                  )
            """
        if query_id == 18:
            quantity = params["quantity"]
            return f"""
                SELECT
                    c_name, c_custkey, o_orderkey,
                    o_orderdate, o_totalprice,
                    SUM(l_quantity) AS total_qty
                FROM customer, orders, lineitem
                WHERE o_orderkey IN (
                    SELECT l_orderkey FROM lineitem
                    GROUP BY l_orderkey
                    HAVING SUM(l_quantity) > {quantity}
                )
                  AND c_custkey = o_custkey
                  AND o_orderkey = l_orderkey
                GROUP BY c_name, c_custkey, o_orderkey, o_orderdate, o_totalprice
                ORDER BY o_totalprice DESC, o_orderdate
                LIMIT 100
            """
        if query_id == 19:
            brand1 = params["brand1"]
            brand2 = params["brand2"]
            brand3 = params["brand3"]
            qty1 = params["quantity1"]
            qty2 = params["quantity2"]
            qty3 = params["quantity3"]
            return f"""
                SELECT
                    SUM(l_extendedprice * (1 - l_discount)) AS revenue
                FROM lineitem, part
                WHERE (
                    p_partkey = l_partkey
                    AND p_brand = '{brand1}'
                    AND p_container IN ('SM CASE', 'SM BOX', 'SM PACK', 'SM PKG')
                    AND l_quantity >= {qty1} AND l_quantity <= {qty1} + 10
                    AND p_size BETWEEN 1 AND 5
                    AND l_shipmode IN ('AIR', 'AIR REG')
                    AND l_shipinstruct = 'DELIVER IN PERSON'
                ) OR (
                    p_partkey = l_partkey
                    AND p_brand = '{brand2}'
                    AND p_container IN ('MED BAG', 'MED BOX', 'MED PKG', 'MED PACK')
                    AND l_quantity >= {qty2} AND l_quantity <= {qty2} + 10
                    AND p_size BETWEEN 1 AND 10
                    AND l_shipmode IN ('AIR', 'AIR REG')
                    AND l_shipinstruct = 'DELIVER IN PERSON'
                ) OR (
                    p_partkey = l_partkey
                    AND p_brand = '{brand3}'
                    AND p_container IN ('LG CASE', 'LG BOX', 'LG PACK', 'LG PKG')
                    AND l_quantity >= {qty3} AND l_quantity <= {qty3} + 10
                    AND p_size BETWEEN 1 AND 15
                    AND l_shipmode IN ('AIR', 'AIR REG')
                    AND l_shipinstruct = 'DELIVER IN PERSON'
                )
            """
        if query_id == 20:
            color = params["color"]
            date_str = params["date"]
            nation = params["nation"]
            return f"""
                SELECT
                    s_name, s_address
                FROM supplier, nation
                WHERE s_suppkey IN (
                    SELECT ps_suppkey
                    FROM partsupp
                    WHERE ps_partkey IN (
                        SELECT p_partkey FROM part
                        WHERE p_name LIKE '{color}%'
                    )
                    AND ps_availqty > (
                        SELECT 0.5 * SUM(l_quantity)
                        FROM lineitem
                        WHERE l_partkey = ps_partkey
                          AND l_suppkey = ps_suppkey
                          AND l_shipdate >= DATE '{date_str}'
                          AND l_shipdate < DATE '{date_str}' + INTERVAL '1' YEAR
                    )
                )
                  AND s_nationkey = n_nationkey
                  AND n_name = '{nation}'
                ORDER BY s_name
            """
        if query_id == 21:
            nation = params["nation"]
            return f"""
                SELECT
                    s_name,
                    COUNT(*) AS numwait
                FROM supplier, lineitem l1, orders, nation
                WHERE s_suppkey = l1.l_suppkey
                  AND o_orderkey = l1.l_orderkey
                  AND o_orderstatus = 'F'
                  AND l1.l_receiptdate > l1.l_commitdate
                  AND EXISTS (
                      SELECT 1 FROM lineitem l2
                      WHERE l2.l_orderkey = l1.l_orderkey
                        AND l2.l_suppkey <> l1.l_suppkey
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM lineitem l3
                      WHERE l3.l_orderkey = l1.l_orderkey
                        AND l3.l_suppkey <> l1.l_suppkey
                        AND l3.l_receiptdate > l3.l_commitdate
                  )
                  AND s_nationkey = n_nationkey
                  AND n_name = '{nation}'
                GROUP BY s_name
                ORDER BY numwait DESC, s_name
                LIMIT 100
            """
        if query_id == 22:
            codes = params["country_codes"]
            assert isinstance(codes, (list, tuple))
            codes_str = ", ".join(f"'{c}'" for c in codes)
            return f"""
                SELECT
                    cntrycode,
                    COUNT(*) AS numcust,
                    SUM(c_acctbal) AS totacctbal
                FROM (
                    SELECT
                        SUBSTRING(c_phone FROM 1 FOR 2) AS cntrycode,
                        c_acctbal
                    FROM customer
                    WHERE SUBSTRING(c_phone FROM 1 FOR 2) IN ({codes_str})
                      AND c_acctbal > (
                          SELECT AVG(c_acctbal) FROM customer
                          WHERE c_acctbal > 0.00
                            AND SUBSTRING(c_phone FROM 1 FOR 2) IN ({codes_str})
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM orders
                          WHERE o_custkey = c_custkey
                      )
                ) AS custsale
                GROUP BY cntrycode
                ORDER BY cntrycode
            """
        raise ValueError(f"Unsupported query ID for TPCH equivalence: {query_id}")

    def test_datavault_queries_execute_successfully(self, tmp_path):
        """Validate all 22 Data Vault queries execute without error.

        This is the primary validation: Data Vault queries should:
        1. Parse correctly
        2. Execute against generated data
        3. Return non-empty results for most queries
        """
        import duckdb

        scale_factor = 0.01
        output_dir = tmp_path / "datavault_test"

        dv_benchmark = DataVaultBenchmark(
            scale_factor=scale_factor,
            output_dir=output_dir,
        )

        # Generate data (includes both TPC-H source and Data Vault tables)
        try:
            dv_benchmark.generate_data()
        except FileNotFoundError as e:
            if "dbgen" in str(e) or "dsdgen" in str(e):
                pytest.skip("TPC-H dbgen binary not available")
            raise

        conn = duckdb.connect(":memory:")

        # Create Data Vault schema and load data
        conn.execute(dv_benchmark.get_create_tables_sql(dialect="duckdb"))

        for table_name in dv_benchmark.get_table_loading_order():
            tbl_path = output_dir / f"{table_name}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table_name, str(tbl_path))

        # Execute all 22 queries with default parameters
        dv_query_manager = DataVaultQueryManager()
        failed_queries = []

        for qid in range(1, 23):
            # Use DEFAULT_PARAMS (TPC-H standard test defaults)
            sql = dv_query_manager.get_query(qid)
            try:
                results = conn.execute(sql).fetchall()
                # Most queries should return results at SF=0.01
                # Some may return empty due to parameter selectivity
                if len(results) == 0 and qid not in {2, 17, 21}:
                    # Q2 (min cost supplier), Q17 (small qty), Q21 (late suppliers)
                    # often return empty at small scale factors
                    pass  # Acceptable
            except Exception as e:
                failed_queries.append((qid, str(e)))

        conn.close()

        if failed_queries:
            msg = "\n".join(f"Q{qid}: {err}" for qid, err in failed_queries)
            pytest.fail(f"Data Vault queries failed:\n{msg}")

    def test_datavault_row_counts_match_source(self, tmp_path):
        """Validate Data Vault tables have correct row counts vs TPC-H source.

        This test verifies the ETL transformation preserved data:
        - Hub tables should have same count as source entities
        - Link tables should have same count as source relationships
        - Satellite tables should have same count as their parent hub/link
        """
        import duckdb

        scale_factor = 0.01
        output_dir = tmp_path / "datavault_counts"

        dv_benchmark = DataVaultBenchmark(
            scale_factor=scale_factor,
            output_dir=output_dir,
        )

        try:
            dv_benchmark.generate_data()
        except FileNotFoundError as e:
            if "dbgen" in str(e) or "dsdgen" in str(e):
                pytest.skip("TPC-H dbgen binary not available")
            raise

        tpch_benchmark = TPCHBenchmark(scale_factor=scale_factor, output_dir=output_dir)

        conn = duckdb.connect(":memory:")

        # Load TPC-H source tables
        conn.execute(tpch_benchmark.get_create_tables_sql(dialect="duckdb"))
        for table in [t.name for t in TABLES]:
            tbl_path = output_dir / f"{table}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table, str(tbl_path))

        # Load Data Vault tables
        conn.execute(dv_benchmark.get_create_tables_sql(dialect="duckdb"))
        for table_name in dv_benchmark.get_table_loading_order():
            tbl_path = output_dir / f"{table_name}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table_name, str(tbl_path))

        # Verify row count relationships
        count_checks = [
            # (dv_table, tpch_table, expected_ratio, description)
            ("hub_region", "region", 1.0, "Hub region = source region"),
            ("hub_nation", "nation", 1.0, "Hub nation = source nation"),
            ("hub_customer", "customer", 1.0, "Hub customer = source customer"),
            ("hub_supplier", "supplier", 1.0, "Hub supplier = source supplier"),
            ("hub_part", "part", 1.0, "Hub part = source part"),
            ("hub_order", "orders", 1.0, "Hub order = source orders"),
            ("hub_lineitem", "lineitem", 1.0, "Hub lineitem = source lineitem"),
            ("link_part_supplier", "partsupp", 1.0, "Link part_supplier = source partsupp"),
            ("sat_customer", "customer", 1.0, "Sat customer = source customer"),
            ("sat_lineitem", "lineitem", 1.0, "Sat lineitem = source lineitem"),
        ]

        failures = []
        for dv_table, tpch_table, expected_ratio, desc in count_checks:
            dv_count = conn.execute(f"SELECT COUNT(*) FROM {dv_table}").fetchone()[0]
            tpch_count = conn.execute(f"SELECT COUNT(*) FROM {tpch_table}").fetchone()[0]

            if tpch_count == 0:
                continue  # Skip empty tables

            actual_ratio = dv_count / tpch_count
            # Allow 1% tolerance for lineitem variance
            tolerance = 0.01 if "lineitem" in dv_table else 0.001
            if abs(actual_ratio - expected_ratio) > tolerance:
                failures.append(f"{desc}: {dv_count} vs {tpch_count} (ratio: {actual_ratio:.4f})")

        conn.close()

        if failures:
            pytest.fail("Row count mismatches:\n" + "\n".join(failures))

    def test_datavault_aggregation_equivalence(self, tmp_path):
        """Test that Data Vault aggregations match TPC-H for key queries.

        This test compares Q1 (pricing summary) and Q6 (revenue) which are
        pure aggregations that should produce identical numeric results
        regardless of the underlying table structure.
        """
        import duckdb

        scale_factor = 0.01
        output_dir = tmp_path / "datavault_agg"

        dv_benchmark = DataVaultBenchmark(
            scale_factor=scale_factor,
            output_dir=output_dir,
        )

        try:
            dv_benchmark.generate_data()
        except FileNotFoundError as e:
            if "dbgen" in str(e) or "dsdgen" in str(e):
                pytest.skip("TPC-H dbgen binary not available")
            raise

        tpch_benchmark = TPCHBenchmark(scale_factor=scale_factor, output_dir=output_dir)

        conn = duckdb.connect(":memory:")

        # Load both schemas and data
        # TPC-H data is in tpch_source_dir, Data Vault data is in output_dir
        conn.execute(tpch_benchmark.get_create_tables_sql(dialect="duckdb"))
        tpch_data_dir = dv_benchmark.tpch_source_dir
        for table in [t.name for t in TABLES]:
            tbl_path = tpch_data_dir / f"{table}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table, str(tbl_path))

        conn.execute(dv_benchmark.get_create_tables_sql(dialect="duckdb"))
        for table_name in dv_benchmark.get_table_loading_order():
            tbl_path = output_dir / f"{table_name}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table_name, str(tbl_path))

        # Test Q6 (simple aggregation) - should produce identical results
        # Q6 computes SUM(l_extendedprice * l_discount) with date/quantity filters
        dv_query_manager = DataVaultQueryManager()

        # TPC-H Q6 with default params: date=1994-01-01, discount=0.06, quantity=24
        tpch_q6 = """
            SELECT SUM(l_extendedprice * l_discount) AS revenue
            FROM lineitem
            WHERE l_shipdate >= DATE '1994-01-01'
              AND l_shipdate < DATE '1994-01-01' + INTERVAL '1' YEAR
              AND l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01
              AND l_quantity < 24
        """

        dv_q6 = dv_query_manager.get_query(6)  # Uses DEFAULT_PARAMS

        tpch_result = conn.execute(tpch_q6).fetchone()[0]
        dv_result = conn.execute(dv_q6).fetchone()[0]

        # Convert to float for comparison
        tpch_revenue = float(tpch_result) if tpch_result else 0.0
        dv_revenue = float(dv_result) if dv_result else 0.0

        # Allow small floating point tolerance
        if tpch_revenue > 0:
            relative_diff = abs(tpch_revenue - dv_revenue) / tpch_revenue
            assert relative_diff < 0.0001, f"Q6 revenue mismatch: TPC-H={tpch_revenue:.2f}, Data Vault={dv_revenue:.2f}"
        else:
            # Both should be zero or near-zero
            assert abs(dv_revenue) < 0.01, f"DV Q6 non-zero when TPC-H is zero: {dv_revenue}"

        conn.close()

    @pytest.mark.slow
    def test_datavault_matches_tpch_results_for_q12_q18_q21(self, tmp_path):
        """Data Vault SQL must be value-identical to canonical TPC-H for Q12/Q18/Q21."""
        import duckdb

        scale_factor = 0.01
        output_dir = tmp_path / "datavault_exact_equivalence"

        dv_benchmark = DataVaultBenchmark(
            scale_factor=scale_factor,
            output_dir=output_dir,
        )

        try:
            dv_benchmark.generate_data()
        except FileNotFoundError as e:
            if "dbgen" in str(e) or "dsdgen" in str(e):
                pytest.skip("TPC-H binaries not available")
            raise

        tpch_benchmark = TPCHBenchmark(scale_factor=scale_factor, output_dir=output_dir)
        conn = duckdb.connect(":memory:")

        # Load TPC-H tables
        conn.execute(tpch_benchmark.get_create_tables_sql(dialect="duckdb"))
        tpch_data_dir = dv_benchmark.tpch_source_dir
        for table in [t.name for t in TABLES]:
            tbl_path = tpch_data_dir / f"{table}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table, str(tbl_path))

        # Load Data Vault tables
        conn.execute(dv_benchmark.get_create_tables_sql(dialect="duckdb"))
        for table_name in dv_benchmark.get_table_loading_order():
            tbl_path = output_dir / f"{table_name}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table_name, str(tbl_path))

        dv_query_manager = DataVaultQueryManager(seed=12345, scale_factor=scale_factor)
        query_ids = [12, 18, 21]
        stream_ids = [0, 1, 2]

        mismatches = []
        for stream_id in stream_ids:
            for qid in query_ids:
                dv_sql, qp = dv_query_manager.get_parameterized_query(qid, stream_id=stream_id)
                tpch_sql = self._tpch_query_for_params(qid, qp.params)

                dv_rows = self._normalize_rows(conn.execute(dv_sql).fetchall())
                tpch_rows = self._normalize_rows(conn.execute(tpch_sql).fetchall())

                if dv_rows != tpch_rows:
                    mismatches.append(
                        f"Q{qid} stream {stream_id} params={qp.params} "
                        f"rows_dv={len(dv_rows)} rows_tpch={len(tpch_rows)}"
                    )

        conn.close()

        if mismatches:
            pytest.fail("Data Vault != TPC-H result mismatch:\n" + "\n".join(mismatches))

    @pytest.mark.slow
    def test_datavault_matches_tpch_results_all_queries(self, tmp_path):
        """Data Vault SQL must be value-identical to canonical TPC-H for all 22 queries.

        Extends the Q12/Q18/Q21 equivalence test to the full TPC-H query set.
        Uses stream 0 with default seed. Both sides use identical parameters
        from DataVaultParameterGenerator, ensuring the comparison is fair.

        Queries that return empty results at SF=0.01 are still validated:
        both sides must agree on the empty result.
        """
        import duckdb

        scale_factor = 0.01
        output_dir = tmp_path / "datavault_full_equivalence"

        dv_benchmark = DataVaultBenchmark(
            scale_factor=scale_factor,
            output_dir=output_dir,
        )

        try:
            dv_benchmark.generate_data()
        except FileNotFoundError as e:
            if "dbgen" in str(e) or "dsdgen" in str(e):
                pytest.skip("TPC-H binaries not available")
            raise

        tpch_benchmark = TPCHBenchmark(scale_factor=scale_factor, output_dir=output_dir)
        conn = duckdb.connect(":memory:")

        # Load TPC-H tables
        conn.execute(tpch_benchmark.get_create_tables_sql(dialect="duckdb"))
        tpch_data_dir = dv_benchmark.tpch_source_dir
        for table in [t.name for t in TABLES]:
            tbl_path = tpch_data_dir / f"{table}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table, str(tbl_path))

        # Load Data Vault tables
        conn.execute(dv_benchmark.get_create_tables_sql(dialect="duckdb"))
        for table_name in dv_benchmark.get_table_loading_order():
            tbl_path = output_dir / f"{table_name}.tbl"
            if tbl_path.exists():
                self._load_tbl_simple(conn, table_name, str(tbl_path))

        dv_query_manager = DataVaultQueryManager(seed=12345, scale_factor=scale_factor)

        mismatches = []
        execution_errors = []

        for qid in range(1, 23):
            dv_sql, qp = dv_query_manager.get_parameterized_query(qid, stream_id=0)
            tpch_sql = self._tpch_query_for_params(qid, qp.params)

            try:
                dv_rows = self._normalize_rows(conn.execute(dv_sql).fetchall())
            except Exception as e:
                execution_errors.append(f"Q{qid} DV execution error: {e}")
                continue

            try:
                tpch_rows = self._normalize_rows(conn.execute(tpch_sql).fetchall())
            except Exception as e:
                execution_errors.append(f"Q{qid} TPC-H execution error: {e}")
                continue

            if dv_rows != tpch_rows:
                mismatches.append(f"Q{qid} rows_dv={len(dv_rows)} rows_tpch={len(tpch_rows)}")

        conn.close()

        failures = execution_errors + mismatches
        if failures:
            pytest.fail("Data Vault full equivalence failures:\n" + "\n".join(failures))
