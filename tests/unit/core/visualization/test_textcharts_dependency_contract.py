"""Package-install and compatibility contract for the retained textcharts dependency."""

from __future__ import annotations

import importlib
from importlib.metadata import version
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_textcharts_is_installed_and_legacy_shim_delegates() -> None:
    package = importlib.import_module("textcharts")
    from benchbox.core.visualization.ascii.bar_chart import BarChart

    assert version("textcharts")
    assert BarChart is package.BarChart


def test_textcharts_remains_a_core_manifest_dependency() -> None:
    manifest = (Path(__file__).resolve().parents[4] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"textcharts>=0.1.0"' in manifest
