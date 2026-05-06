#!/usr/bin/env bash
# On-demand smoke for catalog `expected_value_min/max` storage-size bounds.
# Generates a DuckDB SF=0.01 lineitem in-memory, runs each persist+merge
# cycle for the sketch ops with `sketch_bytes` validation queries, and
# prints TSV: tool / op_id / observed_bytes.
#
# Not run in CI -- this is the on-demand sweep tool referenced by
# `_project/handoffs/catalog-verified-comment-sweep-*.md`. Run when:
#   - a tool version pin moves (DuckDB, datasketches extension, etc.)
#   - a catalog `expected_value_min/max` bound is touched
#   - quarterly, to catch silent drift
#
# Usage: scripts/sketch_storage_smoke.sh [output.tsv]
# Default output: stdout

set -euo pipefail

OUT="${1:-/dev/stdout}"

uv run -- python - <<'PY' >"${OUT}"
import duckdb

con = duckdb.connect(":memory:")
con.execute("INSTALL tpch")
con.execute("LOAD tpch")
con.execute("CALL dbgen(sf=0.01)")

try:
    con.execute("INSTALL datasketches FROM community")
    con.execute("LOAD datasketches")
    datasketches_ok = True
except duckdb.Error:
    datasketches_ok = False

print("tool\top_id\tobserved_bytes")

if datasketches_ok:
    for k_label, k in (("kll_k100", 100), ("kll_k1000", 1000)):
        con.execute(
            f"""
            CREATE OR REPLACE TABLE sketch_ops_kll_partitions AS
            SELECT
                l_shipdate, l_returnflag,
                datasketch_kll({k}, l_extendedprice::DOUBLE) AS price_sketch
            FROM lineitem
            GROUP BY l_shipdate, l_returnflag
            """
        )
        bytes_observed = con.execute(
            f"SELECT octet_length(datasketch_kll({k}, price_sketch::sketch_kll_double)) "
            "FROM sketch_ops_kll_partitions"
        ).fetchone()[0]
        print(f"duckdb\tsketch_query_kll_quantiles_merge[{k_label}]\t{bytes_observed}")
else:
    print("duckdb\tsketch_query_kll_quantiles_merge\tSKIP (datasketches extension unavailable)")

# ClickHouse-local probe is parked behind a stub; re-running ClickHouse
# requires a live `clickhouse-local` binary on PATH (not bundled with
# BenchBox's CI runner). Document the blocker so the next sweep author
# knows to add it.
print("clickhouse-local\tsketch_query_*\tSKIP (clickhouse-local not on PATH; see TODO catalog-empirical-claim-durability)")
PY
