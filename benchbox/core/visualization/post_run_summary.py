# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
import math
import re
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from benchbox.core.results.query_normalizer import format_query_id, normalize_query_id
from benchbox.core.visualization.ascii_api import (
    BarChart,
    BarData,
    ChartOptions,
    Histogram,
    HistogramBar,
    SummaryBox,
    SummaryStats,
    detect_terminal_capabilities,
)
from benchbox.core.visualization.ascii_runtime import _SUMMARY_QUERY_COUNT

if TYPE_CHECKING:
    from benchbox.core.results.models import BenchmarkResults

logger = logging.getLogger(__name__)

_SUMMARY_LABELS = {
    "primary_label": "Geo Mean",
    "secondary_label": "Median",
    "total_label": "Total",
    "count_label": "Queries",
}


@dataclass
class PostRunSummary:
    summary_box: str
    query_histogram: str
    charts: list[str] = field(default_factory=list)


def generate_post_run_summary(
    result: BenchmarkResults,
    *,
    theme: str = "dark",
    color: bool = True,
    unicode: bool = True,
    max_width: int | None = None,
) -> PostRunSummary:
    options = ChartOptions(
        theme=theme,
        use_color=color,
        use_unicode=unicode,
    )
    if max_width is not None:
        options.width = max_width

    successful = [
        q for q in (result.query_results or []) if q.get("status") == "SUCCESS" and q.get("execution_time_ms")
    ]

    if not successful:
        return PostRunSummary(summary_box="", query_histogram="", charts=[])

    query_timings: dict[str, list[float]] = {}
    query_display_ids: dict[str, str] = {}
    query_order: list[str] = []
    for q in successful:
        raw_query_id = q["query_id"]
        canonical_query_id = normalize_query_id(raw_query_id)
        if canonical_query_id not in query_timings:
            query_order.append(canonical_query_id)
            if re.fullmatch(r"\d+[A-Za-z]*", canonical_query_id):
                query_display_ids[canonical_query_id] = format_query_id(canonical_query_id, with_prefix=True)
            else:
                query_display_ids[canonical_query_id] = canonical_query_id
        query_timings.setdefault(canonical_query_id, []).append(q["execution_time_ms"])

    query_means: dict[str, float] = {qid: sum(timings) / len(timings) for qid, timings in query_timings.items()}

    mean_values = [query_means[qid] for qid in query_order]

    log_sum = sum(math.log(max(t, 0.001)) for t in mean_values)
    geo_mean = math.exp(log_sum / len(mean_values))

    total_time = sum(mean_values)
    median_time = statistics.median(mean_values)

    sorted_queries = sorted(query_order, key=lambda qid: query_means[qid])
    best = [(query_display_ids[qid], query_means[qid]) for qid in sorted_queries[:_SUMMARY_QUERY_COUNT]]
    worst = [(query_display_ids[qid], query_means[qid]) for qid in sorted_queries[-_SUMMARY_QUERY_COUNT:]]
    worst.reverse()

    title = f"{result.benchmark_name} on {result.platform} (SF {result.scale_factor})"

    environment = _extract_environment(result.system_profile)
    run_cfg = (result.execution_metadata or {}).get("run_config") or {}
    platform_config = _extract_platform_config(result.platform_info, run_cfg)

    stats = SummaryStats(
        title=title,
        primary_value=geo_mean,
        secondary_value=median_time,
        total_value=total_time,
        num_items=len(query_order),
        best_items=best,
        worst_items=worst,
        environment=environment,
        platform_config=platform_config,
        **_SUMMARY_LABELS,
    )

    summary_box_chart = SummaryBox(stats, options=options)
    summary_box_text = summary_box_chart.render()

    best_qid = sorted_queries[0] if sorted_queries else None
    worst_qid = sorted_queries[-1] if sorted_queries else None
    display_ids = [query_display_ids[qid] for qid in query_order]
    use_horizontal = _should_use_horizontal(display_ids)

    if use_horizontal:
        histogram_text = _render_horizontal_bars(
            query_order, query_display_ids, query_means, best_qid, worst_qid, options
        )
    else:
        histogram_bars = [
            HistogramBar(
                label=query_display_ids[qid],
                value=query_means[qid],
                is_best=(qid == best_qid),
                is_worst=(qid == worst_qid),
            )
            for qid in query_order
        ]
        histogram_chart = Histogram(
            data=histogram_bars,
            title="Query Latency",
            y_label="Execution Time (ms)",
            max_per_chart=_max_vertical_bars_for_labels(display_ids, options),
            options=options,
        )
        histogram_text = histogram_chart.render()

    charts = [summary_box_text, histogram_text]

    return PostRunSummary(
        summary_box=summary_box_text,
        query_histogram=histogram_text,
        charts=charts,
    )


