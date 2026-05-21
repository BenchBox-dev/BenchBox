"""TSBS DevOps DataFrame query implementations.

All 18 TSBS DevOps benchmark queries for Expression and Pandas families.

Tables: cpu, mem, disk, net, tags
Categories:
- Single Host (Q1-Q2): Time-series scan for one host
- Aggregation (Q3-Q4): Max CPU across all hosts
- GroupBy (Q5-Q6): Double GROUP BY (hostname + time bucket)
- Threshold (Q7-Q8, Q10, Q14): High/low metric detection with HAVING
- Memory (Q9): Per-host memory stats
- Disk (Q11-Q12): IOPS and latency with CASE WHEN
- Network (Q13-Q14): Throughput and error detection
- Combined (Q15): Cross-metric JOIN (cpu+mem)
- LastPoint (Q16): Subquery for latest metrics
- Tags (Q17-Q18): JOIN to tags dimension

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from typing import Any

from benchbox.core.dataframe.context import DataFrameContext
from benchbox.core.dataframe.query import DataFrameQuery, QueryCategory

from .parameters import get_parameters
from .registry import register_query

# =============================================================================
# Single Host (Q1-Q2)
# =============================================================================


def q1_expression_impl(ctx: DataFrameContext) -> Any:
    """Q1: Single host CPU over 12 hours."""
    params = get_parameters("Q1")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    hostname = params.get("hostname", "host_0")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter(
            (col("hostname") == lit(hostname)) & (col("time") >= lit(start_time)) & (col("time") < lit(end_time))
        )
        .select("time", "usage_user", "usage_system", "usage_idle")
        .sort("time")
    )


def q1_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q1: Single host CPU over 12 hours."""
    params = get_parameters("Q1")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    hostname = params.get("hostname", "host_0")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["hostname"] == hostname) & (cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    return filtered[["time", "usage_user", "usage_system", "usage_idle"]].sort_values("time")


def q2_expression_impl(ctx: DataFrameContext) -> Any:
    """Q2: Single host CPU over 1 hour (with iowait)."""
    params = get_parameters("Q2")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    hostname = params.get("hostname", "host_0")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter(
            (col("hostname") == lit(hostname)) & (col("time") >= lit(start_time)) & (col("time") < lit(end_time))
        )
        .select("time", "usage_user", "usage_system", "usage_idle", "usage_iowait")
        .sort("time")
    )


def q2_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q2: Single host CPU over 1 hour (with iowait)."""
    params = get_parameters("Q2")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    hostname = params.get("hostname", "host_0")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["hostname"] == hostname) & (cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    return filtered[["time", "usage_user", "usage_system", "usage_idle", "usage_iowait"]].sort_values("time")


# =============================================================================
# Aggregation (Q3-Q4)
# =============================================================================


def q3_expression_impl(ctx: DataFrameContext) -> Any:
    """Q3: Max CPU across all hosts - 1 hour."""
    params = get_parameters("Q3")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname")
        .agg(
            col("usage_user").max().alias("max_user"),
            col("usage_system").max().alias("max_system"),
        )
        .sort("max_user", descending=True)
    )


def q3_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q3: Max CPU across all hosts - 1 hour."""
    params = get_parameters("Q3")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    return (
        filtered.groupby(["hostname"], as_index=False)
        .agg(max_user=("usage_user", "max"), max_system=("usage_system", "max"))
        .sort_values("max_user", ascending=False)
    )


def q4_expression_impl(ctx: DataFrameContext) -> Any:
    """Q4: Max CPU across all hosts - 8 hours (with iowait)."""
    params = get_parameters("Q4")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname")
        .agg(
            col("usage_user").max().alias("max_user"),
            col("usage_system").max().alias("max_system"),
            col("usage_iowait").max().alias("max_iowait"),
        )
        .sort("max_user", descending=True)
    )


