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
    build_applicability_sweep,
    render_markdown,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return build_applicability_sweep()


def test_only_clickbench_and_joinorder_synthetic_are_gateable(rows):
    """Exactly the two benchmarks that ship DataFrame queries are cross-surface gateable.

    If this set changes (a benchmark gains/loses a DataFrame query surface), update
    the sweep artifact and the cross-surface gate dispatch deliberately.
    """
    gateable = {r["benchmark"] for r in rows if r["status"] == "gateable"}
    assert gateable == {"clickbench", "joinorder_synthetic"}, f"cross-surface gateable set changed: {sorted(gateable)}"


def test_no_candidate_is_silently_dropped(rows):
    """Every candidate is classified (gateable / no-df-query-surface / blocked)."""
    assert rows, "applicability sweep produced no candidates"
    for r in rows:
        assert r["status"] in {"gateable", "no-df-query-surface", "blocked"}, r


def test_committed_artifact_is_current(rows):
    """The checked-in sweep artifact must match a fresh run."""
    assert ARTIFACT.exists(), f"missing {ARTIFACT}"
    assert ARTIFACT.read_text(encoding="utf-8") == render_markdown(rows), (
        "cross-surface applicability artifact is stale; run `make cross-surface-applicability-report` and commit"
    )
