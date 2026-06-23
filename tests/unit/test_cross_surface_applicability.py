"""Lock the cross-surface applicability finding (benchmark-cross-surface-equivalence-gate w2).

The sweep distinguishes dual-surface benchmarks that ship comparable DataFrame
*queries* (cross-surface gateable) from those that only support DataFrame
*loading* (`supports_dataframe=True` but no DataFrame query surface -> need a w2
fallback oracle). These tests pin the current gateable set and keep the committed
artifact honest. Marked ``medium`` because resolving applicability instantiates
every candidate benchmark.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from _project.scripts.cross_surface_applicability_sweep import (  # noqa: E402
    ARTIFACT,
    BLOCKED,
    CANDIDATE_UNVERIFIED,
    GATEABLE,
    NO_DF_QUERY_SURFACE,
    build_applicability_sweep,
    render_markdown,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

# Benchmarks that ship NO DataFrame query registry, so the cross-surface gate
# cannot reach them - they need a w2 fallback oracle (differential second-engine
# or curated expected-results). This is the stable, meaningful invariant: if a
# benchmark gains a DataFrame query registry it should drop off this list (and
# become gateable), and a new benchmark without one should be added deliberately.
_W2_FALLBACK_BENCHMARKS = {"metadata_primitives", "tpcdi", "transaction_primitives", "write_primitives"}


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return build_applicability_sweep()


def test_w2_fallback_set_is_exactly_the_registry_less_benchmarks(rows):
    """Only benchmarks with no DataFrame query registry are dispatched to a w2 fallback.

    Registry detection (not the production resolver) is the gate-applicability
    signal: e.g. coffeeshop ships a registry and was gated in #842, even though the
    resolver returned zero for it.
    """
    no_surface = {r["benchmark"] for r in rows if r["status"] == NO_DF_QUERY_SURFACE}
    assert no_surface == _W2_FALLBACK_BENCHMARKS, f"w2-fallback set changed: {sorted(no_surface)}"


# Benchmarks whose DataFrame registry has ZERO verbatim id overlap with the SQL
# ids: there is no VERIFIED SQL<->DataFrame query correspondence, so they are
# `candidate-unverified` (honest M2 classification), NOT gateable. Wiring a gate
# would require guessing an id mapping, which the campaign TODO forbids. (amplab,
# clickbench, joinorder_synthetic were previously here; all are now enforced
# cross-surface gates, so they no longer appear among the unguarded candidates.)
_CANDIDATE_UNVERIFIED_BENCHMARKS = {"datavault", "nyctaxi", "tpcds_obt", "tpch_skew", "tsbs_devops"}


def test_registry_bearing_benchmarks_are_gateable(rows):
    """h2odb (verified verbatim overlap) is gateable; a zero-overlap registry is not."""
    by_id = {r["benchmark"]: r["status"] for r in rows}
    assert by_id.get("h2odb") == GATEABLE
    # datavault ships a registry but its ids do not overlap the SQL ids verbatim
    # (friendly/Q-prefixed names), so there is no verified correspondence: it is
    # candidate-unverified, NOT counted as gateable coverage.
    assert by_id.get("datavault") == CANDIDATE_UNVERIFIED


def test_zero_overlap_registries_are_candidate_unverified_not_gateable(rows):
    """An unverified id mapping is never counted as gateable coverage (M2 honesty).

    Each of these ships a DataFrame query registry but with ZERO verbatim id
    overlap, so a gate would require guessing the SQL<->DataFrame mapping. They
    must be classified `candidate-unverified`, never `gateable`.
    """
    unverified = {r["benchmark"] for r in rows if r["status"] == CANDIDATE_UNVERIFIED}
    assert unverified == _CANDIDATE_UNVERIFIED_BENCHMARKS, f"candidate-unverified set changed: {sorted(unverified)}"
    gateable = {r["benchmark"] for r in rows if r["status"] == GATEABLE}
    assert _CANDIDATE_UNVERIFIED_BENCHMARKS.isdisjoint(gateable), "a zero-overlap benchmark was counted as gateable"


def test_no_candidate_is_silently_dropped(rows):
    """Every candidate is classified into a known status."""
    assert rows, "applicability sweep produced no candidates"
    for r in rows:
        assert r["status"] in {GATEABLE, CANDIDATE_UNVERIFIED, NO_DF_QUERY_SURFACE, BLOCKED}, r


def test_committed_artifact_is_current(rows):
    """The checked-in sweep artifact must match a fresh run."""
    assert ARTIFACT.exists(), f"missing {ARTIFACT}"
    assert ARTIFACT.read_text(encoding="utf-8") == render_markdown(rows), (
        "cross-surface applicability artifact is stale; run `make cross-surface-applicability-report` and commit"
    )
