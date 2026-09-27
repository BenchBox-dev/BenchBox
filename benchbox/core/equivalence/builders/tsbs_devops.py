"""TSBS DevOps cross-surface gate builder."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

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


# Fixed query seed so SQL windows are deterministic across gate runs.
TSBS_DEVOPS_GATE_SEED = 42


def _extract_sql_windows(sql_queries: dict[str, str]) -> dict[str, dict[str, Any]]:
    """Parse each rendered SQL query's window and host into DF overrides."""
    overrides: dict[str, dict[str, Any]] = {}
    for sql_id, sql in sql_queries.items():
        df_id = TSBS_DEVOPS_SQL_TO_DF_IDS[sql_id]
        times = re.findall(r"'(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})'", sql)
        params: dict[str, Any] = {}
        if len(times) >= 2:
            params["start_time"] = datetime.fromisoformat(times[0])
            params["end_time"] = datetime.fromisoformat(times[1])
        host = re.search(r"hostname = '([^']+)'", sql)
        if host:
            params["hostname"] = host.group(1)
        region = re.search(r"(?:t\.region|region) = '([^']+)'", sql)
        if region:
            params["region"] = region.group(1)
        if params:
            overrides[df_id] = params
    return overrides


def build_tsbs_devops_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TSBS DevOps data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark
    from benchbox.core.tsbs_devops.dataframe_queries import TSBS_DEVOPS_DATAFRAME_QUERIES
    from benchbox.core.tsbs_devops.dataframe_queries.parameters import set_parameter_overrides
    from benchbox.core.tsbs_devops.schema import TSBS_DEVOPS_SCHEMA

    output_dir = Path(output_dir)
    benchmark = TSBSDevOpsBenchmark(scale_factor=scale_factor, output_dir=output_dir, seed=TSBS_DEVOPS_GATE_SEED)
    benchmark.generate_data()

    connection = _load_duckdb_cell(benchmark, output_dir, list(TSBS_DEVOPS_SCHEMA.keys()), label="TSBS DevOps")
    sql_queries = benchmark.get_queries()
    # Align the DF surface with the seeded SQL windows before wiring queries.
    set_parameter_overrides(_extract_sql_windows(sql_queries))
    queries = TSBS_DEVOPS_DATAFRAME_QUERIES
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=lambda query_id: queries.get_or_raise(TSBS_DEVOPS_SQL_TO_DF_IDS[query_id]),
        benchmark=benchmark,
        data_dir=output_dir,
    )
