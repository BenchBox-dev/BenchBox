#!/usr/bin/env bash
# On-demand smoke for catalog `expected_value_min/max` storage-size bounds.
# Generates a DuckDB SF=0.01 lineitem in-memory, runs each persist+merge
# cycle for the sketch ops with `sketch_bytes` validation queries, and
# prints TSV: tool / op_id / observed_bytes. If clickhouse-local is on
# PATH (or CLICKHOUSE_LOCAL_BIN is set), it also runs ClickHouse probes.
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
PY

CLICKHOUSE_LOCAL_BIN="${CLICKHOUSE_LOCAL_BIN:-}"
if [[ -z "${CLICKHOUSE_LOCAL_BIN}" ]]; then
  CLICKHOUSE_LOCAL_BIN="$(command -v clickhouse-local || true)"
fi

if [[ -z "${CLICKHOUSE_LOCAL_BIN}" ]]; then
  printf 'clickhouse-local\tsketch_query_*\tSKIP (clickhouse-local not on PATH; set CLICKHOUSE_LOCAL_BIN to run ClickHouse probes)\n' >>"${OUT}"
else
  "${CLICKHOUSE_LOCAL_BIN}" --multiquery --query "
    DROP TABLE IF EXISTS lineitem;
    CREATE TABLE lineitem
    (
      l_orderkey UInt64,
      l_shipdate Date,
      l_returnflag String,
      l_extendedprice Float64,
      l_shipmode String
    ) ENGINE = Memory;
    INSERT INTO lineitem
    SELECT
      number + 1,
      toDate('1992-01-01') + toIntervalDay(number % 2500),
      if(number % 3 = 0, 'A', if(number % 3 = 1, 'R', 'N')),
      toFloat64(1000 + (number % 100000)) / 100,
      concat('MODE', toString(number % 7))
    FROM numbers(15000);

    DROP TABLE IF EXISTS sketch_ops_daily_users;
    CREATE TABLE sketch_ops_daily_users
    (
      activity_date Date,
      region String,
      user_sketch AggregateFunction(uniq, UInt64)
    ) ENGINE = MergeTree() ORDER BY (activity_date, region);
    INSERT INTO sketch_ops_daily_users
    SELECT l_shipdate, l_returnflag, uniqState(l_orderkey)
    FROM lineitem GROUP BY l_shipdate, l_returnflag;
    SELECT 'clickhouse-local', 'sketch_query_theta_union_merge', length(toString(uniqMergeState(user_sketch)))
    FROM sketch_ops_daily_users;

    DROP TABLE IF EXISTS sketch_ops_kll_partitions;
    CREATE TABLE sketch_ops_kll_partitions
    (
      activity_date Date,
      region String,
      price_sketch AggregateFunction(quantileTDigest(0.5), Float64)
    ) ENGINE = MergeTree() ORDER BY (activity_date, region);
    INSERT INTO sketch_ops_kll_partitions
    SELECT l_shipdate, l_returnflag, quantileTDigestState(0.5)(l_extendedprice)
    FROM lineitem GROUP BY l_shipdate, l_returnflag;
    SELECT 'clickhouse-local', 'sketch_query_kll_quantiles_merge', length(toString(quantileTDigestMergeState(0.5)(price_sketch)))
    FROM sketch_ops_kll_partitions;

    DROP TABLE IF EXISTS sketch_ops_topk;
    CREATE TABLE sketch_ops_topk
    (
      shard_id Int32,
      topk_sketch AggregateFunction(topK(8), String)
    ) ENGINE = MergeTree() ORDER BY shard_id;
    INSERT INTO sketch_ops_topk
    SELECT toInt32(l_orderkey % 8), topKState(8)(l_shipmode)
    FROM lineitem GROUP BY l_orderkey % 8;
    SELECT 'clickhouse-local', 'sketch_query_topk_combine', length(toString(topKMergeState(8)(topk_sketch)))
    FROM sketch_ops_topk;
  " >>"${OUT}"
fi
