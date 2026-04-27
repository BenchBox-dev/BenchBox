"""Shared utilities for cloud platform adapters.

Consolidates duplicated patterns across Redshift, Snowflake, and other
cloud platforms to reduce copy-paste maintenance burden.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from typing import Any

from benchbox.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)


def validate_session_cache_control(
    *,
    connection: Any,
    query: str,
    setting_key: str,
    disabled_value: str,
    enabled_value: str,
    normalize: str,
    platform_name: str,
    disable_result_cache: bool,
    strict_validation: bool,
    adapter_logger: logging.Logger | None = None,
) -> dict[str, Any]:
    """Validate that session-level cache control settings were applied.

    Shared implementation for Redshift/Snowflake/etc. cache validation.

    Args:
        connection: Active database connection with cursor() support.
        query: SQL query that returns the current cache setting value.
        setting_key: Name of the setting in the result dict (e.g. ``USE_CACHED_RESULT``).
        disabled_value: Value when cache is off (e.g. ``"off"`` or ``"FALSE"``).
        enabled_value: Value when cache is on (e.g. ``"on"`` or ``"TRUE"``).
        normalize: ``"lower"`` or ``"upper"`` - how to normalize the raw value.
        platform_name: Human-readable platform name for error messages.
        disable_result_cache: Whether the adapter expects cache to be disabled.
        strict_validation: If True, raise ConfigurationError on mismatch.
        adapter_logger: Optional logger; falls back to module logger.

    Returns:
        Dict with ``validated``, ``cache_disabled``, ``settings``,
        ``warnings``, and ``errors`` keys.
    """
    log = adapter_logger or logger
    cursor = connection.cursor()
    result: dict[str, Any] = {
        "validated": False,
        "cache_disabled": False,
        "settings": {},
        "warnings": [],
        "errors": [],
    }

    try:
        cursor.execute(query)
        row = cursor.fetchone()

        if row:
            raw = str(row[0])
            actual_value = raw.lower() if normalize == "lower" else raw.upper()
            result["settings"][setting_key] = actual_value

            expected_value = disabled_value if disable_result_cache else enabled_value

            if actual_value == expected_value:
                result["validated"] = True
                result["cache_disabled"] = actual_value == disabled_value
                log.debug(f"Cache control validated: {setting_key}={actual_value} (expected {expected_value})")
            else:
                error_msg = (
                    f"Cache control validation failed: expected {setting_key}={expected_value}, got {actual_value}"
                )
                result["errors"].append(error_msg)
                log.error(error_msg)

                if strict_validation:
                    raise ConfigurationError(
                        f"{platform_name} session cache control validation failed - "
                        "benchmark results may be incorrect due to cached query results",
                        details=result,
                    )
        else:
            warning_msg = f"Could not retrieve {setting_key} parameter from session"
            result["warnings"].append(warning_msg)
            log.warning(warning_msg)

    except ConfigurationError:
        raise
    except Exception as e:
        error_msg = f"Validation query failed: {e}"
        result["errors"].append(error_msg)
        log.error(f"Cache control validation error: {e}")

        if strict_validation:
            raise ConfigurationError(
                f"Failed to validate {platform_name} cache control settings",
                details={"original_error": str(e), "validation_result": result},
            ) from e
    finally:
        cursor.close()

    return result
