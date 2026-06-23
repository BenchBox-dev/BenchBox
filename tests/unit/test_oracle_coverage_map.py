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
    STRENGTH_CARDINALITY,
    STRENGTH_NONE,
    STRENGTH_VALUE,
    STRENGTH_VALUE_AND_CARDINALITY,
    build_coverage_map,
    check_artifacts,
    oracle_strength_and_scale,
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


# --- Strength + scale disclosure (oracle-coverage-map-strength-disclosure) ---


def test_strength_and_scale_columns_present(rows):
    """Every row carries a strength + scale field (the new disclosure axes)."""
    for r in rows:
        assert "strength" in r and r["strength"], f"{r['benchmark']} missing strength"
        assert "scale" in r and r["scale"], f"{r['benchmark']} missing scale"
        # Unguarded rows disclose no guarantee on either axis.
        if not r["guarded"]:
            assert r["strength"] == STRENGTH_NONE, f"{r['benchmark']} unguarded but strength={r['strength']}"


def test_known_oracle_strength_and_scale_truth(rows):
    """Pin the TRUTH of strength + scale for known oracles (classifier-truth, w4).

    The drift test only proves committed == regenerated (consistency). This pins
    what each known oracle ACTUALLY proves, so a future change that mislabels an
    oracle's strength/scale fails here even if the artifact is internally consistent.
    """
    by_id = {r["benchmark"]: r for r in rows}

    # expected-results: cardinality-only by default; TPC-H carries stored VALUE
    # digests (bounded-correctness-gate value oracle), so it reads value+cardinality.
    # Both hold only at SF=1 (the loader raises for other scales).
    assert by_id["tpch"]["strength"] == STRENGTH_VALUE_AND_CARDINALITY
    assert by_id["tpch"]["scale"] == "SF=1"
    assert by_id["tpcds"]["strength"] == STRENGTH_CARDINALITY
    assert by_id["tpcds"]["scale"] == "SF=1"

    # cross-surface / variant gates compare full result VALUES at the bounded scale.
    for benchmark in ("ssb", "amplab", "coffeeshop", "tpchavoc"):
        assert by_id[benchmark]["strength"] == STRENGTH_VALUE, f"{benchmark} should be value-level"
        assert by_id[benchmark]["scale"].startswith("SF="), f"{benchmark} missing bounded scale"


def test_expected_results_strength_is_derived_not_hardcoded(monkeypatch):
    """The expected-results strength must track the provider's real digest capability.

    Flipping the live signal (stored value digests present/absent) must flip the
    label, proving it is derived rather than a hand-maintained constant.
    """
    import _project.scripts.generate_oracle_coverage_map as gen

    monkeypatch.setattr(gen, "_expected_results_has_value_digests", lambda _b: True)
    strength, scale = oracle_strength_and_scale(ORACLE_EXPECTED_RESULTS, "tpch")
    assert strength == STRENGTH_VALUE_AND_CARDINALITY
    assert scale == "SF=1"

    monkeypatch.setattr(gen, "_expected_results_has_value_digests", lambda _b: False)
    strength, _ = oracle_strength_and_scale(ORACLE_EXPECTED_RESULTS, "tpch")
    assert strength == STRENGTH_CARDINALITY


def test_value_level_oracle_scale_is_read_live(rows):
    """Value-level gate scale must equal the equivalence module's bounded scale."""
    from benchbox.core.equivalence.cross_surface import EQUIVALENCE_SCALE

    by_id = {r["benchmark"]: r for r in rows}
    assert by_id["ssb"]["scale"] == f"SF={EQUIVALENCE_SCALE}"


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