def q4_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q4: Max CPU across all hosts - 8 hours (with iowait)."""
    params = get_parameters("Q4")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    return (
        filtered.groupby(["hostname"], as_index=False)
        .agg(max_user=("usage_user", "max"), max_system=("usage_system", "max"), max_iowait=("usage_iowait", "max"))
        .sort_values("max_user", ascending=False)
    )


# =============================================================================
# GroupBy (Q5-Q6)
# =============================================================================


def q5_expression_impl(ctx: DataFrameContext) -> Any:
    """Q5: Double GROUP BY - hostname + minute bucket."""
    params = get_parameters("Q5")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .with_columns(col("time").dt.truncate("1m").alias("minute"))
        .group_by("hostname", "minute")
        .agg(
            col("usage_user").mean().alias("avg_user"),
            col("usage_user").max().alias("max_user"),
        )
        .sort(["hostname", "minute"])
    )


def q5_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q5: Double GROUP BY - hostname + minute bucket."""
    params = get_parameters("Q5")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)].copy()
    filtered["minute"] = filtered["time"].dt.floor("min")
    return (
        filtered.groupby(["hostname", "minute"], as_index=False)
        .agg(avg_user=("usage_user", "mean"), max_user=("usage_user", "max"))
        .sort_values(["hostname", "minute"])
    )


def q6_expression_impl(ctx: DataFrameContext) -> Any:
    """Q6: Double GROUP BY - hostname + second bucket (5-min window)."""
    params = get_parameters("Q6")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .with_columns(col("time").dt.truncate("1s").alias("second"))
        .group_by("hostname", "second")
        .agg(
            col("usage_user").mean().alias("avg_user"),
            col("usage_system").mean().alias("avg_system"),
        )
        .sort(["hostname", "second"])
    )


def q6_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q6: Double GROUP BY - hostname + second bucket (5-min window)."""
    params = get_parameters("Q6")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)].copy()
    filtered["second"] = filtered["time"].dt.floor("s")
    return (
        filtered.groupby(["hostname", "second"], as_index=False)
        .agg(avg_user=("usage_user", "mean"), avg_system=("usage_system", "mean"))
        .sort_values(["hostname", "second"])
    )


# =============================================================================
# Threshold (Q7-Q8)
# =============================================================================


def q7_expression_impl(ctx: DataFrameContext) -> Any:
    """Q7: Hosts with CPU > 90% - DISTINCT."""
    params = get_parameters("Q7")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("usage_user") > lit(90)) & (col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .select("hostname")
        .unique()
    )


def q7_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q7: Hosts with CPU > 90% - DISTINCT."""
    params = get_parameters("Q7")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["usage_user"] > 90) & (cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    return filtered[["hostname"]].drop_duplicates()


def q8_expression_impl(ctx: DataFrameContext) -> Any:
    """Q8: Hosts with sustained high CPU - HAVING COUNT > 10."""
    params = get_parameters("Q8")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("usage_user") > lit(90)) & (col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname")
        .agg(col("hostname").count().alias("high_cpu_count"))
        .filter(col("high_cpu_count") > lit(10))
        .sort("high_cpu_count", descending=True)
    )


def q8_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q8: Hosts with sustained high CPU - HAVING COUNT > 10."""
    params = get_parameters("Q8")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[(cpu["usage_user"] > 90) & (cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    grouped = filtered.groupby(["hostname"], as_index=False).agg(high_cpu_count=("hostname", "count"))
    return grouped[grouped["high_cpu_count"] > 10].sort_values("high_cpu_count", ascending=False)


# =============================================================================
# Memory (Q9-Q10)
# =============================================================================


def q9_expression_impl(ctx: DataFrameContext) -> Any:
    """Q9: Memory stats per host - AVG, MAX, MIN."""
    params = get_parameters("Q9")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    mem = ctx.get_table("mem")
    col = ctx.col
    lit = ctx.lit

    return (
        mem.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname")
        .agg(
            col("used_percent").mean().alias("avg_used_pct"),
            col("used_percent").max().alias("max_used_pct"),
            col("available").min().alias("min_available"),
        )
        .sort("avg_used_pct", descending=True)
    )


def q9_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q9: Memory stats per host - AVG, MAX, MIN."""
    params = get_parameters("Q9")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    mem = ctx.get_table("mem")
    filtered = mem[(mem["time"] >= start_time) & (mem["time"] < end_time)]
    return (
        filtered.groupby(["hostname"], as_index=False)
        .agg(
            avg_used_pct=("used_percent", "mean"),
            max_used_pct=("used_percent", "max"),
            min_available=("available", "min"),
        )
        .sort_values("avg_used_pct", ascending=False)
    )


