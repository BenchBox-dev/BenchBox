"""Tests for shared cloud platform adapter utilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from unittest.mock import Mock

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.cloud_shared import validate_session_cache_control

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_validate_session_cache_control_success():
    """Validates session cache setting successfully with default value column index 0."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = ("off",)

    result = validate_session_cache_control(
        connection=mock_conn,
        query="SHOW enable_result_cache_for_session",
        setting_key="enable_result_cache_for_session",
        disabled_value="off",
        enabled_value="on",
        normalize="lower",
        platform_name="Redshift",
        disable_result_cache=True,
        strict_validation=True,
    )

    assert result["validated"] is True
    assert result["cache_disabled"] is True
    assert result["settings"]["enable_result_cache_for_session"] == "off"
    assert not result["errors"]
    assert not result["warnings"]


def test_validate_session_cache_control_with_value_column_index():
    """Validates session cache setting when value is at a non-zero column index (e.g. Snowflake SHOW PARAMETERS)."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    # Snowflake SHOW PARAMETERS returns (key, value, default, ...)
    mock_cursor.fetchone.return_value = ("USE_CACHED_RESULT", "FALSE", "TRUE", "BOOLEAN")

    result = validate_session_cache_control(
        connection=mock_conn,
        query="SHOW PARAMETERS LIKE 'USE_CACHED_RESULT' IN SESSION",
        setting_key="USE_CACHED_RESULT",
        disabled_value="FALSE",
        enabled_value="TRUE",
        normalize="upper",
        platform_name="Snowflake",
        disable_result_cache=True,
        strict_validation=True,
        value_column_index=1,
    )

    assert result["validated"] is True
    assert result["cache_disabled"] is True
    assert result["settings"]["USE_CACHED_RESULT"] == "FALSE"
    assert not result["errors"]


def test_validate_session_cache_control_mismatch_strict():
    """Raises ConfigurationError when cache setting does not match expected and strict=True."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = ("on",)

    with pytest.raises(ConfigurationError) as exc_info:
        validate_session_cache_control(
            connection=mock_conn,
            query="SHOW enable_result_cache_for_session",
            setting_key="enable_result_cache_for_session",
            disabled_value="off",
            enabled_value="on",
            normalize="lower",
            platform_name="Redshift",
            disable_result_cache=True,
            strict_validation=True,
        )

    assert "Redshift session cache control validation failed" in str(exc_info.value)


def test_validate_session_cache_control_no_row():
    """Adds a warning when fetchone returns None."""
    mock_conn = Mock()
    mock_cursor = Mock()
    mock_conn.cursor.return_value = mock_cursor
    mock_cursor.fetchone.return_value = None

    result = validate_session_cache_control(
        connection=mock_conn,
        query="SHOW enable_result_cache_for_session",
        setting_key="enable_result_cache_for_session",
        disabled_value="off",
        enabled_value="on",
        normalize="lower",
        platform_name="Redshift",
        disable_result_cache=True,
        strict_validation=False,
    )

    assert result["validated"] is False
    assert len(result["warnings"]) == 1
    assert "Could not retrieve enable_result_cache_for_session" in result["warnings"][0]
