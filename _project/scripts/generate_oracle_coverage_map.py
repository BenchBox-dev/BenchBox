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

# Oracle STRENGTH-TYPE: what a guarded cell actually proves. Distinct from the
# oracle KIND above, and derived from live sources (provider capability / comparator
# identity), never hand-labelled per benchmark.
STRENGTH_VALUE = "value-level"  # full result values compared (cross-surface, variant gates)
STRENGTH_CARDINALITY = "cardinality-only"  # row counts only (expected-results without value digests)
STRENGTH_VALUE_AND_CARDINALITY = "value+cardinality"  # row counts AND stored value digests
STRENGTH_NONE = "—"

# Sentinel for "no scale guarantee" (UNGUARDED rows).
SCALE_NONE = "—"

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
    staged_cross_surface_gates: set[str],
) -> list[str]:
    """Return every correctness oracle that currently guards ``benchmark_id``.

    Detection is from live sources only; adding a real oracle (a provider, a
    ``GATES`` entry, or a TPC-Havoc gate module) automatically reclassifies the
    benchmark on the next regeneration.

    A cross-surface oracle is detected from membership in either the enforced
    ``GATES`` registry or the (currently empty) ``STAGED_GATES`` registry; the
    caller records *which* of the two via ``cross_surface_enforced`` so a
    registered-but-not-CI-enforced gate is never reported as enforced coverage.
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
    if benchmark_id in cross_surface_gates or benchmark_id in staged_cross_surface_gates:
        oracles.append(ORACLE_CROSS_SURFACE)
    return oracles


def primary_oracle(oracles: list[str]) -> str:
    for kind in _ORACLE_PRIORITY:
        if kind in oracles:
            return kind
    return ORACLE_NONE


def _expected_results_has_value_digests(benchmark_id: str) -> bool:
    """True if the expected-results provider stores VALUE digests for this benchmark.

    Probed from the committed digest reference (no answer files / DuckDB needed, so
    the result is deterministic across environments and the drift check stays
    stable). This is what flips the expected-results strength from cardinality-only
    to value+cardinality once stored digests land -- derived from the provider's
    actual capability, not a hand-edited label.
    """
    try:
        if benchmark_id == "tpch":
            from benchbox.core.expected_results.loader import load_tpch_value_digests

            return bool(load_tpch_value_digests(1.0))
    except Exception:  # pragma: no cover - absence simply means cardinality-only
        return False
    return False


def _bounded_value_gate_scale() -> str:
    """The bounded scale value-level gates run at, read live from the gate module."""
    from benchbox.core.equivalence.cross_surface import EQUIVALENCE_SCALE

    return f"SF={EQUIVALENCE_SCALE}"


def oracle_strength_and_scale(primary: str, benchmark_id: str) -> tuple[str, str]:
    """Return ``(strength_type, scale_coverage)`` for a benchmark's primary oracle.

    Derived from live sources so it cannot rot:
      * expected-results -> cardinality-only OR value+cardinality (probe the
        provider's stored value digests); scale SF=1 (the loader raises for any
        other scale, so no expected-results oracle exists above SF=1).
      * variant-equivalence / cross-surface(-variant) -> value-level (they compare
        full result sets via ResultValidator/validate_results_exact); scale = the
        bounded gate scale read live from the equivalence module.
    """
    if primary == ORACLE_EXPECTED_RESULTS:
        strength = (
            STRENGTH_VALUE_AND_CARDINALITY
            if _expected_results_has_value_digests(benchmark_id)
            else STRENGTH_CARDINALITY
        )
        # SF=1 only: benchbox/core/expected_results/loader.py raises for other scales.
        return strength, "SF=1"
    if primary in (ORACLE_VARIANT_EQUIVALENCE, ORACLE_CROSS_SURFACE_VARIANT, ORACLE_CROSS_SURFACE):
        return STRENGTH_VALUE, _bounded_value_gate_scale()
    return STRENGTH_NONE, SCALE_NONE


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
    from benchbox.core.equivalence.cross_surface import GATES, STAGED_GATES
    from benchbox.core.expected_results.registry import get_registry

    expected_results_providers = set(get_registry().list_available_benchmarks())
    cross_surface_gates = set(GATES.keys())
    staged_cross_surface_gates = set(STAGED_GATES.keys())

    rows: list[dict[str, Any]] = []
    for benchmark_id in sorted(list_benchmark_ids()):
        metadata = get_benchmark_metadata(benchmark_id) or {}
        has_sql, has_dataframe = _surfaces(metadata)
        surfaces = [s for s, present in (("sql", has_sql), ("dataframe", has_dataframe)) if present]
        oracles = classify_oracles(
            benchmark_id,
            expected_results_providers=expected_results_providers,
            cross_surface_gates=cross_surface_gates,
            staged_cross_surface_gates=staged_cross_surface_gates,
        )
        primary = primary_oracle(oracles)
        strength, scale = oracle_strength_and_scale(primary, benchmark_id)
        # A dual-surface benchmark with no oracle is reachable by the cross-surface
        # SQL<->DataFrame gate (the w1 dispatch target). A single-surface benchmark
        # is not and needs a fallback oracle (w2).
        dual_surface = has_sql and has_dataframe
        # Honesty signal (M1): a cross-surface oracle's mere REGISTRATION does not
        # prove it is green. Distinguish a CI-enforced (blocking) gate -- which is
        # green-or-CI-fails -- from a STAGED gate that is registered but not run in
        # CI. ``None`` for benchmarks with no cross-surface gate at all.
        if ORACLE_CROSS_SURFACE in oracles:
            cross_surface_enforced: bool | None = benchmark_id in cross_surface_gates
        else:
            cross_surface_enforced = None
        rows.append(
            {
                "benchmark": benchmark_id,
                "surfaces": surfaces,
                "dual_surface": dual_surface,
                "oracles": oracles,
                "primary_oracle": primary,
                "strength": strength,
                "scale": scale,
                "guarded": primary != ORACLE_NONE,
                "cross_surface_enforced": cross_surface_enforced,
                "cross_surface_applicable": dual_surface and primary == ORACLE_NONE,
            }
        )
    return rows


def _enforcement_label(row: dict[str, Any]) -> str:
    """Honesty signal for a cross-surface gate: CI-enforced vs merely registered.

    ``cross_surface_enforced`` is ``True`` for an enforced (CI-blocking) gate,
    ``False`` for a STAGED (registered-but-not-run-in-CI) gate, and ``None`` when
    the benchmark has no cross-surface gate. Only an enforced gate is green-or-
    CI-fails; a staged gate's registration proves nothing about correctness.
    """
    enforced = row.get("cross_surface_enforced")
    if enforced is True:
        return "enforced (CI-blocking)"
    if enforced is False:
        return "staged (NOT CI-enforced)"
    return "—"


def render_markdown(rows: list[dict[str, Any]]) -> str:
    guarded = [r for r in rows if r["guarded"]]
    unguarded = [r for r in rows if not r["guarded"]]
    dispatchable = [r for r in unguarded if r["cross_surface_applicable"]]
    single_surface_gap = [r for r in unguarded if not r["cross_surface_applicable"]]
    enforced_cross_surface = [r for r in rows if r.get("cross_surface_enforced") is True]
    staged_cross_surface = [r for r in rows if r.get("cross_surface_enforced") is False]

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
        "**What an oracle here means.** A benchmark is listed as *guarded* when an "
        "oracle is REGISTERED for it — it is **not** a claim that the oracle is "
        "currently green. The distinction matters most for cross-surface gates: only "
        "a gate in the enforced `GATES` registry is run as a CI-blocking step (so it "
        "is green or CI fails); a gate in `STAGED_GATES` is registered but not run "
        "in CI, so its registration proves nothing about correctness. The "
        "**Enforced** column reports this *cross-surface* enforcement status: "
        "`enforced (CI-blocking)`, `staged (NOT CI-enforced)`, or `—` for any "
        "benchmark that is not cross-surface-gated. A `—` therefore says nothing "
        "about whether a *non*-cross-surface oracle is enforced: the expected-results "
        "(tpch, tpcds) and TPC-Havoc variant oracles are CI-enforced via their own "
        "test suites despite showing `—` here."
    )
    lines.append("")
    lines.append(
        f"**Summary:** {len(rows)} shipped benchmarks — {len(guarded)} guarded "
        f"(oracle registered), {len(unguarded)} UNGUARDED ({len(dispatchable)} "
        f"reachable by the cross-surface gate, {len(single_surface_gap)} "
        f"single-surface needing a fallback oracle). Cross-surface gates: "
        f"{len(enforced_cross_surface)} CI-enforced, {len(staged_cross_surface)} "
        f"staged (not CI-enforced)."
    )
    lines.append("")
    lines.append(
        "**Strength + scale disclosure:** a guarded cell is not a uniform guarantee. "
        "The **Strength** column says what the oracle proves — `value-level` (full "
        "result values compared) vs `cardinality-only` (row counts only) vs "
        "`value+cardinality` (both) — and the **Scale** column says at which scale it "
        "actually holds. Both are derived from live sources (the provider's stored "
        "answers/digests and the equivalence gate's bounded scale), not hand-labelled. "
        "No expected-results oracle exists above SF=1 (the loader raises for other "
        "scales), so `tpch`/`tpcds` values are unguarded above SF=1."
    )
    lines.append("")
    lines.append("| Benchmark | Surfaces | Oracle | Strength | Scale | Enforced | Notes |")
    lines.append("| --- | --- | --- | --- | --- | --- | --- |")
    for r in rows:
        surfaces = "+".join(r["surfaces"]) or "—"
        oracle = r["primary_oracle"]
        if r["guarded"]:
            note = ", ".join(r["oracles"])
            # M1 honesty: a STAGED cross-surface gate is registered but not run in
            # CI, so spell that out in the row note too -- never let the Oracle
            # column alone imply a verified gate.
            if r.get("cross_surface_enforced") is False:
                note += " (registered, NOT CI-enforced)"
        elif r["cross_surface_applicable"]:
            note = "dual-surface → dispatch to cross-surface gate (w1)"
        else:
            note = "single-surface → needs fallback oracle (w2)"
        enforced = _enforcement_label(r)
        lines.append(
            f"| {r['benchmark']} | {surfaces} | {oracle} | {r['strength']} | {r['scale']} | {enforced} | {note} |"
        )
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


# Provenance is stamped into a leading HTML-comment region of the markdown that the
# drift check IGNORES (see _strip_provenance / check_artifacts). It carries the
# generation date + reviewed git SHA so a reader of the out-of-band artifact can tell
# whether it predates current develop -- WITHOUT putting a volatile SHA into the
# drift-compared body (which would make `--check` churn on every commit).
_PROVENANCE_START = "<!-- PROVENANCE"
_PROVENANCE_END = "-->"


def _current_git_sha() -> str:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:  # pragma: no cover - provenance is best-effort
        pass
    return "unknown"


def _provenance_header() -> str:
    import datetime

    generated = datetime.date.today().isoformat()
    return (
        f"{_PROVENANCE_START}\n"
        f"generated: {generated}\n"
        f"revision: {_current_git_sha()}\n"
        "This header is drift-IGNORED by `--check` (see _strip_provenance); it records when\n"
        "this generated artifact was last written so a reviewer can tell if it predates\n"
        "current develop. Do not rely on it for diffs.\n"
        f"{_PROVENANCE_END}\n"
    )


def _strip_provenance(text: str) -> str:
    """Remove a leading provenance HTML-comment region so drift compares only the body."""
    if not text.startswith(_PROVENANCE_START):
        return text
    end = text.find(_PROVENANCE_END)
    if end == -1:
        return text
    rest = text[end + len(_PROVENANCE_END) :]
    return rest.lstrip("\n")


def write_artifacts(rows: list[dict[str, Any]]) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    JSON_ARTIFACT.write_text(render_json(rows), encoding="utf-8")
    MARKDOWN_ARTIFACT.write_text(_provenance_header() + render_markdown(rows), encoding="utf-8")


def check_artifacts(rows: list[dict[str, Any]]) -> list[str]:
    """Return a list of human-readable drift problems (empty == in sync).

    The markdown's provenance header is stripped before comparison so a refreshed
    date/SHA never makes the drift check churn; only the generated body must match.
    """
    problems: list[str] = []
    checks = (
        (JSON_ARTIFACT, render_json(rows), False),
        (MARKDOWN_ARTIFACT, render_markdown(rows), True),
    )
    for path, expected, strip in checks:
        if not path.exists():
            problems.append(f"missing artifact: {path.relative_to(_REPO_ROOT)} (run the generator)")
            continue
        actual = path.read_text(encoding="utf-8")
        if strip:
            actual = _strip_provenance(actual)
        if actual != expected:
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
