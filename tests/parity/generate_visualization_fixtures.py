"""
Generate visualization parity fixtures for CLI↔explorer contract tests.

Each fixture file captures the canonical Python computation for one chart math
helper and is checked into git as the contract. The Vitest parity suite
(`results-explorer/src/__tests__/parity/chartMath.parity.test.ts`) loads these
files and asserts that the TypeScript helpers in `chartMath.ts` produce
byte-identical results (within 1e-9 for floats).

Usage
-----
Generate (overwrites existing fixtures):
    uv run python tests/parity/generate_visualization_fixtures.py

Or run via Make:
    make parity-fixtures   # regenerate and overwrite
    make parity-check      # regenerate into tmpdir, fail if diff

Each function here MUST mirror the TypeScript counterpart exactly:
  Python source              → TS source
  -------------------------------------------------------
  colorForCell               → results-explorer/src/lib/chartMath.ts
  lightnessForCell           → results-explorer/src/lib/chartMath.ts
  speedupRatio               → results-explorer/src/lib/chartMath.ts
  deltaPct                   → results-explorer/src/lib/chartMath.ts
  sortByMagnitudeDesc        → results-explorer/src/lib/chartMath.ts
  perQuerySpeedup            → results-explorer/src/lib/chartMath.ts
  geomeanMs                  → results-explorer/src/lib/chartMath.ts
  computePercentile          → results-explorer/src/lib/chartMath.ts
  computeBoxStats            → results-explorer/src/lib/chartMath.ts
  computeECDFPoints          → results-explorer/src/lib/chartMath.ts
  computeRankTable           → results-explorer/src/lib/chartMath.ts
  (also: _display_geomean_ms, _compute_percentile in
   _project/scripts/explorer_pipeline/transformer.py)
"""

from __future__ import annotations

import json
import math
import pathlib
import sys
from typing import Any

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Python reference implementations (must match chartMath.ts exactly)
# ---------------------------------------------------------------------------


def color_for_cell(ms: float | None, min_in_col: float | None) -> int | None:
    """
    HSL hue for a heatmap cell.

    log10(ratio) → hue mapped 120 (green/fastest) → 0 (red/10× slower).
    Mirrors: results-explorer/src/lib/chartMath.ts colorForCell
    """
    if ms is None or min_in_col is None or min_in_col <= 0 or ms <= 0:
        return None
    ratio = max(1.0, min(10.0, ms / min_in_col))
    t = math.log10(ratio)
    return round(120 * (1 - t))


def lightness_for_cell(ms: float | None, min_in_col: float | None) -> str | None:
    """
    Grayscale lightness percentage for high-contrast mode.

    Returns "95%" (fastest) → "25%" (10× slower), or None for invalid inputs.
    Mirrors: results-explorer/src/lib/chartMath.ts lightnessForCell
    """
    if ms is None or min_in_col is None or min_in_col <= 0 or ms <= 0:
        return None
    ratio = max(1.0, min(10.0, ms / min_in_col))
    t = math.log10(ratio)
    return f"{round(95 - 70 * t)}%"


def speedup_ratio(baseline_ms: float | None, this_ms: float | None) -> float | None:
    """
    Per-baseline speedup: baseline_ms / this_ms.

    > 1: this result is faster; < 1: slower; = 1: same.
    Mirrors: results-explorer/src/lib/chartMath.ts speedupRatio
    """
    if baseline_ms is None or this_ms is None or baseline_ms <= 0 or this_ms <= 0:
        return None
    return baseline_ms / this_ms


def vs_slowest_ratio(this_ms: float | None, slowest_ms: float | None) -> float | None:
    """
    Slowest-relative ratio: slowest_ms / this_ms.

    > 1: this result is faster than slowest; = 1: this IS the slowest.
    Mirrors: results-explorer/src/lib/chartMath.ts vsSlowestRatio
    """
    if this_ms is None or slowest_ms is None or this_ms <= 0 or slowest_ms <= 0:
        return None
    return slowest_ms / this_ms


def delta_pct(this_ms: float | None, baseline_ms: float | None) -> float | None:
    """
    Percent change of this_ms relative to baseline_ms.

    (this_ms - baseline_ms) / baseline_ms * 100
    Negative = faster; positive = slower.
    Mirrors: results-explorer/src/lib/chartMath.ts deltaPct
    """
    if this_ms is None or baseline_ms is None or baseline_ms <= 0 or this_ms <= 0:
        return None
    return ((this_ms - baseline_ms) / baseline_ms) * 100


