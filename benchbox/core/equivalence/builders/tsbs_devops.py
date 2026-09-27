"""TSBS DevOps cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell

# Builder-local SQL-slug to DataFrame-ID map. The SQL surface uses slug IDs
# (for example ``single-host-12-hr``) while the DataFrame surface uses
# ``Q<N>`` IDs. All 18 pairs are hand-authored: the display names differ in
# punctuation and unit phrasing (``12 Hours`` vs ``12hr``, ``5 Minutes`` vs
# ``5min``), so no mechanical join is reliable.
TSBS_DEVOPS_SQL_TO_DF_IDS: dict[str, str] = {
    "single-host-12-hr": "Q1",
    "single-host-1-hr": "Q2",
    "cpu-max-all-1-hr": "Q3",
    "cpu-max-all-8-hr": "Q4",
    "double-groupby-1-hr": "Q5",
    "double-groupby-5-min": "Q6",
    "high-cpu-1-hr": "Q7",
    "high-cpu-12-hr": "Q8",
    "mem-by-host-1-hr": "Q9",
    "low-memory-hosts": "Q10",
    "disk-iops-1-hr": "Q11",
    "disk-latency": "Q12",
    "net-throughput-1-hr": "Q13",
    "net-errors": "Q14",
    "resource-utilization": "Q15",
    "lastpoint": "Q16",
    "by-region": "Q17",
    "by-service": "Q18",
}

TSBS_DEVOPS_DF_TO_SQL_IDS: dict[str, str] = {df_id: sql_id for sql_id, df_id in TSBS_DEVOPS_SQL_TO_DF_IDS.items()}


def build_tsbs_devops_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TSBS DevOps data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark
    from benchbox.core.tsbs_devops.dataframe_queries import TSBS_DEVOPS_DATAFRAME_QUERIES
    from benchbox.core.tsbs_devops.schema import TSBS_DEVOPS_SCHEMA

    output_dir = Path(output_dir)
    benchmark = TSBSDevOpsBenchmark(scale_factor=scale_factor, output_dir=output_dir)
    benchmark.generate_data()

    connection = _load_duckdb_cell(benchmark, output_dir, list(TSBS_DEVOPS_SCHEMA.keys()), label="TSBS DevOps")
    sql_queries = benchmark.get_queries()
    queries = TSBS_DEVOPS_DATAFRAME_QUERIES
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=lambda query_id: queries.get_or_raise(TSBS_DEVOPS_SQL_TO_DF_IDS[query_id]),
        benchmark=benchmark,
        data_dir=output_dir,
    )
