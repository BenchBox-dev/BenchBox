"""Shared driver metadata propagation helpers for benchmark results."""

from __future__ import annotations

from typing import Any

# Fields propagated from adapter/config → result → execution_metadata.
# Order matters: it defines the iteration order for consistent output.
_DRIVER_FIELDS = (
    "driver_package",
    "driver_version_requested",
    "driver_version_resolved",
    "driver_version_actual",
    "driver_runtime_strategy",
    "driver_runtime_path",
    "driver_runtime_python_executable",
)

# execution_metadata keys that use setdefault (preserve existing values)
# rather than overwrite.
_SETDEFAULT_KEYS = frozenset({"driver_package", "driver_version_requested"})


def apply_driver_metadata(
    result: Any,
    *,
    database_config: Any = None,
    platform_adapter: Any = None,
) -> None:
    """Propagate driver/runtime metadata onto a benchmark result object.

    This helper is intentionally duck-typed so it can be reused by both
    orchestrator/lifecycle and legacy execution compatibility code.
    """
    if result is None:
        return

    values = _collect_driver_values(platform_adapter, database_config)
    _propagate_to_result(result, values)

    execution_metadata = getattr(result, "execution_metadata", None)
    if isinstance(execution_metadata, dict):
        _propagate_to_execution_dict(execution_metadata, values)


def _collect_driver_values(
    platform_adapter: Any,
    database_config: Any,
) -> dict[str, Any]:
    """Collect driver metadata values, adapter taking priority over config."""
    values: dict[str, Any] = dict.fromkeys(_DRIVER_FIELDS)
    values["auto_install_used"] = False

    if platform_adapter is not None:
        for field in _DRIVER_FIELDS:
            values[field] = getattr(platform_adapter, field, None) or values[field]
        values["auto_install_used"] = getattr(platform_adapter, "driver_auto_install_used", False)

    if database_config is not None:
        _merge_config_values(values, database_config)

    return values


def _merge_config_values(values: dict[str, Any], database_config: Any) -> None:
    """Merge database_config fields into values as fallbacks."""
    # Standard fields: use config value only when adapter didn't provide one.
    _STANDARD_CONFIG_ATTRS = (
        ("driver_package", "driver_package"),
        ("driver_version_actual", "driver_version_actual"),
        ("driver_runtime_strategy", "driver_runtime_strategy"),
        ("driver_runtime_path", "driver_runtime_path"),
        ("driver_runtime_python_executable", "driver_runtime_python_executable"),
    )
    for field, config_attr in _STANDARD_CONFIG_ATTRS:
        values[field] = values[field] or getattr(database_config, config_attr, None)

    # Special cases: attribute name differs or fallback chain is non-trivial.
    config_driver_version = getattr(database_config, "driver_version", None)
    values["driver_version_requested"] = values["driver_version_requested"] or config_driver_version
    db_resolved = getattr(database_config, "driver_version_resolved", None)
    values["driver_version_resolved"] = values["driver_version_resolved"] or db_resolved or config_driver_version
    values["auto_install_used"] = values["auto_install_used"] or bool(
        getattr(database_config, "driver_auto_install", False)
    )

    # Sync resolved version back to config when updated by the adapter.
    if (
        values["driver_version_resolved"]
        and getattr(database_config, "driver_version_resolved", None) != values["driver_version_resolved"]
    ):
        database_config.driver_version_resolved = values["driver_version_resolved"]


def _propagate_to_result(result: Any, values: dict[str, Any]) -> None:
    """Set driver metadata attributes on the result object where supported."""
    for field in _DRIVER_FIELDS:
        if hasattr(result, field):
            setattr(result, field, values[field])
    if hasattr(result, "driver_auto_install"):
        result.driver_auto_install = values["auto_install_used"]


def _propagate_to_execution_dict(execution_metadata: dict[str, Any], values: dict[str, Any]) -> None:
    """Fill the execution_metadata dict with driver information."""
    for field in _DRIVER_FIELDS:
        val = values[field]
        if val:
            if field in _SETDEFAULT_KEYS:
                execution_metadata.setdefault(field, val)
            else:
                execution_metadata[field] = val
    execution_metadata.setdefault("driver_auto_install_used", values["auto_install_used"])
