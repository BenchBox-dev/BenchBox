from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import pyarrow as pa
import pyarrow.csv as csv

from benchbox.utils.compression import CompressionManager
from benchbox.utils.file_format import detect_compression, get_column_names_with_trailing, has_trailing_delimiter


@dataclass
class ConversionOptions:
    compression: str = "snappy"
    row_group_size: int = 128 * 1024 * 1024
    partition_cols: list[str] = field(default_factory=list)
    merge_shards: bool = True
    output_dir: Path | None = None
    preserve_source: bool = True
    validate_row_count: bool = True
    strict_schema: bool = False
    data_page_version: Literal["1.0", "2.0"] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        valid_compressions = {"snappy", "gzip", "zstd", "none", None}
        if self.compression not in valid_compressions:
            raise ValueError(f"Invalid compression: {self.compression}. Must be one of {valid_compressions}")

        if self.row_group_size <= 0:
            raise ValueError(f"row_group_size must be positive, got {self.row_group_size}")

        if self.data_page_version is not None and self.data_page_version not in ("1.0", "2.0"):
            raise ValueError(f"Invalid data_page_version: {self.data_page_version!r}. Must be '1.0' or '2.0'.")

        self.validate_row_count = bool(self.validate_row_count)


@dataclass
class ConversionResult:
    output_files: list[Path]
    row_count: int
    source_size_bytes: int
    output_size_bytes: int
    metadata: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    source_format: str = "tbl"
    converted_at: str | None = None
    conversion_options: dict[str, Any] = field(default_factory=dict)

    @property
    def compression_ratio(self) -> float:
        if self.output_size_bytes == 0:
            return 0.0
        return self.source_size_bytes / self.output_size_bytes

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


class ConversionError(Exception):
    pass


class SchemaError(ConversionError):
    pass


class ArrowTypeMapper:
    @staticmethod
    def map_sql_type_to_arrow(sql_type: str, *, strict: bool = False) -> pa.DataType:
        sql_type_upper = sql_type.upper().strip()

        if sql_type_upper in ("INTEGER", "INT"):
            return pa.int64()

        if sql_type_upper == "BIGINT":
            return pa.int64()

        if sql_type_upper.startswith("DECIMAL"):
            if "(" in sql_type_upper:
                try:
                    params = sql_type_upper[sql_type_upper.index("(") + 1 : sql_type_upper.index(")")].split(",")
                    precision = int(params[0].strip())
                    scale = int(params[1].strip()) if len(params) > 1 else 0
                    return pa.decimal128(precision, scale)
                except (ValueError, IndexError) as e:
                    raise SchemaError(f"Invalid DECIMAL type specification: {sql_type}") from e
            else:
                return pa.decimal128(15, 2)

        if sql_type_upper == "DATE":
            return pa.date32()

        if sql_type_upper == "TIMESTAMP":
            return pa.timestamp("us")

        if sql_type_upper.startswith(("VARCHAR", "CHAR")):
            return pa.string()

        if sql_type_upper in ("FLOAT", "REAL"):
            return pa.float32()
        if sql_type_upper == "DOUBLE":
            return pa.float64()

        if sql_type_upper in ("BOOLEAN", "BOOL"):
            return pa.bool_()

        if sql_type_upper == "TEXT":
            return pa.string()

        if strict:
            raise SchemaError(f"Unknown SQL type '{sql_type}' cannot be mapped to Arrow type in strict mode")
        return pa.string()

    @staticmethod
    def build_arrow_schema(schema: dict[str, Any], *, strict: bool = False) -> pa.Schema:
        if not schema or "columns" not in schema:
            raise SchemaError("Schema missing 'columns' field")

        fields = []
        columns = schema["columns"]

        for col in columns:
            col_name = col["name"]
            sql_type = col["type"]
            nullable = col.get("nullable", True)

            try:
                arrow_type = ArrowTypeMapper.map_sql_type_to_arrow(sql_type, strict=strict)
                field = pa.field(col_name, arrow_type, nullable=nullable)
                fields.append(field)
            except Exception as e:
                raise SchemaError(f"Failed to map column '{col_name}' with type '{sql_type}': {e}") from e

        return pa.schema(fields)


