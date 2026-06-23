"""Guards for the benchmark correctness-oracle coverage map (w0/w3).

These keep the generated map (``_project/analysis/oracle-coverage-map.{md,json}``)
honest and current:

  - drift: the checked-in artifacts must match a fresh regeneration, so the map
    cannot silently fall behind the registry / gates;
  - completeness: every shipped benchmark is classified;
  - exemplars: the known oracles (tpch/tpcds expected-results, tpchavoc variant
    gate, ssb cross-surface) stay classified as such (locks in must_preserve);
  - new-benchmark visibility: a newly added benchmark with no oracle changes the
    generated map, which trips the drift check — forcing the author to regenerate
    and consciously record it as UNGUARDED rather than discovering it later.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# The generator lives in _project/scripts (a project tool, not shipped in the
# package); ensure the repo root is importable so `_project.scripts` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _project.scripts.generate_oracle_coverage_map import (  # noqa: E402
    ORACLE_CROSS_SURFACE,
    ORACLE_EXPECTED_RESULTS,
    ORACLE_NONE,
    ORACLE_VARIANT_EQUIVALENCE,
    build_coverage_map,
    check_artifacts,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return build_coverage_map()


def test_checked_in_artifacts_are_current(rows):
    """The committed map must match a fresh regeneration (run the generator + commit)."""
    problems = check_artifacts(rows)
    assert not problems, "oracle coverage map is stale:\n" + "\n".join(problems)


def test_every_shipped_benchmark_is_classified(rows):
    """Every registry benchmark appears exactly once with a primary oracle."""
    from benchbox.core.benchmark_registry import list_benchmark_ids

    mapped = {r["benchmark"] for r in rows}
    assert mapped == set(list_benchmark_ids()), "coverage map and registry disagree on benchmark set"
    assert len(rows) == len(mapped), "duplicate benchmark rows in coverage map"
    for r in rows:
        assert r["primary_oracle"], f"{r['benchmark']} has no primary_oracle classification"
        assert (r["primary_oracle"] == ORACLE_NONE) == (not r["guarded"]), (
            f"{r['benchmark']} guarded/primary_oracle disagree"
        )


def test_known_oracles_stay_classified(rows):
    """The existing oracles must remain recognized (must_preserve)."""
    by_id = {r["benchmark"]: r for r in rows}
    assert ORACLE_EXPECTED_RESULTS in by_id["tpch"]["oracles"]
    assert ORACLE_EXPECTED_RESULTS in by_id["tpcds"]["oracles"]
    assert ORACLE_VARIANT_EQUIVALENCE in by_id["tpchavoc"]["oracles"]
    assert ORACLE_CROSS_SURFACE in by_id["ssb"]["oracles"]


def test_cross_surface_applicable_implies_dual_surface_and_unguarded(rows):
    """The w1 dispatch flag must be self-consistent."""
    for r in rows:
        if r["cross_surface_applicable"]:
            assert r["dual_surface"], f"{r['benchmark']} flagged cross-surface but is single-surface"
            assert not r["guarded"], f"{r['benchmark']} flagged cross-surface but already guarded"


def test_cross_surface_enforced_distinguishes_registered_from_verified_green(rows):
    """A cross-surface gate's CI-enforcement (M1 honesty) is recorded and accurate.

    ``cross_surface_enforced`` separates a CI-enforced (blocking, hence green-or-
    CI-fails) gate from one merely registered: it is ``True`` for gates in the
    enforced ``GATES`` registry, ``False`` for ``STAGED_GATES`` (registered but not
    run in CI), and ``None`` for benchmarks with no cross-surface gate. Mere
    registration must never be reported as enforced coverage.
    """
    from benchbox.core.equivalence.cross_surface import GATES, STAGED_GATES

    by_id = {r["benchmark"]: r for r in rows}
    for benchmark_id in GATES:
        assert by_id[benchmark_id]["cross_surface_enforced"] is True, (
            f"{benchmark_id} is in enforced GATES but not reported as CI-enforced"
        )
    for benchmark_id in STAGED_GATES:
        assert by_id[benchmark_id]["cross_surface_enforced"] is False, (
            f"{benchmark_id} is STAGED (not CI-enforced) but reported as enforced"
        )
    # The currently-enforced cross-surface gates must be reported as such.
    assert {"ssb", "coffeeshop", "amplab", "clickbench", "joinorder_synthetic"} <= set(GATES), (
        "expected enforced cross-surface gate set changed; update the coverage-map honesty test"
    )
    for r in rows:
        # A non-cross-surface benchmark carries no enforcement signal.
        if ORACLE_CROSS_SURFACE not in r["oracles"]:
            assert r["cross_surface_enforced"] is None, (
                f"{r['benchmark']} has no cross-surface gate but carries an enforcement flag"
            )
