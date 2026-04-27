"""Unit tests for runtime tuning helpers."""

from __future__ import annotations

import pytest

from benchbox.cli.tuning_runtime import build_baseline_unified_config, infer_runtime_tuning_mode
from benchbox.core.tuning.interface import TuningType, UnifiedTuningConfiguration

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_infer_runtime_tuning_mode_reports_baseline_as_notuning() -> None:
    config = build_baseline_unified_config()

    enabled, mode = infer_runtime_tuning_mode(config)

    assert enabled is False
    assert mode == "notuning"


def test_infer_runtime_tuning_mode_reports_none_as_notuning() -> None:
    enabled, mode = infer_runtime_tuning_mode(None)

    assert enabled is False
    assert mode == "notuning"


def test_infer_runtime_tuning_mode_reports_enabled_config_as_tuned() -> None:
    config = UnifiedTuningConfiguration()
    config.enable_primary_keys()

    enabled, mode = infer_runtime_tuning_mode(config)

    assert enabled is True
    assert mode == "tuned"


def test_infer_runtime_tuning_mode_reports_platform_optimization_as_tuned() -> None:
    config = UnifiedTuningConfiguration()
    config.enable_platform_optimization(TuningType.Z_ORDERING)

    enabled, mode = infer_runtime_tuning_mode(config)

    assert enabled is True
    assert mode == "tuned"
