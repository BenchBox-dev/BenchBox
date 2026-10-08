from __future__ import annotations

from collections.abc import Callable, Iterable
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

POSTGRES_CONNECTION_PLATFORM_FIELDS = (
    "host",
    "port",
    "username",
    "password",
    "database",
    "admin_database",
    "sslmode",
)
POSTGRES_TUNING_PLATFORM_FIELDS = (
    "work_mem",
    "maintenance_work_mem",
    "effective_cache_size",
    "max_parallel_workers_per_gather",
)
POSTGRES_FAMILY_PLATFORM_FIELDS = POSTGRES_CONNECTION_PLATFORM_FIELDS + POSTGRES_TUNING_PLATFORM_FIELDS


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
    field_defaults: dict[str, Any] | None = None,
    consume_explicit_options: bool = False,
) -> Any:
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.security.credentials import CredentialManager

    cred_manager = CredentialManager()
    saved_creds = cred_manager.get_platform_credentials(credential_key) or {}

    explicit_options = (
        overrides.pop("_explicit_platform_options", {})
        if consume_explicit_options
        else overrides.get("_explicit_platform_options", {})
    )

    merged_options: dict[str, Any] = dict(base_options or {})
    merged_options.update(options)
    merged_options.update(saved_creds)
    merged_options.update(explicit_options)
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

    defaults = field_defaults or {}
    for field in platform_fields:
        config_dict[field] = merged_options.get(field, defaults.get(field))

    config_dict["benchmark"] = overrides.get("benchmark")
    config_dict["scale_factor"] = overrides.get("scale_factor")
    config_dict["tuning_config"] = overrides.get("tuning_config")

    if "database" in overrides and overrides["database"]:
        config_dict["database"] = overrides["database"]

    return DatabaseConfig(**config_dict)


PlatformConfigPostprocess = Callable[[Any], None]
PlatformConfigBuilder = Callable[[str, dict[str, Any], dict[str, Any], Any], Any]


def make_platform_config_builder(
    platform_type: str,
    module_name: str,
    default_display_name: str,
    default_driver_package: str,
    platform_fields: Iterable[str],
    *,
    function_name: str | None = None,
    credential_key: str | None = None,
    base_options: dict[str, Any] | None = None,
    field_defaults: dict[str, Any] | None = None,
    consume_explicit_options: bool = False,
    postprocess: PlatformConfigPostprocess | None = None,
) -> PlatformConfigBuilder:
    fields = tuple(platform_fields)
    name = function_name or f"_build_{platform_type.replace('-', '_')}_config"
    platform_credential_key = credential_key or platform_type

    def _builder(platform: str, options: dict[str, Any], overrides: dict[str, Any], info: Any) -> Any:
        config = build_platform_config(
            platform_type=platform_type,
            credential_key=platform_credential_key,
            default_display_name=default_display_name,
            default_driver_package=default_driver_package,
            platform_fields=list(fields),
            options=options,
            overrides=overrides,
            info=info,
            base_options=dict(base_options) if base_options is not None else None,
            field_defaults=field_defaults,
            consume_explicit_options=consume_explicit_options,
        )
        if postprocess is not None:
            postprocess(config)
        return config

    _builder.__name__ = name
    _builder.__qualname__ = name
    _builder.__module__ = module_name
    return _builder


def make_registered_platform_config_builder(
    registry_platform: str,
    module_name: str,
    default_display_name: str,
    default_driver_package: str,
    platform_fields: Iterable[str],
    **kwargs: Any,
) -> PlatformConfigBuilder:
    builder = make_platform_config_builder(
        registry_platform,
        module_name,
        default_display_name,
        default_driver_package,
        platform_fields,
        **kwargs,
    )
    try:
        from benchbox.core.hooks.platform_hooks import PlatformHookRegistry

        PlatformHookRegistry.register_config_builder(registry_platform, builder)
    except ImportError:
        pass
    return builder


TUNING_FORWARD_KEYS: tuple[str, ...] = (
    "tuning_config",
    "tuning_enabled",
    "unified_tuning_configuration",
    "tuning_source",
    "tuning_source_file",
)


PLAN_FORWARD_KEYS: tuple[str, ...] = (
    "show_query_plans",
    "capture_plans",
    "analyze_plans",
    "strict_plan_capture",
    "normalize_plan_literals",
    "plan_queries",
    "plan_capture_timeout_seconds",
    "plan_max_depth",
)


def build_adapter_config(
    config: dict[str, Any],
    *,
    platform: str,
    generated_key: str | None = "database",
    fields: Iterable[str] = (),
    include_none: bool = True,
) -> dict[str, Any]:
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

    for key in TUNING_FORWARD_KEYS:
        if key in config:
            adapter_config[key] = config[key]

    for key in PLAN_FORWARD_KEYS:
        if key in config and config[key] is not None:
            adapter_config[key] = config[key]

    return adapter_config
