"""Unit tests for TPC-DS compliance classification.

Tests classify_tpcds_run, validate_tpcds_scale, and TpcdsComplianceClass
across all three enum values × official flag combinations, plus the compatibility
parameter and minimum-scale gate.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import pytest

from benchbox.core.tpcds.compliance import (
    OFFICIAL_SCALE_POINTS,
    TPCDS_MIN_SUBSCALE,
    TpcdsComplianceClass,
    classify_tpcds_run,
    validate_tpcds_scale,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# classify_tpcds_run
# ---------------------------------------------------------------------------


class TestClassifyTpcdsRun:
    """Tests for classify_tpcds_run across all three class × official combos."""

    def test_official_sf1_with_official_flag(self):
        assert classify_tpcds_run(1.0, official=True) is TpcdsComplianceClass.OFFICIAL

    def test_official_sf10_with_official_flag(self):
        assert classify_tpcds_run(10.0, official=True) is TpcdsComplianceClass.OFFICIAL

    def test_official_sf100_with_official_flag(self):
        assert classify_tpcds_run(100.0, official=True) is TpcdsComplianceClass.OFFICIAL

    def test_all_official_scale_points_are_official(self):
        for sf in OFFICIAL_SCALE_POINTS:
            result = classify_tpcds_run(sf, official=True)
            assert result is TpcdsComplianceClass.OFFICIAL, f"SF={sf} should be OFFICIAL"

    def test_sf1_without_official_flag_is_nonstandard(self):
        assert classify_tpcds_run(1.0, official=False) is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_sf10_without_official_flag_is_nonstandard(self):
        assert classify_tpcds_run(10.0, official=False) is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_non_official_scale_point_with_official_flag_is_nonstandard(self):
        # SF=2.0 is not an official TPC-DS scale point
        assert classify_tpcds_run(2.0, official=True) is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_subscale_is_unofficial_subscale_regardless_of_official_flag(self):
        assert classify_tpcds_run(0.5, official=False) is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE
        assert classify_tpcds_run(0.5, official=True) is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_subscale_just_below_one(self):
        assert classify_tpcds_run(0.999) is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_minimum_subscale(self):
        assert classify_tpcds_run(TPCDS_MIN_SUBSCALE) is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_default_official_flag_is_false(self):
        # classify_tpcds_run(sf) with no official kwarg should behave as official=False
        assert classify_tpcds_run(1.0) is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD
        assert classify_tpcds_run(0.5) is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE


# ---------------------------------------------------------------------------
# validate_tpcds_scale - minimum-scale gate
# ---------------------------------------------------------------------------


class TestValidateTpcdsScale:
    """Tests for validate_tpcds_scale minimum-scale gate."""

    def test_subscale_returns_subscale_class(self):
        result = validate_tpcds_scale(0.5)
        assert result is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_sf_above_one_returns_nonstandard_class(self):
        result = validate_tpcds_scale(1.0)
        assert result is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_minimum_subscale_accepted(self):
        result = validate_tpcds_scale(TPCDS_MIN_SUBSCALE)
        assert result is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_below_minimum_subscale_raises(self):
        below_min = TPCDS_MIN_SUBSCALE / 10.0
        with pytest.raises(ValueError, match="minimum subscale"):
            validate_tpcds_scale(below_min)

    def test_zero_scale_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            validate_tpcds_scale(0.0)

    def test_negative_scale_raises(self):
        with pytest.raises(ValueError, match="must be positive"):
            validate_tpcds_scale(-1.0)

    def test_exceeds_maximum_raises(self):
        with pytest.raises(ValueError, match="exceeds maximum"):
            validate_tpcds_scale(100001.0)

    def test_official_scale_point_returns_nonstandard_without_official_flag(self):
        # validate_tpcds_scale has no "official" parameter; classify_tpcds_run default is False
        result = validate_tpcds_scale(1.0)
        assert result is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_tpcds_obt_still_requires_scale_one_or_greater(self):
        from benchbox.core.benchmark_registry import validate_scale_factor as validate_registry_scale_factor
        from benchbox.core.errors import ScaleFactorNotSupportedError

        # tpcds_obt declares scale_options=[1.0]; the registry-side gate
        # now enforces strict membership and raises ScaleFactorNotSupportedError
        # (subclass of ValueError, so legacy `except ValueError` callers keep
        # working).
        with pytest.raises(ScaleFactorNotSupportedError, match=r"tpcds_obt accepts scale_factor in \[1\.0\]"):
            validate_registry_scale_factor("tpcds_obt", 0.5)


# ---------------------------------------------------------------------------
# TpcdsComplianceClass enum properties
# ---------------------------------------------------------------------------


class TestTpcdsComplianceClassEnum:
    """TpcdsComplianceClass inherits str - string comparisons must work."""

    def test_enum_values_are_strings(self):
        assert TpcdsComplianceClass.OFFICIAL == "official"
        assert TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD == "unofficial_nonstandard"
        assert TpcdsComplianceClass.UNOFFICIAL_SUBSCALE == "unofficial_subscale"

    def test_enum_is_in_set_by_string_value(self):
        unofficial_classes = {"unofficial_nonstandard", "unofficial_subscale"}
        assert TpcdsComplianceClass.UNOFFICIAL_SUBSCALE in unofficial_classes
        assert TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD in unofficial_classes
        assert TpcdsComplianceClass.OFFICIAL not in unofficial_classes

    def test_value_attribute_matches_string(self):
        assert TpcdsComplianceClass.OFFICIAL.value == "official"
        assert TpcdsComplianceClass.UNOFFICIAL_SUBSCALE.value == "unofficial_subscale"


class TestOfficialFlagReachesTheClassifier:
    """Guard the wiring, not just the pure function.

    `classify_tpcds_run` was always correct, but no production caller passed
    `official=True`: `validate_tpcds_scale` did not accept the argument, so
    `TpcdsComplianceClass.OFFICIAL` was unreachable and every TPC-DS run was
    refused by `benchbox submit`. The existing tests in this module all call
    `classify_tpcds_run` directly and so could not catch that.
    """

    def test_validate_tpcds_scale_forwards_official(self):
        assert validate_tpcds_scale(1.0, official=True) is TpcdsComplianceClass.OFFICIAL
        assert validate_tpcds_scale(1.0) is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_official_only_applies_at_official_scale_points(self):
        assert validate_tpcds_scale(2.0, official=True) is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD
        assert validate_tpcds_scale(0.5, official=True) is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE

    def test_benchmark_runner_classifies_an_official_run_as_official(self):
        """The runner is the seam that was broken."""
        from benchbox.core.tpcds.benchmark.runner import TPCDSBenchmark

        assert TPCDSBenchmark(scale_factor=1.0, official=True).compliance_class is TpcdsComplianceClass.OFFICIAL
        assert TPCDSBenchmark(scale_factor=1.0).compliance_class is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_loader_forwards_official_from_the_benchmark_config(self):
        """BenchmarkConfig -> get_benchmark_instance -> runner must carry the flag."""
        from benchbox.core.benchmark_loader import get_benchmark_instance
        from benchbox.core.schemas import BenchmarkConfig

        config = BenchmarkConfig(name="tpcds", display_name="TPC-DS", scale_factor=1.0, official=True)
        assert get_benchmark_instance(config, None).compliance_class is TpcdsComplianceClass.OFFICIAL

        default = BenchmarkConfig(name="tpcds", display_name="TPC-DS", scale_factor=1.0)
        assert get_benchmark_instance(default, None).compliance_class is TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD

    def test_an_official_run_is_not_refused_by_submit_classification(self):
        """The whole point: an official run must clear the submit gate."""
        from benchbox.validation.bundle import CLI_REFUSED_COMPLIANCE_CLASSES

        official = validate_tpcds_scale(1.0, official=True)
        assert official.value not in CLI_REFUSED_COMPLIANCE_CLASSES
        assert validate_tpcds_scale(1.0).value in CLI_REFUSED_COMPLIANCE_CLASSES

    def test_both_construction_paths_carry_compliance_mode(self):
        """There are two builders; a fix applied to only one is invisible to unit tests.

        `benchmark_loader.get_benchmark_instance` is used by the core runner,
        while `cli/orchestrator.py` has its own `_get_benchmark_instance`. The
        original wiring fix passed unit tests while the CLI still emitted
        unofficial results, because only the first path had been updated.
        """
        import inspect

        from benchbox.cli import orchestrator
        from benchbox.core import benchmark_loader

        for module in (benchmark_loader, orchestrator):
            source = inspect.getsource(module)
            assert "compliance_mode_kwargs" in source, (
                f"{module.__name__} builds benchmark instances but does not apply "
                "compliance_mode_kwargs; CLI runs would be unsubmittable"
            )

    def test_compliance_mode_kwargs_only_targets_gated_benchmarks(self):
        from benchbox.core.benchmark_loader import compliance_mode_kwargs
        from benchbox.core.schemas import BenchmarkConfig

        gated = BenchmarkConfig(name="tpcds", display_name="TPC-DS", scale_factor=1.0, official=True)
        assert compliance_mode_kwargs(gated) == {"official": True}

        ungated = BenchmarkConfig(name="tpch", display_name="TPC-H", scale_factor=1.0, official=True)
        assert compliance_mode_kwargs(ungated) == {}

    def test_official_benchmark_wrapper_defaults_to_official(self):
        from benchbox.core.tpcds.compliance import TpcdsComplianceClass
        from benchbox.core.tpcds.official_benchmark import TPCDSOfficialBenchmark

        wrapper = TPCDSOfficialBenchmark(scale_factor=1.0)
        assert wrapper.benchmark.compliance_class is TpcdsComplianceClass.OFFICIAL
