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

from benchbox.core.benchmark_registry import (
    BENCHMARK_METADATA,
    get_benchmark_surface,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.parametrize("benchmark_id", sorted(BENCHMARK_METADATA.keys()))
def test_existing_benchmarks_default_to_public(benchmark_id: str) -> None:
    """Regression guard: any benchmark NOT explicitly marked internal must
    appear public. Foundation is additive — no behavior change for existing
    entries.
    """
    surface = get_benchmark_surface(benchmark_id)
    declared = BENCHMARK_METADATA[benchmark_id].get("surface")
    if declared == "internal":
        assert surface == "internal"
    else:
        assert surface == "public"


def test_unregistered_benchmark_defaults_public() -> None:
    """Defensive default for ids not in BENCHMARK_METADATA."""
    assert get_benchmark_surface("does-not-exist") == "public"


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
    with patch.dict(BENCHMARK_METADATA, fake_meta, clear=False):
        assert get_benchmark_surface("x_internal") == "internal"


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
    with patch.dict(BENCHMARK_METADATA, fake_meta, clear=False):
        assert get_benchmark_surface("x_public") == "public"
