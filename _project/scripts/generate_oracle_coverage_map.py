#!/usr/bin/env python3
"""Generate the benchmark correctness-oracle coverage map.

The map is the authoritative, *generated* answer to "which correctness oracle, if
any, guards each shipped benchmark?" It is derived from live sources so it cannot
drift from reality:

  - the benchmark registry (``benchbox.core.benchmark_registry``) for the set of
    shipped benchmarks and their surfaces (SQL / DataFrame);
  - the expected-results provider registry
    (``benchbox.core.expected_results.registry``) for stored answer keys;
  - the cross-surface gate registry
    (``benchbox.core.equivalence.cross_surface.GATES``) for SQL<->DataFrame gates;
  - module presence for the bespoke TPC-Havoc variant / variant-DataFrame gates.

Run ``python _project/scripts/generate_oracle_coverage_map.py`` to (re)write the
checked-in artifacts under ``_project/analysis/``. Run with ``--check`` to fail if
those artifacts are stale (used by ``tests/unit/test_oracle_coverage_map.py``).

This script owns w0 (the matrix) and feeds w3 (drift/UNGUARDED visibility) of the
``benchmark-correctness-oracle-coverage-map`` TODO. It deliberately does NOT build
per-benchmark oracles (w1/w2); it makes the gap legible and dispatchable.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

# Oracle kinds, strongest/most-specific first. "primary" oracle = the first of
# these a benchmark has; UNGUARDED benchmarks have none.
ORACLE_EXPECTED_RESULTS = "expected-results"
ORACLE_VARIANT_EQUIVALENCE = "variant-equivalence"
ORACLE_CROSS_SURFACE_VARIANT = "cross-surface-variant"
ORACLE_CROSS_SURFACE = "cross-surface"
ORACLE_NONE = "NONE"

_ORACLE_PRIORITY = [
    ORACLE_EXPECTED_RESULTS,
    ORACLE_VARIANT_EQUIVALENCE,
    ORACLE_CROSS_SURFACE_VARIANT,
    ORACLE_CROSS_SURFACE,
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = _REPO_ROOT / "_project" / "analysis"
JSON_ARTIFACT = ARTIFACT_DIR / "oracle-coverage-map.json"
MARKDOWN_ARTIFACT = ARTIFACT_DIR / "oracle-coverage-map.md"


def _module_exists(dotted: str) -> bool:
    """True if an importable module exists, without importing it."""
    try:
        return importlib.util.find_spec(dotted) is not None
    except ModuleNotFoundError:
        return False


def classify_oracles(
    benchmark_id: str,
    *,
    expected_results_providers: set[str],
    cross_surface_gates: set[str],
) -> list[str]:
    """Return every correctness oracle that currently guards ``benchmark_id``.

    Detection is from live sources only; adding a real oracle (a provider, a
    ``GATES`` entry, or a TPC-Havoc gate module) automatically reclassifies the
    benchmark on the next regeneration.
    """
    oracles: list[str] = []
    if benchmark_id in expected_results_providers:
        oracles.append(ORACLE_EXPECTED_RESULTS)
    # TPC-Havoc ships its own bespoke gates (variant-vs-canonical SQL, and
    # SQL-variant-vs-DataFrame-variant); detect them by module presence.
    if benchmark_id == "tpchavoc":
        if _module_exists("benchbox.core.tpchavoc.equivalence"):
            oracles.append(ORACLE_VARIANT_EQUIVALENCE)
        if _module_exists("benchbox.core.tpchavoc.dataframe_equivalence"):
            oracles.append(ORACLE_CROSS_SURFACE_VARIANT)
    if benchmark_id in cross_surface_gates:
        oracles.append(ORACLE_CROSS_SURFACE)
    return oracles


def primary_oracle(oracles: list[str]) -> str:
    for kind in _ORACLE_PRIORITY:
        if kind in oracles:
            return kind
    return ORACLE_NONE


def _surfaces(metadata: dict[str, Any]) -> tuple[bool, bool]:
    """Return ``(has_sql, has_dataframe)`` for a benchmark's metadata.

    Every shipped benchmark exposes SQL queries (``num_queries`` > 0); DataFrame
    is gated by the registry's ``supports_dataframe`` flag.
    """
    has_sql = bool(metadata.get("num_queries") or 0)
    has_dataframe = bool(metadata.get("supports_dataframe", False))
    return has_sql, has_dataframe


def build_coverage_map() -> list[dict[str, Any]]:
    """Build the coverage matrix: one classified row per shipped benchmark."""
    from benchbox.core.benchmark_registry import get_benchmark_metadata, list_benchmark_ids
    from benchbox.core.equivalence.cross_surface import GATES
    from benchbox.core.expected_results.registry import get_registry

    expected_results_providers = set(get_registry().list_available_benchmarks())
    cross_surface_gates = set(GATES.keys())

    rows: list[dict[str, Any]] = []
    for benchmark_id in sorted(list_benchmark_ids()):
        metadata = get_benchmark_metadata(benchmark_id) or {}
        has_sql, has_dataframe = _surfaces(metadata)
        surfaces = [s for s, present in (("sql", has_sql), ("dataframe", has_dataframe)) if present]
        oracles = classify_oracles(
            benchmark_id,
            expected_results_providers=expected_results_providers,
            cross_surface_gates=cross_surface_gates,
        )
        primary = primary_oracle(oracles)
        # A dual-surface benchmark with no oracle is reachable by the cross-surface
        # SQL<->DataFrame gate (the w1 dispatch target). A single-surface benchmark
        # is not and needs a fallback oracle (w2).
        dual_surface = has_sql and has_dataframe
        rows.append(
            {
                "benchmark": benchmark_id,
                "surfaces": surfaces,
                "dual_surface": dual_surface,
                "oracles": oracles,
                "primary_oracle": primary,
                "guarded": primary != ORACLE_NONE,
                "cross_surface_applicable": dual_surface and primary == ORACLE_NONE,
            }
        )
    return rows


def render_markdown(rows: list[dict[str, Any]]) -> str:
    guarded = [r for r in rows if r["guarded"]]
    unguarded = [r for r in rows if not r["guarded"]]
    dispatchable = [r for r in unguarded if r["cross_surface_applicable"]]
    single_surface_gap = [r for r in unguarded if not r["cross_surface_applicable"]]

    lines: list[str] = []
    lines.append("# Benchmark correctness-oracle coverage map")
    lines.append("")
    lines.append(
        "**Generated** by `_project/scripts/generate_oracle_coverage_map.py` from the "
        "benchmark registry, the expected-results provider registry, and the "
        "equivalence-gate registries. Do not edit by hand — run the generator and "
        "commit. `tests/unit/test_oracle_coverage_map.py` fails if this drifts."
    )
    lines.append("")
    lines.append(
        f"**Summary:** {len(rows)} shipped benchmarks — {len(guarded)} guarded, "
        f"{len(unguarded)} UNGUARDED ({len(dispatchable)} reachable by the "
        f"cross-surface gate, {len(single_surface_gap)} single-surface needing a "
        f"fallback oracle)."
    )
    lines.append("")
    lines.append("| Benchmark | Surfaces | Oracle | Notes |")
    lines.append("| --- | --- | --- | --- |")
    for r in rows:
        surfaces = "+".join(r["surfaces"]) or "—"
        oracle = r["primary_oracle"]
        if r["guarded"]:
            note = ", ".join(r["oracles"])
        elif r["cross_surface_applicable"]:
            note = "dual-surface → dispatch to cross-surface gate (w1)"
        else:
            note = "single-surface → needs fallback oracle (w2)"
        lines.append(f"| {r['benchmark']} | {surfaces} | {oracle} | {note} |")
    lines.append("")
    lines.append("## UNGUARDED benchmarks")
    lines.append("")
    lines.append(
        "These ship with no automated correctness oracle today. Dual-surface ones "
        "are dispatched to `benchmark-cross-surface-equivalence-gate` (w1); "
        "single-surface ones need a per-benchmark fallback — differential vs a "
        "second engine, a small curated expected-results subset, or a documented "
        "structural invariant (w2)."
    )
    lines.append("")
    lines.append(
        "> Caveat (w2 oracle choice): write/DML/nondeterministic benchmarks "
        "(`write_primitives`, `transaction_primitives`, `metadata_primitives`, "
        "`tpcdi`) are listed as dual-surface, but their two surfaces may not be "
        "result-comparable; prefer structural-invariant oracles (row counts, "
        "post-state assertions) over cross-surface equality for those."
    )
    lines.append("")
    lines.append(
        "- Dual-surface (cross-surface candidates): " + (", ".join(r["benchmark"] for r in dispatchable) or "none")
    )
    lines.append(
        "- Single-surface (fallback-oracle needed): "
        + (", ".join(r["benchmark"] for r in single_surface_gap) or "none")
    )
    lines.append("")
    return "\n".join(lines)


def render_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps({"benchmarks": rows}, indent=2, sort_keys=True) + "\n"


def write_artifacts(rows: list[dict[str, Any]]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_ARTIFACT.write_text(render_json(rows), encoding="utf-8")
    MARKDOWN_ARTIFACT.write_text(render_markdown(rows), encoding="utf-8")


def check_artifacts(rows: list[dict[str, Any]]) -> list[str]:
    """Return a list of human-readable drift problems (empty == in sync)."""
    problems: list[str] = []
    expected_json = render_json(rows)
    expected_md = render_markdown(rows)
    for path, expected in ((JSON_ARTIFACT, expected_json), (MARKDOWN_ARTIFACT, expected_md)):
        if not path.exists():
            problems.append(f"missing artifact: {path.relative_to(_REPO_ROOT)} (run the generator)")
        elif path.read_text(encoding="utf-8") != expected:
            problems.append(f"stale artifact: {path.relative_to(_REPO_ROOT)} (run the generator and commit)")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify the checked-in artifacts are current; non-zero exit if stale.",
    )
    args = parser.parse_args(argv)

    rows = build_coverage_map()
    if args.check:
        problems = check_artifacts(rows)
        if problems:
            print("oracle coverage map is out of date:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print("oracle coverage map is up to date.")
        return 0

    write_artifacts(rows)
    unguarded = [r["benchmark"] for r in rows if not r["guarded"]]
    print(f"Wrote {MARKDOWN_ARTIFACT.relative_to(_REPO_ROOT)} and {JSON_ARTIFACT.relative_to(_REPO_ROOT)}")
    print(f"{len(rows)} benchmarks, {len(unguarded)} UNGUARDED: {', '.join(unguarded)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
