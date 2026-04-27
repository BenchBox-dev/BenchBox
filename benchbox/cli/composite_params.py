"""Composite parameter parsers for BenchBox CLI.

This module provides parsers for composite CLI parameters that combine multiple
related options into single, concise parameters using colon syntax.

Examples:
    --compression zstd:9
    --plan-config sample:0.1,first:5,queries:1,6,17
    --table-format parquet:snappy,partition:year,month
    --validation full

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from dataclasses import dataclass, field
from typing import Any, Optional

import click


@dataclass
class CompressionConfig:
    """Parsed compression configuration."""

    type: str = "zstd"
    level: Optional[int] = None
    enabled: bool = True

    @classmethod
    def parse(cls, value: Optional[str]) -> "CompressionConfig":
        """Parse compression string.

        Formats:
            - "none" -> disabled
            - "zstd" -> zstd with default level
            - "zstd:9" -> zstd with level 9
            - "gzip:6" -> gzip with level 6

        Args:
            value: Compression specification string

        Returns:
            CompressionConfig instance

        Raises:
            click.BadParameter: If format is invalid
        """
        if not value or value.lower() == "none":
            return cls(type="none", level=None, enabled=False)

        parts = value.split(":")
        comp_type = parts[0].lower()

        if comp_type not in ("zstd", "gzip", "none"):
            raise click.BadParameter(f"Invalid compression type '{comp_type}'. Valid types: zstd, gzip, none")

        level = None
        if len(parts) > 1:
            try:
                level = int(parts[1])
                # Validate level ranges
                if comp_type == "zstd" and not (1 <= level <= 22):
                    raise click.BadParameter(f"zstd level must be 1-22, got {level}")
                if comp_type == "gzip" and not (1 <= level <= 9):
                    raise click.BadParameter(f"gzip level must be 1-9, got {level}")
            except ValueError:
                raise click.BadParameter(f"Invalid compression level '{parts[1]}', expected integer") from None

        return cls(type=comp_type, level=level, enabled=(comp_type != "none"))


def _split_plan_config_parts(value: str) -> list[str]:
    """Split comma-separated key:value pairs, handling queries: which contains commas."""
    parts: list[str] = []
    current: list[str] = []
    in_queries = False
    for part in value.split(","):
        if "queries:" in part:
            in_queries = True
            current.append(part)
        elif in_queries and ":" not in part:
            current.append(part)
        else:
            if current:
                parts.append(",".join(current))
                current = []
                in_queries = False
            parts.append(part)
    if current:
        parts.append(",".join(current))
    return parts


@dataclass
class PlanCaptureConfig:
    """Parsed plan capture configuration."""

    sample_rate: Optional[float] = None
    first_n: Optional[int] = None
    queries: Optional[list[str]] = None
    strict: bool = False

    @classmethod
    def parse(cls, value: Optional[str]) -> "PlanCaptureConfig":
        """Parse plan-config string.

        Format: key:value pairs separated by commas
            - sample:0.1 -> capture 10% of executions
            - first:5 -> capture first 5 iterations only
            - queries:1,6,17 -> capture specific queries
            - strict:true -> fail if capture fails

        Examples:
            "sample:0.1,first:5"
            "queries:1,6,17,strict:true"

        Args:
            value: Plan config specification string

        Returns:
            PlanCaptureConfig instance

        Raises:
            click.BadParameter: If format is invalid
        """
        if not value:
            return cls()

        config = cls()

        for part in _split_plan_config_parts(value):
            if not part.strip():
                continue

            if ":" not in part:
                raise click.BadParameter(f"Invalid plan-config format '{part}'. Expected key:value")

            key, val = part.split(":", 1)
            key = key.strip().lower()
            val = val.strip()

            if key == "sample":
                try:
                    config.sample_rate = float(val)
                    if not (0.0 <= config.sample_rate <= 1.0):
                        raise click.BadParameter(f"sample rate must be 0.0-1.0, got {val}")
                except ValueError:
                    raise click.BadParameter(f"Invalid sample rate '{val}', expected float") from None

            elif key == "first":
                try:
                    config.first_n = int(val)
                    if config.first_n < 1:
                        raise click.BadParameter(f"first must be positive, got {val}")
                except ValueError:
                    raise click.BadParameter(f"Invalid first value '{val}', expected integer") from None

            elif key == "queries":
                # Split query IDs
                config.queries = [q.strip() for q in val.split(",") if q.strip()]

            elif key == "strict":
                config.strict = val.lower() in ("true", "1", "yes")

            else:
                raise click.BadParameter(f"Unknown plan-config key '{key}'. Valid keys: sample, first, queries, strict")

        return config


@dataclass
class TableFormatConfig:
    """Parsed table format configuration."""

    format: str = "parquet"
    compression: str = "snappy"
    partition_cols: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, value: Optional[str]) -> Optional["TableFormatConfig"]:
        """Parse table format string.

        Formats:
            - "parquet" -> parquet with default compression
            - "delta:snappy" -> delta with snappy compression
            - "iceberg:zstd,partition:year,month" -> iceberg with zstd, partitioned

        Args:
            value: Table format specification string

        Returns:
            TableFormatConfig instance or None if no table format specified

        Raises:
            click.BadParameter: If format is invalid
        """
        if not value:
            return None

        config = cls()

        # First part is always format (optionally with compression)
        parts = value.split(",")
        format_part = parts[0]

        if ":" in format_part:
            fmt, comp = format_part.split(":", 1)
            config.format = fmt.lower()
            config.compression = comp.lower()
        else:
            config.format = format_part.lower()

        # Validate format
        valid_formats = ("parquet", "vortex", "delta", "iceberg")
        if config.format not in valid_formats:
            raise click.BadParameter(f"Invalid format '{config.format}'. Valid formats: {', '.join(valid_formats)}")

        # Validate compression
        valid_compressions = ("snappy", "gzip", "zstd", "none")
        if config.compression not in valid_compressions:
            raise click.BadParameter(
                f"Invalid compression '{config.compression}'. Valid compressions: {', '.join(valid_compressions)}"
            )

        # Parse remaining parts for partition columns
        for part in parts[1:]:
            if not part.strip():
                continue

            if part.startswith("partition:"):
                cols = part.split(":", 1)[1]
                config.partition_cols = [c.strip() for c in cols.split(",") if c.strip()]
            else:
                # Treat as partition column directly
                config.partition_cols.append(part.strip())

        return config


@dataclass
class ValidationConfig:
    """Parsed validation configuration."""

    mode: str = "exact"
    preflight: bool = False
    postgen: bool = False
    postload: bool = False
    check_platforms: bool = False

    @classmethod
    def parse(cls, value: Optional[str]) -> "ValidationConfig":
        """Parse validation string.

        Formats:
            - "exact" -> exact row count validation
            - "loose" -> loose validation (±50% tolerance)
            - "range" -> min/max bounds validation
            - "disabled" -> no validation
            - "full" -> all validation checks enabled

        Args:
            value: Validation specification string

        Returns:
            ValidationConfig instance

        Raises:
            click.BadParameter: If format is invalid
        """
        if not value:
            return cls(mode="exact")

        value = value.lower().strip()

        if value == "full":
            return cls(
                mode="exact",
                preflight=True,
                postgen=True,
                postload=True,
                check_platforms=True,
            )

        # Individual validation type flags (for targeted testing)
        if value == "postgen":
            return cls(mode="exact", postgen=True)
        if value == "preflight":
            return cls(mode="exact", preflight=True)
        if value == "postload":
            return cls(mode="exact", postload=True)
        if value == "check-platforms":
            return cls(mode="exact", check_platforms=True)

        valid_modes = ("exact", "loose", "range", "disabled")
        if value not in valid_modes:
            raise click.BadParameter(
                f"Invalid validation mode '{value}'. "
                f"Valid modes: {', '.join(valid_modes)}, full, postgen, preflight, postload, check-platforms"
            )

        return cls(mode=value)


@dataclass
class ForceConfig:
    """Parsed force regeneration configuration."""

    datagen: bool = False
    upload: bool = False

    @property
    def any(self) -> bool:
        """Return True if any force option is enabled."""
        return self.datagen or self.upload

    @classmethod
    def parse(cls, value: Optional[str]) -> "ForceConfig":
        """Parse force string.

        Formats:
            - "all" or "true" -> force both datagen and upload
            - "datagen" -> force data regeneration only
            - "upload" -> force re-upload only
            - "datagen,upload" -> both explicitly

        Args:
            value: Force specification string

        Returns:
            ForceConfig instance

        Raises:
            click.BadParameter: If format is invalid
        """
        if not value:
            return cls()

        value = value.lower().strip()

        if value in ("all", "true", "1", "yes"):
            return cls(datagen=True, upload=True)

        config = cls()
        parts = [p.strip() for p in value.split(",")]

        for part in parts:
            if part == "datagen":
                config.datagen = True
            elif part == "upload":
                config.upload = True
            else:
                raise click.BadParameter(f"Invalid force option '{part}'. Valid options: datagen, upload, all")

        return config


class ForceParamType(click.ParamType):
    """Click parameter type for force configuration.

    Supports both flag usage (--force) and value usage (--force datagen).
    """

    name = "force"

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> ForceConfig:
        if isinstance(value, ForceConfig):
            return value
        if value is None:
            return ForceConfig()
        # Handle boolean True from flag usage
        if value is True:
            return ForceConfig(datagen=True, upload=True)
        try:
            return ForceConfig.parse(str(value))
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


class CompressionParamType(click.ParamType):
    """Click parameter type for compression configuration."""

    name = "compression"

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> CompressionConfig:
        if isinstance(value, CompressionConfig):
            return value
        if value is None:
            return CompressionConfig()
        try:
            return CompressionConfig.parse(str(value))
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


class PlanConfigParamType(click.ParamType):
    """Click parameter type for plan capture configuration."""

    name = "plan-config"

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> PlanCaptureConfig:
        if isinstance(value, PlanCaptureConfig):
            return value
        if value is None:
            return PlanCaptureConfig()
        try:
            return PlanCaptureConfig.parse(str(value))
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


class TableFormatParamType(click.ParamType):
    """Click parameter type for table format configuration."""

    name = "table-format"

    def convert(
        self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]
    ) -> Optional[TableFormatConfig]:
        if isinstance(value, TableFormatConfig):
            return value
        if value is None:
            return None
        try:
            return TableFormatConfig.parse(str(value))
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


class ValidationParamType(click.ParamType):
    """Click parameter type for validation configuration."""

    name = "validation"

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> ValidationConfig:
        if isinstance(value, ValidationConfig):
            return value
        if value is None:
            return ValidationConfig()
        try:
            return ValidationConfig.parse(str(value))
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


# Singleton instances for use in Click decorators
COMPRESSION = CompressionParamType()
PLAN_CONFIG = PlanConfigParamType()
TABLE_FORMAT = TableFormatParamType()
VALIDATION = ValidationParamType()
FORCE = ForceParamType()
