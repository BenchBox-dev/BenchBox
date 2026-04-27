"""Canonical ClickHouse deployment-mode normalization helpers.

Migration Contract (as of 2026-04-11):
    Three first-class platform names now represent the ClickHouse family:
    - ``clickhouse-local``  - embedded chDB (in-process, no network)
    - ``clickhouse-server`` - self-hosted ClickHouse via clickhouse-driver (Docker/dedicated)
    - ``clickhouse-cloud``  - managed ClickHouse Cloud via clickhouse-connect

    Bare ``clickhouse`` and colon-suffix syntax (``clickhouse:local``,
    ``clickhouse:server``) are accepted as deprecating compatibility aliases.
    They emit a DeprecationWarning and route to the appropriate first-class name.
    These aliases will be removed after one deprecation window.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

DEFAULT_CLICKHOUSE_DEPLOYMENT_MODE = "local"
CLICKHOUSE_DEPLOYMENT_MODE_VALUES = frozenset({"local", "server"})
CLICKHOUSE_DEPLOYMENT_MODE_ALIASES = {
    "embedded": "local",
}

# ---------------------------------------------------------------------------
# Migration contract: canonical first-class platform names
# ---------------------------------------------------------------------------

#: The three first-class ClickHouse platform identifiers.
CLICKHOUSE_CANONICAL_PLATFORM_NAMES: frozenset[str] = frozenset(
    {"clickhouse-local", "clickhouse-server", "clickhouse-cloud"}
)

#: Explicit colon-suffix selectors mapped to their canonical first-class names.
#: Bare ``clickhouse`` is handled separately (deployment-aware).
CLICKHOUSE_LEGACY_SELECTOR_MAP: dict[str, str] = {
    "clickhouse:local": "clickhouse-local",
    "clickhouse:server": "clickhouse-server",
    "clickhouse:cloud": "clickhouse-cloud",
}

#: Default canonical platform for bare ``clickhouse`` (matches current default_deployment="local").
CLICKHOUSE_DEFAULT_CANONICAL_PLATFORM: str = "clickhouse-local"

#: All ClickHouse family platform names, including legacy and first-class.
#: Use ``is_clickhouse_platform()`` for membership tests instead of direct string comparison.
_CLICKHOUSE_ALL_PLATFORM_NAMES: frozenset[str] = frozenset(
    {
        "clickhouse",
        "clickhouse-local",
        "clickhouse-server",
        "clickhouse-cloud",
        "chdb",
    }
)


def is_clickhouse_platform(platform: str) -> bool:
    """Return True if *platform* belongs to the ClickHouse family.

    Accepts all ClickHouse platform names: first-class (``clickhouse-local``,
    ``clickhouse-server``, ``clickhouse-cloud``), the legacy base name
    (``clickhouse``), and the internal chDB alias (``chdb``).

    Args:
        platform: Platform name string (case-insensitive).

    Returns:
        True if the platform is in the ClickHouse family.
    """
    return platform.lower() in _CLICKHOUSE_ALL_PLATFORM_NAMES


def clickhouse_legacy_selector_warning(selector: str, target: str) -> str:
    """Return the canonical deprecation message for a legacy ClickHouse selector.

    Args:
        selector: The legacy selector used (e.g. ``clickhouse``, ``clickhouse:local``).
        target: The first-class platform name to migrate to.

    Returns:
        Human-readable deprecation message with migration guidance.
    """
    return (
        f"ClickHouse selector '{selector}' is deprecated. "
        f"Use '--platform {target}' instead. "
        "See docs/platforms/clickhouse-migration.md for the full migration guide."
    )


def clickhouse_cloud_mode_error_message() -> str:
    """Return the canonical guidance for deprecated base-platform cloud mode."""
    return (
        "ClickHouse Cloud is now a separate first-class platform.\n"
        "Use --platform clickhouse-cloud instead of --platform clickhouse:cloud\n"
        "For more information: benchbox run --platform clickhouse-cloud --help"
    )


def normalize_clickhouse_deployment_mode(
    value: Any,
    *,
    default: str = DEFAULT_CLICKHOUSE_DEPLOYMENT_MODE,
    allow_cloud: bool = False,
) -> str:
    """Normalize a ClickHouse deployment selector to canonical values.

    Accepted compatibility inputs:
    - ``local`` -> ``local``
    - ``server`` -> ``server``
    - ``embedded`` -> ``local``
    - ``True``/``False`` for legacy ``embedded`` booleans -> ``local``/``server``

    Args:
        value: Raw deployment selector.
        default: Canonical fallback when value is unset.
        allow_cloud: Whether the dedicated ClickHouse Cloud adapter may pass through
            ``cloud`` during its internal initialization path.

    Returns:
        Canonical deployment mode string.

    Raises:
        ValueError: If the value is invalid or points to deprecated base-platform cloud mode.
    """
    if value is None:
        return default

    if isinstance(value, bool):
        return "local" if value else "server"

    normalized = str(value).strip().lower()
    if not normalized:
        return default

    if normalized == "cloud":
        if allow_cloud:
            return "cloud"
        raise ValueError(clickhouse_cloud_mode_error_message())

    normalized = CLICKHOUSE_DEPLOYMENT_MODE_ALIASES.get(normalized, normalized)
    if normalized in CLICKHOUSE_DEPLOYMENT_MODE_VALUES:
        return normalized

    valid_modes = sorted(CLICKHOUSE_DEPLOYMENT_MODE_VALUES)
    raise ValueError(f"Invalid ClickHouse deployment mode '{normalized}'. Valid modes: {', '.join(valid_modes)}")


def resolve_clickhouse_deployment_mode(
    config: Mapping[str, Any],
    *,
    default: str = DEFAULT_CLICKHOUSE_DEPLOYMENT_MODE,
    allow_cloud: bool = False,
) -> str:
    """Resolve deployment mode from canonical and legacy ClickHouse config keys.

    Resolution priority is:
    1. ``deployment_mode`` (canonical)
    2. ``mode`` (legacy string alias)
    3. ``embedded`` (legacy bool alias)
    4. ``default``
    """
    if (value := config.get("deployment_mode")) not in (None, ""):
        return normalize_clickhouse_deployment_mode(value, default=default, allow_cloud=allow_cloud)

    if (value := config.get("mode")) not in (None, ""):
        return normalize_clickhouse_deployment_mode(value, default=default, allow_cloud=allow_cloud)

    if "embedded" in config and config.get("embedded") is not None:
        return normalize_clickhouse_deployment_mode(config["embedded"], default=default, allow_cloud=allow_cloud)

    return default


__all__ = [
    "CLICKHOUSE_CANONICAL_PLATFORM_NAMES",
    "CLICKHOUSE_DEFAULT_CANONICAL_PLATFORM",
    "CLICKHOUSE_DEPLOYMENT_MODE_ALIASES",
    "CLICKHOUSE_DEPLOYMENT_MODE_VALUES",
    "CLICKHOUSE_LEGACY_SELECTOR_MAP",
    "DEFAULT_CLICKHOUSE_DEPLOYMENT_MODE",
    "clickhouse_cloud_mode_error_message",
    "clickhouse_legacy_selector_warning",
    "is_clickhouse_platform",
    "normalize_clickhouse_deployment_mode",
    "resolve_clickhouse_deployment_mode",
]
