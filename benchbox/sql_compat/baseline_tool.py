"""Baseline snapshot tool for sql_compat - records pre-migration SQL hashes.

Generates _project/compat/baseline.v1.jsonl: for each known compatibility
decision site discovered by the w2 inventory, records the source SQL hash,
decision type, and final SQL hash so the dual-run harness can detect
divergence after rules are registered.

Imports only lightweight query-data modules (no DB connection required).
The tool is idempotent: identical source code produces identical output.

Schema version: 1. See docs/development/adr/adr-sql-compat-phase-aware-pipeline.md
§Baseline Schema v1 for the
version-bump and refresh protocol.

Usage:
    uv run -- python -m benchbox.sql_compat.baseline_tool
    uv run -- python -m benchbox.sql_compat.baseline_tool --output PATH
    uv run -- python -m benchbox.sql_compat.baseline_tool --summary
"""

from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from benchbox.utils.printing import emit

SCHEMA_VERSION = 1
DEFAULT_OUTPUT = "_project/compat/baseline.v1.jsonl"


# ---------------------------------------------------------------------------
# Record shape
# ---------------------------------------------------------------------------


@dataclass
class BaselineRecord:
    schema_version: int
    platform: str
    benchmark: str | None  # None = applies to all benchmarks on this platform
    query_id: str | None
    phase: str
    mode: str
    source_sql_hash: str | None
    decision: str  # SupportLevel value: NATIVE | TRANSLATED | REWRITTEN | INFORMATIONAL | SKIPPED_QUERY | SKIPPED_DDL_FRAGMENT | BLOCKED
    rule_id: str | None  # always null in the baseline (no rules exist yet)
    final_sql_hash: str | None
    benchmark_gate_outcome: str | None  # "allowed" | "blocked" | None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _rec(
    platform: str,
    benchmark: str | None,
    query_id: str | None,
    phase: str,
    mode: str,
    decision: str,
    *,
    source_sql: str | None = None,
    final_sql: str | None = None,
    gate: str | None = None,
) -> BaselineRecord:
    return BaselineRecord(
        schema_version=SCHEMA_VERSION,
        platform=platform,
        benchmark=benchmark,
        query_id=query_id,
        phase=phase,
        mode=mode,
        source_sql_hash=_sha256(source_sql) if source_sql is not None else None,
        decision=decision,
        rule_id=None,
        final_sql_hash=_sha256(final_sql) if final_sql is not None else None,
        benchmark_gate_outcome=gate,
    )


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------


def _h2o_q9_records() -> list[BaselineRecord]:
    """H2O Q9 per-platform SQL variants (ClickHouse and StarRocks)."""
    from benchbox.core.h2odb.benchmark import H2OBenchmark
    from benchbox.core.h2odb.queries import H2OQueryManager

    default_q9 = H2OQueryManager().get_query("Q9")
    return [
        _rec(
            "clickhouse",
            "h2odb",
            "Q9",
            "query_source",
            "sql",
            "REWRITTEN",
            source_sql=default_q9,
            final_sql=H2OBenchmark._CLICKHOUSE_Q9,
        ),
        _rec(
            "starrocks",
            "h2odb",
            "Q9",
            "query_source",
            "sql",
            "REWRITTEN",
            source_sql=default_q9,
            final_sql=H2OBenchmark._STARROCKS_Q9,
        ),
    ]


def _vector_search_records() -> list[BaselineRecord]:
    """Vector search QUERY_VARIANTS - per-platform SQL for all 6 queries."""
    from benchbox.core.vector_search.queries import _QUERIES, QUERY_VARIANTS

    records: list[BaselineRecord] = []
    for platform in sorted(QUERY_VARIANTS):
        for query_id in sorted(QUERY_VARIANTS[platform]):
            default_sql = _QUERIES[query_id]  # KeyError = variant key missing from default dict
            variant_sql = QUERY_VARIANTS[platform][query_id]
            records.append(
                _rec(
                    platform,
                    "vector_search",
                    query_id,
                    "query_source",
                    "sql",
                    "REWRITTEN",
                    source_sql=default_sql,
                    final_sql=variant_sql,
                )
            )
    return records


