# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from dataclasses import dataclass, field
from typing import Any, Optional

import click


@dataclass
class CompressionConfig:
    type: str = "zstd"
    level: Optional[int] = None
    enabled: bool = True

    @classmethod
    def parse(cls, value: Optional[str]) -> "CompressionConfig":
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
                if comp_type == "zstd" and not (1 <= level <= 22):
                    raise click.BadParameter(f"zstd level must be 1-22, got {level}")
                if comp_type == "gzip" and not (1 <= level <= 9):
                    raise click.BadParameter(f"gzip level must be 1-9, got {level}")
            except ValueError:
                raise click.BadParameter(f"Invalid compression level '{parts[1]}', expected integer") from None

        return cls(type=comp_type, level=level, enabled=(comp_type != "none"))


def _split_plan_config_parts(value: str) -> list[str]:
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
    queries: Optional[list[str]] = None
    strict: bool = False

    @classmethod
    def parse(cls, value: Optional[str]) -> "PlanCaptureConfig":
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

            if key in ("sample", "first"):
                raise click.BadParameter(
                    f"plan-config key '{key}' has been removed: plan capture now records each "
                    "distinct query exactly once in an isolated post-measurement phase, so "
                    "per-iteration sampling ('sample'/'first') no longer applies. Use "
                    "'queries:<ids>' to restrict which queries are captured."
                )

            elif key == "queries":
                config.queries = [q.strip() for q in val.split(",") if q.strip()]

            elif key == "strict":
                config.strict = val.lower() in ("true", "1", "yes")

            else:
                raise click.BadParameter(f"Unknown plan-config key '{key}'. Valid keys: queries, strict")

        return config


@dataclass
class TableFormatConfig:
    format: str = "parquet"
    compression: str = "snappy"
    partition_cols: list[str] = field(default_factory=list)

    @classmethod
    def parse(cls, value: Optional[str]) -> Optional["TableFormatConfig"]:
        if not value:
            return None

        config = cls()

        parts = value.split(",")
        format_part = parts[0]

        if ":" in format_part:
            fmt, comp = format_part.split(":", 1)
            config.format = fmt.lower()
            config.compression = comp.lower()
        else:
            config.format = format_part.lower()

        valid_formats = ("parquet", "vortex", "delta", "iceberg")
        if config.format not in valid_formats:
            raise click.BadParameter(f"Invalid format '{config.format}'. Valid formats: {', '.join(valid_formats)}")

        valid_compressions = ("snappy", "gzip", "zstd", "none")
        if config.compression not in valid_compressions:
            raise click.BadParameter(
                f"Invalid compression '{config.compression}'. Valid compressions: {', '.join(valid_compressions)}"
            )

        for part in parts[1:]:
            if not part.strip():
                continue

            if part.startswith("partition:"):
                cols = part.split(":", 1)[1]
                config.partition_cols = [c.strip() for c in cols.split(",") if c.strip()]
            else:
                config.partition_cols.append(part.strip())

        return config


@dataclass
class ValidationConfig:
    mode: str = "exact"
    preflight: bool = False
    postgen: bool = False
    postload: bool = False
    check_platforms: bool = False

    @classmethod
    def parse(cls, value: Optional[str]) -> "ValidationConfig":
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
    datagen: bool = False
    upload: bool = False

    @property
    def any(self) -> bool:
        return self.datagen or self.upload

    @classmethod
    def parse(cls, value: Optional[str]) -> "ForceConfig":
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
    name = "force"

    def convert(self, value: Any, param: Optional[click.Parameter], ctx: Optional[click.Context]) -> ForceConfig:
        if isinstance(value, ForceConfig):
            return value
        if value is None:
            return ForceConfig()
        if value is True:
            return ForceConfig(datagen=True, upload=True)
        try:
            return ForceConfig.parse(str(value))
        except click.BadParameter as e:
            self.fail(str(e), param, ctx)


class CompressionParamType(click.ParamType):
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


COMPRESSION = CompressionParamType()
PLAN_CONFIG = PlanConfigParamType()
TABLE_FORMAT = TableFormatParamType()
VALIDATION = ValidationParamType()
FORCE = ForceParamType()
