#!/usr/bin/env python3
"""Cross-surface applicability sweep (benchmark-cross-surface-equivalence-gate w2).

The oracle coverage map flags a benchmark as a cross-surface candidate when it is
dual-surface (ships SQL queries AND has ``supports_dataframe=True``) and currently
unguarded. But ``supports_dataframe`` is a *loading* capability flag: it does NOT
mean the benchmark ships comparable DataFrame *query* implementations. The
cross-surface gate compares a query's SQL result to its DataFrame result, so it is
only applicable to benchmarks that ship DataFrame *queries*.

Signal: each benchmark that ships a DataFrame query surface exposes a
``QueryRegistry`` (a ``<BENCH>_DATAFRAME_QUERIES`` instance) in its
``benchbox.core.<bench>.dataframe_queries`` module/package -- this is the registry
the cross-surface gate builders (e.g. ``build_clickbench_duckdb``) consume
directly. Detecting that registry is the authoritative gate-applicability signal.

History: an earlier version of this sweep used the production query *resolver*
(``get_dataframe_queries_for_benchmark``). That under-counted: the resolver only
special-cases tpch/tpcds/clickbench plus a generic ``get_dataframe_queries()``
method, so benchmarks that expose only a ``<BENCH>_DATAFRAME_QUERIES`` registry
(e.g. coffeeshop -- which was nonetheless successfully gated in #842) resolved to
zero and were wrongly dispatched to a fallback oracle. Registry detection fixes
that.

Classification per candidate:
  - ``gateable``: has a registry whose ids overlap the SQL ids as-is -> wire a
    cross-surface gate on the overlapping ids (w3).
  - ``gateable-needs-id-mapping``: has a registry but its ids do not overlap the
    SQL ids verbatim (a prefix/naming convention differs, e.g. ``1`` vs ``Q1``);
    gateable after a mechanical id normalization in the builder (w3).
  - ``no-df-query-surface``: no DataFrame query registry -> NOT cross-surface
    gateable; needs a w2 fallback oracle (differential second-engine or a curated
    expected-results subset).
  - ``blocked``: could not instantiate the benchmark or read its registry.

Report-mode (regenerate the committed artifact). Detecting a registry + reading
SQL ids needs only an import + a benchmark instance (no generated data), so the
sweep is cheap. Enumerating real divergences still requires a load-faithful
per-benchmark gate builder (see ``build_ssb_duckdb`` /
``build_clickbench_duckdb``).
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ARTIFACT = _REPO_ROOT / "_project" / "analysis" / "cross-surface-applicability.md"

# Scales to try when instantiating a benchmark (some reject the default small SF
# and require a canonical scale, e.g. joinorder=1.0, tpcds_obt>=1.0). Reading SQL
# ids needs no generated data, so a larger scale here is still cheap.
_INSTANTIATE_SCALES = (0.01, 1.0)

GATEABLE = "gateable"
GATEABLE_NEEDS_ID_MAPPING = "gateable-needs-id-mapping"
NO_DF_QUERY_SURFACE = "no-df-query-surface"
BLOCKED = "blocked"

# Statuses that mean "a DataFrame query surface exists, so a cross-surface gate is
# applicable" (directly or after id normalization).
_GATEABLE_STATUSES = frozenset({GATEABLE, GATEABLE_NEEDS_ID_MAPPING})


def _dataframe_query_registry(benchmark_id: str) -> Any | None:
    """Return the benchmark's DataFrame ``QueryRegistry``, or ``None`` if it ships none.

    Each benchmark with a DataFrame query surface exposes a ``QueryRegistry``
    instance in ``benchbox.core.<bench>.dataframe_queries``; the cross-surface gate
    builders consume it directly. Detect it by type rather than by a derived name,
    because the constant name is not uniform (e.g. ``ODB_DATAFRAME_QUERIES`` for
    h2odb, ``JOINORDER_DATAFRAME_QUERIES`` for both joinorder variants).
    """
    from benchbox.core.dataframe.query import QueryRegistry

    try:
        module = importlib.import_module(f"benchbox.core.{benchmark_id}.dataframe_queries")
    except ModuleNotFoundError:
        return None
    for value in vars(module).values():
        if isinstance(value, QueryRegistry):
            return value
    return None


def _instantiate(benchmark_id: str) -> tuple[Any | None, float | None, str]:
    from benchbox.core.benchmark_registry import get_benchmark_class

    cls = get_benchmark_class(benchmark_id)
    last_error = ""
    for scale in _INSTANTIATE_SCALES:
        try:
            return cls(scale_factor=scale), scale, ""
        except Exception as exc:  # noqa: BLE001 - record why instantiation failed, do not crash the sweep
            last_error = f"{type(exc).__name__}: {exc}"
    return None, None, last_error


def classify_applicability(benchmark_id: str) -> tuple[str, dict[str, Any]]:
    """Classify a benchmark's cross-surface gate applicability via registry detection."""
    registry = _dataframe_query_registry(benchmark_id)
    if registry is None:
        return NO_DF_QUERY_SURFACE, {"df_queries": 0}

    try:
        df_ids = [str(q) for q in registry.get_query_ids()]
    except Exception as exc:  # noqa: BLE001 - a registry read error is a finding, not a crash
        return BLOCKED, {"error": f"registry {type(exc).__name__}: {exc}"}

    instance, used_scale, error = _instantiate(benchmark_id)
    if instance is None:
        return BLOCKED, {"error": error, "df_queries": len(df_ids)}

    sql_ids = [str(q) for q in instance.get_queries().keys()]
    raw_overlap = len(set(sql_ids) & set(df_ids))
    detail = {
        "sql_queries": len(sql_ids),
        "df_queries": len(df_ids),
        "raw_id_overlap": raw_overlap,
        "scale": used_scale,
    }
    status = GATEABLE if raw_overlap > 0 else GATEABLE_NEEDS_ID_MAPPING
    return status, detail