def _benchmark_gate_records() -> list[BaselineRecord]:
    """Blocked platform×benchmark combinations (from platform_registry)."""
    from benchbox.core.platform_registry import PlatformRegistry

    metadata = PlatformRegistry.get_all_platform_metadata()
    records: list[BaselineRecord] = []
    for platform_key in sorted(metadata):
        caps = PlatformRegistry.get_platform_capabilities(platform_key)
        if caps is None or not caps.unsupported_benchmarks:
            continue
        for benchmark in sorted(caps.unsupported_benchmarks):
            records.append(
                _rec(
                    platform_key,
                    benchmark,
                    None,
                    "benchmark_gate",
                    "sql",
                    "BLOCKED",
                    gate="blocked",
                )
            )
    return records


def _schema_emit_records() -> list[BaselineRecord]:
    """DDL schema-emit decision sites (dialect branches in schema/DDL helpers).

    Derived from the w2 inventory. SQL hashes are null - these sites modify
    DDL text, not query SQL, so only the decision label matters for parity.
    Deduplication by (platform, benchmark): multiple dialect branches in the
    same file/benchmark collapse to one REWRITTEN record.
    """
    # (platform, benchmark) tuples with REWRITTEN DDL decisions.
    # Sources: inventory entries with kind=ddl and suggested_phase=schema_emit.
    sites: list[tuple[str, str]] = [
        # write_primitives: lock-table bypass + _supports_primary_keys() (pk_capability.py)
        ("clickhouse", "write_primitives"),
        ("datafusion", "write_primitives"),
        ("doris", "write_primitives"),
        ("starrocks", "write_primitives"),
        # transaction_primitives: lock-table bypass (pk_capability_txn.py)
        # StarRocks and Doris added by registry - were absent from legacy code (silent bugs)
        ("clickhouse", "transaction_primitives"),
        ("datafusion", "transaction_primitives"),
        ("doris", "transaction_primitives"),
        ("starrocks", "transaction_primitives"),
        # nyctaxi/schema.py:263  - ClickHouse dialect branch
        ("clickhouse", "nyctaxi"),
        # nyctaxi/spatial.py:724,736,752  - duckdb, postgresql, clickhouse dialect branches
        ("duckdb", "nyctaxi"),
        ("postgresql", "nyctaxi"),
        # joinorder/schema.py:299,301  - postgres and mysql dialect branches
        ("mysql", "joinorder"),
        ("postgresql", "joinorder"),
        # tsbs_devops/schema.py:184  - ClickHouse dialect branch
        ("clickhouse", "tsbs_devops"),
    ]
    return [_rec(platform, benchmark, None, "schema_emit", "sql", "REWRITTEN") for platform, benchmark in sites]


def _ddl_optimize_records() -> list[BaselineRecord]:
    """Platform-level DDL optimization sites (_optimize_table_definition).

    Derived from inventory entries with kind=ddl and suggested_phase=ddl_optimize.
    benchmark=None because these functions run for every benchmark on the platform.
    """
    # Platform keys inferred from file paths in the inventory.
    # Note: azure_synapse registers under canonical key "synapse" in the registry
    # (see synapse_ddl_rewrites.py and test_synapse_ddl_optimize_rule_uses_canonical_platform_key).
    #   platforms/athena.py              → athena  (_convert_to_external_table)
    #   platforms/azure_synapse.py       → azure_synapse  (registry canonical key: "synapse")
    #   platforms/bigquery.py            → bigquery  (_convert_to_bigquery_table)
    #   platforms/clickhouse/workload.py → clickhouse
    #   platforms/databend/adapter.py    → databend
    #   platforms/databricks/adapter.py  → databricks  (platform_transform_fn → pre-pass loop, w17)
    #   platforms/doris.py               → doris  (_inject_doris_ddl_clauses, not _optimize_table_definition)
    #   platforms/fabric_warehouse.py    → fabric_dw  (_optimize_table_definition; CLI key is fabric_dw)
    #   platforms/firebolt.py            → firebolt
    #   platforms/lakesail.py            → lakesail
    #   platforms/postgresql.py          → postgresql  (FK strip retry, not _optimize_table_definition)
    #   platforms/presto.py              → presto
    #   platforms/questdb.py             → questdb  (strip_foreign_keys + _strip_pk_constraints)
    #   platforms/redshift.py            → redshift
    #   platforms/singlestore.py         → singlestore  (_transform_create_statement, not _optimize_table_definition)
    #   platforms/snowflake.py           → snowflake
    #   platforms/spark.py               → spark
    #   platforms/starrocks/workload.py  → starrocks
    #   platforms/trino.py               → trino
    #   platforms/velox.py               → velox
    platforms = [
        "athena",
        "azure_synapse",
        "bigquery",
        "clickhouse",
        "databend",
        "databricks",
        "doris",
        "fabric_dw",
        "firebolt",
        "lakesail",
        "pg_mooncake",
        "postgresql",
        "presto",
        "questdb",
        "redshift",
        "singlestore",
        "snowflake",
        "spark",
        "starrocks",
        "trino",
        "velox",
    ]
    return [_rec(p, None, None, "ddl_optimize", "sql", "REWRITTEN") for p in platforms]


