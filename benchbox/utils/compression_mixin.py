# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from pathlib import Path
from typing import Union

from .compression import CompressionError, CompressionManager
from .file_format import strip_compression_suffix
from .printing import emit

COMPRESSION_KWARG_KEYS = frozenset(
    {
        "compress_data",
        "compression_type",
        "compression_level",
        "uncompressed_output",
    }
)


def extract_compression_kwargs(kwargs: dict) -> dict:
    return {key: value for key, value in kwargs.items() if key in COMPRESSION_KWARG_KEYS}


class CompressionMixin:
    def __init__(self, *args, **kwargs):
        uncompressed_output = kwargs.pop("uncompressed_output", False)

        if uncompressed_output:
            self.compression_type = "none"
            self.compression_level = None
            self.compress_data = False
        else:
            self.compression_type = kwargs.pop("compression_type", "none")
            self.compression_level = kwargs.pop("compression_level", None)
            self.compress_data = kwargs.pop("compress_data", False)

        self.compression_manager = CompressionManager()

        if self.compress_data and self.compression_type == "none":
            self.compression_type = "zstd"

        self._validate_compression_settings()

        if args or kwargs:
            try:
                super().__init__(*args, **kwargs)
            except TypeError:
                pass

    def _validate_compression_settings(self):
        if self.compression_type not in self.compression_manager.get_available_compressors():
            available = self.compression_manager.get_available_compressors()
            raise ValueError(f"Unsupported compression type '{self.compression_type}'. Available: {available}")

    def get_compressor(self):
        return self.compression_manager.get_compressor(
            compression_type=self.compression_type, level=self.compression_level
        )

    def get_compressed_filename(self, filename: str) -> str:
        if not self.compress_data or self.compression_type == "none":
            return filename

        compressor = self.get_compressor()
        return filename + compressor.get_file_extension()

    def open_output_file(self, path: Union[str, Path], mode: str = "wt"):
        path = Path(path)

        if not self.compress_data or self.compression_type == "none":
            kwargs: dict = {"newline": ""} if "b" not in mode else {}
            return open(path, mode, **kwargs)

        compressor = self.get_compressor()
        if not str(path).endswith(compressor.get_file_extension()):
            path = path.with_suffix(path.suffix + compressor.get_file_extension())

        return compressor.open_for_write(path, mode)

    def compress_existing_file(self, file_path: Path, remove_original: bool = False) -> Path:
        if not self.compress_data or self.compression_type == "none":
            return file_path

        compressor = self.get_compressor()
        compressed_path = compressor.compress_file(file_path)

        if remove_original and compressed_path != file_path:
            try:
                file_path.unlink()
            except OSError:
                pass

        return compressed_path

    def get_compression_report(self, files: dict[str, Path]) -> dict[str, dict]:
        if not self.compress_data or self.compression_type == "none":
            return {}

        report = {}
        total_original = 0
        total_compressed = 0

        for table_name, file_path in files.items():
            original_path = file_path
            compressor = self.get_compressor()
            extension = compressor.get_file_extension()

            if str(file_path).endswith(extension):
                original_path = strip_compression_suffix(file_path)
                if not original_path.exists():
                    continue

            try:
                info = self.compression_manager.get_compression_info(original_path, file_path)
                report[table_name] = info
                total_original += info["original_size"]
                total_compressed += info["compressed_size"]
            except CompressionError:
                continue

        if total_original > 0:
            report["total"] = {
                "original_size": total_original,
                "compressed_size": total_compressed,
                "compression_ratio": total_original / total_compressed if total_compressed > 0 else float("inf"),
                "space_savings_percent": ((total_original - total_compressed) / total_original * 100),
            }

        return report

    def print_compression_report(self, files: dict[str, Path], verbose: bool = False):
        if not self.compress_data or self.compression_type == "none":
            return

        report = self.get_compression_report(files)
        if not report:
            return

        emit(f"\nCompression Report ({self.compression_type})")
        emit("=" * 50)

        if verbose and len(report) > 1:
            for table_name, info in report.items():
                if table_name == "total":
                    continue

                original_mb = info["original_size"] / (1024 * 1024)
                compressed_mb = info["compressed_size"] / (1024 * 1024)

                emit(f"{table_name}:")
                emit(f"  Original: {original_mb:.2f} MB")
                emit(f"  Compressed: {compressed_mb:.2f} MB")
                emit(f"  Ratio: {info['compression_ratio']:.2f}:1")
                emit(f"  Savings: {info['space_savings_percent']:.1f}%")
                emit()

        if "total" in report:
            total = report["total"]
            original_mb = total["original_size"] / (1024 * 1024)
            compressed_mb = total["compressed_size"] / (1024 * 1024)

            emit(f"Total Original Size: {original_mb:.2f} MB")
            emit(f"Total Compressed Size: {compressed_mb:.2f} MB")
            emit(f"Overall Compression Ratio: {total['compression_ratio']:.2f}:1")
            emit(f"Space Savings: {total['space_savings_percent']:.1f}%")

    def should_use_compression(self) -> bool:
        return self.compress_data and self.compression_type != "none"
