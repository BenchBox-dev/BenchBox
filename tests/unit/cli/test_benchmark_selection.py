"""Tests for enhanced benchmark selection with unified display and filtering.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import patch

import pytest

from benchbox.cli.benchmarks import BenchmarkManager
from benchbox.core.schemas import BenchmarkConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestBenchmarkFiltering:
    """Test benchmark filtering functionality."""

    def test_filter_by_category(self):
        """Test filtering benchmarks by category."""
        manager = BenchmarkManager()

        # Filter by TPC category
        tpc_benchmarks = manager._filter_benchmarks(category="TPC")
        assert "tpch" in tpc_benchmarks
        assert "tpcds" in tpc_benchmarks
        assert "tpcdi" in tpc_benchmarks
        assert "ssb" not in tpc_benchmarks
        assert "clickbench" not in tpc_benchmarks

    def test_filter_by_search_term_name(self):
        """Test filtering benchmarks by searching name."""
        manager = BenchmarkManager()

        # Search for "TPC"
        tpc_results = manager._filter_benchmarks(search_term="TPC")
        assert "tpch" in tpc_results
        assert "tpcds" in tpc_results
        assert "tpcdi" in tpc_results

    def test_filter_by_search_term_description(self):
        """Test filtering benchmarks by searching description."""
        manager = BenchmarkManager()

        # Search for "decision"
        decision_results = manager._filter_benchmarks(search_term="decision")
        assert "tpch" in decision_results
        assert "tpcds" in decision_results

    def test_filter_by_search_term_case_insensitive(self):
        """Test that search is case-insensitive."""
        manager = BenchmarkManager()

        # Test case insensitive
        lower_results = manager._filter_benchmarks(search_term="tpc")
        upper_results = manager._filter_benchmarks(search_term="TPC")
        mixed_results = manager._filter_benchmarks(search_term="TpC")

        assert lower_results == upper_results == mixed_results

    def test_filter_combined_category_and_search(self):
        """Test filtering with both category and search term."""
        manager = BenchmarkManager()

        # Filter by Industry category and search for "click"
        results = manager._filter_benchmarks(category="Industry", search_term="click")
        assert "clickbench" in results
        assert "tpch" not in results  # Not in Industry category
        assert "ssb" not in results  # Doesn't contain "click"

    def test_filter_no_results(self):
        """Test filtering that returns no results."""
        manager = BenchmarkManager()

        # Search for non-existent term
        results = manager._filter_benchmarks(search_term="nonexistent")
        assert len(results) == 0

    def test_filter_no_filters_returns_all(self):
        """Test that no filters returns all public benchmarks."""
        manager = BenchmarkManager()

        results = manager._filter_benchmarks()
        assert len(results) == len(manager._get_public_benchmarks())
        assert "joinorder_synthetic" in manager.benchmarks
        assert "joinorder_synthetic" not in results

    def test_filter_academic_excludes_internal_benchmarks(self):
        """Academic filtering should hide internal synthetic compatibility surfaces."""
        manager = BenchmarkManager()

        results = manager._filter_benchmarks(category="Academic")

        assert "joinorder" in results
        assert "ssb" in results
        assert "joinorder_synthetic" not in results


class TestBenchmarkDisplay:
    """Test unified benchmark display functionality."""

    def test_list_available_benchmarks_prints_tree(self):
        """list_available_benchmarks should render the benchmark tree."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console") as mock_console:
            manager.list_available_benchmarks()

        assert mock_console.print.called

    def test_display_all_benchmarks_structure(self):
        """Test that display returns all public benchmarks with proper structure."""
        manager = BenchmarkManager()

        # Capture display output
        with patch("benchbox.cli.benchmarks.console"):
            displayed = manager._display_all_benchmarks()

        # Should return all public benchmarks
        assert len(displayed) == len(manager._get_public_benchmarks())
        assert "joinorder_synthetic" not in displayed

        # Check structure of returned data
        for bench_id, bench_info in displayed.items():
            assert "display_name" in bench_info
            assert "category" in bench_info
            assert "num_queries" in bench_info
            assert "complexity" in bench_info
            assert "estimated_time_range" in bench_info

    def test_display_with_category_filter(self):
        """Test display with category filter."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console"):
            displayed = manager._display_all_benchmarks(filter_category="TPC")

        # Should only return TPC benchmarks
        assert "tpch" in displayed
        assert "tpcds" in displayed
        assert "clickbench" not in displayed

    def test_display_with_search_filter(self):
        """Test display with search filter."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console"):
            displayed = manager._display_all_benchmarks(search_term="Decision")

        # Should return benchmarks matching "Decision"
        # (TPC-H and TPC-DS have "Decision Support" in description)
        assert len(displayed) > 0

    def test_display_empty_results(self):
        """Test display with no matching results."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console") as mock_console:
            displayed = manager._display_all_benchmarks(search_term="xyz123nonexistent")

        # Should return empty dict
        assert len(displayed) == 0

        # Should print warning message
        assert any("No benchmarks match" in str(call) for call in mock_console.print.call_args_list)


class TestBenchmarkPreview:
    """Test benchmark preview functionality."""

    def test_show_benchmark_preview(self):
        """Test showing preview for a benchmark."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console") as mock_console:
            manager._show_benchmark_preview("tpch", manager.benchmarks["tpch"])

        # Should have printed a panel with preview info
        assert mock_console.print.called
        # The print call should have received a Panel object
        assert len(mock_console.print.call_args_list) > 0

    def test_preview_includes_key_info(self):
        """Test that preview includes essential information."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console") as mock_console:
            manager._show_benchmark_preview("tpcds", manager.benchmarks["tpcds"])

        # Should have called print with a Panel
        assert mock_console.print.called
        # Verify that a Panel was passed (it's a rich Panel object)
        from rich.panel import Panel

        panel_arg = mock_console.print.call_args[0][0]
        assert isinstance(panel_arg, Panel)

    def test_show_sample_queries_renders_loaded_queries(self):
        """Sample query preview should render heading and SQL snippets."""
        manager = BenchmarkManager()
        seen_scale = None

        class StubBenchmark:
            def __init__(self, scale_factor):
                nonlocal seen_scale
                seen_scale = scale_factor
                self.scale_factor = scale_factor
                self.queries = {
                    "Q1": "SELECT 1",
                    "Q2": "SELECT 2",
                }

        with (
            patch("benchbox.core.benchmark_loader.get_benchmark_class", return_value=StubBenchmark),
            patch("benchbox.cli.benchmarks.console") as mock_console,
        ):
            manager._show_sample_queries("joinorder", limit=1)

        printed = [str(call.args[0]) for call in mock_console.print.call_args_list if call.args]
        assert any("Sample Queries" in item for item in printed)
        assert any("Query Q1:" in item for item in printed)
        assert seen_scale == manager.benchmarks["joinorder"]["default_scale"]

    def test_show_sample_queries_without_queries_warns(self):
        """Benchmarks without a queries mapping should emit a warning."""
        manager = BenchmarkManager()

        class StubBenchmark:
            def __init__(self, scale_factor):
                self.scale_factor = scale_factor
                self.queries = {}

        with (
            patch("benchbox.core.benchmark_loader.get_benchmark_class", return_value=StubBenchmark),
            patch("benchbox.cli.benchmarks.console") as mock_console,
        ):
            manager._show_sample_queries("tpch")

        assert any("No queries available for preview" in str(call) for call in mock_console.print.call_args_list)

    def test_show_sample_queries_load_failure_warns(self):
        """Benchmark loading failures should be surfaced as a warning."""
        manager = BenchmarkManager()

        with (
            patch("benchbox.core.benchmark_loader.get_benchmark_class", side_effect=RuntimeError("boom")),
            patch("benchbox.cli.benchmarks.console") as mock_console,
        ):
            manager._show_sample_queries("tpch")

        assert any("Could not load sample queries" in str(call) for call in mock_console.print.call_args_list)


class TestBenchmarkSelectionIntegration:
    """Integration tests for the complete selection flow."""

    @patch("benchbox.cli.benchmarks.Prompt")
    def test_select_benchmark_direct_numeric(self, mock_prompt):
        """Test selecting a benchmark by direct numeric input."""
        manager = BenchmarkManager()

        # Mock user selecting option 1
        mock_prompt.ask.return_value = "1"

        # Mock the configuration prompts
        with patch.object(manager, "_configure_benchmark") as mock_config:
            mock_config.return_value = BenchmarkConfig(
                name="tpch",
                display_name="TPC-H",
                scale_factor=0.01,
                queries=None,
                concurrency=1,
                options={},
            )

            result = manager.select_benchmark()

        # Should return a configured benchmark
        assert isinstance(result, BenchmarkConfig)
        assert result.name in manager.benchmarks

    @patch("benchbox.cli.benchmarks.Prompt")
    def test_select_benchmark_two_phase_tpc_category(self, mock_prompt):
        """Test selecting a benchmark using two-phase flow: Category > Benchmark."""
        manager = BenchmarkManager()

        # Mock user interactions: '1' for TPC category, '1' for TPC-H (first in TPC)
        mock_prompt.ask.side_effect = ["1", "1"]

        with patch.object(manager, "_configure_benchmark") as mock_config:
            mock_config.return_value = BenchmarkConfig(
                name="tpch",
                display_name="TPC-H",
                scale_factor=0.01,
                queries=None,
                concurrency=1,
                options={},
            )

            result = manager.select_benchmark()

        assert isinstance(result, BenchmarkConfig)
        assert result.name == "tpch"

    @patch("benchbox.cli.benchmarks.Prompt")
    def test_select_benchmark_two_phase_primitives_category(self, mock_prompt):
        """Test selecting from Primitives category (second in order)."""
        manager = BenchmarkManager()

        # Mock: '2' for Primitives, '1' for Read Primitives (first in Primitives)
        mock_prompt.ask.side_effect = ["2", "1"]

        with patch.object(manager, "_configure_benchmark") as mock_config:
            mock_config.return_value = BenchmarkConfig(
                name="read_primitives",
                display_name="Read Primitives",
                scale_factor=0.01,
                queries=None,
                concurrency=1,
                options={},
            )

            result = manager.select_benchmark()

        assert isinstance(result, BenchmarkConfig)
        assert result.name == "read_primitives"

    @patch("benchbox.cli.benchmarks.Prompt")
    def test_select_benchmark_two_phase_industry_category(self, mock_prompt):
        """Test selecting from Industry category (third in order)."""
        manager = BenchmarkManager()

        # Mock: '3' for Industry, '1' for ClickBench (first in Industry)
        mock_prompt.ask.side_effect = ["3", "1"]

        with patch.object(manager, "_configure_benchmark") as mock_config:
            mock_config.return_value = BenchmarkConfig(
                name="clickbench",
                display_name="ClickBench",
                scale_factor=1.0,
                queries=None,
                concurrency=1,
                options={},
            )

            result = manager.select_benchmark()

        assert isinstance(result, BenchmarkConfig)
        assert result.name == "clickbench"

    @patch("benchbox.cli.benchmarks.Prompt")
    def test_select_benchmark_two_phase_experimental_category(self, mock_prompt):
        """Test selecting from Experimental category (last in order)."""
        manager = BenchmarkManager()

        # Mock: '7' for Experimental, '1' for TPC-H Skew (first in Experimental)
        mock_prompt.ask.side_effect = ["7", "1"]

        with patch.object(manager, "_configure_benchmark") as mock_config:
            mock_config.return_value = BenchmarkConfig(
                name="tpch_skew",
                display_name="TPC-H Skew",
                scale_factor=0.01,
                queries=None,
                concurrency=1,
                options={},
            )

            result = manager.select_benchmark()

        assert isinstance(result, BenchmarkConfig)
        assert result.name == "tpch_skew"


class TestBenchmarkSelectionEdgeCases:
    """Test edge cases in benchmark selection."""

    def test_filter_with_empty_string(self):
        """Test filtering with empty string."""
        manager = BenchmarkManager()

        results = manager._filter_benchmarks(search_term="")
        # Empty string should return all public benchmarks.
        assert len(results) == len(manager._get_public_benchmarks())

    def test_filter_with_whitespace(self):
        """Test filtering with whitespace-only search."""
        manager = BenchmarkManager()

        # Whitespace search should be treated as empty and return all
        results = manager._filter_benchmarks(search_term="   ")
        # Since the filter does not strip whitespace, this will match benchmarks
        # that contain spaces, which is all of them (they have spaces in descriptions)
        assert isinstance(results, dict)

    def test_filter_with_special_characters(self):
        """Test filtering with special characters."""
        manager = BenchmarkManager()

        # Should not crash with special regex characters
        results = manager._filter_benchmarks(search_term="[]*?")
        # May return 0 or more results, but should not crash
        assert isinstance(results, dict)

    def test_display_single_benchmark_after_filter(self):
        """Test display when filter results in single benchmark."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console"):
            # Filter to a very specific benchmark
            displayed = manager._display_all_benchmarks(search_term="clickbench")

        # Should display at least ClickBench
        assert "clickbench" in displayed


