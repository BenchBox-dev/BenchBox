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