def q10_expression_impl(ctx: DataFrameContext) -> Any:
    """Q10: Low memory hosts - HAVING MIN < 10."""
    params = get_parameters("Q10")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    mem = ctx.get_table("mem")
    col = ctx.col
    lit = ctx.lit

    return (
        mem.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname")
        .agg(col("available_percent").min().alias("min_avail_pct"))
        .filter(col("min_avail_pct") < lit(10))
        .sort("min_avail_pct")
    )


def q10_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q10: Low memory hosts - HAVING MIN < 10."""
    params = get_parameters("Q10")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    mem = ctx.get_table("mem")
    filtered = mem[(mem["time"] >= start_time) & (mem["time"] < end_time)]
    grouped = filtered.groupby(["hostname"], as_index=False).agg(min_avail_pct=("available_percent", "min"))
    return grouped[grouped["min_avail_pct"] < 10].sort_values("min_avail_pct")


# =============================================================================
# Disk (Q11-Q12)
# =============================================================================


def q11_expression_impl(ctx: DataFrameContext) -> Any:
    """Q11: Disk IOPS per host and device."""
    params = get_parameters("Q11")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    disk = ctx.get_table("disk")
    col = ctx.col
    lit = ctx.lit

    return (
        disk.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname", "device")
        .agg(
            col("reads_completed").sum().alias("total_reads"),
            col("writes_completed").sum().alias("total_writes"),
        )
        .sort("total_writes", descending=True)
    )


def q11_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q11: Disk IOPS per host and device."""
    params = get_parameters("Q11")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    disk = ctx.get_table("disk")
    filtered = disk[(disk["time"] >= start_time) & (disk["time"] < end_time)]
    return (
        filtered.groupby(["hostname", "device"], as_index=False)
        .agg(total_reads=("reads_completed", "sum"), total_writes=("writes_completed", "sum"))
        .sort_values("total_writes", ascending=False)
    )


def q12_expression_impl(ctx: DataFrameContext) -> Any:
    """Q12: Disk latency - CASE WHEN for safe division."""
    params = get_parameters("Q12")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    disk = ctx.get_table("disk")
    col = ctx.col
    lit = ctx.lit

    return (
        disk.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .with_columns(
            ctx.when(col("reads_completed") > lit(0))
            .then(col("read_time_ms").cast_float() / col("reads_completed").cast_float())
            .otherwise(lit(0.0))
            .alias("read_latency_ms"),
            ctx.when(col("writes_completed") > lit(0))
            .then(col("write_time_ms").cast_float() / col("writes_completed").cast_float())
            .otherwise(lit(0.0))
            .alias("write_latency_ms"),
        )
        .group_by("hostname", "device")
        .agg(
            col("read_latency_ms").mean().alias("avg_read_latency_ms"),
            col("write_latency_ms").mean().alias("avg_write_latency_ms"),
        )
        .sort("avg_write_latency_ms", descending=True)
    )


def q12_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q12: Disk latency - CASE WHEN for safe division."""
    import numpy as np

    params = get_parameters("Q12")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    disk = ctx.get_table("disk")
    filtered = disk[(disk["time"] >= start_time) & (disk["time"] < end_time)].copy()
    filtered["read_latency_ms"] = np.where(
        filtered["reads_completed"] > 0, filtered["read_time_ms"] / filtered["reads_completed"], 0.0
    )
    filtered["write_latency_ms"] = np.where(
        filtered["writes_completed"] > 0, filtered["write_time_ms"] / filtered["writes_completed"], 0.0
    )
    return (
        filtered.groupby(["hostname", "device"], as_index=False)
        .agg(avg_read_latency_ms=("read_latency_ms", "mean"), avg_write_latency_ms=("write_latency_ms", "mean"))
        .sort_values("avg_write_latency_ms", ascending=False)
    )


# =============================================================================
# Network (Q13-Q14)
# =============================================================================


def q13_expression_impl(ctx: DataFrameContext) -> Any:
    """Q13: Network throughput per host and interface."""
    params = get_parameters("Q13")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    net = ctx.get_table("net")
    col = ctx.col
    lit = ctx.lit

    return (
        net.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname", "interface")
        .agg(
            col("bytes_sent").sum().alias("total_bytes_sent"),
            col("bytes_recv").sum().alias("total_bytes_recv"),
        )
        .sort("total_bytes_sent", descending=True)
    )


def q13_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q13: Network throughput per host and interface."""
    params = get_parameters("Q13")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    net = ctx.get_table("net")
    filtered = net[(net["time"] >= start_time) & (net["time"] < end_time)]
    return (
        filtered.groupby(["hostname", "interface"], as_index=False)
        .agg(total_bytes_sent=("bytes_sent", "sum"), total_bytes_recv=("bytes_recv", "sum"))
        .sort_values("total_bytes_sent", ascending=False)
    )