def build_applicability_sweep() -> list[dict[str, Any]]:
    """Drill into every dual-surface UNGUARDED benchmark from the coverage map."""
    from _project.scripts.generate_oracle_coverage_map import build_coverage_map

    candidates = [row["benchmark"] for row in build_coverage_map() if row["dual_surface"] and not row["guarded"]]
    rows: list[dict[str, Any]] = []
    for benchmark_id in candidates:
        status, detail = classify_applicability(benchmark_id)
        rows.append({"benchmark": benchmark_id, "status": status, **detail})
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    gateable = [r for r in rows if r["status"] in _GATEABLE_STATUSES]
    no_surface = [r for r in rows if r["status"] == NO_DF_QUERY_SURFACE]
    blocked = [r for r in rows if r["status"] == BLOCKED]

    lines: list[str] = []
    lines.append("# Cross-surface applicability sweep")
    lines.append("")
    lines.append(
        "**Generated** by `_project/scripts/cross_surface_applicability_sweep.py`. "
        "Drills into the dual-surface UNGUARDED benchmarks from the oracle coverage "
        "map and detects which ship a DataFrame query `QueryRegistry` (the registry "
        "the cross-surface gate builders consume). `supports_dataframe` (the coverage "
        "map's signal) is a DataFrame *loading* flag and over-counts candidates; the "
        "production query *resolver* under-counts (it misses per-benchmark "
        "`<BENCH>_DATAFRAME_QUERIES` registries). Registry detection is the "
        "authoritative gate-applicability signal."
    )
    lines.append("")
    lines.append(
        f"**Summary:** {len(rows)} dual-surface unguarded candidates — "
        f"{len(gateable)} cross-surface gateable (ship a DataFrame query registry), "
        f"{len(no_surface)} have no DataFrame query surface (need a w2 fallback oracle), "
        f"{len(blocked)} blocked."
    )
    lines.append("")
    lines.append("| Benchmark | Status | SQL queries | DataFrame queries | Raw id overlap | Note |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for r in rows:
        if r["status"] == BLOCKED:
            lines.append(f"| {r['benchmark']} | {BLOCKED} | — | {r.get('df_queries', '—')} | — | {r.get('error', '')} |")
            continue
        if r["status"] == NO_DF_QUERY_SURFACE:
            note = "→ w2 fallback oracle (no DataFrame query registry)"
            lines.append(f"| {r['benchmark']} | {r['status']} | — | 0 | — | {note} |")
            continue
        note = (
            "→ cross-surface gate (w3)"
            if r["status"] == GATEABLE
            else "→ cross-surface gate after id normalization (w3)"
        )
        lines.append(
            f"| {r['benchmark']} | {r['status']} | {r.get('sql_queries', '—')} | "
            f"{r.get('df_queries', '—')} | {r.get('raw_id_overlap', '—')} | {note} |"
        )
    lines.append("")
    lines.append("## Campaign dispatch")
    lines.append("")
    direct = [r["benchmark"] for r in rows if r["status"] == GATEABLE]
    needs_mapping = [r["benchmark"] for r in rows if r["status"] == GATEABLE_NEEDS_ID_MAPPING]
    lines.append(
        "- **Cross-surface gate, ids overlap as-is (w3):** " + (", ".join(direct) or "none") + "."
    )
    lines.append(
        "- **Cross-surface gate, needs id normalization first (w3):** "
        + (", ".join(needs_mapping) or "none")
        + " — a DataFrame query registry exists but its ids differ from the SQL ids "
        "by a naming convention (e.g. `1` vs `Q1`); normalize in the builder."
    )
    lines.append(
        "- **w2 fallback oracle** — no DataFrame query registry, so the cross-surface "
        "gate cannot reach them; they need a differential second-engine check or a "
        "curated expected-results subset: " + (", ".join(r["benchmark"] for r in no_surface) or "none") + "."
    )
    if blocked:
        lines.append("- **Blocked** (instantiate/registry): " + ", ".join(r["benchmark"] for r in blocked) + ".")
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
    gateable = [r["benchmark"] for r in rows if r["status"] in _GATEABLE_STATUSES]
    print(f"Wrote {ARTIFACT.relative_to(_REPO_ROOT)}")
    print(f"{len(rows)} candidates, {len(gateable)} gateable: {', '.join(gateable)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