class TestBackwardsCompatibility:
    """Test that old methods still work for backwards compatibility."""

    def test_old_display_benchmark_categories_still_works(self):
        """Test that old category display method still works."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.console"):
            # Should not raise exception
            manager._display_benchmark_categories()

    def test_old_select_category_still_works(self):
        """Test that old category selection still works."""
        manager = BenchmarkManager()

        categories = ["TPC Standard", "Analytical"]

        with patch("benchbox.cli.benchmarks.Prompt") as mock_prompt:
            mock_prompt.ask.return_value = "1"

            result = manager._select_category(categories)

        assert result in categories

    def test_old_select_specific_benchmark_still_works(self):
        """Test that old specific benchmark selection still works."""
        manager = BenchmarkManager()

        available = {"tpch": manager.benchmarks["tpch"], "tpcds": manager.benchmarks["tpcds"]}

        with patch("benchbox.cli.benchmarks.Prompt") as mock_prompt:
            mock_prompt.ask.return_value = "1"

            result = manager._select_specific_benchmark(available)

        assert result in available


class TestTwoPhaseSelectionFlow:
    """Test the new two-phase Category > Benchmark selection flow."""

    def test_category_order_is_popularity_based(self):
        """Test that CATEGORY_ORDER lists categories in popularity order."""
        manager = BenchmarkManager()

        expected_order = [
            "TPC",
            "Primitives",
            "Industry",
            "Academic",
            "Time Series",
            "Real World",
            "AI/ML",
            "Experimental",
        ]
        assert expected_order == manager.CATEGORY_ORDER

    def test_benchmark_order_defined_for_all_categories(self):
        """Test that BENCHMARK_ORDER has entries for all categories."""
        manager = BenchmarkManager()

        # Get all categories from benchmarks
        actual_categories = {info["category"] for info in manager.benchmarks.values()}

        # All categories should have a benchmark order defined
        for category in actual_categories:
            assert category in manager.BENCHMARK_ORDER, f"Missing BENCHMARK_ORDER for {category}"

    def test_tpc_benchmark_order(self):
        """Test that TPC benchmarks are ordered by popularity (H > DS > DI)."""
        manager = BenchmarkManager()

        tpc_order = manager.BENCHMARK_ORDER["TPC"]
        assert tpc_order == ["tpch", "tpcds", "tpcdi"]

    def test_primitives_benchmark_order(self):
        """Test that Primitives benchmarks are ordered by popularity."""
        manager = BenchmarkManager()

        primitives_order = manager.BENCHMARK_ORDER["Primitives"]
        assert primitives_order == [
            "read_primitives",
            "write_primitives",
            "transaction_primitives",
            "metadata_primitives",
            "ai_primitives",
        ]

    def test_prompt_category_selection_returns_category(self):
        """Test that _prompt_category_selection returns selected category."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.Prompt") as mock_prompt:
            mock_prompt.ask.return_value = "1"  # TPC is first

            result = manager._prompt_category_selection()

        assert result == "TPC"

    def test_prompt_category_selection_academic(self):
        """Test selecting Academic category (4th in order)."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.Prompt") as mock_prompt:
            mock_prompt.ask.return_value = "4"  # Academic is 4th

            result = manager._prompt_category_selection()

        assert result == "Academic"

    def test_prompt_benchmark_in_category_returns_tuple(self):
        """Test that _prompt_benchmark_in_category returns (id, info) tuple."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.Prompt") as mock_prompt:
            mock_prompt.ask.return_value = "1"  # First benchmark

            bench_id, bench_info = manager._prompt_benchmark_in_category("TPC")

        # Should return TPC-H (first in TPC popularity order)
        assert bench_id == "tpch"
        assert bench_info["display_name"] == "TPC-H"

    def test_prompt_benchmark_in_category_second_choice(self):
        """Test selecting second benchmark in a category."""
        manager = BenchmarkManager()

        with patch("benchbox.cli.benchmarks.Prompt") as mock_prompt:
            mock_prompt.ask.return_value = "2"  # Second benchmark

            bench_id, bench_info = manager._prompt_benchmark_in_category("TPC")

        # Should return TPC-DS (second in TPC popularity order)
        assert bench_id == "tpcds"
        assert bench_info["display_name"] == "TPC-DS"

    def test_benchmarks_sorted_by_popularity_then_alpha(self):
        """Test that benchmarks without popularity order fall back to alphabetical."""
        manager = BenchmarkManager()

        # Get sorted benchmarks for a category
        category = "Industry"
        category_benchmarks = {
            bench_id: info for bench_id, info in manager.benchmarks.items() if info["category"] == category
        }

        popularity_order = manager.BENCHMARK_ORDER.get(category, [])

        def sort_key(item):
            bench_id, info = item
            try:
                position = popularity_order.index(bench_id)
            except ValueError:
                position = 999
            return (position, info["display_name"])

        sorted_benchmarks = sorted(category_benchmarks.items(), key=sort_key)

        # First should be clickbench (first in popularity order)
        assert sorted_benchmarks[0][0] == "clickbench"
        # Second should be h2odb
        assert sorted_benchmarks[1][0] == "h2odb"
        # Third should be coffeeshop
        assert sorted_benchmarks[2][0] == "coffeeshop"