def sort_by_magnitude_desc(groups: list[tuple[str, list[dict[str, Any]]]]) -> list[tuple[str, list[dict[str, Any]]]]:
    """
    Sort query groups by max(|deltaPct|) descending.

    Mirrors: results-explorer/src/lib/chartMath.ts sortByMagnitudeDesc
    Note: Python's sort is stable; JS Array.prototype.sort is also stable in
    ES2019+. Both are guaranteed stable so tie-breaking order is deterministic.
    """
    return sorted(
        groups,
        key=lambda g: max(abs(e["deltaPct"]) for e in g[1]),
        reverse=True,
    )


def per_query_speedup(valid_ms: list[float]) -> float | None:
    """
    Within-query spread: slowest / fastest across a set of results.

    Always >= 1 when valid. Returns None for empty or all-zero inputs.
    Mirrors: results-explorer/src/lib/chartMath.ts perQuerySpeedup
    """
    if not valid_ms:
        return None
    fastest = min(valid_ms)
    slowest = max(valid_ms)
    if fastest <= 0:
        return None
    return slowest / fastest


def geomean_ms(values: list[float | None]) -> float | None:
    """
    Geometric mean of non-null positive values.

    exp(mean(log(v) for v in positives))
    Mirrors: results-explorer/src/lib/chartMath.ts geomeanMs
    Also matches: _project/scripts/explorer_pipeline/transformer.py _display_geomean_ms
    """
    valid = [v for v in values if v is not None and v > 0]
    if not valid:
        return None
    return math.exp(sum(math.log(v) for v in valid) / len(valid))


def compute_percentile(values: list[float], p: float) -> float | None:
    """
    Linear-interpolation percentile.

    Mirrors: results-explorer/src/lib/chartMath.ts computePercentile
             (and textcharts.percentile_ladder.compute_percentile)
    """
    if not values:
        return None
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    k = (p / 100) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_vals[int(round(k))]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def platform_percentile_stats(
    display_ms_values: list[float],
) -> dict[str, float | None] | None:
    """
    PercentileStats from a list of display_ms values.

    Mirrors: _project/scripts/explorer_pipeline/transformer._platform_percentile_stats
    """
    positive = [v for v in display_ms_values if v is not None and v > 0]
    if not positive:
        return None
    return {
        "p50": compute_percentile(positive, 50),
        "p90": compute_percentile(positive, 90),
        "p95": compute_percentile(positive, 95),
        "p99": compute_percentile(positive, 99),
    }


def compute_box_stats(values: list[float | None]) -> dict[str, float | None] | None:
    """
    Five-number summary {min, q1, median, q3, max}.

    NOTE: the explorer deliberately reports raw min/max, not IQR-whiskered
    extremes - this is a conscious divergence from
    textcharts.box_plot.compute_quartiles, which returns whisker_low/whisker_high
    and a separate outliers list. The explorer visualization shows the true
    data extent; outliers are not collapsed into the whiskers.

    Mirrors: results-explorer/src/lib/chartMath.ts computeBoxStats
    """
    valid = [v for v in values if v is not None and v > 0 and math.isfinite(v)]
    if not valid:
        return None
    sorted_vals = sorted(valid)
    return {
        "min": sorted_vals[0],
        "q1": compute_percentile(sorted_vals, 25),
        "median": compute_percentile(sorted_vals, 50),
        "q3": compute_percentile(sorted_vals, 75),
        "max": sorted_vals[-1],
    }


def compute_rank_table(
    query_ids: list[str],
    timings_by_platform: list[dict[str, float | None]],
) -> dict[str, list[int | None]]:
    """
    Per-query ordinal ranks across platforms (1 = fastest).

    Standard competition ranking: ties share the lower rank, the rank after a
    tie group jumps by the group size (e.g. 1, 1, 3).  Null/zero/negative
    timings receive rank None.

    Mirrors: results-explorer/src/lib/chartMath.ts computeRankTable.
    Python's `sorted` and JS's `Array.sort` are both stable (CPython / ES2019+),
    so relative order of equal-ms entries matches on both sides.
    """
    ranks: dict[str, list[int | None]] = {}
    n_platforms = len(timings_by_platform)
    for qid in query_ids:
        valid: list[tuple[int, float]] = []
        for i, row in enumerate(timings_by_platform):
            ms = row.get(qid)
            if ms is not None and ms > 0:
                valid.append((i, ms))
        valid.sort(key=lambda e: e[1])
        rank_arr: list[int | None] = [None] * n_platforms
        r = 1
        for j, (i, ms) in enumerate(valid):
            if j > 0 and ms != valid[j - 1][1]:
                r = j + 1
            rank_arr[i] = r
        ranks[qid] = rank_arr
    return ranks