def _execution_skip_records() -> list[BaselineRecord]:
    """Query skip decisions (execution_filter and dataframe_filter).

    Sources: get_platform_skip_queries / get_df_platform_skip_queries
    definition sites in the inventory.
    """
    return [
        # read_primitives/benchmark.py:704  - lakesail SQL skip
        _rec("lakesail", "read_primitives", None, "execution_filter", "sql", "SKIPPED"),
        # read_primitives/benchmark.py:719  - datafusion/polars DF skip
        _rec("datafusion", "read_primitives", None, "dataframe_filter", "dataframe", "SKIPPED"),
        _rec("polars", "read_primitives", None, "dataframe_filter", "dataframe", "SKIPPED"),
    ]


def _query_adapter_records() -> list[BaselineRecord]:
    """Per-platform query adapter and session-policy decisions.

    benchmark=None: these functions apply to all benchmarks on the platform.
    """
    return [
        # clickhouse/query_transformer.py:359,377
        #   add_query_settings / joined_subquery_requires_alias=0 session policy
        _rec("clickhouse", None, None, "query_adapter", "sql", "REWRITTEN"),
        # starrocks/workload.py:485
        #   _inject_missing_subquery_aliases - token-aware subquery alias injection
        _rec("starrocks", None, None, "query_adapter", "sql", "REWRITTEN"),
        # firebolt.py:1262  - SET enable_result_cache = false before each query
        _rec("firebolt", None, None, "query_adapter", "sql", "REWRITTEN"),
        # redshift.py:1701  - SET enable_result_cache_for_session TO ...
        _rec("redshift", None, None, "query_adapter", "sql", "REWRITTEN"),
    ]


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def generate() -> list[BaselineRecord]:
    """Generate all baseline records, deduplicated and sorted."""
    records: list[BaselineRecord] = []
    records.extend(_h2o_q9_records())
    records.extend(_vector_search_records())
    records.extend(_benchmark_gate_records())
    records.extend(_schema_emit_records())
    records.extend(_ddl_optimize_records())
    records.extend(_execution_skip_records())
    records.extend(_query_adapter_records())

    # Deduplicate by (platform, benchmark, query_id, phase, mode) - first wins.
    seen: set[tuple[str, str | None, str | None, str, str]] = set()
    unique: list[BaselineRecord] = []
    for r in records:
        key = (r.platform, r.benchmark, r.query_id, r.phase, r.mode)
        if key not in seen:
            seen.add(key)
            unique.append(r)

    unique.sort(
        key=lambda r: (
            r.platform,
            r.benchmark or "",
            r.query_id or "",
            r.phase,
            r.mode,
        )
    )
    return unique


def write_jsonl(records: list[BaselineRecord], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(asdict(record)) + "\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BenchBox sql_compat baseline snapshot tool")
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Output JSONL path (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a summary of emitted records after writing",
    )
    args = parser.parse_args(argv)

    output = Path(args.output)
    emit("Generating baseline records ...", stderr=True)

    records = generate()
    write_jsonl(records, output)
    emit(f"Wrote {len(records)} records to {output}", stderr=True)

    if args.summary:
        from collections import Counter

        phase_counts = Counter(r.phase for r in records)
        decision_counts = Counter(r.decision for r in records)
        emit("\nPhase distribution:")
        for phase, count in sorted(phase_counts.items()):
            emit(f"  {phase:20s} {count}")
        emit("\nDecision distribution:")
        for decision, count in sorted(decision_counts.items()):
            emit(f"  {decision:20s} {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
