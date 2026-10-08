# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class PlatformInfoInput:
    name: str
    platform_version: str | None = None
    client_library_version: str | None = None
    execution_mode: str = "sql"
    connection_mode: str | None = None
    family: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    engine_version: str | None = None
    engine_version_source: str | None = None


@runtime_checkable
class StandardPlatformInfo(Protocol):
    def get_standard_platform_info(self) -> PlatformInfoInput: ...


def build_platform_info(
    adapter: Any,
    execution_mode: str = "sql",
) -> PlatformInfoInput:
    if isinstance(adapter, StandardPlatformInfo):
        return adapter.get_standard_platform_info()

    legacy_info: dict[str, Any] = {}
    if hasattr(adapter, "get_platform_info"):
        try:
            result = adapter.get_platform_info()
            if isinstance(result, dict):
                legacy_info = result
        except Exception:
            pass

    platform_version = _extract_version(legacy_info)
    client_version = _extract_client_version(legacy_info)
    if client_version is None:
        client_version = "unknown"
    if platform_version is None:
        platform_version = "unknown"

    return PlatformInfoInput(
        name=_extract_platform_name(adapter, legacy_info),
        platform_version=platform_version,
        client_library_version=client_version,
        execution_mode=execution_mode,
        connection_mode=_extract_connection_mode(legacy_info),
        family=_extract_family(adapter, legacy_info),
        config=_extract_config(legacy_info),
    )


def _extract_platform_name(adapter: Any, info: dict[str, Any]) -> str:
    if hasattr(adapter, "platform_name"):
        name = adapter.platform_name
        if name:
            return str(name)

    for key in ("platform_name", "platform", "name"):
        if key in info and info[key]:
            return str(info[key])

    class_name = type(adapter).__name__
    for suffix in ("Adapter", "Platform", "DataFrame", "DF"):
        if class_name.endswith(suffix):
            class_name = class_name[: -len(suffix)]
    return class_name or "Unknown"


def _extract_version(info: dict[str, Any]) -> str | None:
    for key in (
        "version",
        "platform_version",
        "embedded_library_version",
    ):
        if key in info and info[key]:
            return str(info[key])
    return None


def _extract_client_version(info: dict[str, Any]) -> str | None:
    for key in ("client_library_version", "client_version", "driver_version"):
        if key in info and info[key]:
            return str(info[key])
    return None


def _extract_connection_mode(info: dict[str, Any]) -> str | None:
    return info.get("connection_mode")


def _extract_family(adapter: Any, info: dict[str, Any]) -> str | None:
    if hasattr(adapter, "family"):
        return adapter.family

    return info.get("family")


def _extract_config(info: dict[str, Any]) -> dict[str, Any]:
    config: dict[str, Any] = {}

    exclude = {
        "platform_version",
        "version",
        "client_library_version",
        "client_version",
        "driver_version",
        "embedded_library_version",
        "name",
        "platform",
        "platform_name",
        "adapter_name",
        "platform_type",
        "connection_mode",
        "family",
    }

    def flatten_config(d: dict[str, Any], target: dict[str, Any]) -> None:
        for key, value in d.items():
            if key in exclude:
                continue
            if key == "configuration" and isinstance(value, dict):
                flatten_config(value, target)
            else:
                target[key] = value

    flatten_config(info, config)
    return config


def format_platform_display_name(
    platform_name: str,
    execution_mode: str = "sql",
) -> str:
    return platform_name


def merge_platform_info(
    base_info: PlatformInfoInput,
    additional_config: dict[str, Any] | None = None,
) -> PlatformInfoInput:
    if not additional_config:
        return base_info

    merged_config = {**base_info.config, **additional_config}

    return PlatformInfoInput(
        name=base_info.name,
        platform_version=base_info.platform_version,
        client_library_version=base_info.client_library_version,
        execution_mode=base_info.execution_mode,
        connection_mode=base_info.connection_mode,
        family=base_info.family,
        config=merged_config,
        engine_version=base_info.engine_version,
        engine_version_source=base_info.engine_version_source,
    )