def compute_ecdf_points(values: list[float | None]) -> list[dict[str, float]]:
    """
    Empirical CDF points: for n sorted positive values, yield
    [{x: xi, y: (i+1)/n * 100}].

    Mirrors: results-explorer/src/lib/chartMath.ts computeECDFPoints
             (and textcharts.cdf_chart ECDF plotting logic)
    """
    valid = [v for v in values if v is not None and v > 0 and math.isfinite(v)]
    if not valid:
        return []
    sorted_vals = sorted(valid)
    n = len(sorted_vals)
    return [{"x": x, "y": ((i + 1) / n) * 100} for i, x in enumerate(sorted_vals)]


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _write_fixture(name: str, cases: list[dict[str, Any]]) -> None:
    fixture = {"chart": name, "version": 1, "cases": cases}
    dest = FIXTURES_DIR / f"{name}.json"
    dest.write_text(json.dumps(fixture, indent=2) + "\n")
    try:
        label = dest.relative_to(pathlib.Path(__file__).parent.parent.parent)
    except ValueError:
        label = dest
    print(f"  wrote {label}")


def build_heatmap_color_fixture() -> None:
    cases = [
        {
            "id": "fastest_in_col",
            "input": {"ms": 100.0, "minInCol": 100.0},
            "expected": {"hue": color_for_cell(100.0, 100.0)},
        },
        {
            "id": "ten_x_slower",
            "input": {"ms": 1000.0, "minInCol": 100.0},
            "expected": {"hue": color_for_cell(1000.0, 100.0)},
        },
        {
            "id": "two_x_slower",
            "input": {"ms": 200.0, "minInCol": 100.0},
            "expected": {"hue": color_for_cell(200.0, 100.0)},
        },
        {
            "id": "outlier_clamped_to_ten_x",
            "input": {"ms": 5000.0, "minInCol": 100.0},
            "expected": {"hue": color_for_cell(5000.0, 100.0)},
        },
        {
            "id": "null_ms",
            "input": {"ms": None, "minInCol": 100.0},
            "expected": {"hue": color_for_cell(None, 100.0)},
        },
        {
            "id": "null_min_in_col",
            "input": {"ms": 100.0, "minInCol": None},
            "expected": {"hue": color_for_cell(100.0, None)},
        },
        {
            "id": "zero_min_in_col",
            "input": {"ms": 100.0, "minInCol": 0.0},
            "expected": {"hue": color_for_cell(100.0, 0.0)},
        },
        {
            "id": "sub_ms_realistic",
            "input": {"ms": 0.5, "minInCol": 0.1},
            "expected": {"hue": color_for_cell(0.5, 0.1)},
        },
    ]
    _write_fixture("heatmap_color", cases)


def build_lightness_for_cell_fixture() -> None:
    cases = [
        {
            "id": "fastest_in_col",
            "input": {"ms": 100.0, "minInCol": 100.0},
            "expected": {"lightness": lightness_for_cell(100.0, 100.0)},
        },
        {
            "id": "ten_x_slower",
            "input": {"ms": 1000.0, "minInCol": 100.0},
            "expected": {"lightness": lightness_for_cell(1000.0, 100.0)},
        },
        {
            "id": "two_x_slower",
            "input": {"ms": 200.0, "minInCol": 100.0},
            "expected": {"lightness": lightness_for_cell(200.0, 100.0)},
        },
        {
            "id": "null_ms",
            "input": {"ms": None, "minInCol": 100.0},
            "expected": {"lightness": lightness_for_cell(None, 100.0)},
        },
        {
            "id": "zero_ms",
            "input": {"ms": 0.0, "minInCol": 100.0},
            "expected": {"lightness": lightness_for_cell(0.0, 100.0)},
        },
    ]
    _write_fixture("lightness_for_cell", cases)