def q14_expression_impl(ctx: DataFrameContext) -> Any:
    """Q14: Network errors - HAVING SUM > 0."""
    params = get_parameters("Q14")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    net = ctx.get_table("net")
    col = ctx.col
    lit = ctx.lit

    return (
        net.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .group_by("hostname", "interface")
        .agg(
            (col("err_in") + col("err_out")).sum().alias("total_errors"),
            (col("drop_in") + col("drop_out")).sum().alias("total_drops"),
        )
        .filter((col("total_errors") + col("total_drops")) > lit(0))
        .sort("total_errors", descending=True)
    )


def q14_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q14: Network errors - HAVING SUM > 0."""
    params = get_parameters("Q14")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    net = ctx.get_table("net")
    filtered = net[(net["time"] >= start_time) & (net["time"] < end_time)].copy()
    filtered["err_total"] = filtered["err_in"] + filtered["err_out"]
    filtered["drop_total"] = filtered["drop_in"] + filtered["drop_out"]
    grouped = filtered.groupby(["hostname", "interface"], as_index=False).agg(
        total_errors=("err_total", "sum"), total_drops=("drop_total", "sum")
    )
    return grouped[(grouped["total_errors"] + grouped["total_drops"]) > 0].sort_values("total_errors", ascending=False)


# =============================================================================
# Combined (Q15)
# =============================================================================


def q15_expression_impl(ctx: DataFrameContext) -> Any:
    """Q15: Resource utilization - JOIN cpu+mem on hostname and minute.

    Uses two-stage aggregation: mean per (hostname, minute), then mean of
    minute-level means per hostname.  This matches the TSBS benchmark
    specification for resource utilization, which defines per-host averages
    as the mean of per-interval averages (equal weight per time bucket,
    regardless of sample density within each bucket).
    """
    params = get_parameters("Q15")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    mem = ctx.get_table("mem")
    col = ctx.col
    lit = ctx.lit

    cpu_agg = (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .with_columns(col("time").dt.truncate("1m").alias("minute"))
        .group_by("hostname", "minute")
        .agg((col("usage_user") + col("usage_system")).mean().alias("avg_cpu_total"))
    )
    mem_agg = (
        mem.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .with_columns(col("time").dt.truncate("1m").alias("minute"))
        .group_by("hostname", "minute")
        .agg(col("used_percent").mean().alias("avg_mem_used"))
    )
    return (
        cpu_agg.join(mem_agg, on=["hostname", "minute"])
        .group_by("hostname")
        .agg(
            col("avg_cpu_total").mean().alias("avg_cpu_total"),
            col("avg_mem_used").mean().alias("avg_mem_used"),
        )
        .sort("avg_cpu_total", descending=True)
    )


def q15_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q15: Resource utilization - JOIN cpu+mem on hostname and minute.

    Uses two-stage aggregation: mean per (hostname, minute), then mean of
    minute-level means per hostname.  See expression_impl docstring for
    rationale.
    """
    params = get_parameters("Q15")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    mem = ctx.get_table("mem")

    cpu_f = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)].copy()
    cpu_f["minute"] = cpu_f["time"].dt.floor("min")
    cpu_f["cpu_total"] = cpu_f["usage_user"] + cpu_f["usage_system"]
    cpu_agg = cpu_f.groupby(["hostname", "minute"], as_index=False).agg(avg_cpu_total=("cpu_total", "mean"))

    mem_f = mem[(mem["time"] >= start_time) & (mem["time"] < end_time)].copy()
    mem_f["minute"] = mem_f["time"].dt.floor("min")
    mem_agg = mem_f.groupby(["hostname", "minute"], as_index=False).agg(avg_mem_used=("used_percent", "mean"))

    merged = cpu_agg.merge(mem_agg, on=["hostname", "minute"])
    return (
        merged.groupby(["hostname"], as_index=False)
        .agg(avg_cpu_total=("avg_cpu_total", "mean"), avg_mem_used=("avg_mem_used", "mean"))
        .sort_values("avg_cpu_total", ascending=False)
    )


