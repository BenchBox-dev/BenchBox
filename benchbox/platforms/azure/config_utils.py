"""Shared config builder for Azure-compatible platform adapters."""

from __future__ import annotations

from typing import Any


def build_platform_config(
    platform_type: str,
    credential_key: str,
    default_display_name: str,
    default_driver_package: str,
    platform_fields: list[str],
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
) -> Any:
    """Build a DatabaseConfig with credential loading and option merging.

    Shared implementation for Azure-compatible platforms (Azure Synapse,
    LakeSail) that follow the same config construction pattern.

    Args:
        platform_type: Config type identifier (e.g. "synapse", "lakesail").
        credential_key: Key for CredentialManager lookup.
        default_display_name: Fallback display name if info is None.
        default_driver_package: Fallback driver package if info is None.
        platform_fields: Field names to extract from merged_options.
        options: CLI platform options dict.
        overrides: Runtime override dict.
        info: Platform info from registry (has .display_name, .driver_package).

    Returns:
        A DatabaseConfig instance.
    """
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials(credential_key) or {}

    merged_options: dict[str, Any] = {}
    merged_options.update(saved_creds)
    merged_options.update(options)
    merged_options.update(overrides)

    name = info.display_name if info else default_display_name
    driver_package = info.driver_package if info else default_driver_package

    config_dict: dict[str, Any] = {
        "type": platform_type,
        "name": name,
        "options": merged_options or {},
        "driver_package": driver_package,
        "driver_version": overrides.get("driver_version") or options.get("driver_version"),
        "driver_auto_install": bool(overrides.get("driver_auto_install", options.get("driver_auto_install", False))),
    }

    for field in platform_fields:
        config_dict[field] = merged_options.get(field)

    config_dict["benchmark"] = overrides.get("benchmark")
    config_dict["scale_factor"] = overrides.get("scale_factor")
    config_dict["tuning_config"] = overrides.get("tuning_config")

    if "database" in overrides and overrides["database"]:
        config_dict["database"] = overrides["database"]

    return DatabaseConfig(**config_dict)
