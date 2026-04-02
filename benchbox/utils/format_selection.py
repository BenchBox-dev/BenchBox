"""Format selection logic for choosing the best format for a platform.

This module implements the logic for selecting which format to use when loading
data, based on platform capabilities, user preferences, and available formats.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchbox.platforms.base.format_capabilities import get_preferred_format, is_format_supported


class FormatSelector:
    """Handles format selection logic for data loading."""

    @staticmethod
    def select_format(
        platform_name: str,
        available_formats: list[str],
        user_preference: str | None = None,
    ) -> str:
        """Select the best format for loading data.

        Args:
            platform_name: Name of the platform (e.g., 'duckdb', 'databricks')
            available_formats: List of formats available for this table
            user_preference: Optional user-specified format preference (CLI override)

        Returns:
            Selected format name

        Raises:
            ValueError: If user preference is not available or supported
        """
        if not available_formats:
            # No formats available, fallback to tbl
            return "tbl"

        # If user specified a preference, validate and use it
        if user_preference:
            if user_preference not in available_formats:
                raise ValueError(f"Preferred format '{user_preference}' not available. Available: {available_formats}")

            if not is_format_supported(platform_name, user_preference):
                raise ValueError(
                    f"Format '{user_preference}' not supported on platform '{platform_name}'. "
                    f"Consider using a different format or platform."
                )

            return user_preference

        # Otherwise, use platform's preferred format from available options
        return get_preferred_format(platform_name, available_formats)

    @staticmethod
    def get_fallback_chain(platform_name: str, available_formats: list[str]) -> list[str]:
        """Get fallback chain of formats to try in order.

        Args:
            platform_name: Name of the platform
            available_formats: List of available formats

        Returns:
            List of formats to try, in order of preference
        """
        # Get all supported formats in preference order
        from benchbox.platforms.base.format_capabilities import PLATFORM_FORMAT_PREFERENCES

        preference_order = PLATFORM_FORMAT_PREFERENCES.get(platform_name, [])

        # Filter to only available and supported formats
        fallback_chain = []
        for fmt in preference_order:
            if fmt in available_formats and is_format_supported(platform_name, fmt):
                fallback_chain.append(fmt)

        # Add any remaining available formats not in preference order
        for fmt in available_formats:
            if fmt not in fallback_chain:
                fallback_chain.append(fmt)

        return fallback_chain

    @staticmethod
    def detect_available_formats(
        data_dir: Path, table_name: str, manifest_data: dict[str, Any] | None = None
    ) -> list[str]:
        """Detect which formats are available for a table.

        Args:
            data_dir: Data directory path
            table_name: Name of the table
            manifest_data: Optional manifest data (if available)

        Returns:
            List of available format names
        """
        manifest_formats = FormatSelector._manifest_formats(table_name, manifest_data)
        if manifest_formats:
            return manifest_formats

        available = FormatSelector._filesystem_formats(data_dir, table_name)
        return available if available else ["tbl"]

    @staticmethod
    def _manifest_formats(table_name: str, manifest_data: dict[str, Any] | None) -> list[str]:
        """Collect available formats from manifest metadata, if present."""
        available: list[str] = []
        if not manifest_data:
            return available

        if "formats" in manifest_data and isinstance(manifest_data["formats"], list):
            available.extend(manifest_data["formats"])

        table_data = manifest_data.get("tables", {}).get(table_name, {}) if "tables" in manifest_data else {}
        if isinstance(table_data, dict):
            formats_section = table_data.get("formats")
            if isinstance(formats_section, dict):
                available.extend(list(formats_section.keys()))

        return list(dict.fromkeys(available))

    @staticmethod
    def _filesystem_formats(data_dir: Path, table_name: str) -> list[str]:
        """Detect available formats directly from files and table-format directories."""
        available: list[str] = []
        patterns = {
            "tbl": [f"{table_name}.tbl*", f"{table_name}.dat*"],
            "csv": [f"{table_name}.csv*"],
            "parquet": [f"{table_name}.parquet*"],
        }

        for format_name, pattern_list in patterns.items():
            if any(next(data_dir.glob(pattern), None) is not None for pattern in pattern_list):
                available.append(format_name)

        delta_dir = data_dir / table_name / "_delta_log"
        if delta_dir.exists() and delta_dir.is_dir():
            available.append("delta")

        iceberg_dir = data_dir / table_name / "metadata"
        if iceberg_dir.exists() and iceberg_dir.is_dir() and list(iceberg_dir.glob("*.metadata.json")):
            available.append("iceberg")

        return available
