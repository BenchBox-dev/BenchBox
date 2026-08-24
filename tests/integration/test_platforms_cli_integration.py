"""Integration tests for platforms CLI commands via subprocess."""

from __future__ import annotations

import pytest

from tests.integration._cli_e2e_utils import run_cli_command

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


@pytest.mark.integration
def test_platforms_command_help():
    """Test that platforms command shows help correctly."""
    result = run_cli_command(["platforms", "--help"])

    assert result.returncode == 0
    assert "Manage database platform adapters" in result.stdout
    assert "Commands:" in result.stdout
    # Verify all subcommands are listed
    assert "list" in result.stdout
    assert "status" in result.stdout
    assert "enable" in result.stdout
    assert "disable" in result.stdout
    assert "install" in result.stdout
    assert "check" in result.stdout
    assert "setup" in result.stdout


@pytest.mark.integration
def test_platforms_list_command():
    """Test that platforms list command executes successfully."""
    result = run_cli_command(["platforms", "list"])

    assert result.returncode == 0
    # Should show at least DuckDB which is always available
    assert "DuckDB" in result.stdout or "duckdb" in result.stdout.lower()
    # Should have table header or status indicators
    assert "Platform" in result.stdout or "Status" in result.stdout or "✅" in result.stdout


@pytest.mark.integration
def test_platforms_list_help():
    """Test that platforms list shows help correctly."""
    result = run_cli_command(["platforms", "list", "--help"])

    assert result.returncode == 0
    assert "List all available platforms" in result.stdout
    assert "--all" in result.stdout
    assert "--format" in result.stdout


@pytest.mark.integration
def test_platforms_status_all():
    """Test that platforms status command works without arguments."""
    result = run_cli_command(["platforms", "status"])

    assert result.returncode == 0
    # Should show platform information
    assert "DuckDB" in result.stdout or "Platform" in result.stdout


@pytest.mark.integration
def test_platforms_status_specific():
    """Test that platforms status shows info for specific platform."""
    result = run_cli_command(["platforms", "status", "duckdb"])

    assert result.returncode == 0
    assert "DuckDB" in result.stdout
    # Should show library information
    assert "duckdb" in result.stdout.lower()


@pytest.mark.integration
def test_platforms_status_help():
    """Test that platforms status shows help correctly."""
    result = run_cli_command(["platforms", "status", "--help"])

    assert result.returncode == 0
    assert "Show detailed status" in result.stdout


@pytest.mark.integration
def test_platforms_check_command():
    """Test that platforms check command executes successfully."""
    result = run_cli_command(["platforms", "check"])

    # Should succeed with exit code 0 if all platforms are ready
    # Or exit code 1 if some platforms have issues
    assert result.returncode in (0, 1)
    # Should show check results
    assert "Ready" in result.stdout or "Platform Check Results" in result.stdout


@pytest.mark.integration
def test_platforms_check_help():
    """Test that platforms check shows help correctly."""
    result = run_cli_command(["platforms", "check", "--help"])

    assert result.returncode == 0
    assert "Check platform availability" in result.stdout
    assert "--enabled-only" in result.stdout


@pytest.mark.integration
def test_platforms_enable_help():
    """Test that platforms enable shows help correctly."""
    result = run_cli_command(["platforms", "enable", "--help"])

    assert result.returncode == 0
    assert "Enable a database platform" in result.stdout
    assert "--force" in result.stdout


@pytest.mark.integration
def test_platforms_disable_help():
    """Test that platforms disable shows help correctly."""
    result = run_cli_command(["platforms", "disable", "--help"])

    assert result.returncode == 0
    assert "Disable a database platform" in result.stdout


@pytest.mark.integration
def test_platforms_install_help():
    """Test that platforms install shows help correctly."""
    result = run_cli_command(["platforms", "install", "--help"])

    assert result.returncode == 0
    assert "Guide installation" in result.stdout or "installation" in result.stdout.lower()
    assert "--dry-run" in result.stdout


@pytest.mark.integration
def test_platforms_setup_help():
    """Test that platforms setup shows help correctly.

    The summary line moved from "Interactive platform setup wizard" to one
    that says what the command actually does, when `--platform` was added to
    delegate credential setup to `benchbox setup` (#1844). Assert on the
    options and on the cross-reference the two same-named commands rely on,
    rather than on prose that is expected to be edited.
    """
    result = run_cli_command(["platforms", "setup", "--help"])

    assert result.returncode == 0
    assert "--interactive" in result.stdout
    assert "--non-interactive" in result.stdout
    assert "--platform" in result.stdout
    # `benchbox setup` is the other command spelled "setup"; each help text
    # must name the other so a user who lands on one can find the right one.
    assert "benchbox setup" in result.stdout


@pytest.mark.integration
def test_platforms_install_specific():
    """Test that platforms install provides guidance for specific platform."""
    result = run_cli_command(["platforms", "install", "duckdb"])

    assert result.returncode == 0
    # Should show installation guidance (even if already installed)
    assert "duckdb" in result.stdout.lower() or "DuckDB" in result.stdout


@pytest.mark.integration
def test_platforms_command_appears_in_main_help():
    """Test that platforms command is listed in main CLI help."""
    result = run_cli_command(["--help"])

    assert result.returncode == 0
    assert "platforms" in result.stdout
    assert "Manage database platform adapters" in result.stdout


@pytest.mark.integration
def test_platforms_check_specific_platform():
    """Test checking a specific platform that should be available."""
    result = run_cli_command(["platforms", "check", "duckdb"])

    # DuckDB should always be available
    assert result.returncode == 0
    assert "Ready" in result.stdout or "ready" in result.stdout.lower()


@pytest.mark.integration
def test_platforms_list_with_format_option():
    """Test platforms list with different format options."""
    # Test table format
    result_table = run_cli_command(["platforms", "list", "--format", "table"])
    assert result_table.returncode == 0

    # Test simple format
    result_simple = run_cli_command(["platforms", "list", "--format", "simple"])
    assert result_simple.returncode == 0

    # Both should show platform information
    assert "duckdb" in result_table.stdout.lower()
    assert "duckdb" in result_simple.stdout.lower()


@pytest.mark.integration
def test_platforms_list_with_all_flag():
    """Test platforms list --all shows unavailable platforms."""
    result = run_cli_command(["platforms", "list", "--all"])

    assert result.returncode == 0
    # Should show platform information
    assert "Platform" in result.stdout or "duckdb" in result.stdout.lower()


@pytest.mark.integration
def test_platforms_check_enabled_only():
    """Test platforms check with --enabled-only flag."""
    result = run_cli_command(["platforms", "check", "--enabled-only"])

    # Should execute successfully
    assert result.returncode in (0, 1)
    # Should show some check output
    assert len(result.stdout) > 0


@pytest.mark.integration
def test_platforms_status_unknown_platform():
    """Test platforms status with unknown platform name."""
    result = run_cli_command(["platforms", "status", "nonexistent-platform"])

    # Should fail or show an error message
    assert "Unknown platform" in result.stdout or "not found" in result.stdout.lower() or result.returncode != 0
