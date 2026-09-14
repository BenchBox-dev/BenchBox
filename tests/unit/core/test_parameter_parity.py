"""Tests for DataFrame parameter parity with SQL variants.

Verifies that:
1. TPC-H parameter override mechanism works correctly
2. TPC-DS parameter override mechanism works correctly
3. get_tpch_parameters() merges overrides on top of defaults
4. get_parameters() (TPC-DS) merges overrides on top of defaults
5. Parameter extractors produce valid output
6. Seed-derived overrides take precedence over scaled defaults

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.tpcds.dataframe_queries.parameters import (
    TPCDS_DEFAULT_PARAMS,
    get_parameters,
    set_parameter_overrides as tpcds_set_overrides,
)
from benchbox.core.tpch.dataframe_queries import (
    TPCH_DEFAULT_PARAMS,
    get_tpch_parameters,
    set_parameter_overrides as tpch_set_overrides,
    set_scale_factor as tpch_set_scale_factor,
)
from benchbox.core.tpch.parameter_extractor import (
    clear_cache as tpch_clear_cache,
    extract_tpch_parameters,
    get_tpch_extracted_parameters,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


# =============================================================================
# TPC-H Parameter Override Tests
# =============================================================================


class TestTPCHParameterOverrides:
    """Tests for the TPC-H parameter override mechanism."""

    def setup_method(self):
        tpch_set_overrides(None)

    def teardown_method(self):
        tpch_set_overrides(None)

    def test_defaults_returned_when_no_overrides(self):
        """get_tpch_parameters returns defaults with no overrides set."""
        params = get_tpch_parameters(1)
        assert params == TPCH_DEFAULT_PARAMS[1]

    def test_override_merges_on_top_of_defaults(self):
        """Overrides merge into defaults, not replace entirely."""
        # Q6 has start_date, end_date, discount_low, discount_high, quantity_limit
        tpch_set_overrides({6: {"start_date": date(1995, 1, 1)}})
        params = get_tpch_parameters(6)

        # Overridden key
        assert params["start_date"] == date(1995, 1, 1)
        # Non-overridden keys preserved from defaults
        assert params["discount_low"] == 0.05
        assert params["discount_high"] == 0.07
        assert params["quantity_limit"] == 24

    def test_override_does_not_affect_other_queries(self):
        """Overriding Q1 does not affect Q6."""
        tpch_set_overrides({1: {"cutoff_date": date(1998, 8, 17)}})
        params_q6 = get_tpch_parameters(6)
        assert params_q6 == TPCH_DEFAULT_PARAMS[6]

    def test_clear_overrides(self):
        """Setting overrides to None reverts to defaults."""
        tpch_set_overrides({1: {"cutoff_date": date(1998, 8, 17)}})
        assert get_tpch_parameters(1)["cutoff_date"] == date(1998, 8, 17)

        tpch_set_overrides(None)
        assert get_tpch_parameters(1)["cutoff_date"] == TPCH_DEFAULT_PARAMS[1]["cutoff_date"]

    def test_all_22_queries_have_defaults(self):
        """Every TPC-H query (1-22) has a default parameter entry."""
        for qid in range(1, 23):
            assert qid in TPCH_DEFAULT_PARAMS, f"Q{qid} missing from TPCH_DEFAULT_PARAMS"
            assert len(TPCH_DEFAULT_PARAMS[qid]) > 0, f"Q{qid} has empty defaults"

    def test_override_does_not_mutate_defaults(self):
        """Setting overrides does not change TPCH_DEFAULT_PARAMS."""
        original_q1 = dict(TPCH_DEFAULT_PARAMS[1])
        tpch_set_overrides({1: {"cutoff_date": date(1998, 8, 17)}})
        assert TPCH_DEFAULT_PARAMS[1] == original_q1

    def test_default_params_symbol(self):
        """TPCH_DEFAULT_PARAMS contains the canonical defaults."""
        assert isinstance(TPCH_DEFAULT_PARAMS, dict)
        assert len(TPCH_DEFAULT_PARAMS) == 22


# =============================================================================
# TPC-DS Parameter Override Tests
# =============================================================================


class TestTPCDSParameterOverrides:
    """Tests for the TPC-DS parameter override mechanism."""

    def setup_method(self):
        tpcds_set_overrides(None)

    def teardown_method(self):
        tpcds_set_overrides(None)

    def test_defaults_returned_when_no_overrides(self):
        """get_parameters returns defaults with no overrides set."""
        params = get_parameters(1)
        assert params.get("year") == TPCDS_DEFAULT_PARAMS[1]["year"]
        assert params.get("state") == TPCDS_DEFAULT_PARAMS[1]["state"]

    def test_override_merges_on_top_of_defaults(self):
        """Overrides merge into defaults, preserving non-overridden keys."""
        tpcds_set_overrides({1: {"year": 2001, "state": "CA"}})
        params = get_parameters(1)

        # Overridden keys
        assert params.get("year") == 2001
        assert params.get("state") == "CA"
        # Non-overridden key preserved
        assert params.get("agg_field") == "sr_return_amt"

    def test_override_does_not_affect_other_queries(self):
        """Overriding Q1 does not affect Q2."""
        tpcds_set_overrides({1: {"year": 2001}})
        params_q2 = get_parameters(2)
        assert params_q2.get("year") == TPCDS_DEFAULT_PARAMS[2]["year"]

    def test_clear_overrides(self):
        """Setting overrides to None reverts to defaults."""
        tpcds_set_overrides({1: {"year": 2001}})
        assert get_parameters(1).get("year") == 2001

        tpcds_set_overrides(None)
        assert get_parameters(1).get("year") == TPCDS_DEFAULT_PARAMS[1]["year"]

    def test_override_does_not_mutate_defaults(self):
        """Setting overrides does not change TPCDS_DEFAULT_PARAMS."""
        original_q1 = dict(TPCDS_DEFAULT_PARAMS[1])
        tpcds_set_overrides({1: {"year": 2001}})
        assert TPCDS_DEFAULT_PARAMS[1] == original_q1


# =============================================================================
# TPC-H Parameter Extractor Tests
# =============================================================================


class TestTPCHParameterExtractor:
    """Tests for the TPC-H parameter extractor module."""

    def test_extractor_functions_are_callable(self):
        """Parameter extractor functions exist and are callable."""
        assert callable(extract_tpch_parameters)
        assert callable(get_tpch_extracted_parameters)
        assert callable(tpch_clear_cache)

    def test_cache_clear_does_not_raise(self):
        """Cache clear works without error."""
        tpch_clear_cache()


# =============================================================================
# TPC-DS Parameter Extractor Tests
# =============================================================================


class TestTPCDSParameterExtractor:
    """Tests for the TPC-DS parameter extractor module."""

    def test_extractor_functions_are_callable(self):
        """Parameter extractor functions exist and are callable."""
        from benchbox.core.tpcds.parameter_extractor import (
            clear_cache,
            extract_tpcds_parameters,
            get_tpcds_extracted_parameters,
        )

        assert callable(extract_tpcds_parameters)
        assert callable(get_tpcds_extracted_parameters)
        assert callable(clear_cache)

    def test_cache_clear_does_not_raise(self):
        """Cache clear works without error."""
        from benchbox.core.tpcds.parameter_extractor import clear_cache

        clear_cache()


# =============================================================================
# Integration: Query Functions Use Centralized Parameters
# =============================================================================


class TestQueryFunctionsCentralized:
    """Verify query functions read from centralized parameter function."""

    def setup_method(self):
        tpch_set_overrides(None)

    def teardown_method(self):
        tpch_set_overrides(None)

    def test_get_tpch_parameters_for_all_queries(self):
        """Verify get_tpch_parameters works for all 22 queries."""
        for qid in range(1, 23):
            params = get_tpch_parameters(qid)
            assert isinstance(params, dict), f"Q{qid} returned non-dict: {type(params)}"
            assert len(params) > 0, f"Q{qid} returned empty params"

    def test_tpcds_get_parameters_for_all_queries(self):
        """Verify get_parameters works for all TPC-DS queries with defaults."""
        for qid in TPCDS_DEFAULT_PARAMS:
            params = get_parameters(qid)
            assert params.query_id == qid
            assert len(params.params) > 0, f"TPC-DS Q{qid} returned empty params"

    def test_q7_dates_come_from_params(self):
        """Q7 start_date/end_date are in TPCH_DEFAULT_PARAMS and consumed via get_tpch_parameters."""
        params = get_tpch_parameters(7)
        assert "start_date" in params, "Q7 missing start_date in TPCH_DEFAULT_PARAMS"
        assert "end_date" in params, "Q7 missing end_date in TPCH_DEFAULT_PARAMS"
        assert params["start_date"] == date(1995, 1, 1)
        assert params["end_date"] == date(1996, 12, 31)

    def test_q8_dates_come_from_params(self):
        """Q8 start_date/end_date are in TPCH_DEFAULT_PARAMS and consumed via get_tpch_parameters."""
        params = get_tpch_parameters(8)
        assert "start_date" in params, "Q8 missing start_date in TPCH_DEFAULT_PARAMS"
        assert "end_date" in params, "Q8 missing end_date in TPCH_DEFAULT_PARAMS"
        assert params["start_date"] == date(1995, 1, 1)
        assert params["end_date"] == date(1996, 12, 31)

    def test_q7_date_overrides_propagate(self):
        """Overriding Q7 start_date/end_date flows through get_tpch_parameters."""
        tpch_set_overrides({7: {"start_date": date(1994, 1, 1), "end_date": date(1995, 12, 31)}})
        params = get_tpch_parameters(7)
        assert params["start_date"] == date(1994, 1, 1)
        assert params["end_date"] == date(1995, 12, 31)
        # Non-overridden keys preserved
        assert params["nation1"] == "FRANCE"
        assert params["nation2"] == "GERMANY"

    def test_q8_date_overrides_propagate(self):
        """Overriding Q8 start_date/end_date flows through get_tpch_parameters."""
        tpch_set_overrides({8: {"start_date": date(1994, 1, 1), "end_date": date(1995, 12, 31)}})
        params = get_tpch_parameters(8)
        assert params["start_date"] == date(1994, 1, 1)
        assert params["end_date"] == date(1995, 12, 31)
        # Non-overridden keys preserved
        assert params["target_nation"] == "BRAZIL"

    def test_tpcds_q96_override_propagates(self):
        """Overriding Q96 hours flows through get_parameters."""
        tpcds_set_overrides({96: {"hours": [(10, 11)]}})
        params = get_parameters(96)
        assert params.get("hours") == [(10, 11)]

        tpcds_set_overrides(None)
        params = get_parameters(96)
        assert params.get("hours") == [(8, 9)]


# =============================================================================
# Unseeded Q11 Scale-Fraction Regression
# =============================================================================


class TestSeededOverridePrecedence:
    """A seed-derived Q11 fraction override wins over the scaled default.

    The legacy runner seam tests retired with benchbox/core/runner/dataframe_runner.py;
    unseeded scale behavior on the production path is pinned by
    TestMixinUnseededQ11ScaleFraction below. This keeps the parameter-module
    precedence contract both remaining override callers rely on.
    """

    def setup_method(self):
        tpch_set_overrides(None)
        tpch_set_scale_factor(None)

    def teardown_method(self):
        tpch_set_overrides(None)
        tpch_set_scale_factor(None)

    def test_seeded_override_takes_precedence_over_scaled_default(self):
        """A seed-derived Q11 fraction override wins over the scaled default."""
        tpch_set_scale_factor(0.1)  # scaled default would be 0.001
        tpch_set_overrides({11: {"fraction": 0.00002}})
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.00002)


# =============================================================================
# Production DataFrame Path (BenchmarkExecutionMixin) Q11 Scale-Fraction
# =============================================================================


class TestMixinUnseededQ11ScaleFraction:
    """The production DataFrame execution path must scope Q11's scaled fraction.

    Real polars-df/pandas-df runs execute via BenchmarkExecutionMixin (not the
    deprecated compatibility runner), so the mixin must set the scale factor for
    the duration of query execution and reset it afterwards. Regression for the
    follow-up to tpch-dataframe-unseeded-q11-scale-fraction.
    """

    def setup_method(self):
        tpch_set_overrides(None)
        tpch_set_scale_factor(None)

    def teardown_method(self):
        tpch_set_overrides(None)
        tpch_set_scale_factor(None)

    @staticmethod
    def _make_probe_adapter():
        """A minimal mixin subclass that records the active Q11 fraction."""
        from benchbox.platforms.dataframe.benchmark_mixin import BenchmarkExecutionMixin

        class _ScaleProbeAdapter(BenchmarkExecutionMixin):
            def __init__(self):
                self.observed_fraction = None

            def _run_query_iterations(self, *, ctx, benchmark_config, benchmark_instance, monitor, run_options=None):
                self.observed_fraction = get_tpch_parameters(11)["fraction"]
                return []

        return _ScaleProbeAdapter()

    @pytest.mark.parametrize("benchmark_name", ["tpch", "tpch_skew", "tpchavoc"])
    def test_mixin_scopes_q11_scale_for_tpch_family(self, benchmark_name):
        """The mixin scales Q11 during execution and resets afterwards."""
        adapter = self._make_probe_adapter()
        config = MagicMock()
        config.name = benchmark_name
        config.scale_factor = 0.1

        adapter._execute_queries_phase(ctx=MagicMock(), benchmark_config=config, benchmark_instance=None, monitor=None)

        # Scale was active during execution ...
        assert adapter.observed_fraction == pytest.approx(0.001)
        # ... and reset to the SF=1 rendering once execution finished.
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.0001)

    def test_mixin_is_noop_for_non_tpch_family(self):
        """A non-TPC-H-family benchmark leaves the Q11 default untouched."""
        adapter = self._make_probe_adapter()
        config = MagicMock()
        config.name = "tpcds"
        config.scale_factor = 0.1

        adapter._execute_queries_phase(ctx=MagicMock(), benchmark_config=config, benchmark_instance=None, monitor=None)

        assert adapter.observed_fraction == pytest.approx(0.0001)

    def test_mixin_resets_scale_on_exception(self):
        """The scale factor is reset even when execution raises."""
        from benchbox.platforms.dataframe.benchmark_mixin import BenchmarkExecutionMixin

        class _BoomAdapter(BenchmarkExecutionMixin):
            def _run_query_iterations(self, **kwargs):
                raise RuntimeError("boom")

        config = MagicMock()
        config.name = "tpch"
        config.scale_factor = 0.1

        with pytest.raises(RuntimeError, match="boom"):
            _BoomAdapter()._execute_queries_phase(
                ctx=MagicMock(), benchmark_config=config, benchmark_instance=None, monitor=None
            )

        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.0001)


class TestSetScaleFactorForBenchmark:
    """Direct coverage for the shared scale-seam helper."""

    def setup_method(self):
        tpch_set_scale_factor(None)

    def teardown_method(self):
        tpch_set_scale_factor(None)

    @pytest.mark.parametrize("benchmark_id", ["tpch", "tpch_skew", "tpchavoc"])
    def test_applies_for_tpch_family(self, benchmark_id):
        from benchbox.core.tpch.dataframe_queries import set_scale_factor_for_benchmark

        set_scale_factor_for_benchmark(benchmark_id, 0.1)
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.001)

    def test_noop_for_other_benchmarks(self):
        from benchbox.core.tpch.dataframe_queries import set_scale_factor_for_benchmark

        set_scale_factor_for_benchmark("tpcds", 0.1)
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.0001)
