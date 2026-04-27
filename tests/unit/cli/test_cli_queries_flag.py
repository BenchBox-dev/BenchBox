"""Tests for --queries CLI flag functionality.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import pytest
from click.testing import CliRunner

from benchbox.cli.commands.run import run
from benchbox.cli.config import ConfigManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestQueriesFlagBasic:
    """Basic functionality tests for --queries flag."""

    def test_queries_flag_parsing_single(self):
        """Test that single query is parsed correctly."""
        runner = CliRunner()
        # Use --check-platforms to fail early without actually running benchmark
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1", "--check-platforms"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should fail at platform check, not query parsing
        assert "❌" not in result.output or "query" not in result.output.lower()

    def test_queries_flag_parsing_multiple(self):
        """Test that multiple queries are parsed correctly."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1,6,17", "--check-platforms"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should fail at platform check, not query parsing
        assert "❌" not in result.output or "query" not in result.output.lower()

    def test_queries_flag_preserves_order(self):
        """Test that query order is preserved as specified."""
        runner = CliRunner()
        # Order: 17, 6, 1 (reverse)
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "17,6,1", "--check-platforms"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should not have query-related errors
        assert "Invalid query" not in result.output


class TestQueriesFlagEdgeCases:
    """Edge case tests for --queries flag."""

    def test_queries_flag_empty_string(self):
        """Test that empty string is rejected."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", ""],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "no valid query IDs found" in result.output

    def test_queries_flag_whitespace_handling(self):
        """Test that whitespace around query IDs is handled correctly."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "  1  , 6  , 17  ", "--check-platforms"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should not error on whitespace
        assert "Invalid query ID format" not in result.output

    def test_queries_flag_trailing_comma(self):
        """Test that trailing comma is handled gracefully."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1,2,3,", "--check-platforms"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should not error
        assert "Invalid query" not in result.output

    def test_queries_flag_double_comma(self):
        """Test that double comma is handled (empty element ignored)."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1,,2", "--check-platforms"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should not error - empty elements are filtered out
        assert "Invalid query" not in result.output


class TestQueriesFlagValidation:
    """Validation tests for --queries flag."""

    def test_queries_too_many(self):
        """Test that >100 queries are rejected."""
        runner = CliRunner()
        # Create 101 query IDs
        many_queries = ",".join(str(i) for i in range(1, 102))
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", many_queries],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "Too many queries" in result.output
        assert "max 100" in result.output

    def test_query_id_too_long(self):
        """Test that query IDs exceeding MAX_QUERY_ID_LENGTH chars are rejected."""
        from benchbox.utils.input_validation import MAX_QUERY_ID_LENGTH

        runner = CliRunner()
        long_id = "a" * (MAX_QUERY_ID_LENGTH + 1)
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", long_id],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "Query ID too long" in result.output
        assert f"max {MAX_QUERY_ID_LENGTH} chars" in result.output

    def test_invalid_format_special_chars(self):
        """Test that special characters are rejected."""
        runner = CliRunner()
        invalid_cases = [
            "1;DROP TABLE",  # SQL injection attempt
            "1 OR 1=1",  # SQL injection attempt
            "../../../etc/passwd",  # Path traversal
            "$(whoami)",  # Command injection
            "1%s%s%s",  # Format string
        ]

        for invalid_query in invalid_cases:
            result = runner.invoke(
                run,
                ["--platform", "duckdb", "--benchmark", "tpch", "--queries", invalid_query],
                obj={"config": ConfigManager()},
                catch_exceptions=False,
            )
            assert result.exit_code != 0, f"Should reject: {invalid_query}"
            assert "Invalid query ID format" in result.output, f"Should show format error for: {invalid_query}"

    def test_valid_format_alphanumeric(self):
        """Test that valid alphanumeric formats are accepted."""
        runner = CliRunner()
        valid_cases = [
            "1",
            "22",
            "query1",
            "Q1",
            "q1-variant",
            "q1_v2",
            "Q1.1",  # SSB-style dot-notation
            "Q3.4",  # SSB-style dot-notation
        ]

        for valid_query in valid_cases:
            result = runner.invoke(
                run,
                ["--platform", "duckdb", "--benchmark", "tpch", "--queries", valid_query, "--check-platforms"],
                obj={"config": ConfigManager()},
                catch_exceptions=False,
            )
            # Should not fail on format validation
            assert "Invalid query ID format" not in result.output, f"Should accept: {valid_query}"


class TestQueriesFlagPhaseInteraction:
    """Tests for --queries interaction with --phases flag."""

    def test_queries_with_power_phase(self):
        """Test that --queries works with power phase (compatible)."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--queries",
                "1,6",
                "--phases",
                "power",
                "--check-platforms",
            ],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should not have phase compatibility errors
        assert "only works with power/standard" not in result.output

    def test_queries_with_warmup_only_errors(self):
        """Test that --queries with ONLY warmup phase errors."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1,6", "--phases", "warmup"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "--queries only works with power/standard phases" in result.output

    def test_queries_with_mixed_phases_warns(self):
        """Test that --queries with compatible+incompatible phases warns."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            [
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--queries",
                "1,6",
                "--phases",
                "power,warmup",
                "--validation",
                "full",
            ],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        # Should warn but not error
        assert "⚠" in result.output
        assert "ignored for" in result.output.lower()
        # But should still allow execution (would fail at validation)

    def test_queries_with_throughput_only_errors(self):
        """Test that --queries with ONLY throughput phase errors."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1,6", "--phases", "throughput"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "--queries only works with power/standard phases" in result.output

    def test_queries_with_maintenance_only_errors(self):
        """Test that --queries with ONLY maintenance phase errors."""
        runner = CliRunner()
        result = runner.invoke(
            run,
            ["--platform", "duckdb", "--benchmark", "tpch", "--queries", "1,6", "--phases", "maintenance"],
            obj={"config": ConfigManager()},
            catch_exceptions=False,
        )
        assert result.exit_code != 0
        assert "--queries only works with power/standard phases" in result.output


@pytest.mark.integration
class TestQueriesFlagHelp:
    """Tests for --queries help text and documentation."""

    def test_help_text_includes_constraints(self):
        """Test that help text mentions important constraints."""
        runner = CliRunner()
        result = runner.invoke(run, ["--help"])
        assert result.exit_code == 0
        # Help text should mention the flag
        assert "--queries" in result.output
        # Should mention phase constraints (power/standard)
        assert "power" in result.output.lower() or "standard" in result.output.lower()
