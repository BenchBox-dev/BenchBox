"""Tests for linting tool consolidation.

Verifies that redundant linting tools have been removed and ruff handles
all linting and formatting tasks correctly.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import subprocess
import sys
from pathlib import Path

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[import-not-found]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestLintingConsolidation:
    """Test that linting has been properly consolidated to ruff."""

    def test_pyproject_toml_has_ruff_config(self):
        """Test that pyproject.toml contains comprehensive ruff configuration."""
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        # Verify ruff configuration exists
        assert "tool" in config
        assert "ruff" in config["tool"]

        ruff_config = config["tool"]["ruff"]

        # Basic settings
        assert "line-length" in ruff_config
        assert ruff_config["line-length"] == 120
        assert "exclude" in ruff_config

        # Linting configuration
        assert "lint" in ruff_config
        lint_config = ruff_config["lint"]
        assert "select" in lint_config
        assert "ignore" in lint_config

        # Should include key rule sets
        selected_rules = lint_config["select"]
        assert "E" in selected_rules  # pycodestyle errors
        assert "W" in selected_rules  # pycodestyle warnings
        assert "F" in selected_rules  # pyflakes
        assert "I" in selected_rules  # isort

        # Import sorting configuration
        assert "isort" in ruff_config["lint"]

        # Formatting configuration
        assert "format" in ruff_config
        format_config = ruff_config["format"]
        assert "quote-style" in format_config
        assert "indent-style" in format_config

    def test_redundant_tool_configs_removed(self):
        """Test that redundant tool configurations have been removed."""
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        tool_config = config.get("tool", {})

        # These tools should no longer have configuration sections
        redundant_tools = ["isort", "pycodestyle", "flake8", "black"]
        for tool in redundant_tools:
            assert tool not in tool_config, f"Found configuration for redundant tool: {tool}"

    def test_dev_dependencies_only_include_ruff(self):
        """Test that dev dependencies only include ruff for linting/formatting."""
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        # Check dependency-groups dev section
        dev_deps = config.get("dependency-groups", {}).get("dev", [])

        # Should include ruff
        ruff_found = any("ruff" in dep for dep in dev_deps)
        assert ruff_found, "ruff not found in dev dependencies"

        # Should not include redundant linting tools
        redundant_tools = ["black", "isort", "pycodestyle", "flake8"]
        for tool in redundant_tools:
            tool_found = any(tool in dep for dep in dev_deps)
            assert not tool_found, f"Redundant tool {tool} found in dev dependencies"

    def test_ruff_commands_work(self):
        """Test that ruff commands execute successfully."""
        # Test ruff check (may find issues but should not crash)
        result = subprocess.run(
            ["uv", "run", "ruff", "check", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 0, f"ruff check failed: {result.stderr}"

        # Test ruff format
        result = subprocess.run(
            ["uv", "run", "ruff", "format", "--help"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        assert result.returncode == 0, f"ruff format failed: {result.stderr}"

    def test_makefile_targets_use_ruff(self):
        """Test that Makefile targets use ruff commands."""
        makefile_path = Path(__file__).parent.parent.parent / "Makefile"

        with open(makefile_path, encoding="utf-8") as f:
            makefile_content = f.read()

        # Lint target should use ruff check
        assert "lint:" in makefile_content
        assert "uv run ruff check ." in makefile_content

        # Format target should use ruff format
        assert "format:" in makefile_content
        assert "uv run ruff format ." in makefile_content

        # Should not contain references to old tools
        redundant_commands = ["black", "isort", "flake8", "pycodestyle"]
        for cmd in redundant_commands:
            assert cmd not in makefile_content, f"Found reference to {cmd} in Makefile"

    def test_github_actions_use_ruff(self):
        """Test that GitHub Actions workflows use ruff."""
        lint_workflow_path = Path(__file__).parent.parent.parent / ".github" / "workflows" / "lint.yml"

        with open(lint_workflow_path, encoding="utf-8") as f:
            workflow_content = f.read()

        # Should use ruff commands
        assert "uv run ruff check ." in workflow_content
        assert "uv run ruff format --check ." in workflow_content

        # Should not install redundant tools
        redundant_tools = ["black", "isort", "flake8", "pycodestyle"]
        for tool in redundant_tools:
            assert f"pip install {tool}" not in workflow_content, f"Found {tool} installation in workflow"

    @pytest.mark.integration
    def test_linting_integration_works(self):
        """Integration test that linting workflow works end-to-end."""
        project_root = Path(__file__).parent.parent.parent

        # Test that we can run ruff check on a sample file
        sample_file = project_root / "benchbox" / "__init__.py"
        assert sample_file.exists()

        result = subprocess.run(
            ["uv", "run", "ruff", "check", str(sample_file)], capture_output=True, text=True, cwd=project_root
        )
        # Command should execute (may find issues, but shouldn't crash)
        assert result.returncode in [0, 1], f"ruff check failed unexpectedly: {result.stderr}"

        # Test format check
        result = subprocess.run(
            ["uv", "run", "ruff", "format", "--check", str(sample_file)],
            capture_output=True,
            text=True,
            cwd=project_root,
        )
        # Command should execute
        assert result.returncode in [0, 1], f"ruff format check failed unexpectedly: {result.stderr}"


class TestRuffConfiguration:
    """Test specific ruff configuration aspects."""

    def test_ruff_rule_selection(self):
        """Test that ruff is configured with appropriate rules."""
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        selected_rules = config["tool"]["ruff"]["lint"]["select"]

        # Should include core Python linting rules
        expected_rule_prefixes = ["E", "W", "F", "I", "N", "UP", "B"]
        for prefix in expected_rule_prefixes:
            assert prefix in selected_rules, f"Missing rule prefix: {prefix}"

    def test_ruff_import_sorting_config(self):
        """Test that ruff import sorting is properly configured."""
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        isort_config = config["tool"]["ruff"]["lint"]["isort"]

        # Should have basic isort configuration
        assert "force-single-line" in isort_config
        assert "combine-as-imports" in isort_config
        assert isort_config["combine-as-imports"] is True

    def test_ruff_format_black_compatibility(self):
        """Test that ruff formatting is configured for black compatibility."""
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"

        with open(pyproject_path, "rb") as f:
            config = tomllib.load(f)

        format_config = config["tool"]["ruff"]["format"]

        # Should be compatible with black formatting
        assert format_config["quote-style"] == "double"
        assert format_config["indent-style"] == "space"
        assert format_config["line-ending"] == "auto"