# =============================================================================
# LastPoint (Q16)
# =============================================================================


def q16_expression_impl(ctx: DataFrameContext) -> Any:
    """Q16: Last point per host - subquery pattern."""
    params = get_parameters("Q16")
    start_time = params.get("start_time")

    cpu = ctx.get_table("cpu")
    col = ctx.col
    lit = ctx.lit

    # Get max time per hostname
    last_times = (
        cpu.filter(col("time") >= lit(start_time)).group_by("hostname").agg(col("time").max().alias("max_time"))
    )
    # Join back to get the full row
    return (
        cpu.join(last_times, on="hostname")
        .filter(col("time") == col("max_time"))
        .select("hostname", "time", "usage_user", "usage_system", "usage_idle")
        .sort("hostname")
    )


def q16_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q16: Last point per host - subquery pattern."""
    params = get_parameters("Q16")
    start_time = params.get("start_time")

    cpu = ctx.get_table("cpu")
    filtered = cpu[cpu["time"] >= start_time]
    last_times = filtered.groupby("hostname")["time"].max().reset_index().rename(columns={"time": "max_time"})
    merged = filtered.merge(last_times, on="hostname")
    result = merged[merged["time"] == merged["max_time"]]
    return result[["hostname", "time", "usage_user", "usage_system", "usage_idle"]].sort_values("hostname")


# =============================================================================
# Tags (Q17-Q18)
# =============================================================================


def q17_expression_impl(ctx: DataFrameContext) -> Any:
    """Q17: CPU metrics filtered by region via tags JOIN."""
    params = get_parameters("Q17")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    region = params.get("region", "us-east-1")

    cpu = ctx.get_table("cpu")
    tags = ctx.get_table("tags")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .join(tags, on="hostname")
        .filter(col("region") == lit(region))
        .group_by("region")
        .agg(
            col("usage_user").mean().alias("avg_cpu_user"),
            col("usage_system").mean().alias("avg_cpu_system"),
        )
    )


def q17_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q17: CPU metrics filtered by region via tags JOIN."""
    params = get_parameters("Q17")
    start_time = params.get("start_time")
    end_time = params.get("end_time")
    region = params.get("region", "us-east-1")

    cpu = ctx.get_table("cpu")
    tags = ctx.get_table("tags")
    filtered = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    merged = filtered.merge(tags, on="hostname")
    merged = merged[merged["region"] == region]
    return merged.groupby(["region"], as_index=False).agg(
        avg_cpu_user=("usage_user", "mean"), avg_cpu_system=("usage_system", "mean")
    )


def q18_expression_impl(ctx: DataFrameContext) -> Any:
    """Q18: CPU metrics grouped by service via tags JOIN."""
    params = get_parameters("Q18")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    tags = ctx.get_table("tags")
    col = ctx.col
    lit = ctx.lit

    return (
        cpu.filter((col("time") >= lit(start_time)) & (col("time") < lit(end_time)))
        .join(tags, on="hostname")
        .group_by("service")
        .agg(
            col("hostname").n_unique().alias("host_count"),
            (col("usage_user") + col("usage_system")).mean().alias("avg_cpu_total"),
        )
        .sort("avg_cpu_total", descending=True)
    )


