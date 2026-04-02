"""Format preference resolution for multi-format manifests."""

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
    """Get preferred format for a table on a platform.

    Resolution order:
    1. Manifest format_preference (user-selected load order)
    2. Platform default preferences
    3. First available format

    Set ``prefer_platform_defaults=True`` for platform-native loaders that must
    override manifest order with platform-specific requirements.

    Args:
        manifest: ManifestV2 instance
        table_name: Name of the table
        platform_name: Name of the platform (e.g., 'duckdb', 'datafusion')

    Returns:
        Preferred format name if available, None if no formats found
    """
    table_formats = manifest.tables.get(table_name)
    if not table_formats:
        return None

    available_formats = list(table_formats.formats.keys())
    if not available_formats:
        return None

    # Get platform supported formats (in preference order)
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

    # Fallback: first available format
    return available_formats[0]


def get_files_for_format(
    manifest: ManifestV2,
    table_name: str,
    format_name: str,
) -> list[str]:
    """Get file paths for a specific format.

    Args:
        manifest: ManifestV2 instance
        table_name: Name of the table
        format_name: Format to retrieve (e.g., 'parquet', 'delta')

    Returns:
        List of file paths for the specified format, empty list if not found
    """
    table_formats = manifest.tables.get(table_name)
    if not table_formats:
        return []

    files = table_formats.formats.get(format_name, [])
    return [f.path for f in files]


def list_available_formats(manifest: ManifestV2, table_name: str) -> list[str]:
    """List all available formats for a table.

    Args:
        manifest: ManifestV2 instance
        table_name: Name of the table

    Returns:
        List of format names available for the table
    """
    table_formats = manifest.tables.get(table_name)
    if not table_formats:
        return []

    return list(table_formats.formats.keys())
