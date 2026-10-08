from __future__ import annotations

from typing import Any, Mapping

from benchbox.core.manifest.models import ManifestV2
from benchbox.platforms.base.format_capabilities import get_supported_formats


def get_preferred_format(
    manifest: ManifestV2,
    table_name: str,
    platform_name: str,
    table_mode: str = "native",
    platform_config: Mapping[str, Any] | None = None,
    *,
    prefer_platform_defaults: bool = False,
) -> str | None:
    table_formats = manifest.tables.get(table_name)
    if not table_formats:
        return None

    available_formats = list(table_formats.formats.keys())
    if not available_formats:
        return None

    platform_formats = get_supported_formats(platform_name, table_mode=table_mode, platform_config=platform_config)

    def _manifest_preference() -> str | None:
        for fmt in manifest.format_preference:
            if fmt in available_formats and fmt in platform_formats:
                return fmt
        return None

    def _platform_preference() -> str | None:
        for fmt in platform_formats:
            if fmt in available_formats:
                return fmt
        return None

    selection_order = (
        (_platform_preference, _manifest_preference)
        if prefer_platform_defaults
        else (_manifest_preference, _platform_preference)
    )
    for selector in selection_order:
        selected = selector()
        if selected:
            return selected

    return available_formats[0]


def get_files_for_format(
    manifest: ManifestV2,
    table_name: str,
    format_name: str,
) -> list[str]:
    table_formats = manifest.tables.get(table_name)
    if not table_formats:
        return []

    files = table_formats.formats.get(format_name, [])
    return [f.path for f in files]


def list_available_formats(manifest: ManifestV2, table_name: str) -> list[str]:
    table_formats = manifest.tables.get(table_name)
    if not table_formats:
        return []

    return list(table_formats.formats.keys())