def build_speedup_ratio_fixture() -> None:
    cases = [
        {
            "id": "identical",
            "input": {"baselineMs": 100.0, "thisMs": 100.0},
            "expected": {"speedup": speedup_ratio(100.0, 100.0)},
        },
        {
            "id": "two_x_faster",
            "input": {"baselineMs": 200.0, "thisMs": 100.0},
            "expected": {"speedup": speedup_ratio(200.0, 100.0)},
        },
        {
            "id": "two_x_slower",
            "input": {"baselineMs": 100.0, "thisMs": 200.0},
            "expected": {"speedup": speedup_ratio(100.0, 200.0)},
        },
        {
            "id": "null_baseline",
            "input": {"baselineMs": None, "thisMs": 100.0},
            "expected": {"speedup": speedup_ratio(None, 100.0)},
        },
        {
            "id": "null_this",
            "input": {"baselineMs": 100.0, "thisMs": None},
            "expected": {"speedup": speedup_ratio(100.0, None)},
        },
        {
            "id": "zero_baseline",
            "input": {"baselineMs": 0.0, "thisMs": 100.0},
            "expected": {"speedup": speedup_ratio(0.0, 100.0)},
        },
        {
            "id": "sub_ms_precision",
            "input": {"baselineMs": 1.234567, "thisMs": 0.987654},
            "expected": {"speedup": speedup_ratio(1.234567, 0.987654)},
        },
    ]
    _write_fixture("speedup_ratio", cases)


def build_vs_slowest_ratio_fixture() -> None:
    cases = [
        {
            "id": "identical_to_slowest",
            "input": {"thisMs": 100.0, "slowestMs": 100.0},
            "expected": {"speedup": vs_slowest_ratio(100.0, 100.0)},
        },
        {
            "id": "twice_faster_than_slowest",
            "input": {"thisMs": 50.0, "slowestMs": 100.0},
            "expected": {"speedup": vs_slowest_ratio(50.0, 100.0)},
        },
        {
            "id": "null_this",
            "input": {"thisMs": None, "slowestMs": 100.0},
            "expected": {"speedup": vs_slowest_ratio(None, 100.0)},
        },
        {
            "id": "null_slowest",
            "input": {"thisMs": 100.0, "slowestMs": None},
            "expected": {"speedup": vs_slowest_ratio(100.0, None)},
        },
        {
            "id": "zero_this",
            "input": {"thisMs": 0.0, "slowestMs": 100.0},
            "expected": {"speedup": vs_slowest_ratio(0.0, 100.0)},
        },
        {
            "id": "sub_ms_precision",
            "input": {"thisMs": 0.987654, "slowestMs": 1.234567},
            "expected": {"speedup": vs_slowest_ratio(0.987654, 1.234567)},
        },
    ]
    _write_fixture("vs_slowest_ratio", cases)


def build_delta_pct_fixture() -> None:
    cases = [
        {
            "id": "identical",
            "input": {"thisMs": 100.0, "baselineMs": 100.0},
            "expected": {"deltaPct": delta_pct(100.0, 100.0)},
        },
        {
            "id": "fifty_pct_faster",
            "input": {"thisMs": 50.0, "baselineMs": 100.0},
            "expected": {"deltaPct": delta_pct(50.0, 100.0)},
        },
        {
            "id": "one_hundred_pct_slower",
            "input": {"thisMs": 200.0, "baselineMs": 100.0},
            "expected": {"deltaPct": delta_pct(200.0, 100.0)},
        },
        {
            "id": "extreme_regression_300pct",
            "input": {"thisMs": 400.0, "baselineMs": 100.0},
            "expected": {"deltaPct": delta_pct(400.0, 100.0)},
        },
        {
            "id": "null_baseline",
            "input": {"thisMs": 100.0, "baselineMs": None},
            "expected": {"deltaPct": delta_pct(100.0, None)},
        },
        {
            "id": "null_this",
            "input": {"thisMs": None, "baselineMs": 100.0},
            "expected": {"deltaPct": delta_pct(None, 100.0)},
        },
        {
            "id": "sub_ms_precision",
            "input": {"thisMs": 1.111, "baselineMs": 1.0},
            "expected": {"deltaPct": delta_pct(1.111, 1.0)},
        },
    ]
    _write_fixture("delta_pct", cases)


