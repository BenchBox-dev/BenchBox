#!/usr/bin/env python3
"""Cross-surface applicability sweep (benchmark-cross-surface-equivalence-gate w2).

The oracle coverage map flags a benchmark as a cross-surface candidate when it is
dual-surface (ships SQL queries AND has ``supports_dataframe=True``) and currently
unguarded. But ``supports_dataframe`` is a *loading* capability flag: it does NOT
guarantee the benchmark ships comparable DataFrame *query* implementations. The
cross-surface gate compares a query's SQL result to its DataFrame result, so it is
only applicable to benchmarks that actually ship DataFrame queries with 1:1 id
correspondence to their SQL queries.

This sweep drills into each cross-surface candidate from the coverage map and asks
the authoritative production resolver
(``benchbox.core.dataframe.query_resolution.get_dataframe_queries_for_benchmark``,
the same path the production DataFrame adapter uses) how many DataFrame queries it
actually resolves. The result re-scopes the unguarded-benchmark campaign:

  - GATEABLE: ships DataFrame queries -> dispatch to the cross-surface gate (w3).
  - no DataFrame query surface -> NOT cross-surface-gateable; needs a w2 fallback
    oracle (differential second-engine or a curated expected-results subset).

It is report-mode (regenerate the committed artifact); resolving DataFrame queries
needs only a benchmark instance, not generated data, so the sweep is cheap. Note
that running the gate to enumerate actual divergences additionally requires a
load-faithful per-benchmark build (see the SSB builder in
``benchbox.core.equivalence.cross_surface``); a generic build is not load-faithful
and produces spurious column errors, so divergence COUNTS are deferred to the
per-benchmark gate wiring (w3), starting with the two gateable benchmarks here.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ARTIFACT = _REPO_ROOT / "_project" / "analysis" / "cross-surface-applicability.md"

# Scales to try when instantiating a benchmark (some reject the default small SF
# and require a canonical scale, e.g. joinorder=1.0, tpcds_obt>=1.0). Resolving
# DataFrame queries needs no generated data, so a larger scale here is still cheap.
_INSTANTIATE_SCALES = (0.01, 1.0)


def _resolve_dataframe_query_count(benchmark_id: str) -> tuple[str, dict[str, Any]]:
    """Classify a benchmark's cross-surface applicability.

    Returns ``(status, detail)`` where status is one of "gateable",
    "no-df-query-surface", or "blocked".
    """
    from benchbox.core.benchmark_registry import get_benchmark_class
    from benchbox.core.dataframe.query_resolution import get_dataframe_queries_for_benchmark

    cls = get_benchmark_class(benchmark_id)
    instance = None
    used_scale = None
    last_error = ""
    for scale in _INSTANTIATE_SCALES:
        try:
            instance = cls(scale_factor=scale)
            used_scale = scale
            break
        except Exception as exc:  # noqa: BLE001 - record why instantiation failed, do not crash the sweep
            last_error = f"{type(exc).__name__}: {exc}"
    if instance is None:
        return "blocked", {"error": last_error}

    try:
        sql_count = len(instance.get_queries())
        config = SimpleNamespace(name=benchmark_id, stream_id=0)
        df_queries = get_dataframe_queries_for_benchmark(config, instance, 0) or []
        df_count = len(df_queries)
    except Exception as exc:  # noqa: BLE001 - a resolution error is a finding, not a crash
        return "blocked", {"error": f"df-resolve {type(exc).__name__}: {exc}"}

    status = "gateable" if df_count > 0 else "no-df-query-surface"
    return status, {"sql_queries": sql_count, "df_queries": df_count, "scale": used_scale}


def build_applicability_sweep() -> list[dict[str, Any]]:
    """Drill into every dual-surface UNGUARDED benchmark from the coverage map."""
    from _project.scripts.generate_oracle_coverage_map import build_coverage_map

    candidates = [row["benchmark"] for row in build_coverage_map() if row["dual_surface"] and not row["guarded"]]
    rows: list[dict[str, Any]] = []
    for benchmark_id in candidates:
        status, detail = _resolve_dataframe_query_count(benchmark_id)
        rows.append({"benchmark": benchmark_id, "status": status, **detail})
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    gateable = [r for r in rows if r["status"] == "gateable"]
    no_surface = [r for r in rows if r["status"] == "no-df-query-surface"]
    blocked = [r for r in rows if r["status"] == "blocked"]

    lines: list[str] = []
    lines.append("# Cross-surface applicability sweep")
    lines.append("")
    lines.append(
        "**Generated** by `_project/scripts/cross_surface_applicability_sweep.py`. "
        "Drills into the dual-surface UNGUARDED benchmarks from the oracle coverage "
        "map and asks the production DataFrame resolver how many DataFrame *queries* "
        "each actually ships. `supports_dataframe` (the coverage map's signal) is a "
        "DataFrame *loading* flag and over-counts cross-surface candidates."
    )
    lines.append("")
    lines.append(
        f"**Summary:** {len(rows)} dual-surface unguarded candidates — "
        f"{len(gateable)} GATEABLE (ship DataFrame queries), "
        f"{len(no_surface)} have no DataFrame query surface (need a w2 fallback oracle), "
        f"{len(blocked)} blocked."
    )
    lines.append("")
    lines.append("| Benchmark | Status | SQL queries | DataFrame queries | Note |")
    lines.append("| --- | --- | --- | --- | --- |")
    for r in rows:
        if r["status"] == "blocked":
            note = r.get("error", "")
            sql_n = df_n = "—"
        else:
            note = "→ cross-surface gate (w3)" if r["status"] == "gateable" else "→ w2 fallback oracle"
            sql_n = r.get("sql_queries", "—")
            df_n = r.get("df_queries", "—")
        lines.append(f"| {r['benchmark']} | {r['status']} | {sql_n} | {df_n} | {note} |")
    lines.append("")
    lines.append("## Campaign dispatch")
    lines.append("")
    lines.append(
        "- **Cross-surface gate (w3)** — ships DataFrame queries, 1:1 with SQL: "
        + (", ".join(r["benchmark"] for r in gateable) or "none")
        + ". These need a load-faithful per-benchmark builder (see the SSB builder in "
        "`benchbox.core.equivalence.cross_surface`) before the gate can enumerate real "
        "divergences; a generic build is not load-faithful."
    )
    lines.append(
        "- **w2 fallback oracle** — no comparable DataFrame query surface, so the "
        "cross-surface gate cannot reach them; they need a differential second-engine "
        "check or a curated expected-results subset: " + (", ".join(r["benchmark"] for r in no_surface) or "none") + "."
    )
    if blocked:
        lines.append("- **Blocked** (instantiate/resolve): " + ", ".join(r["benchmark"] for r in blocked) + ".")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the committed artifact is stale.")
    args = parser.parse_args(argv)

    rows = build_applicability_sweep()
    rendered = render_markdown(rows)
    if args.check:
        if not ARTIFACT.exists():
            print(f"missing artifact: {ARTIFACT.relative_to(_REPO_ROOT)} (run the sweep)")
            return 1
        if ARTIFACT.read_text(encoding="utf-8") != rendered:
            print(f"stale artifact: {ARTIFACT.relative_to(_REPO_ROOT)} (run the sweep and commit)")
            return 1
        print("cross-surface applicability sweep is up to date.")
        return 0

    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(rendered, encoding="utf-8")
    gateable = [r["benchmark"] for r in rows if r["status"] == "gateable"]
    print(f"Wrote {ARTIFACT.relative_to(_REPO_ROOT)}")
    print(f"{len(rows)} candidates, {len(gateable)} gateable: {', '.join(gateable)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