_HORIZONTAL_LABEL_THRESHOLD = 6
_VERTICAL_Y_AXIS_WIDTH = 8
_VERTICAL_AXIS_PADDING = 2
_VERTICAL_LABEL_GAP = 1
_VERTICAL_MIN_BARS_PER_CHART = 5


def _should_use_horizontal(display_ids: list[str]) -> bool:
    if not display_ids:
        return False
    median_len = statistics.median(len(qid) for qid in display_ids)
    return median_len > _HORIZONTAL_LABEL_THRESHOLD


def _max_vertical_bars_for_labels(display_ids: list[str], options: ChartOptions) -> int:
    if not display_ids:
        return Histogram.DEFAULT_MAX_BARS

    if options.width is None and options._capabilities is None:
        options._capabilities = detect_terminal_capabilities()

    width = options.get_effective_width()
    bar_area_width = width - _VERTICAL_Y_AXIS_WIDTH - _VERTICAL_AXIS_PADDING
    longest_label = max(len(label) for label in display_ids)
    max_bars = bar_area_width // (longest_label + _VERTICAL_LABEL_GAP)
    if len(display_ids) <= max_bars:
        return Histogram.DEFAULT_MAX_BARS
    return max(_VERTICAL_MIN_BARS_PER_CHART, min(Histogram.DEFAULT_MAX_BARS, max_bars))


def _render_horizontal_bars(
    query_order: list[str],
    query_display_ids: dict[str, str],
    query_means: dict[str, float],
    best_qid: str | None,
    worst_qid: str | None,
    options: ChartOptions,
) -> str:
    bars = [
        BarData(
            label=query_display_ids[qid],
            value=query_means[qid],
            is_best=(qid == best_qid),
            is_worst=(qid == worst_qid),
        )
        for qid in query_order
    ]
    chart = BarChart(
        data=bars,
        title="Query Latency",
        metric_label="ms",
        sort_by="value",
        options=options,
    )
    return chart.render()


def _extract_environment(
    system_profile: dict | None,
) -> dict[str, str] | None:
    if not system_profile:
        return None

    env: dict[str, str] = {}

    os_name = system_profile.get("os_name") or system_profile.get("os_type", "")
    os_version = system_profile.get("os_version") or system_profile.get("os_release", "")
    if os_name:
        env["OS"] = f"{os_name} {os_version}".strip()

    python_version = system_profile.get("python_version", "")
    if python_version:
        env["Python"] = python_version

    cpus = system_profile.get("cpu_cores_logical") or system_profile.get("cpu_cores") or system_profile.get("cpu_count")
    arch = system_profile.get("architecture", "")
    if cpus:
        env["CPUs"] = f"{cpus} ({arch})" if arch else str(cpus)

    mem_gb = (
        system_profile.get("memory_total_gb")
        or system_profile.get("total_memory_gb")
        or system_profile.get("memory_gb")
    )
    if mem_gb is not None:
        env["Memory"] = f"{mem_gb:.0f} GB"

    return env if env else None


def _extract_platform_config(
    platform_info: dict | None,
    run_cfg: dict,
) -> dict[str, str] | None:
    cfg: dict[str, str] = {}

    if platform_info and isinstance(platform_info, dict):
        version = (
            platform_info.get("platform_version")
            or platform_info.get("version")
            or platform_info.get("driver_version_actual")
        )
        if version:
            platform_name = platform_info.get("platform_name") or platform_info.get("name", "")
            cfg["Driver"] = f"{platform_name} {version}".strip() if platform_name else str(version)

    table_mode = run_cfg.get("table_mode")
    if table_mode and table_mode != "native":
        external_format = run_cfg.get("external_format")
        if external_format:
            cfg["Tables"] = f"{table_mode.capitalize()} ({external_format.capitalize()})"
        else:
            cfg["Tables"] = table_mode.capitalize()

    table_format = run_cfg.get("table_format")
    if table_format:
        tf_value = str(table_format).capitalize()
        table_format_compression = run_cfg.get("table_format_compression")
        if table_format_compression:
            tf_value = f"{tf_value} ({table_format_compression})"
        cfg["Table Format"] = tf_value

    tuning_mode = run_cfg.get("tuning_mode")
    if tuning_mode:
        cfg["Tuning"] = tuning_mode.capitalize()

    return cfg if cfg else None
