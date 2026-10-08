# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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

TPCH_BLOOM_FILTER_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_orderkey", "l_partkey", "l_suppkey"],
    "orders": ["o_orderkey", "o_custkey"],
    "customer": ["c_custkey"],
    "part": ["p_partkey"],
    "partsupp": ["ps_partkey", "ps_suppkey"],
    "supplier": ["s_suppkey"],
}

TPCH_BITMAP_INDEX_COLUMNS: dict[str, list[str]] = {
    "lineitem": ["l_returnflag", "l_linestatus", "l_shipmode", "l_shipinstruct"],
    "orders": ["o_orderstatus", "o_orderpriority"],
    "part": ["p_brand", "p_type", "p_container", "p_mfgr"],
    "customer": ["c_mktsegment"],
}


TPCDS_DUPLICATE_KEY_COLUMNS: dict[str, list[str]] = {
    "store_sales": ["ss_sold_date_sk", "ss_item_sk"],
    "store_returns": ["sr_returned_date_sk", "sr_item_sk"],
    "catalog_sales": ["cs_sold_date_sk", "cs_item_sk"],
    "catalog_returns": ["cr_returned_date_sk", "cr_item_sk"],
    "web_sales": ["ws_sold_date_sk", "ws_item_sk"],
    "web_returns": ["wr_returned_date_sk", "wr_item_sk"],
    "inventory": ["inv_date_sk", "inv_item_sk"],
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
    "store_sales": "ss_item_sk",
    "store_returns": "sr_item_sk",
    "catalog_sales": "cs_item_sk",
    "catalog_returns": "cr_item_sk",
    "web_sales": "ws_item_sk",
    "web_returns": "wr_item_sk",
    "inventory": "inv_item_sk",
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
    "store_sales": "group_item_facts",
    "store_returns": "group_item_facts",
    "catalog_sales": "group_item_facts",
    "catalog_returns": "group_item_facts",
    "web_sales": "group_item_facts",
    "web_returns": "group_item_facts",
    "inventory": "group_item_facts",
    "item": "group_item_facts",
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
    "store_sales": 10,
    "store_returns": 10,
    "catalog_sales": 10,
    "catalog_returns": 10,
    "web_sales": 10,
    "web_returns": 10,
    "inventory": 10,
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

DEFAULT_BUCKET_COUNT = 10

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

    def render_partition_clause(self, partition_by: str) -> str:
        return f"PARTITION BY RANGE ({partition_by}) ()"

    def _get_benchmark_tuning(self) -> dict[str, Any] | None:
        if self._benchmark_type:
            return _BENCHMARK_TUNING.get(self._benchmark_type)
        return None

    def _compute_bucket_count(self, table_name: str) -> int:
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
        clauses = TuningClauses(platform=self.platform_name)

        if not table_tuning:
            return clauses

        table_name = table_tuning.table_name.lower() if table_tuning.table_name else ""
        tuning = self._get_benchmark_tuning()

        from benchbox.core.tuning.interface import TuningType

        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            sorted_cols = sorted(sort_columns, key=lambda c: c.order)
            clauses.sort_by = ", ".join(c.name for c in sorted_cols)
        elif tuning and table_name in tuning["duplicate_keys"]:
            clauses.sort_by = ", ".join(tuning["duplicate_keys"][table_name])
            logger.info(f"Doris table {table_name}: using benchmark default DUPLICATE KEY ({clauses.sort_by})")

        distribution_columns = table_tuning.get_columns_by_type(TuningType.DISTRIBUTION)
        if distribution_columns:
            sorted_cols = sorted(distribution_columns, key=lambda c: c.order)
            dist_col = sorted_cols[0].name
            clauses.distribute_by = dist_col
        elif tuning and table_name in tuning["distribution_keys"]:
            clauses.distribute_by = tuning["distribution_keys"][table_name]
            logger.info(f"Doris table {table_name}: using benchmark default distribution key ({clauses.distribute_by})")

        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda c: c.order)
            clauses.partition_by = self.render_partition_clause(", ".join(c.name for c in sorted_cols))

        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            logger.info(
                f"Clustering hint for Doris table {table_name}: "
                f"{[c.name for c in cluster_columns]}. "
                f"Doris uses colocate groups for join colocation instead of explicit clustering."
            )

        properties: dict[str, str] = {}

        properties["replication_num"] = str(self._replication_num)

        if self._enable_colocate and tuning and table_name in tuning.get("colocate_groups", {}):
            properties["colocate_with"] = tuning["colocate_groups"][table_name]

        if self._enable_bloom_filter and tuning and table_name in tuning.get("bloom_filter_columns", {}):
            bf_cols = tuning["bloom_filter_columns"][table_name]
            properties["bloom_filter_columns"] = ", ".join(bf_cols)

        clauses.table_properties = properties

        bucket_count = self._compute_bucket_count(table_name)
        if clauses.distribute_by:
            clauses.distribute_by = f"DISTRIBUTED BY HASH(`{clauses.distribute_by}`) BUCKETS {bucket_count}"

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
        parts = ["CREATE TABLE"]

        if if_not_exists:
            parts.append("IF NOT EXISTS")

        parts.append(self.format_qualified_name(table_name, schema))

        statement = " ".join(parts)

        col_list = self.generate_column_list(columns)
        statement = f"{statement}\n(\n    {col_list}\n)"

        if tuning:
            if tuning.sort_by:
                statement = f"{statement}\nDUPLICATE KEY ({tuning.sort_by})"

            if tuning.partition_by:
                statement = f"{statement}\n{tuning.partition_by}"

            if tuning.distribute_by:
                statement = f"{statement}\n{tuning.distribute_by}"
            for clause in tuning.additional_clauses:
                statement = f"{statement}\n{clause}"

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
        statements = []

        if tuning and tuning.post_create_statements:
            statements.extend(tuning.post_create_statements)

        qualified_name = self.format_qualified_name(table_name, schema)
        statements.append(f"ANALYZE TABLE {qualified_name}")

        return statements


__all__ = [
    "DorisDDLGenerator",
]