def build_sort_by_magnitude_fixture() -> None:
    """Fixture for sortByMagnitudeDesc - covers stable sort and ties."""
    groups_input = [
        ("Q1", [{"deltaPct": 10.0}, {"deltaPct": -5.0}]),
        ("Q2", [{"deltaPct": 50.0}]),
        ("Q3", [{"deltaPct": -30.0}, {"deltaPct": 20.0}]),
        ("Q4", [{"deltaPct": 1.0}]),
    ]
    sorted_groups = sort_by_magnitude_desc(groups_input)
    # Encode as serialisable form
    cases = [
        {
            "id": "four_queries",
            "input": {"groups": [{"queryId": qid, "entries": entries} for qid, entries in groups_input]},
            "expected": {"sortedQueryIds": [qid for qid, _ in sorted_groups]},
        },
        {
            "id": "single_query",
            "input": {"groups": [{"queryId": "Q1", "entries": [{"deltaPct": 42.0}]}]},
            "expected": {"sortedQueryIds": ["Q1"]},
        },
        {
            "id": "tie_preserves_stable_order",
            "input": {
                "groups": [
                    {"queryId": "A", "entries": [{"deltaPct": 20.0}]},
                    {"queryId": "B", "entries": [{"deltaPct": -20.0}]},
                ]
            },
            "expected": {
                "sortedQueryIds": [
                    qid
                    for qid, _ in sort_by_magnitude_desc(
                        [
                            ("A", [{"deltaPct": 20.0}]),
                            ("B", [{"deltaPct": -20.0}]),
                        ]
                    )
                ]
            },
        },
    ]
    _write_fixture("sort_by_magnitude_desc", cases)


def build_per_query_speedup_fixture() -> None:
    cases = [
        {
            "id": "two_results_two_x_spread",
            "input": {"validMs": [100.0, 200.0]},
            "expected": {"speedup": per_query_speedup([100.0, 200.0])},
        },
        {
            "id": "three_results",
            "input": {"validMs": [50.0, 100.0, 300.0]},
            "expected": {"speedup": per_query_speedup([50.0, 100.0, 300.0])},
        },
        {
            "id": "all_identical",
            "input": {"validMs": [100.0, 100.0, 100.0]},
            "expected": {"speedup": per_query_speedup([100.0, 100.0, 100.0])},
        },
        {
            "id": "single_result",
            "input": {"validMs": [100.0]},
            "expected": {"speedup": per_query_speedup([100.0])},
        },
        {
            "id": "empty",
            "input": {"validMs": []},
            "expected": {"speedup": per_query_speedup([])},
        },
        {
            "id": "sub_ms_values",
            "input": {"validMs": [0.1, 0.5, 1.2]},
            "expected": {"speedup": per_query_speedup([0.1, 0.5, 1.2])},
        },
    ]
    _write_fixture("per_query_speedup", cases)


def build_geomean_ms_fixture() -> None:
    cases = [
        {
            "id": "single_value",
            "input": {"values": [100.0]},
            "expected": {"geomean": geomean_ms([100.0])},
        },
        {
            "id": "two_values",
            "input": {"values": [100.0, 400.0]},
            "expected": {"geomean": geomean_ms([100.0, 400.0])},
        },
        {
            "id": "tpch_realistic_22_queries",
            "input": {
                "values": [
                    120.5,
                    450.2,
                    88.1,
                    234.7,
                    567.3,
                    103.4,
                    290.8,
                    145.6,
                    678.9,
                    223.1,
                    512.4,
                    97.3,
                    445.7,
                    167.2,
                    389.5,
                    78.4,
                    534.1,
                    201.3,
                    456.8,
                    123.9,
                    345.6,
                    189.7,
                ]
            },
            "expected": {
                "geomean": geomean_ms(
                    [
                        120.5,
                        450.2,
                        88.1,
                        234.7,
                        567.3,
                        103.4,
                        290.8,
                        145.6,
                        678.9,
                        223.1,
                        512.4,
                        97.3,
                        445.7,
                        167.2,
                        389.5,
                        78.4,
                        534.1,
                        201.3,
                        456.8,
                        123.9,
                        345.6,
                        189.7,
                    ]
                )
            },
        },
        {
            "id": "null_values_excluded",
            "input": {"values": [100.0, None, 400.0, None]},
            "expected": {"geomean": geomean_ms([100.0, None, 400.0, None])},
        },
        {
            "id": "all_null",
            "input": {"values": [None, None]},
            "expected": {"geomean": geomean_ms([None, None])},
        },
        {
            "id": "empty",
            "input": {"values": []},
            "expected": {"geomean": geomean_ms([])},
        },
        {
            "id": "sub_ms_precision",
            "input": {"values": [0.123, 0.456, 0.789]},
            "expected": {"geomean": geomean_ms([0.123, 0.456, 0.789])},
        },
    ]
    _write_fixture("geomean_ms", cases)


