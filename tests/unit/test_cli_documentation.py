"""Tests for CLI documentation and help system improvements."""

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestCLIDocumentation:
    """Test CLI help text and documentation improvements."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_main_cli_help_includes_description(self):
        """Test that main CLI help includes comprehensive description."""
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

        # Check for enhanced main description
        assert "Interactive database benchmark runner" in result.output
        assert "comprehensive benchmarking capabilities" in result.output
        assert "TPC-H, TPC-DS" in result.output
        assert "Quick start:" in result.output

    def test_run_command_help_comprehensive(self):
        """Test that run command help is comprehensive and includes examples."""
        result = self.runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0

        # Check for basic help content
        assert "Run benchmarks" in result.output
        assert "--platform" in result.output
        assert "--benchmark" in result.output
        assert "Examples:" in result.output
        assert "--help-topic examples" in result.output  # Points to full examples

    def test_run_command_help_examples(self):
        """Test that run command --help-topic examples shows categorized examples."""
        result = self.runner.invoke(cli, ["run", "--help-topic", "examples"])
        assert result.exit_code == 0

        # Check for cloud platform examples
        assert "Snowflake:" in result.output
        assert "Databricks:" in result.output
        assert "BigQuery:" in result.output
        assert "Redshift:" in result.output

        # Check for newly added platform examples
        assert "Firebolt Core:" in result.output
        assert "Firebolt Cloud:" in result.output
        assert "Presto:" in result.output
        assert "Trino:" in result.output
        assert "Athena:" in result.output
        assert "Azure Synapse:" in result.output
        assert "Fabric Warehouse:" in result.output
        assert "PostgreSQL:" in result.output

        # Check for local and DataFrame platforms
        assert "Local Platforms:" in result.output
        assert "DataFrame Platforms:" in result.output

        # Check for use-case examples
        assert "Quick Validation" in result.output
        assert "Full TPC Benchmark:" in result.output
        assert "Platform Comparison:" in result.output

        # Check for tuning and advanced examples
        assert "Tuning Configuration:" in result.output
        assert "Dry Run (Preview):" in result.output
        assert "Compression (Advanced):" in result.output

    def test_profile_command_help_enhanced(self):
        """Test that profile command help includes detailed description."""
        result = self.runner.invoke(cli, ["profile", "--help"])
        assert result.exit_code == 0

        # Check for enhanced description and examples
        assert "optimization recommendations" in result.output
        assert "CPU, memory, disk space" in result.output
        assert "Examples:" in result.output
        assert "benchbox profile" in result.output

    def test_benchmarks_list_help_enhanced(self):
        """Test that benchmarks list command help is comprehensive."""
        result = self.runner.invoke(cli, ["benchmarks", "list", "--help"])
        assert result.exit_code == 0

        # Check for detailed description
        assert "benchmark suites with descriptions" in result.output
        assert "TPC standards" in result.output
        assert "industry benchmarks" in result.output
        assert "Examples:" in result.output

    def test_validate_command_help_enhanced(self):
        """Test that validate command help includes examples."""
        result = self.runner.invoke(cli, ["validate", "--help"])
        assert result.exit_code == 0

        # Check for enhanced description and examples
        assert "syntax and completeness" in result.output
        assert "Examples:" in result.output
        assert "benchbox validate" in result.output
        assert "--config custom.yaml" in result.output

    def test_export_command_help_enhanced(self):
        """Test that export command help includes examples."""
        result = self.runner.invoke(cli, ["export", "--help"])
        assert result.exit_code == 0

        # Check for enhanced description and examples
        assert "various formats" in result.output
        assert "sharing results" in result.output  # Part of "sharing results, generating reports"
        assert "Examples:" in result.output
        assert "benchbox export" in result.output or "cli export" in result.output

    def test_check_deps_help_enhanced(self):
        """Test that check-deps command help includes examples."""
        result = self.runner.invoke(cli, ["check-deps", "--help"])
        assert result.exit_code == 0

        # Check for enhanced description and examples
        assert "installation guidance" in result.output
        assert "installation matrix" in result.output
        assert "Examples:" in result.output
        assert "--platform databricks" in result.output
        assert "--matrix" in result.output

    def test_results_command_help_enhanced(self):
        """Test that results command help includes examples."""
        result = self.runner.invoke(cli, ["results", "--help"])
        assert result.exit_code == 0

        # Check for enhanced description and examples
        assert "execution history" in result.output
        assert "performance" in result.output  # Part of "performance metrics"
        assert "Examples:" in result.output
        assert "--limit 25" in result.output

    def test_setup_command_help_available(self):
        """Test that setup command help is available."""
        result = self.runner.invoke(cli, ["setup", "--help"])
        assert result.exit_code == 0
        assert "setup" in result.output.lower() or "credential" in result.output.lower()

    def test_all_commands_have_help(self):
        """Test that all commands provide help without errors."""
        # Get list of commands
        result = self.runner.invoke(cli, ["--help"])
        assert result.exit_code == 0

        # Extract command names from help output
        commands = []
        lines = result.output.split("\n")
        in_commands_section = False

        for line in lines:
            if "Commands:" in line:
                in_commands_section = True
                continue
            if in_commands_section and line.strip():
                if line.startswith("  ") and not line.startswith("    "):
                    stripped = line.strip()
                    # Skip category headers (end with ":" after any text)
                    # Category lines have format "Category Name:" with no additional text
                    if stripped.endswith(":"):
                        continue
                    command_name = stripped.split()[0]
                    commands.append(command_name)

        # Test help for each command
        for command in commands:
            if command:  # Skip empty strings
                result = self.runner.invoke(cli, [command, "--help"])
                assert result.exit_code == 0, f"Help failed for command: {command}"
                assert "Usage:" in result.output, f"No usage info for command: {command}"

    def test_cli_reference_documentation_exists(self):
        """Test that CLI reference documentation file exists."""
        from pathlib import Path

        # Check if CLI_REFERENCE.md exists
        docs_path = Path(__file__).parent.parent.parent / "docs" / "CLI_REFERENCE.md"
        assert docs_path.exists(), "CLI_REFERENCE.md documentation file should exist"

        # Check that it has content
        content = docs_path.read_text()
        assert len(content) > 1000, "CLI_REFERENCE.md should have substantial content"
        assert "# BenchBox CLI Reference" in content, "CLI_REFERENCE.md should have proper title"
        assert "## Command Reference" in content, "CLI_REFERENCE.md should have command reference section"

    @pytest.mark.parametrize(
        "command,expected_content",
        [
            (["run"], ["Run benchmarks", "--platform", "--benchmark", "Examples:"]),
            (["profile"], ["optimization recommendations", "Examples:"]),
            (["benchmarks", "list"], ["benchmark suites", "TPC standards", "Examples:"]),
            (["validate"], ["syntax and completeness", "Examples:"]),
            (["export"], ["various formats", "Examples:"]),
            (["check-deps"], ["installation guidance", "Examples:"]),
            (["results"], ["execution history", "Examples:"]),
        ],
    )
    def test_command_help_content_quality(self, command, expected_content):
        """Test that each command has quality help content."""
        result = self.runner.invoke(cli, command + ["--help"])
        assert result.exit_code == 0

        for content in expected_content:
            assert content in result.output, f"Command {command} missing expected content: {content}"

    def test_help_examples_are_valid_syntax(self):
        """Test that help examples use valid CLI syntax."""
        # Test run command examples in help
        result = self.runner.invoke(cli, ["run", "--help"])
        assert result.exit_code == 0

        # Check that examples follow proper syntax patterns
        examples = result.output

        # Look for common patterns that should be present
        assert "--platform duckdb" in examples
        assert "--benchmark tpch" in examples
        assert "--scale" in examples
        assert "--phases" in examples
        assert "--dry-run" in examples
        assert "--tuning" in examples

        # Ensure examples use proper flag format
        lines = examples.split("\n")
        example_lines = [line for line in lines if "benchbox run" in line and "--" in line]

        for line in example_lines:
            # Examples should not have obvious syntax errors
            assert not line.strip().endswith("--"), f"Malformed example line: {line}"
            assert "--=" not in line, f"Malformed option in example: {line}"

    def test_version_callback_works(self):
        """Test that version callback provides enhanced version information."""
        result = self.runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

        # Should contain version information
        output = result.output.lower()
        assert "benchbox" in output or "version" in output

    def test_help_consistency_across_commands(self):
        """Test that help text style is consistent across commands."""
        commands_to_test = [
            ["profile"],
            ["benchmarks", "list"],
            ["validate"],
            ["export"],
        ]  # Excluding "run" for now

        for command in commands_to_test:
            result = self.runner.invoke(cli, command + ["--help"])
            assert result.exit_code == 0

            # All enhanced commands should have Examples section
            assert "Examples:" in result.output, f"Command {command} missing Examples section"

            # Help should be descriptive - look for substantial content
            # Check that the help contains more than just basic usage
            lines = result.output.split("\n")
            substantial_content = False

            for line in lines:
                # Look for descriptive lines that explain what the command does
                if len(line.strip()) > 60 and ("." in line or "with" in line.lower() or "including" in line.lower()):
                    substantial_content = True
                    break

            assert substantial_content, f"Command {command} lacks substantial description"
