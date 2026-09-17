"""Apache Doris DDL Generator.

Generates CREATE TABLE statements with Doris-specific physical tuning:
- DUPLICATE KEY model with configurable key columns
- DISTRIBUTED BY HASH for data sharding across BE nodes
- PARTITION BY RANGE for time-based data organization
- Bloom filter indexes for high-cardinality join columns
- Bitmap indexes for low-cardinality filter columns
- Colocate join groups for co-located table joins

Apache Doris is a high-performance MPP analytical database supporting both
high-concurrency point queries and high-throughput complex analysis. Its
storage engine uses a columnar format with LSM-tree-based indexing.

Doris Table Models:
- DUPLICATE KEY: Append-only, preserves all rows (best for analytics)
- UNIQUE KEY: Deduplicates on key columns (MERGE-ON-WRITE or MERGE-ON-READ)
- AGGREGATE KEY: Pre-aggregates on key columns

For TPC-H/TPC-DS benchmarks, DUPLICATE KEY is the optimal model since
queries are read-heavy analytical workloads with no updates.

Example:
    >>> from benchbox.core.tuning.generators.doris import DorisDDLGenerator
    >>> generator = DorisDDLGenerator()
    >>> clauses = generator.generate_tuning_clauses(table_tuning)
    >>> ddl = generator.generate_create_table_ddl("lineitem", columns, clauses)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    ColumnDefinition,
    TuningClauses,
)

if TYPE_CHECKING:
    from benchbox.core.tuning.interface import (
        PlatformOptimizationConfiguration,
        TableTuning,
    )

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# TPC-H tuning defaults for Apache Doris.
#
# Distribution keys are chosen based on join patterns in TPC-H queries.
# Tables that frequently join should share the same distribution key
# and colocate group so Doris can perform local (colocated) joins
# without data shuffling.
#
# Colocate join groups:
#   - group_orders: lineitem (l_orderkey), orders (o_orderkey)
#     Queries: Q3, Q4, Q5, Q7, Q8, Q9, Q10, Q12, Q13, Q14, Q18, Q21
#   - group_partsupp: partsupp (ps_partkey), part (p_partkey)
#     Queries: Q2, Q11, Q16, Q17, Q20
#   - group_customer: customer (c_custkey)
#     Queries: Q3, Q10, Q13, Q18
#   - group_supplier: supplier (s_suppkey)
#     Queries: Q2, Q5, Q7, Q8, Q9, Q20, Q21
# ──────────────────────────────────────────────────────────────────────

# DUPLICATE KEY columns per TPC-H table.
# These define the sort prefix in Doris's columnar storage segments.
# Chosen to match common filter and join predicates for query pruning.
TPCH_DUPLICATE_KEY_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_orderkey", "l_linenumber"],
    "orders": ["o_orderkey"],
    "customer": ["c_custkey"],
    "part": ["p_partkey"],
    "partsupp": ["ps_partkey", "ps_suppkey"],
    "supplier": ["s_suppkey"],
    "nation": ["n_nationkey"],
    "region": ["r_regionkey"],
}

# Hash distribution key per TPC-H table.
# Chosen to align with the most frequent join column for each table.
TPCH_DISTRIBUTION_KEYS: dict[str, str] = {
    "lineitem": "l_orderkey",
    "orders": "o_orderkey",
    "customer": "c_custkey",
    "part": "p_partkey",
    "partsupp": "ps_partkey",
    "supplier": "s_suppkey",
    "nation": "n_nationkey",
    "region": "r_regionkey",
}

# Colocate group assignments for TPC-H tables.
# Tables in the same colocate group with the same bucket count can
# perform local joins without network shuffle.
TPCH_COLOCATE_GROUPS: dict[str, str] = {
    "lineitem": "group_orders",
    "orders": "group_orders",
    "customer": "group_customer",
    "part": "group_partsupp",
    "partsupp": "group_partsupp",
    "supplier": "group_supplier",
    "nation": "group_reference",
    "region": "group_reference",
}

# Default bucket counts per TPC-H table for small scale factors (SF <= 1).
# For larger scale factors, multiply by SF (capped at a reasonable max).
TPCH_DEFAULT_BUCKETS: dict[str, int] = {
    "lineitem": 10,
    "orders": 10,
    "customer": 10,
    "part": 10,
    "partsupp": 10,
    "supplier": 1,
    "nation": 1,
    "region": 1,
}

# Bloom filter index recommendations for high-cardinality join columns.
# These accelerate point lookups and equi-joins on columns with many
# distinct values. Stored in each data segment's index block.
TPCH_BLOOM_FILTER_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_orderkey", "l_partkey", "l_suppkey"],
    "orders": ["o_orderkey", "o_custkey"],
    "customer": ["c_custkey"],
    "part": ["p_partkey"],
    "partsupp": ["ps_partkey", "ps_suppkey"],
    "supplier": ["s_suppkey"],
}

# Bitmap index recommendations for low-cardinality filter columns.
# Bitmap indexes are efficient for columns with few distinct values
# that appear frequently in WHERE clauses.
TPCH_BITMAP_INDEX_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_returnflag", "l_linestatus", "l_shipmode", "l_shipinstruct"],
    "orders": ["o_orderstatus", "o_orderpriority"],
    "part": ["p_brand", "p_type", "p_container", "p_mfgr"],
    "customer": ["c_mktsegment"],
}

# ──────────────────────────────────────────────────────────────────────
# TPC-DS tuning defaults for Apache Doris.
#
# TPC-DS has a much larger schema (~24 fact/dimension tables). Distribution
# keys are chosen based on the most frequent join predicates in the 99 queries.
# ──────────────────────────────────────────────────────────────────────

TPCDS_DUPLICATE_KEY_COLUMNS: dict[str, list[str]] = {
    # Fact tables
    "store_sales": ["ss_sold_date_sk", "ss_item_sk"],
    "store_returns": ["sr_returned_date_sk", "sr_item_sk"],
    "catalog_sales": ["cs_sold_date_sk", "cs_item_sk"],
    "catalog_returns": ["cr_returned_date_sk", "cr_item_sk"],
    "web_sales": ["ws_sold_date_sk", "ws_item_sk"],
    "web_returns": ["wr_returned_date_sk", "wr_item_sk"],
    "inventory": ["inv_date_sk", "inv_item_sk"],
    # Dimension tables
    "date_dim": ["d_date_sk"],
    "time_dim": ["t_time_sk"],
    "item": ["i_item_sk"],
    "customer": ["c_customer_sk"],
    "customer_address": ["ca_address_sk"],
    "customer_demographics": ["cd_demo_sk"],
    "household_demographics": ["hd_demo_sk"],
    "store": ["s_store_sk"],
    "promotion": ["p_promo_sk"],
    "warehouse": ["w_warehouse_sk"],
    "ship_mode": ["sm_ship_mode_sk"],
    "reason": ["r_reason_sk"],
    "income_band": ["ib_income_band_sk"],
    "call_center": ["cc_call_center_sk"],
    "catalog_page": ["cp_catalog_page_sk"],
    "web_site": ["web_site_sk"],
    "web_page": ["wp_web_page_sk"],
}

TPCDS_DISTRIBUTION_KEYS: dict[str, str] = {
    # Fact tables: distribute on the surrogate key that joins to the
    # most frequently filtered dimension (date_dim via *_sold_date_sk)
    "store_sales": "ss_item_sk",
    "store_returns": "sr_item_sk",
    "catalog_sales": "cs_item_sk",
    "catalog_returns": "cr_item_sk",
    "web_sales": "ws_item_sk",
    "web_returns": "wr_item_sk",
    "inventory": "inv_item_sk",
    # Dimension tables: distribute on primary surrogate key
    "date_dim": "d_date_sk",
    "time_dim": "t_time_sk",
    "item": "i_item_sk",
    "customer": "c_customer_sk",
    "customer_address": "ca_address_sk",
    "customer_demographics": "cd_demo_sk",
    "household_demographics": "hd_demo_sk",
    "store": "s_store_sk",
    "promotion": "p_promo_sk",
    "warehouse": "w_warehouse_sk",
    "ship_mode": "sm_ship_mode_sk",
    "reason": "r_reason_sk",
    "income_band": "ib_income_band_sk",
    "call_center": "cc_call_center_sk",
    "catalog_page": "cp_catalog_page_sk",
    "web_site": "web_site_sk",
    "web_page": "wp_web_page_sk",
}

TPCDS_COLOCATE_GROUPS: dict[str, str] = {
    # Fact tables that join to item dimension share a colocate group
    "store_sales": "group_item_facts",
    "store_returns": "group_item_facts",
    "catalog_sales": "group_item_facts",
    "catalog_returns": "group_item_facts",
    "web_sales": "group_item_facts",
    "web_returns": "group_item_facts",
    "inventory": "group_item_facts",
    "item": "group_item_facts",
    # Dimension tables with low join frequency get their own groups
    "date_dim": "group_date",
    "time_dim": "group_time",
    "customer": "group_customer",
    "customer_address": "group_customer_addr",
    "customer_demographics": "group_demographics",
    "household_demographics": "group_demographics",
    "store": "group_store",
    "promotion": "group_misc_dim",
    "warehouse": "group_misc_dim",
    "ship_mode": "group_misc_dim",
    "reason": "group_misc_dim",
    "income_band": "group_misc_dim",
    "call_center": "group_misc_dim",
    "catalog_page": "group_misc_dim",
    "web_site": "group_misc_dim",
    "web_page": "group_misc_dim",
}

TPCDS_DEFAULT_BUCKETS: dict[str, int] = {
    # Fact tables need more buckets for parallelism
    "store_sales": 10,
    "store_returns": 10,
    "catalog_sales": 10,
    "catalog_returns": 10,
    "web_sales": 10,
    "web_returns": 10,
    "inventory": 10,
    # Dimension tables
    "date_dim": 1,
    "time_dim": 1,
    "item": 3,
    "customer": 3,
    "customer_address": 3,
    "customer_demographics": 1,
    "household_demographics": 1,
    "store": 1,
    "promotion": 1,
    "warehouse": 1,
    "ship_mode": 1,
    "reason": 1,
    "income_band": 1,
    "call_center": 1,
    "catalog_page": 1,
    "web_site": 1,
    "web_page": 1,
}

TPCDS_BLOOM_FILTER_COLUMNS: dict[str, list[str]] = {
    "store_sales": ["ss_item_sk", "ss_customer_sk", "ss_sold_date_sk"],
    "store_returns": ["sr_item_sk", "sr_customer_sk", "sr_returned_date_sk"],
    "catalog_sales": ["cs_item_sk", "cs_bill_customer_sk", "cs_sold_date_sk"],
    "catalog_returns": ["cr_item_sk", "cr_returning_customer_sk", "cr_returned_date_sk"],
    "web_sales": ["ws_item_sk", "ws_bill_customer_sk", "ws_sold_date_sk"],
    "web_returns": ["wr_item_sk", "wr_returning_customer_sk", "wr_returned_date_sk"],
    "inventory": ["inv_item_sk", "inv_date_sk"],
    "customer": ["c_customer_sk"],
    "item": ["i_item_sk"],
}

TPCDS_BITMAP_INDEX_COLUMNS: dict[str, list[str]] = {
    "store_sales": ["ss_store_sk", "ss_promo_sk"],
    "catalog_sales": ["cs_warehouse_sk", "cs_ship_mode_sk"],
    "web_sales": ["ws_warehouse_sk", "ws_ship_mode_sk"],
    "customer": ["c_birth_country", "c_preferred_cust_flag"],
    "item": ["i_category", "i_class", "i_brand"],
    "store": ["s_state", "s_market_id"],
}

# Default number of hash buckets for tables not in the lookup dicts
DEFAULT_BUCKET_COUNT = 10

# Benchmark-specific tuning lookup: maps benchmark name to its dicts
_BENCHMARK_TUNING: dict[str, dict[str, Any]] = {
    "tpch": {
        "duplicate_keys": TPCH_DUPLICATE_KEY_COLUMNS,
        "distribution_keys": TPCH_DISTRIBUTION_KEYS,
        "colocate_groups": TPCH_COLOCATE_GROUPS,
        "default_buckets": TPCH_DEFAULT_BUCKETS,
        "bloom_filter_columns": TPCH_BLOOM_FILTER_COLUMNS,
        "bitmap_index_columns": TPCH_BITMAP_INDEX_COLUMNS,
    },
    "tpcds": {
        "duplicate_keys": TPCDS_DUPLICATE_KEY_COLUMNS,
        "distribution_keys": TPCDS_DISTRIBUTION_KEYS,
        "colocate_groups": TPCDS_COLOCATE_GROUPS,
        "default_buckets": TPCDS_DEFAULT_BUCKETS,
        "bloom_filter_columns": TPCDS_BLOOM_FILTER_COLUMNS,
        "bitmap_index_columns": TPCDS_BITMAP_INDEX_COLUMNS,
    },
}


class DorisDDLGenerator(BaseDDLGenerator):
    """DDL generator for Apache Doris physical tuning.

    Generates Doris table DDL with:
    - DUPLICATE KEY: Sort prefix columns for segment pruning
    - DISTRIBUTED BY HASH: Data sharding across BE nodes
    - PARTITION BY RANGE: Optional time-based partitioning
    - PROPERTIES: Colocate group, replication, bloom filters
    - Post-create bitmap indexes for low-cardinality filter columns

    Doris Tuning Mapping:
    - SORTING -> DUPLICATE KEY (sort prefix in storage segments)
    - DISTRIBUTION -> DISTRIBUTED BY HASH (data sharding)
    - PARTITIONING -> PARTITION BY RANGE
    - CLUSTERING -> Logged only (Doris uses colocate groups instead)

    Example DDL:
        CREATE TABLE IF NOT EXISTS lineitem (
            l_orderkey BIGINT,
            l_linenumber INT,
            l_shipdate DATE,
            ...
        )
        DUPLICATE KEY (l_orderkey, l_linenumber)
        DISTRIBUTED BY HASH(l_orderkey) BUCKETS 10
        PROPERTIES (
            "replication_num" = "1",
            "colocate_with" = "group_orders",
            "bloom_filter_columns" = "l_orderkey, l_partkey, l_suppkey"
        );
    """

    IDENTIFIER_QUOTE = "`"
    SUPPORTS_IF_NOT_EXISTS = True
    STATEMENT_TERMINATOR = ";"

    SUPPORTED_TUNING_TYPES = frozenset({"sorting", "distribution", "partitioning", "clustering"})

    def __init__(
        self,
        default_bucket_count: int = DEFAULT_BUCKET_COUNT,
        replication_num: int = 1,
        benchmark_type: str | None = None,
        scale_factor: float = 1.0,
        enable_colocate: bool = True,
        enable_bloom_filter: bool = True,
        enable_bitmap_index: bool = True,
    ):
        """Initialize the Apache Doris DDL generator.

        Args:
            default_bucket_count: Default number of hash buckets when not
                specified per table. Should be tuned to cluster size.
            replication_num: Number of data replicas. Use 1 for benchmarks
                (faster loads), 3 for production.
            benchmark_type: Benchmark type (tpch, tpcds) for automatic
                tuning defaults. None disables benchmark-specific defaults.
            scale_factor: Benchmark scale factor, used to scale bucket counts.
            enable_colocate: Whether to assign colocate groups for join
                optimization. Requires tables in same group to share the
                same bucket count.
            enable_bloom_filter: Whether to add bloom filter index
                recommendations to table properties.
            enable_bitmap_index: Whether to generate CREATE INDEX statements
                for bitmap indexes as post-create actions.
        """
        self._default_bucket_count = default_bucket_count
        self._replication_num = replication_num
        self._benchmark_type = benchmark_type.lower() if benchmark_type else None
        self._scale_factor = scale_factor
        self._enable_colocate = enable_colocate
        self._enable_bloom_filter = enable_bloom_filter
        self._enable_bitmap_index = enable_bitmap_index

    @property
    def platform_name(self) -> str:
        return "doris"

    def _get_benchmark_tuning(self) -> dict[str, Any] | None:
        """Get benchmark-specific tuning dictionaries.

        Returns:
            Dict of tuning config for the benchmark, or None.
        """
        if self._benchmark_type:
            return _BENCHMARK_TUNING.get(self._benchmark_type)
        return None

    def _compute_bucket_count(self, table_name: str) -> int:
        """Compute the number of hash buckets for a table.

        For scale factors > 1, bucket counts are scaled up proportionally
        from the base defaults, capped at 128 to avoid excessive overhead.

        Args:
            table_name: Lowercase table name.

        Returns:
            Number of hash buckets.
        """
        tuning = self._get_benchmark_tuning()
        if tuning:
            base_buckets = tuning["default_buckets"].get(table_name, self._default_bucket_count)
        else:
            base_buckets = self._default_bucket_count

        if self._scale_factor > 1.0:
            scaled = int(base_buckets * self._scale_factor)
            return min(scaled, 128)

        return base_buckets

    def generate_tuning_clauses(
        self,
        table_tuning: TableTuning | None,
        platform_opts: PlatformOptimizationConfiguration | None = None,
    ) -> TuningClauses:
        """Generate Apache Doris tuning clauses.

        Produces TuningClauses with:
        - ``sort_by``: DUPLICATE KEY columns (sort prefix)
        - ``distribute_by``: rendered ``DISTRIBUTED BY HASH(`col`) BUCKETS N``
          clause (rendered-SQL contract: never a bare column name, so dry-run
          preview via ``TuningClauses.get_inline_clauses()`` and execution DDL
          render the identical string exactly once)
        - ``partition_by``: Optional PARTITION BY RANGE expression
        - ``table_properties``: Doris PROPERTIES (replication, colocate, bloom filter)
        - ``platform``: ``"doris"`` so inline clauses order DISTRIBUTED BY
          after PARTITION BY, as the Doris dialect requires
        - ``post_create_statements``: CREATE INDEX for bitmap indexes

        When ``table_tuning`` provides explicit columns via TuningType, those
        take precedence. Otherwise, benchmark-specific defaults are used.

        Args:
            table_tuning: Table tuning configuration.
            platform_opts: Platform-specific options.

        Returns:
            TuningClauses with Doris-specific configuration.
        """
        clauses = TuningClauses(platform=self.platform_name)

        if not table_tuning:
            return clauses

        table_name = table_tuning.table_name.lower() if table_tuning.table_name else ""
        tuning = self._get_benchmark_tuning()

        from benchbox.core.tuning.interface import TuningType

        # ── DUPLICATE KEY (from SORTING tuning or benchmark defaults) ──
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            sorted_cols = sorted(sort_columns, key=lambda c: c.order)
            clauses.sort_by = ", ".join(c.name for c in sorted_cols)
        elif tuning and table_name in tuning["duplicate_keys"]:
            clauses.sort_by = ", ".join(tuning["duplicate_keys"][table_name])
            logger.info(f"Doris table {table_name}: using benchmark default DUPLICATE KEY ({clauses.sort_by})")

        # ── DISTRIBUTED BY HASH (from DISTRIBUTION tuning or benchmark defaults) ──
        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            dist_col = sorted_cols[0].name  # Doris HASH distribution uses a single column
            clauses.distribute_by = dist_col
        elif tuning and table_name in tuning["distribution_keys"]:
            clauses.distribute_by = tuning["distribution_keys"][table_name]
            logger.info(f"Doris table {table_name}: using benchmark default distribution key ({clauses.distribute_by})")

        # ── PARTITION BY RANGE (from PARTITIONING tuning) ──
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            clauses.partition_by = ", ".join(c.name for c in sorted_cols)

        # ── Clustering warning ──
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                f"Clustering hint for Doris table {table_name}: "
                f"{[c.name for c in cluster_columns]}. "
                f"Doris uses colocate groups for join colocation instead of explicit clustering."
            )

        # ── Table PROPERTIES ──
        properties: dict[str, str] = {}

        # Replication
        properties["replication_num"] = str(self._replication_num)

        # Colocate group for join optimization
        if self._enable_colocate and tuning and table_name in tuning.get("colocate_groups", {}):
            properties["colocate_with"] = tuning["colocate_groups"][table_name]

        # Bloom filter index columns
        if self._enable_bloom_filter and tuning and table_name in tuning.get("bloom_filter_columns", {}):
            bf_cols = tuning["bloom_filter_columns"][table_name]
            properties["bloom_filter_columns"] = ", ".join(bf_cols)

        clauses.table_properties = properties

        # ── Distribution clause with buckets (rendered into distribute_by) ──
        # Stored rendered (not bare): get_inline_clauses() emits it verbatim
        # after PARTITION BY, and generate_create_table_ddl() uses it directly,
        # so preview and execution can never disagree or duplicate it.
        bucket_count = self._compute_bucket_count(table_name)
        if clauses.distribute_by:
            clauses.distribute_by = f"DISTRIBUTED BY HASH(`{clauses.distribute_by}`) BUCKETS {bucket_count}"

        # ── Bitmap indexes as post-create statements ──
        if self._enable_bitmap_index and tuning and table_name in tuning.get("bitmap_index_columns", {}):
            for col in tuning["bitmap_index_columns"][table_name]:
                idx_name = f"idx_bitmap_{table_name}_{col}"
                stmt = f"CREATE INDEX IF NOT EXISTS `{idx_name}` ON `{table_name}` (`{col}`) USING BITMAP"
                clauses.post_create_statements.append(stmt)

        return clauses

    def generate_create_table_ddl(
        self,
        table_name: str,
        columns: list[ColumnDefinition],
        tuning: TuningClauses | None = None,
        if_not_exists: bool = False,
        schema: str | None = None,
    ) -> str:
        """Generate Apache Doris CREATE TABLE statement.

        Produces DDL with DUPLICATE KEY model, DISTRIBUTED BY HASH, and
        PROPERTIES block. The structure follows Doris DDL syntax:

            CREATE TABLE [IF NOT EXISTS] table_name (
                column_definitions
            )
            DUPLICATE KEY (key_columns)
            [PARTITION BY RANGE (partition_columns) (...)]
            DISTRIBUTED BY HASH(dist_column) BUCKETS N
            PROPERTIES (
                "key" = "value", ...
            );

        Args:
            table_name: Table name.
            columns: Column definitions.
            tuning: Tuning clauses from generate_tuning_clauses().
            if_not_exists: Add IF NOT EXISTS clause.
            schema: Database/schema name.

        Returns:
            Complete CREATE TABLE DDL string.
        """
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        # Column definitions
        col_list = self.generate_column_list(columns)
        statement = f"{statement}\n(\n    {col_list}\n)"

        if tuning:
            # DUPLICATE KEY clause
            if tuning.sort_by:
                statement = f"{statement}\nDUPLICATE KEY ({tuning.sort_by})"

            # PARTITION BY RANGE clause (if specified)
            if tuning.partition_by:
                statement = f"{statement}\nPARTITION BY RANGE ({tuning.partition_by}) ()"

            # DISTRIBUTED BY HASH ... BUCKETS N (already rendered in distribute_by)
            if tuning.distribute_by:
                statement = f"{statement}\n{tuning.distribute_by}"
            for clause in tuning.additional_clauses:
                statement = f"{statement}\n{clause}"

            # PROPERTIES block
            if tuning.table_properties:
                props_lines = []
                for key, value in tuning.table_properties.items():
                    props_lines.append(f'    "{key}" = "{value}"')
                props_block = ",\n".join(props_lines)
                statement = f"{statement}\nPROPERTIES (\n{props_block}\n)"

        statement = f"{statement}{self.STATEMENT_TERMINATOR}"

        return statement

    def get_post_load_statements(
        self,
        table_name: str,
        tuning: TuningClauses | None = None,
        schema: str | None = None,
    ) -> list[str]:
        """Get post-load statements for Apache Doris.

        Returns bitmap index creation statements and ANALYZE TABLE
        for statistics collection after data loading.

        Args:
            table_name: Table name.
            tuning: Tuning clauses containing post_create_statements.
            schema: Database/schema name.

        Returns:
            List of SQL statements to execute after data load.
        """
        statements = []

        # Add bitmap index creation from tuning
        if tuning and tuning.post_create_statements:
            statements.extend(tuning.post_create_statements)

        # ANALYZE TABLE for statistics collection (improves query planning)
        qualified_name = self.format_qualified_name(table_name, schema)
        statements.append(f"ANALYZE TABLE {qualified_name}")

        return statements


__all__ = [
    "DorisDDLGenerator",
]