_TPCH_22Q_SAMPLE = [
    5.1,
    8.3,
    12.7,
    3.2,
    45.6,
    22.1,
    67.8,
    9.4,
    15.2,
    31.0,
    7.8,
    19.4,
    88.2,
    4.5,
    11.3,
    23.7,
    55.4,
    16.8,
    28.9,
    6.7,
    42.1,
    14.5,
]


def _write_percentile_ladder_fixture() -> None:
    """
    Combined fixture covering both computePercentile (raw values/p → result)
    and _platform_percentile_stats (display_ms_values → PercentileStats).
    """
    raw_cases: list[dict[str, Any]] = [
        {
            "id": "single_value",
            "input": {"values": [42.0], "p": 50},
            "expected": {"result": compute_percentile([42.0], 50)},
        },
        {
            "id": "two_values_p50",
            "input": {"values": [10.0, 20.0], "p": 50},
            "expected": {"result": compute_percentile([10.0, 20.0], 50)},
        },
        {
            "id": "five_values_p50",
            "input": {"values": [10.0, 20.0, 30.0, 100.0, 200.0], "p": 50},
            "expected": {"result": compute_percentile([10.0, 20.0, 30.0, 100.0, 200.0], 50)},
        },
        {
            "id": "five_values_p90",
            "input": {"values": [10.0, 20.0, 30.0, 100.0, 200.0], "p": 90},
            "expected": {"result": compute_percentile([10.0, 20.0, 30.0, 100.0, 200.0], 90)},
        },
        {
            "id": "five_values_p95",
            "input": {"values": [10.0, 20.0, 30.0, 100.0, 200.0], "p": 95},
            "expected": {"result": compute_percentile([10.0, 20.0, 30.0, 100.0, 200.0], 95)},
        },
        {
            "id": "five_values_p99",
            "input": {"values": [10.0, 20.0, 30.0, 100.0, 200.0], "p": 99},
            "expected": {"result": compute_percentile([10.0, 20.0, 30.0, 100.0, 200.0], 99)},
        },
        {
            "id": "tied_values_p50",
            "input": {"values": [10.0, 10.0, 10.0, 100.0], "p": 50},
            "expected": {"result": compute_percentile([10.0, 10.0, 10.0, 100.0], 50)},
        },
        {
            "id": "tpch_22q_p50",
            "input": {"values": list(_TPCH_22Q_SAMPLE), "p": 50},
            "expected": {"result": compute_percentile(list(_TPCH_22Q_SAMPLE), 50)},
        },
        {
            "id": "tpch_22q_p90",
            "input": {"values": list(_TPCH_22Q_SAMPLE), "p": 90},
            "expected": {"result": compute_percentile(list(_TPCH_22Q_SAMPLE), 90)},
        },
        {
            "id": "tpch_22q_p95",
            "input": {"values": list(_TPCH_22Q_SAMPLE), "p": 95},
            "expected": {"result": compute_percentile(list(_TPCH_22Q_SAMPLE), 95)},
        },
        {
            "id": "tpch_22q_p99",
            "input": {"values": list(_TPCH_22Q_SAMPLE), "p": 99},
            "expected": {"result": compute_percentile(list(_TPCH_22Q_SAMPLE), 99)},
        },
    ]
    stats_cases: list[dict[str, Any]] = [
        {
            "id": "empty_display_timings",
            "input": {"display_ms_values": []},
            "expected": {"stats": platform_percentile_stats([])},
        },
        {
            "id": "platform_stats_5q",
            "input": {"display_ms_values": [10.0, 20.0, 30.0, 100.0, 200.0]},
            "expected": {
                "stats": platform_percentile_stats([10.0, 20.0, 30.0, 100.0, 200.0]),
            },
        },
    ]
    fixture = {
        "chart": "percentile_ladder",
        "version": 1,
        "description": (
            "Parity tests for _compute_percentile / computePercentile "
            "(matches textcharts.percentile_ladder.compute_percentile) "
            "plus _platform_percentile_stats aggregation shape."
        ),
        "cases": raw_cases + stats_cases,
    }
    dest = FIXTURES_DIR / "percentile_ladder.json"
    dest.write_text(json.dumps(fixture, indent=2) + "\n")
    try:
        label = dest.relative_to(pathlib.Path(__file__).parent.parent.parent)
    except ValueError:
        label = dest
    print(f"  wrote {label}")


