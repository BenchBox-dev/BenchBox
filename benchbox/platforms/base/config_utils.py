"""Shared config builder for BenchBox platform adapters."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

POSTGRES_FAMILY_BASE_OPTIONS: dict[str, Any] = {
    "host": "localhost",
    "port": 5432,
    "username": "postgres",
    "schema": "public",
    "admin_database": "postgres",
    "sslmode": "prefer",
    "work_mem": "256MB",
    "maintenance_work_mem": "512MB",
    "effective_cache_size": "1GB",
    "max_parallel_workers_per_gather": 2,
}


def build_platform_config(
    platform_type: str,
    credential_key: str,
    default_display_name: str,
    default_driver_package: str,
    platform_fields: list[str],
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Any,
    base_options: dict[str, Any] | None = None,
) -> Any:
    """Build a DatabaseConfig with credential loading and option merging.

    Shared implementation for platform adapters that follow the standard
    config construction pattern (credential merge → option merge → DatabaseConfig).

    Args:
        platform_type: Config type identifier (e.g. "velox", "lakesail").
        credential_key: Key for CredentialManager lookup.
        default_display_name: Fallback display name if info is None.
        default_driver_package: Fallback driver package if info is None.
        platform_fields: Field names to extract from merged_options.
        options: CLI platform options dict.
        overrides: Runtime override dict.
        info: Platform info from registry (has .display_name, .driver_package).
        base_options: Optional seed values applied before options (lowest priority).
            Used by platforms that need a fixed default (e.g. schema="public")
            that options/credentials/overrides should still be able to override.

    Returns:
        A DatabaseConfig instance.
    """
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials(credential_key) or {}

    explicit_options = overrides.get("_explicit_platform_options", {})

    merged_options: dict[str, Any] = dict(base_options or {})
    merged_options.update(options)  # registered defaults (lowest priority)
    merged_options.update(saved_creds)  # saved credentials win over defaults
    merged_options.update(explicit_options)  # explicit CLI flags win over credentials
    merged_options.update(overrides)  # runtime overrides (highest priority)

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


def build_adapter_config(
    config: dict[str, Any],
    *,
    platform: str,
    generated_key: str | None = "database",
    fields: Iterable[str] = (),
    include_none: bool = True,
) -> dict[str, Any]:
    """Build common adapter constructor kwargs from unified config."""
    adapter_config: dict[str, Any] = {}
    if generated_key:
        if config.get(generated_key):
            adapter_config[generated_key] = config[generated_key]
        else:
            from benchbox.utils.database_naming import generate_database_name

            adapter_config[generated_key] = generate_database_name(
                benchmark_name=config["benchmark"],
                scale_factor=config["scale_factor"],
                platform=platform,
                tuning_config=config.get("tuning_config"),
            )

    for key in fields:
        if key in config and (include_none or config[key] is not None):
            adapter_config[key] = config[key]
    return adapter_config
