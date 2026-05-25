"""Tests for the registry's `surface` visibility field.

Foundation w3 introduces a `surface: "public" | "internal"` registry
field. Default is "public" so existing benchmarks see no behavior
change. Cutover TODO uses "internal" for joinorder_synthetic to hide
it from the result-publisher's public surface without explorer UI
changes.

This test file ships with foundation w3; cutover adds joinorder_synthetic
and the per-benchmark surface assertion (test_joinorder_synthetic_hidden,
referenced by cutover's verification).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from benchbox.core import benchmark_registry

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.parametrize("benchmark_id", sorted(benchmark_registry.BENCHMARK_METADATA.keys()))
def test_existing_benchmarks_default_to_public(benchmark_id: str) -> None:
    """Regression guard: any benchmark NOT explicitly marked internal must
    appear public. Foundation is additive — no behavior change for existing
    entries.
    """
    surface = benchmark_registry.get_benchmark_surface(benchmark_id)
    declared = benchmark_registry.BENCHMARK_METADATA[benchmark_id].get("surface")
    if declared == "internal":
        assert surface == "internal"
    else:
        assert surface == "public"


def test_unregistered_benchmark_defaults_public() -> None:
    """Defensive default for ids not in BENCHMARK_METADATA."""
    assert benchmark_registry.get_benchmark_surface("does-not-exist") == "public"


def test_internal_surface_recognized() -> None:
    """A benchmark marked internal is surfaced as 'internal' by the helper."""
    fake_meta = {
        "x_internal": {
            "display_name": "Internal Test",
            "description": "test",
            "category": "Test",
            "num_queries": 0,
            "query_description": "n/a",
            "supports_streams": False,
            "default_scale": 1.0,
            "scale_options": [1.0],
            "min_scale": 1.0,
            "complexity": "Low",
            "estimated_time_range": (0, 0),
            "supports_dataframe": False,
            "surface": "internal",
        }
    }
    with patch.dict(benchmark_registry.BENCHMARK_METADATA, fake_meta, clear=False):
        assert benchmark_registry.get_benchmark_surface("x_internal") == "internal"


def test_public_surface_recognized() -> None:
    """Explicitly setting surface=public is equivalent to omitting the field."""
    fake_meta = {
        "x_public": {
            "display_name": "Public Test",
            "description": "test",
            "category": "Test",
            "num_queries": 0,
            "query_description": "n/a",
            "supports_streams": False,
            "default_scale": 1.0,
            "scale_options": [1.0],
            "min_scale": 1.0,
            "complexity": "Low",
            "estimated_time_range": (0, 0),
            "supports_dataframe": False,
            "surface": "public",
        }
    }
    with patch.dict(benchmark_registry.BENCHMARK_METADATA, fake_meta, clear=False):
        assert benchmark_registry.get_benchmark_surface("x_public") == "public"


def test_joinorder_synthetic_hidden() -> None:
    """The cutover's synthetic compatibility surface is not public."""
    assert benchmark_registry.get_benchmark_surface("joinorder_synthetic") == "internal"


def test_public_benchmark_ids_exclude_joinorder_synthetic() -> None:
    """Public discovery helpers omit internal benchmark surfaces."""
    public_ids = benchmark_registry.list_public_benchmark_ids()

    assert "joinorder" in public_ids
    assert "joinorder_synthetic" not in public_ids


def _synthetic_meta(support_status: str, surface: str, *, supports_dataframe: bool = False) -> dict[str, object]:
    """Build a metadata entry for a hypothetical future benchmark."""
    return {
        "display_name": f"Synthetic {support_status}/{surface}",
        "description": "synthetic future-status fixture",
        "category": "Test",
        "num_queries": 0,
        "query_description": "n/a",
        "supports_streams": False,
        "default_scale": 1.0,
        "scale_options": [1.0],
        "min_scale": 1.0,
        "complexity": "Low",
        "estimated_time_range": (0, 0),
        "supports_dataframe": supports_dataframe,
        "support_status": support_status,
        "surface": surface,
    }


@pytest.mark.parametrize("support_status", sorted(benchmark_registry.BENCHMARK_SUPPORT_STATUS_VALUES))
def test_surface_gates_discovery_independent_of_support_status(support_status: str) -> None:
    """`surface` alone controls public discovery; `support_status` never hides or reveals.

    Future-proofing invariant: a benchmark of ANY support tier is listed when
    public and hidden when internal. Visibility must not be repurposed onto the
    status field.
    """
    fixtures = {
        "x_future_public": _synthetic_meta(support_status, "public"),
        "x_future_internal": _synthetic_meta(support_status, "internal"),
    }
    with patch.dict(benchmark_registry.BENCHMARK_METADATA, fixtures, clear=False):
        public_ids = benchmark_registry.list_public_benchmark_ids()
        assert "x_future_public" in public_ids, f"public {support_status} benchmark must be discoverable"
        assert "x_future_internal" not in public_ids, f"internal {support_status} benchmark must be hidden"
        assert benchmark_registry.get_benchmark_support_status("x_future_public") == support_status
        assert benchmark_registry.get_benchmark_support_status("x_future_internal") == support_status


def test_supports_dataframe_independent_of_support_status() -> None:
    """The DataFrame capability flag is read directly, never inferred from support tier."""
    fixtures = {
        "x_experimental_df": _synthetic_meta("experimental", "public", supports_dataframe=True),
        "x_stable_nodf": _synthetic_meta("stable", "public", supports_dataframe=False),
    }
    with patch.dict(benchmark_registry.BENCHMARK_METADATA, fixtures, clear=False):
        assert benchmark_registry.BENCHMARK_METADATA["x_experimental_df"]["supports_dataframe"] is True
        assert benchmark_registry.BENCHMARK_METADATA["x_stable_nodf"]["supports_dataframe"] is False