def build_percentile_ladder_fixture() -> None:
    _write_percentile_ladder_fixture()


def build_box_stats_fixture() -> None:
    cases = [
        {
            "id": "five_values",
            "input": {"values": [10, 20, 30, 40, 50]},
            "expected": compute_box_stats([10, 20, 30, 40, 50]),
        },
        {
            "id": "single_value",
            "input": {"values": [42]},
            "expected": compute_box_stats([42]),
        },
        {
            "id": "two_values",
            "input": {"values": [10, 20]},
            "expected": compute_box_stats([10, 20]),
        },
        {
            "id": "three_values",
            "input": {"values": [5, 15, 25]},
            "expected": compute_box_stats([5, 15, 25]),
        },
        {
            "id": "nulls_filtered",
            "input": {"values": [None, 10, None, 30, 50]},
            "expected": compute_box_stats([None, 10, None, 30, 50]),
        },
        {
            "id": "all_null",
            "input": {"values": [None, None]},
            "expected": compute_box_stats([None, None]),
        },
        {
            "id": "empty",
            "input": {"values": []},
            "expected": compute_box_stats([]),
        },
        {
            "id": "real_latencies_ms",
            "input": {
                "values": [12.4, 34.8, 8.1, 55.6, 22.3, 18.9, 41.2, 9.7, 67.5, 15.3],
            },
            "expected": compute_box_stats(
                [12.4, 34.8, 8.1, 55.6, 22.3, 18.9, 41.2, 9.7, 67.5, 15.3],
            ),
        },
    ]
    fixture = {"chart": "distribution_box", "version": 1, "cases": cases}
    dest = FIXTURES_DIR / "box_stats.json"
    dest.write_text(json.dumps(fixture, indent=2) + "\n")
    try:
        label = dest.relative_to(pathlib.Path(__file__).parent.parent.parent)
    except ValueError:
        label = dest
    print(f"  wrote {label}")


def build_rank_table_fixture() -> None:
    """Fixture for computeRankTable - covers no-ties, ties, nulls, realistic TPCH."""
    no_ties = {
        "query_ids": ["Q1", "Q2", "Q3"],
        "timings": [
            {"Q1": 100.0, "Q2": 50.0, "Q3": 200.0},
            {"Q1": 200.0, "Q2": 25.0, "Q3": 100.0},
            {"Q1": 300.0, "Q2": 75.0, "Q3": 50.0},
        ],
    }
    two_way_tie = {
        "query_ids": ["Q1"],
        "timings": [
            {"Q1": 100.0},
            {"Q1": 100.0},
            {"Q1": 200.0},
        ],
    }
    all_tied = {
        "query_ids": ["Q1"],
        "timings": [{"Q1": 100.0}, {"Q1": 100.0}, {"Q1": 100.0}],
    }
    mixed_nulls = {
        "query_ids": ["Q1", "Q2"],
        "timings": [
            {"Q1": 100.0, "Q2": None},
            {"Q1": None, "Q2": 50.0},
            {"Q1": 200.0, "Q2": 50.0},
        ],
    }
    zero_and_negative_are_null = {
        "query_ids": ["Q1"],
        "timings": [
            {"Q1": 0.0},
            {"Q1": -5.0},
            {"Q1": 100.0},
            {"Q1": 50.0},
        ],
    }
    tpch_realistic = {
        "query_ids": [f"Q{i}" for i in range(1, 5)],
        "timings": [
            {"Q1": 120.5, "Q2": 450.2, "Q3": 88.1, "Q4": 234.7},
            {"Q1": 103.4, "Q2": 290.8, "Q3": 145.6, "Q4": 678.9},
            {"Q1": 97.3, "Q2": 445.7, "Q3": 167.2, "Q4": 389.5},
            {"Q1": 120.5, "Q2": 78.4, "Q3": 534.1, "Q4": 201.3},
        ],
    }
    empty_query_ids = {"query_ids": [], "timings": []}
    no_platforms = {"query_ids": ["Q1"], "timings": []}
    all_null_for_query = {
        "query_ids": ["Q1"],
        "timings": [{"Q1": None}, {"Q1": None}],
    }

    cases_data: list[tuple[str, dict[str, Any]]] = [
        ("no_ties", no_ties),
        ("two_way_tie", two_way_tie),
        ("all_tied", all_tied),
        ("mixed_nulls", mixed_nulls),
        ("zero_and_negative_are_null", zero_and_negative_are_null),
        ("tpch_realistic_4q_4p", tpch_realistic),
        ("empty_query_ids", empty_query_ids),
        ("no_platforms", no_platforms),
        ("all_null_for_query", all_null_for_query),
    ]

    cases = [
        {
            "id": case_id,
            "input": {
                "queryIds": data["query_ids"],
                "timingsByPlatform": data["timings"],
            },
            "expected": {
                "ranks": compute_rank_table(data["query_ids"], data["timings"]),
            },
        }
        for case_id, data in cases_data
    ]
    _write_fixture("rank_table", cases)