class FormatConverter(ABC):
    @abstractmethod
    def convert(
        self,
        source_files: list[Path],
        table_name: str,
        schema: dict[str, Any],
        options: ConversionOptions | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> ConversionResult: ...

    @abstractmethod
    def validate_schema(self, schema: dict[str, Any]) -> bool: ...

    def get_output_path(
        self,
        table_name: str,
        source_dir: Path,
        options: ConversionOptions | None = None,
    ) -> Path:
        opts = options or ConversionOptions()
        output_dir = opts.output_dir or source_dir

        extension = self.get_file_extension()

        return output_dir / f"{table_name}{extension}"

    @abstractmethod
    def get_file_extension(self) -> str: ...

    @abstractmethod
    def get_format_name(self) -> str: ...


class BaseFormatConverter(FormatConverter):
    def validate_source_files(self, source_files: list[Path]) -> None:
        if not source_files:
            raise ConversionError("No source files provided")

        for file_path in source_files:
            if not file_path.exists():
                raise ConversionError(f"Source file not found: {file_path}")
            if not file_path.is_file():
                raise ConversionError(f"Source path is not a file: {file_path}")

    def validate_schema(self, schema: dict[str, Any] | None) -> bool:
        if not schema:
            raise SchemaError("Schema is empty or None")

        if "columns" not in schema:
            raise SchemaError("Schema missing 'columns' field")

        columns = schema["columns"]
        if not columns or not isinstance(columns, list):
            raise SchemaError("Schema 'columns' must be a non-empty list")

        for i, col in enumerate(columns):
            if not isinstance(col, dict):
                raise SchemaError(f"Column {i} is not a dictionary")

            if "name" not in col:
                raise SchemaError(f"Column {i} missing 'name' field")

            if "type" not in col:
                raise SchemaError(f"Column {i} ({col.get('name', 'unknown')}) missing 'type' field")

        return True

    def _map_sql_type_to_arrow(self, sql_type: str, *, strict: bool = False) -> pa.DataType:
        return ArrowTypeMapper.map_sql_type_to_arrow(sql_type, strict=strict)

    def _build_arrow_schema(self, schema: dict[str, Any], *, strict: bool = False) -> pa.Schema:
        return ArrowTypeMapper.build_arrow_schema(schema, strict=strict)

    def read_tbl_files(
        self,
        source_files: list[Path],
        schema: dict[str, Any],
        progress_callback: Callable[[str, float], None] | None = None,
        progress_start: float = 0.0,
        progress_end: float = 0.8,
    ) -> pa.Table:
        arrow_schema = self._build_arrow_schema(schema)
        column_names = [col["name"] for col in schema["columns"]]

        tables = []
        total_files = len(source_files)
        progress_range = progress_end - progress_start
        compression_manager = CompressionManager()

        try:
            for i, file_path in enumerate(source_files):
                if progress_callback:
                    progress = progress_start + (i / total_files) * progress_range
                    progress_callback(f"Reading {file_path.name}", progress)

                has_trailing = has_trailing_delimiter(file_path, "|", column_names)
                column_names_for_file = get_column_names_with_trailing(column_names, has_trailing)

                read_options = csv.ReadOptions(
                    column_names=column_names_for_file,
                    autogenerate_column_names=False,
                )

                parse_options = csv.ParseOptions(
                    delimiter="|",
                    quote_char='"',
                    escape_char="\\",
                )

                convert_options = csv.ConvertOptions(
                    column_types=arrow_schema,
                    null_values=[""],
                    strings_can_be_null=True,
                    include_columns=column_names,
                )

                compression_type = detect_compression(file_path)
                if compression_type:
                    compressor = compression_manager.get_compressor(compression_type)
                    with compressor.open_for_read(file_path, mode="rb") as stream:
                        table = csv.read_csv(
                            stream,
                            read_options=read_options,
                            parse_options=parse_options,
                            convert_options=convert_options,
                        )
                else:
                    table = csv.read_csv(
                        file_path,
                        read_options=read_options,
                        parse_options=parse_options,
                        convert_options=convert_options,
                    )

                tables.append(table)

        except Exception as e:
            raise ConversionError(f"Failed to read TBL files: {e}") from e

        try:
            if len(tables) > 1:
                if progress_callback:
                    progress_callback("Merging sharded files", progress_end)
                return pa.concat_tables(tables)
            else:
                return tables[0]
        except Exception as e:
            raise ConversionError(f"Failed to concatenate tables: {e}") from e

    def calculate_file_size(self, file_paths: list[Path]) -> int:
        return sum(f.stat().st_size for f in file_paths if f.exists())

    def count_rows(self, file_paths: list[Path], delimiter: str = "|") -> int:
        total_rows = 0
        compression_manager = CompressionManager()
        for file_path in file_paths:
            compression_type = detect_compression(file_path)
            if compression_type:
                compressor = compression_manager.get_compressor(compression_type)
                with compressor.open_for_read(file_path, mode="rt") as f:
                    for line in f:
                        if line.strip():
                            total_rows += 1
            else:
                with open(file_path, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        if line.strip():
                            total_rows += 1
        return total_rows

    def validate_row_count(
        self,
        source_files: list[Path],
        output_row_count: int,
        table_name: str,
    ) -> None:
        input_row_count = self.count_rows(source_files)

        if input_row_count != output_row_count:
            raise ConversionError(
                f"Row count mismatch for table '{table_name}': "
                f"input={input_row_count:,} rows, output={output_row_count:,} rows. "
                f"Data loss detected during conversion! "
                f"This violates TPC compliance and indicates a serious conversion error."
            )

    def _detect_source_format(self, source_files: list[Path]) -> str:
        if not source_files:
            return "tbl"

        first_file = source_files[0]
        suffixes = first_file.suffixes
        name_lower = first_file.name.lower()

        if ".parquet" in suffixes:
            return "parquet"
        elif ".tbl" in suffixes or name_lower.endswith(".tbl") or ".dat" in suffixes or name_lower.endswith(".dat"):
            return "tbl"
        elif ".csv" in suffixes or name_lower.endswith(".csv"):
            return "csv"
        else:
            return "tbl"

    @staticmethod
    def get_current_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat()
