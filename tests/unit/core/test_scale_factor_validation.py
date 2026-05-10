"""Tests for the registry-driven scale-factor enforcement gate.

w3 of joinorder-canonical-foundation tightens
``benchbox.core.benchmark_registry.validate_scale_factor`` so that
benchmarks declaring ``scale_options`` reject any non-listed scale.
The gate raises ``ScaleFactorNotSupportedError`` (subclass of
``ValueError`` so legacy ``except ValueError`` paths keep working).

joinorder is the motivating case: ``scale_options=[1.0]`` rejects
sf!=1.0 and points users at the canonical scale.
"""

from __future__ import annotations

import pytest

from benchbox.core.benchmark_registry import (
    BENCHMARK_METADATA,
    validate_scale_factor,
)
from benchbox.core.errors import ScaleFactorNotSupportedError

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_joinorder_accepts_canonical_unit_scale() -> None:
    # sf=1.0 is the only canonical scale; both float and int literals work.
    validate_scale_factor("joinorder", 1.0)
    validate_scale_factor("joinorder", 1)


def test_joinorder_rejects_non_unit_scale() -> None:
    """Verification command target: foundation w3."""
    with pytest.raises(ScaleFactorNotSupportedError) as excinfo:
        validate_scale_factor("joinorder", 0.5)
    assert excinfo.value.benchmark_id == "joinorder"
    assert excinfo.value.scale_factor == 0.5
    assert excinfo.value.scale_options == [1.0]
    # Subclasses ValueError so legacy callers still catch it.
    assert isinstance(excinfo.value, ValueError)


@pytest.mark.parametrize("bad_sf", [0.0, 0.01, 0.5, 1.5, 2.0, 10.0, -1.0])
def test_joinorder_rejects_arbitrary_scales(bad_sf: float) -> None:
    with pytest.raises(ScaleFactorNotSupportedError):
        validate_scale_factor("joinorder", bad_sf)


@pytest.mark.parametrize("sf", [0.01, 0.1, 1.0, 10.0])
def test_tpch_accepts_declared_scale_options(sf: float) -> None:
    """tpch declares scale_options=[0.01, 0.1, 1.0, 10.0]; each must pass."""
    validate_scale_factor("tpch", sf)


def test_tpch_rejects_undeclared_scale() -> None:
    """sf=0.5 is not in tpch's scale_options; gate must reject."""
    with pytest.raises(ScaleFactorNotSupportedError):
        validate_scale_factor("tpch", 0.5)


def test_tpcds_obt_rejects_subscale() -> None:
    """tpcds_obt scale_options=[1.0] — same single-element pattern as joinorder."""
    with pytest.raises(ScaleFactorNotSupportedError, match=r"tpcds_obt accepts scale_factor in"):
        validate_scale_factor("tpcds_obt", 0.5)


def test_tpcds_delegates_to_compliance_classifier() -> None:
    """tpcds keeps its dedicated compliance path; the registry gate must NOT
    raise ScaleFactorNotSupportedError for tpcds. The compliance classifier
    is responsible for deciding (un)official tier classification."""
    # sf=1.0 is one of tpcds's listed scale_options; the compliance classifier
    # treats it as UNOFFICIAL_NONSTANDARD without an "official" flag, but it
    # does not raise from validate_scale_factor (delegation contract).
    validate_scale_factor("tpcds", 1.0)


@pytest.mark.parametrize(
    "benchmark_id",
    [bid for bid, meta in BENCHMARK_METADATA.items() if "scale_options" in meta and bid != "tpcds"],
)
def test_every_benchmark_accepts_first_declared_scale(benchmark_id: str) -> None:
    """Regression guard: every registered benchmark with scale_options must
    accept its FIRST declared scale (e.g., default for the UI). Prevents a
    drift where someone tightens validation without aligning the option list.
    """
    sf = float(BENCHMARK_METADATA[benchmark_id]["scale_options"][0])
    validate_scale_factor(benchmark_id, sf)


def test_unknown_benchmark_skips_validation() -> None:
    """Defensive default: unknown benchmark ids do not raise (the runner
    surfaces a 'no such benchmark' error elsewhere)."""
    validate_scale_factor("does-not-exist", 999.0)


def test_float_tolerance_accepts_imperceptible_drift() -> None:
    """Float comparison uses 1e-9 tolerance — a difference well below
    that threshold (e.g., from JSON round-trip, numpy widening) must
    still match the canonical scale."""
    # 1.0 + 1e-12 is FAR inside the 1e-9 tolerance window.
    validate_scale_factor("joinorder", 1.0 + 1e-12)


def test_float_tolerance_rejects_perceptible_drift() -> None:
    """Drift greater than the 1e-9 tolerance must reject — a user
    typo of `1.0001` for joinorder is not silently accepted."""
    with pytest.raises(ScaleFactorNotSupportedError):
        validate_scale_factor("joinorder", 1.0001)
