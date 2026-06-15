"""Tests for DataFrame parameter parity with SQL variants.

Verifies that:
1. TPC-H parameter override mechanism works correctly
2. TPC-DS parameter override mechanism works correctly
3. get_tpch_parameters() merges overrides on top of defaults
4. get_parameters() (TPC-DS) merges overrides on top of defaults
5. Parameter extractors produce valid output
6. dataframe_runner wiring sets/clears overrides correctly

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.runner.dataframe_runner import (
    _clear_parameter_overrides,
    _execute_dataframe_queries,
    _setup_parameter_overrides,
    _setup_parameter_overrides_for_stream,
)
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
# Runner Wiring Tests
# =============================================================================


class TestRunnerParameterWiring:
    """Tests for the dataframe_runner parameter override wiring."""

    def teardown_method(self):
        tpch_set_overrides(None)
        tpcds_set_overrides(None)

    def test_setup_noop_without_seed(self):
        """_setup_parameter_overrides does nothing when seed is None."""
        _setup_parameter_overrides("tpch", None, 1.0)
        _setup_parameter_overrides("tpcds", None, 1.0)

    def test_setup_noop_unknown_benchmark(self):
        """_setup_parameter_overrides does nothing for unknown benchmarks."""
        _setup_parameter_overrides("ssb", 42, 1.0)

    def test_clear_tpch(self):
        """_clear_parameter_overrides clears TPC-H overrides."""
        tpch_set_overrides({1: {"cutoff_date": date(1998, 8, 17)}})
        assert get_tpch_parameters(1)["cutoff_date"] == date(1998, 8, 17)

        _clear_parameter_overrides("tpch")
        assert get_tpch_parameters(1)["cutoff_date"] == date(1998, 9, 2)

    def test_clear_tpcds(self):
        """_clear_parameter_overrides clears TPC-DS overrides."""
        tpcds_set_overrides({1: {"year": 2001}})
        assert get_parameters(1).get("year") == 2001

        _clear_parameter_overrides("tpcds")
        assert get_parameters(1).get("year") == 2000

    def test_setup_tpch_calls_extractor(self):
        """_setup_parameter_overrides calls the TPC-H extractor with the correct seed."""
        mock_overrides = {1: {"cutoff_date": date(1998, 8, 17)}}

        with (
            patch(
                "benchbox.core.tpch.parameter_extractor.get_tpch_extracted_parameters",
                return_value=mock_overrides,
            ) as mock_extract,
            patch("benchbox.core.tpch.dataframe_queries.set_parameter_overrides") as mock_set,
        ):
            _setup_parameter_overrides("tpch", 42, 0.01)

            mock_extract.assert_called_once_with(42, 0.01)
            mock_set.assert_called_once_with(mock_overrides)

    def test_setup_tpcds_calls_extractor(self):
        """_setup_parameter_overrides calls the TPC-DS extractor with the correct seed."""
        mock_overrides = {1: {"year": 2001}}

        with (
            patch(
                "benchbox.core.tpcds.parameter_extractor.get_tpcds_extracted_parameters",
                return_value=mock_overrides,
            ) as mock_extract,
            patch("benchbox.core.tpcds.dataframe_queries.parameters.set_parameter_overrides") as mock_set,
        ):
            _setup_parameter_overrides("tpcds", 42, 1.0)

            mock_extract.assert_called_once_with(42, 1.0, None)
            mock_set.assert_called_once_with(mock_overrides)

    def test_setup_graceful_on_extractor_failure(self):
        """_setup_parameter_overrides logs warning and continues if extractor fails."""
        with patch(
            "benchbox.core.tpch.parameter_extractor.get_tpch_extracted_parameters",
            side_effect=RuntimeError("qgen binary not found"),
        ):
            # Should not raise
            _setup_parameter_overrides("tpch", 42, 0.01)

    def test_setup_noop_when_extractor_returns_empty(self):
        """_setup_parameter_overrides does not set overrides if extractor returns empty dict."""
        with (
            patch(
                "benchbox.core.tpch.parameter_extractor.get_tpch_extracted_parameters",
                return_value={},
            ),
            patch("benchbox.core.tpch.dataframe_queries.set_parameter_overrides") as mock_set,
        ):
            _setup_parameter_overrides("tpch", 42, 0.01)
            mock_set.assert_not_called()

    def test_execute_queries_clears_overrides_on_no_query_path(self):
        """_execute_dataframe_queries clears overrides even when no queries are discovered."""
        config = MagicMock()
        config.name = "tpch"
        config.scale_factor = 0.01
        config.options = {"seed": 7, "power_warmup_iterations": 0, "power_iterations": 1}
        config.queries = None

        adapter = MagicMock()
        ctx = MagicMock()
        benchmark_instance = MagicMock()

        with (
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", return_value=[]),
            patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides") as mock_clear,
        ):
            out = _execute_dataframe_queries(adapter, ctx, config, benchmark_instance, monitor=None)
            assert out == []
            mock_clear.assert_called_once_with("tpch")

    def test_execute_queries_clears_overrides_on_unexpected_exception(self):
        """_execute_dataframe_queries clears overrides when execution path raises unexpectedly."""
        config = MagicMock()
        config.name = "tpcds"
        config.scale_factor = 1.0
        config.options = {"seed": 11, "power_warmup_iterations": 0, "power_iterations": 1}
        config.queries = None

        adapter = MagicMock()
        ctx = MagicMock()
        benchmark_instance = MagicMock()
        query = MagicMock()
        query.query_id = "Q1"

        # Initial discovery succeeds; measurement query retrieval fails unexpectedly.
        side_effect = [[query], RuntimeError("boom")]
        with (
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", side_effect=side_effect),
            patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides") as mock_clear,
            pytest.raises(RuntimeError, match="boom"),
        ):
            _execute_dataframe_queries(adapter, ctx, config, benchmark_instance, monitor=None)

        mock_clear.assert_called_once_with("tpcds")

    def test_execute_queries_clears_overrides_on_unexpected_exception_tpch(self):
        """TPC-H execution also clears overrides on unexpected exceptions."""
        config = MagicMock()
        config.name = "tpch"
        config.scale_factor = 1.0
        config.options = {"seed": 11, "power_warmup_iterations": 0, "power_iterations": 1}
        config.queries = None

        adapter = MagicMock()
        ctx = MagicMock()
        benchmark_instance = MagicMock()
        query = MagicMock()
        query.query_id = "Q1"

        side_effect = [[query], RuntimeError("tpch-boom")]
        with (
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", side_effect=side_effect),
            patch("benchbox.core.runner.dataframe_runner._clear_parameter_overrides") as mock_clear,
            pytest.raises(RuntimeError, match="tpch-boom"),
        ):
            _execute_dataframe_queries(adapter, ctx, config, benchmark_instance, monitor=None)

        mock_clear.assert_called_once_with("tpch")

    def test_execute_queries_tpcds_sets_overrides_per_stream(self):
        """TPC-DS override setup is stream-aware during query execution."""
        config = MagicMock()
        config.name = "tpcds"
        config.scale_factor = 1.0
        config.options = {"seed": 42, "power_warmup_iterations": 1, "power_iterations": 2}
        config.queries = None

        adapter = MagicMock()
        adapter.execute_query.return_value = {"query_id": "Q1", "status": "OK", "execution_time_seconds": 0.1}
        ctx = MagicMock()
        benchmark_instance = MagicMock()
        query = MagicMock()
        query.query_id = "Q1"

        with (
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", return_value=[query]),
            patch("benchbox.core.runner.dataframe_runner._setup_parameter_overrides") as mock_setup,
        ):
            _execute_dataframe_queries(adapter, ctx, config, benchmark_instance, monitor=None)

        # Stream 0 is setup once (initial + warmup deduped), then stream 1 and 2.
        expected = [
            (("tpcds", 42, 1.0), {"stream_id": 0}),
            (("tpcds", 42, 1.0), {"stream_id": 1}),
            (("tpcds", 42, 1.0), {"stream_id": 2}),
        ]
        actual = [(call.args, call.kwargs) for call in mock_setup.call_args_list]
        assert actual == expected

    def test_execute_queries_tpcds_stream_specific_overrides_flow_to_execution(self):
        """Mock stream-specific extractor values and assert execution sees per-stream overrides."""
        config = MagicMock()
        config.name = "tpcds"
        config.scale_factor = 1.0
        config.options = {"seed": 9, "power_warmup_iterations": 1, "power_iterations": 2}
        config.queries = None

        query = MagicMock()
        query.query_id = "Q1"
        ctx = MagicMock()
        benchmark_instance = MagicMock()

        def _extract(seed: int, scale_factor: float, stream_id: int | None):
            assert seed == 9
            assert scale_factor == 1.0
            assert stream_id is not None
            return {1: {"year": 2000 + stream_id}}

        def _execute_query(_ctx, _query):
            params = get_parameters(1)
            return {
                "query_id": "Q1",
                "status": "OK",
                "execution_time_seconds": 0.01,
                "year": params.get("year"),
            }

        adapter = MagicMock()
        adapter.execute_query.side_effect = _execute_query

        with (
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", return_value=[query]),
            patch("benchbox.core.tpcds.parameter_extractor.get_tpcds_extracted_parameters", side_effect=_extract),
        ):
            out = _execute_dataframe_queries(adapter, ctx, config, benchmark_instance, monitor=None)

        # 1 warmup stream (0) + 2 measurement streams (1,2).
        years_by_stream = {(row["stream_id"], row["run_type"]): row["year"] for row in out}
        assert years_by_stream[(0, "warmup")] == 2000
        assert years_by_stream[(1, "measurement")] == 2001
        assert years_by_stream[(2, "measurement")] == 2002

    def test_execute_queries_tpcds_stream_inputs_align_for_queries_and_extractor(self):
        """Stream IDs used for query retrieval align with stream IDs used for override extraction."""
        config = MagicMock()
        config.name = "tpcds"
        config.scale_factor = 0.01
        config.options = {"seed": 17, "power_warmup_iterations": 1, "power_iterations": 2}
        config.queries = None

        query = MagicMock()
        query.query_id = "Q1"
        ctx = MagicMock()
        benchmark_instance = MagicMock()
        adapter = MagicMock()
        adapter.execute_query.return_value = {"query_id": "Q1", "status": "OK", "execution_time_seconds": 0.01}

        query_stream_calls: list[int] = []
        extractor_stream_calls: list[int | None] = []

        def _get_queries(_cfg, _instance, stream_id=None):
            query_stream_calls.append(stream_id)
            return [query]

        def _extract(_seed: int, _sf: float, stream_id: int | None):
            extractor_stream_calls.append(stream_id)
            return {1: {"year": 2000}}

        with (
            patch("benchbox.core.runner.dataframe_runner._get_queries_for_benchmark", side_effect=_get_queries),
            patch("benchbox.core.tpcds.parameter_extractor.get_tpcds_extracted_parameters", side_effect=_extract),
        ):
            _execute_dataframe_queries(adapter, ctx, config, benchmark_instance, monitor=None)

        # Query discovery + warmup + measurement streams.
        assert query_stream_calls == [0, 0, 1, 2]
        # Stream-specific overrides are applied once per unique stream context.
        assert extractor_stream_calls == [0, 1, 2]


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


class TestUnseededQ11ScaleFraction:
    """Unseeded DataFrame runs must render Q11's fraction as 0.0001 / SF.

    Canonical TPC-H qgen renders the Q11 value threshold as 0.0001 / SF, and the
    SQL run path mirrors that via the {q11_fraction} token. Without a seed, the
    DataFrame surface used to fall back to the static SF=1 value at every scale;
    these tests pin the scale-aware default so the product run path stays
    scale-faithful (regression for tpch-dataframe-unseeded-q11-scale-fraction).
    """

    def setup_method(self):
        tpch_set_overrides(None)
        tpch_set_scale_factor(None)

    def teardown_method(self):
        tpch_set_overrides(None)
        tpch_set_scale_factor(None)

    @pytest.mark.parametrize(
        "scale_factor, expected_fraction",
        [(0.1, 0.001), (1.0, 0.0001), (10.0, 0.00001)],
    )
    def test_unseeded_runner_setup_scales_q11_fraction(self, scale_factor, expected_fraction):
        """The unseeded runner seam derives Q11's fraction from the scale factor."""
        _setup_parameter_overrides_for_stream(
            benchmark_id="tpch",
            seed=None,
            scale_factor=scale_factor,
            stream_id=0,
            applied_contexts=set(),
        )
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(expected_fraction)

    @pytest.mark.parametrize("benchmark_id", ["tpch", "tpch_skew", "tpchavoc"])
    def test_tpch_family_unseeded_setup_scales_q11_fraction(self, benchmark_id):
        """Every TPC-H-family benchmark shares the parameter seam and scales alike.

        TPC-H Skew re-registers the canonical TPC-H DataFrame queries verbatim and
        TPC-Havoc's variants read the same seam, so all three must derive Q11's
        fraction from the run's scale factor on the unseeded path.
        """
        _setup_parameter_overrides_for_stream(
            benchmark_id=benchmark_id,
            seed=None,
            scale_factor=0.1,
            stream_id=0,
            applied_contexts=set(),
        )
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.001)

    def test_seeded_override_takes_precedence_over_scaled_default(self):
        """A seed-derived Q11 fraction override wins over the scaled default."""
        tpch_set_scale_factor(0.1)  # scaled default would be 0.001
        tpch_set_overrides({11: {"fraction": 0.00002}})
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.00002)

    def test_clear_resets_scale_factor_to_sf1(self):
        """Clearing overrides resets the Q11 fraction to the SF=1 rendering."""
        tpch_set_scale_factor(0.1)
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.001)

        _clear_parameter_overrides("tpch")
        assert get_tpch_parameters(11)["fraction"] == pytest.approx(0.0001)


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