def build_cdf_ecdf_fixture() -> None:
    cases = [
        {
            "id": "five_values_sorted",
            "input": {"values": [30, 10, 50, 20, 40]},
            "expected": compute_ecdf_points([30, 10, 50, 20, 40]),
        },
        {
            "id": "three_values",
            "input": {"values": [10, 30, 20]},
            "expected": compute_ecdf_points([10, 30, 20]),
        },
        {
            "id": "nulls_filtered",
            "input": {"values": [None, 5, None, 15, 25]},
            "expected": compute_ecdf_points([None, 5, None, 15, 25]),
        },
        {
            "id": "single_value",
            "input": {"values": [42]},
            "expected": compute_ecdf_points([42]),
        },
        {
            "id": "empty",
            "input": {"values": []},
            "expected": compute_ecdf_points([]),
        },
        {
            "id": "all_null",
            "input": {"values": [None, None]},
            "expected": compute_ecdf_points([None, None]),
        },
    ]
    fixture = {"chart": "cdf_chart", "version": 1, "cases": cases}
    dest = FIXTURES_DIR / "cdf_ecdf.json"
    dest.write_text(json.dumps(fixture, indent=2) + "\n")
    try:
        label = dest.relative_to(pathlib.Path(__file__).parent.parent.parent)
    except ValueError:
        label = dest
    print(f"  wrote {label}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def build_chart_ids_fixture() -> None:
    """Emit the canonical list of CLI chart IDs from chart_types.py _CHART_SPECS.

    The parity test reads this file instead of regex-matching the Python source,
    so any Python syntax change inside _CHART_SPECS won't silently break the test.
    """
    from benchbox.core.visualization.chart_types import ALL_CHART_TYPES  # noqa: PLC0415

    ids = list(ALL_CHART_TYPES)
    out = FIXTURES_DIR / "chart_ids.json"
    out.write_text(json.dumps({"chart_ids": ids}, indent=2) + "\n")
    print(f"  wrote {out.name} ({len(ids)} ids)")


# Convention: builder functions are named build_<chart_name>_fixture.
# The chart_name must match the "chart" field written into the fixture JSON
# (used by the TS parity suite to map fixture file → helper). Keep entries
# in the same order as _CHART_SPECS in chart_types.py.
BUILDERS = [
    build_heatmap_color_fixture,
    build_lightness_for_cell_fixture,
    build_speedup_ratio_fixture,
    build_vs_slowest_ratio_fixture,
    build_delta_pct_fixture,
    build_sort_by_magnitude_fixture,
    build_per_query_speedup_fixture,
    build_geomean_ms_fixture,
    build_percentile_ladder_fixture,
    build_box_stats_fixture,
    build_cdf_ecdf_fixture,
    build_rank_table_fixture,
    build_chart_ids_fixture,
]


def main(out_dir: pathlib.Path | None = None) -> None:
    global FIXTURES_DIR  # noqa: PLW0603
    if out_dir is not None:
        FIXTURES_DIR = out_dir
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating {len(BUILDERS)} fixture files in {FIXTURES_DIR}/ ...")
    for builder in BUILDERS:
        builder()
    print("Done.")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate visualization parity fixtures.")
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=None,
        help="Output directory (default: tests/parity/fixtures/)",
    )
    args = parser.parse_args()
    main(out_dir=args.out)
