from __future__ import annotations

import contextlib
import shutil
from pathlib import Path
from typing import Any, Callable

import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq

from benchbox.utils.format_converters.base import (
    BaseFormatConverter,
    ConversionError,
    ConversionOptions,
    ConversionResult,
    SchemaError,
)


class ParquetConverter(BaseFormatConverter):
    def get_file_extension(self) -> str:
        return ".parquet"

    def get_format_name(self) -> str:
        return "Parquet"

    def _validate_partition_columns(self, partition_cols: list[str], schema: dict[str, Any]) -> None:
        available_columns = {col["name"] for col in schema["columns"]}
        for col in partition_cols:
            if col not in available_columns:
                raise ConversionError(
                    f"Partition column '{col}' not found in schema. Available columns: {sorted(available_columns)}"
                )

    def convert(
        self,
        source_files: list[Path],
        table_name: str,
        schema: dict[str, Any],
        options: ConversionOptions | None = None,
        progress_callback: Callable[[str, float], None] | None = None,
    ) -> ConversionResult:
        opts = options or ConversionOptions()

        self.validate_source_files(source_files)
        self.validate_schema(schema)

        if opts.partition_cols:
            self._validate_partition_columns(opts.partition_cols, schema)

        if progress_callback:
            progress_callback(f"Starting Parquet conversion for {table_name}", 0.0)

        try:
            self._build_arrow_schema(schema)
        except SchemaError:
            raise
        except Exception as e:
            raise SchemaError(f"Failed to build Arrow schema: {e}") from e

        combined_table = self.read_tbl_files(
            source_files, schema, progress_callback, progress_start=0.0, progress_end=0.8
        )

        column_names = [col["name"] for col in schema["columns"]]

        source_dir = source_files[0].parent
        output_dir = opts.output_dir if opts.output_dir else source_dir

        compression_map = {
            "snappy": "SNAPPY",
            "gzip": "GZIP",
            "zstd": "ZSTD",
            "none": None,
            None: None,
        }
        compression = compression_map.get(opts.compression, "SNAPPY")

        if opts.partition_cols:
            return self._write_partitioned(
                combined_table=combined_table,
                table_name=table_name,
                output_dir=output_dir,
                source_files=source_files,
                column_names=column_names,
                opts=opts,
                compression=compression,
                progress_callback=progress_callback,
            )
        else:
            return self._write_single_file(
                combined_table=combined_table,
                table_name=table_name,
                output_dir=output_dir,
                source_files=source_files,
                column_names=column_names,
                opts=opts,
                compression=compression,
                progress_callback=progress_callback,
            )

    def _write_single_file(
        self,
        combined_table: pa.Table,
        table_name: str,
        output_dir: Path,
        source_files: list[Path],
        column_names: list[str],
        opts: ConversionOptions,
        compression: str | None,
        progress_callback: Callable[[str, float], None] | None,
    ) -> ConversionResult:
        output_path = output_dir / f"{table_name}.parquet"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            if progress_callback:
                progress_callback("Writing Parquet file", 0.9)

            write_kwargs: dict[str, Any] = {
                "compression": compression,
                "use_dictionary": True,
                "write_statistics": True,
                "row_group_size": opts.row_group_size,
            }
            if opts.data_page_version is not None:
                write_kwargs["data_page_version"] = opts.data_page_version
            pq.write_table(combined_table, output_path, **write_kwargs)

        except Exception as e:
            if output_path.exists():
                with contextlib.suppress(Exception):
                    output_path.unlink()
            raise ConversionError(f"Failed to write Parquet file: {e}") from e

        source_size = self.calculate_file_size(source_files)
        output_size = output_path.stat().st_size
        row_count = combined_table.num_rows

        if opts.validate_row_count:
            try:
                self.validate_row_count(source_files, row_count, table_name)
            except ConversionError:
                if output_path.exists():
                    with contextlib.suppress(Exception):
                        output_path.unlink()
                raise

        metadata = {
            "row_groups": pq.read_metadata(output_path).num_row_groups,
            "compression": opts.compression,
            "num_columns": len(column_names),
            "partitioned": False,
        }

        if progress_callback:
            progress_callback(f"Conversion complete: {row_count:,} rows", 1.0)

        source_format = self._detect_source_format(source_files)

        return ConversionResult(
            output_files=[output_path],
            row_count=row_count,
            source_size_bytes=source_size,
            output_size_bytes=output_size,
            metadata=metadata,
            source_format=source_format,
            converted_at=self.get_current_timestamp(),
            conversion_options={
                "compression": opts.compression,
                "row_group_size": opts.row_group_size,
                "merge_shards": opts.merge_shards,
                "partition_cols": opts.partition_cols,
                "validate_row_count": opts.validate_row_count,
            },
        )

    def _write_partitioned(
        self,
        combined_table: pa.Table,
        table_name: str,
        output_dir: Path,
        source_files: list[Path],
        column_names: list[str],
        opts: ConversionOptions,
        compression: str | None,
        progress_callback: Callable[[str, float], None] | None,
    ) -> ConversionResult:
        partitioned_dir = output_dir / table_name
        partitioned_dir.mkdir(parents=True, exist_ok=True)

        try:
            if progress_callback:
                progress_callback(
                    f"Writing partitioned Parquet (by {', '.join(opts.partition_cols)})",
                    0.9,
                )

            partition_fields = [combined_table.schema.field(col) for col in opts.partition_cols]
            partitioning = ds.partitioning(pa.schema(partition_fields), flavor="hive")

            ds.write_dataset(
                combined_table,
                partitioned_dir,
                format="parquet",
                partitioning=partitioning,
                basename_template="part-{i}.parquet",
                existing_data_behavior="overwrite_or_ignore",
                file_options=ds.ParquetFileFormat().make_write_options(
                    compression=compression,
                    write_statistics=True,
                    **({"data_page_version": opts.data_page_version} if opts.data_page_version else {}),
                ),
            )

        except Exception as e:
            if partitioned_dir.exists():
                shutil.rmtree(partitioned_dir, ignore_errors=True)
            raise ConversionError(f"Failed to write partitioned Parquet: {e}") from e

        output_files = sorted(partitioned_dir.rglob("*.parquet"))

        source_size = self.calculate_file_size(source_files)
        output_size = sum(f.stat().st_size for f in output_files)
        row_count = combined_table.num_rows

        if opts.validate_row_count:
            try:
                self.validate_row_count(source_files, row_count, table_name)
            except ConversionError:
                if partitioned_dir.exists():
                    shutil.rmtree(partitioned_dir, ignore_errors=True)
                raise

        partition_counts = {}
        for col in opts.partition_cols:
            partition_counts[col] = len(combined_table.column(col).unique())

        metadata = {
            "compression": opts.compression,
            "num_columns": len(column_names),
            "partitioned": True,
            "partition_cols": opts.partition_cols,
            "partition_counts": partition_counts,
            "num_files": len(output_files),
            "table_path": str(partitioned_dir),
        }

        if progress_callback:
            progress_callback(
                f"Conversion complete: {row_count:,} rows across {len(output_files)} files",
                1.0,
            )

        source_format = self._detect_source_format(source_files)

        return ConversionResult(
            output_files=[partitioned_dir],
            row_count=row_count,
            source_size_bytes=source_size,
            output_size_bytes=output_size,
            metadata=metadata,
            source_format=source_format,
            converted_at=self.get_current_timestamp(),
            conversion_options={
                "compression": opts.compression,
                "row_group_size": opts.row_group_size,
                "merge_shards": opts.merge_shards,
                "partition_cols": opts.partition_cols,
                "validate_row_count": opts.validate_row_count,
            },
        )
