"""PostgreSQL-family execution-filter rules for write_primitives operation gaps."""

from __future__ import annotations

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import Phase
from benchbox.sql_compat.decision import CompatibilityDecision, FailureMode, SkipQueryPayload, SupportLevel
from benchbox.sql_compat.registry import REGISTRY

POSTGRES_WRITE_PRIMITIVES_CATEGORY_SKIPS = {
    "bulk_load": "PostgreSQL-family operation execution cannot run the catalog's server-side file COPY/read_csv path.",
    "sketch": "PostgreSQL-family engines do not expose DuckDB DataSketches INSTALL/LOAD SQL.",
}

POSTGRES_WRITE_PRIMITIVES_OPERATION_SKIPS = {
    "merge_simple_upsert_small": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
    "merge_upsert_with_delete": "PostgreSQL MERGE does not support the catalog's NOT MATCHED BY SOURCE form.",
    "merge_overlap_10pct": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
    "merge_overlap_50pct": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
    "merge_overlap_90pct": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
    "merge_no_overlap_all_insert": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
    "merge_conditional_update": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
    "merge_returning_clause": "pg_duckdb rejects the catalog's MERGE RETURNING form in UAT.",
    "merge_error_handling": "PostgreSQL MERGE requires an explicit INSERT VALUES clause; the catalog uses DuckDB shorthand.",
}

_BULK_LOAD_OPERATION_IDS = {
    "bulk_load_append_mode",
    "bulk_load_column_subset",
    "bulk_load_csv_large_bzip2",
    "bulk_load_csv_large_gzip",
    "bulk_load_csv_large_uncompressed",
    "bulk_load_csv_large_zstd",
    "bulk_load_csv_medium_bzip2",
    "bulk_load_csv_medium_gzip",
    "bulk_load_csv_medium_uncompressed",
    "bulk_load_csv_medium_zstd",
    "bulk_load_csv_small_bzip2",
    "bulk_load_csv_small_gzip",
    "bulk_load_csv_small_uncompressed",
    "bulk_load_csv_small_zstd",
    "bulk_load_date_format_custom",
    "bulk_load_delimited_custom",
    "bulk_load_encoding_utf8",
    "bulk_load_error_handling_skip_bad_rows",
    "bulk_load_null_handling",
    "bulk_load_parallel_multi_file",
    "bulk_load_parquet_large_gzip",
    "bulk_load_parquet_large_snappy",
    "bulk_load_parquet_large_uncompressed",
    "bulk_load_parquet_large_zstd",
    "bulk_load_parquet_medium_gzip",
    "bulk_load_parquet_medium_snappy",
    "bulk_load_parquet_medium_uncompressed",
    "bulk_load_parquet_medium_zstd",
    "bulk_load_parquet_small_gzip",
    "bulk_load_parquet_small_snappy",
    "bulk_load_parquet_small_uncompressed",
    "bulk_load_parquet_small_zstd",
    "bulk_load_quoted_fields",
    "bulk_load_replace_mode",
    "bulk_load_upsert_mode",
    "bulk_load_with_transformation",
}

_SKETCH_OPERATION_IDS = {
    "sketch_cpc_create_persistent_table",
    "sketch_cpc_drop_persistent_table",
    "sketch_cpc_insert_per_partition",
    "sketch_cpc_query_union_merge",
    "sketch_ddl_create_persistent_table",
    "sketch_drop_persistent_table",
    "sketch_insert_kll_per_partition",
    "sketch_insert_theta_per_partition",
    "sketch_insert_topk_per_shard",
    "sketch_query_kll_quantiles_merge",
    "sketch_query_kll_quantiles_merge_k100",
    "sketch_query_kll_quantiles_merge_k1000",
    "sketch_query_theta_union_merge",
    "sketch_query_theta_union_merge_lgk10",
    "sketch_query_theta_union_merge_lgk14",
    "sketch_query_topk_combine",
    "sketch_query_topk_combine_lgmm10",
    "sketch_query_topk_combine_lgmm8",
    "sketch_req_create_persistent_table",
    "sketch_req_drop_persistent_table",
    "sketch_req_insert_per_partition",
    "sketch_req_query_quantile_merge",
}

_SKIPS_BY_QUERY_ID = {
    **dict.fromkeys(_BULK_LOAD_OPERATION_IDS, POSTGRES_WRITE_PRIMITIVES_CATEGORY_SKIPS["bulk_load"]),
    **dict.fromkeys(_SKETCH_OPERATION_IDS, POSTGRES_WRITE_PRIMITIVES_CATEGORY_SKIPS["sketch"]),
    **POSTGRES_WRITE_PRIMITIVES_OPERATION_SKIPS,
}

# NOTE: The runtime skip decision is made by ``_get_effective_write_sql`` reading
# the CATEGORY/OPERATION skip dicts above directly; nothing resolves the
# EXECUTION_FILTER registry phase at execution time today. Unlike the DuckDB rule
# (whose skip set is a dynamic MERGE INTO token match and is therefore NOT
# registered), this loop enumerates exactly the same static skip set the dicts
# hold, so the registry and the runtime cannot disagree. It is registered for any
# future registry-driven coverage consumer; the dicts remain the source of truth.
for _query_id, _reason in _SKIPS_BY_QUERY_ID.items():
    REGISTRY.register(
        CompatibilityDecision(
            rule_id=f"execution_filter.postgres.write_primitives.{_query_id}",
            action=CompatAction.SKIP_QUERY,
            support_level=SupportLevel.SKIPPED_QUERY,
            failure_mode=FailureMode.UNSUPPORTED_FEATURE,
            payload=SkipQueryPayload(
                reason=f"{_reason} Evidence: pg-duckdb targeted UAT on 2026-05-13.",
                query_id=_query_id,
            ),
            reason=_reason,
        ),
        Phase.EXECUTION_FILTER,
        "postgres",
        benchmark="write_primitives",
        query_id=_query_id,
    )