def q18_pandas_impl(ctx: DataFrameContext) -> Any:
    """Q18: CPU metrics grouped by service via tags JOIN."""
    params = get_parameters("Q18")
    start_time = params.get("start_time")
    end_time = params.get("end_time")

    cpu = ctx.get_table("cpu")
    tags = ctx.get_table("tags")
    filtered = cpu[(cpu["time"] >= start_time) & (cpu["time"] < end_time)]
    merged = filtered.merge(tags, on="hostname")
    merged["cpu_total"] = merged["usage_user"] + merged["usage_system"]
    return (
        merged.groupby(["service"], as_index=False)
        .agg(host_count=("hostname", "nunique"), avg_cpu_total=("cpu_total", "mean"))
        .sort_values("avg_cpu_total", ascending=False)
    )


# =============================================================================
# Query Registration
# =============================================================================

_CATEGORY_CODES = {
    "AG": QueryCategory.AGGREGATE,
    "AN": QueryCategory.ANALYTICAL,
    "FI": QueryCategory.FILTER,
    "GB": QueryCategory.GROUP_BY,
    "JO": QueryCategory.JOIN,
    "PR": QueryCategory.PROJECTION,
    "SC": QueryCategory.SCAN,
    "SO": QueryCategory.SORT,
    "SQ": QueryCategory.SUBQUERY,
}

_QUERY_METADATA = """\
Q1|Single Host 12hr|CPU usage for a single host over 12 hours (time-series scan)|SC,FI,SO|q1
Q2|Single Host 1hr|CPU usage with iowait for a single host over 1 hour|SC,FI,SO|q2
Q3|CPU Max All 1hr|Max CPU user/system across all hosts in 1 hour window|FI,GB,AG|q3
Q4|CPU Max All 8hr|Max CPU user/system/iowait across all hosts in 8 hour window|FI,GB,AG|q4
Q5|Double GroupBy 1hr|CPU avg/max grouped by hostname and minute bucket using DATE_TRUNC|FI,GB,AG,AN|q5
Q6|Double GroupBy 5min|CPU avg grouped by hostname and second bucket (fine-grained)|FI,GB,AG,AN|q6
Q7|High CPU 1hr|DISTINCT hostnames with CPU usage > 90% in 1 hour|FI,PR|q7
Q8|High CPU 12hr Sustained|Hosts with sustained high CPU (>90%) using HAVING COUNT > 10|FI,GB,AG|q8
Q9|Memory by Host|Memory AVG/MAX used% and MIN available per host|FI,GB,AG|q9
Q10|Low Memory Hosts|Hosts with MIN available_percent < 10 using HAVING|FI,GB,AG|q10
Q11|Disk IOPS|Disk read/write IOPS per host and device|FI,GB,AG|q11
Q12|Disk Latency|Average disk latency with CASE WHEN safe division|FI,GB,AG,AN|q12
Q13|Network Throughput|Network bytes sent/received per host and interface|FI,GB,AG|q13
Q14|Network Errors|Network errors and drops with HAVING SUM > 0|FI,GB,AG|q14
Q15|Resource Utilization|Combined CPU+memory utilization via JOIN on hostname and minute|FI,JO,GB,AG|q15
Q16|Last Point per Host|Most recent CPU metrics per host using self-join subquery pattern|FI,JO,SQ|q16
Q17|Metrics by Region|CPU metrics filtered by region via tags JOIN|FI,JO,GB,AG|q17
Q18|Metrics by Service|CPU metrics grouped by service with host count via tags JOIN|FI,JO,GB,AG|q18
"""


def _impl_for(stem: str, family: str) -> Any:
    return globals()[f"{stem}_{family}_impl"]


def _register_all_queries() -> None:
    for query_id, query_name, description, category_codes, impl_stem in reader(
        _QUERY_METADATA.splitlines(), delimiter="|"
    ):
        register_query(
            DataFrameQuery(
                query_id=query_id,
                query_name=query_name,
                description=description,
                categories=[_CATEGORY_CODES[code] for code in category_codes.split(",")],
                expression_impl=_impl_for(impl_stem, "expression"),
                pandas_impl=_impl_for(impl_stem, "pandas"),
            )
        )


_register_all_queries()
