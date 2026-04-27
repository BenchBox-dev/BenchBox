"""Data compression utilities for BenchBox.

This module provides compression support for data generation and storage,
including streaming compression and decompression capabilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import gzip
import shutil
from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO, Optional, TextIO, Union, cast

from benchbox.utils.file_format import detect_compression as _detect_compression_from_path

try:
    import zstandard as zstd

    ZSTD_AVAILABLE = True
except ImportError:
    ZSTD_AVAILABLE = False


class CompressionError(Exception):
    """Exception raised for compression-related errors."""


class BaseCompressor(ABC):
    """Base class for all compressors."""

    def __init__(self, level: Optional[int] = None):
        """Initialize compressor with optional compression level.

        Args:
            level: Compression level (algorithm-specific range)
        """
        self.level = level

    @abstractmethod
    def get_file_extension(self) -> str:
        """Get the file extension for this compression format."""

    @abstractmethod
    def compress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Compress a file.

        Args:
            input_path: Path to input file
            output_path: Optional output path. If None, appends compression extension.

        Returns:
            Path to compressed file
        """

    @abstractmethod
    def decompress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Decompress a file.

        Args:
            input_path: Path to compressed file
            output_path: Optional output path. If None, removes compression extension.

        Returns:
            Path to decompressed file
        """

    @abstractmethod
    def open_for_write(self, path: Path, mode: str = "wt") -> Union[TextIO, BinaryIO]:
        """Open a file for compressed writing.

        Args:
            path: Path to output file
            mode: File mode ('wt' for text, 'wb' for binary)

        Returns:
            File-like object for writing compressed data
        """

    @abstractmethod
    def open_for_read(self, path: Path, mode: str = "rt") -> Union[TextIO, BinaryIO]:
        """Open a compressed file for reading.

        Args:
            path: Path to compressed file
            mode: File mode ('rt' for text, 'rb' for binary)

        Returns:
            File-like object for reading decompressed data
        """


class GzipCompressor(BaseCompressor):
    """Gzip compression implementation."""

    def __init__(self, level: Optional[int] = None):
        """Initialize Gzip compressor.

        Args:
            level: Compression level (1-9, default 6)
        """
        if level is None:
            level = 6
        if level < 1 or level > 9:
            raise ValueError(f"Gzip compression level must be 1-9, got {level}")
        super().__init__(level)

    def get_file_extension(self) -> str:
        return ".gz"

    def compress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Compress a file with gzip."""
        if output_path is None:
            output_path = input_path.with_suffix(input_path.suffix + self.get_file_extension())

        try:
            with open(input_path, "rb") as f_in:
                with gzip.open(output_path, "wb", compresslevel=self.level) as f_out:
                    shutil.copyfileobj(f_in, f_out)
            return output_path
        except Exception as e:
            raise CompressionError(f"Failed to compress {input_path}: {e}") from e

    def decompress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Decompress a gzip file."""
        if output_path is None:
            if input_path.suffix == self.get_file_extension():
                output_path = input_path.with_suffix("")
            else:
                output_path = input_path.with_suffix(".decompressed")

        try:
            with gzip.open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            return output_path
        except Exception as e:
            raise CompressionError(f"Failed to decompress {input_path}: {e}") from e

    def open_for_write(self, path: Path, mode: str = "wt") -> Union[TextIO, BinaryIO]:
        """Open a file for gzip-compressed writing."""
        try:
            result: Union[TextIO, BinaryIO] = cast(
                Union[TextIO, BinaryIO], gzip.open(path, mode, compresslevel=self.level)
            )
            return result
        except Exception as e:
            raise CompressionError(f"Failed to open {path} for compressed writing: {e}") from e

    def open_for_read(self, path: Path, mode: str = "rt") -> Union[TextIO, BinaryIO]:
        """Open a gzip file for reading."""
        try:
            result: Union[TextIO, BinaryIO] = cast(Union[TextIO, BinaryIO], gzip.open(path, mode))
            return result
        except Exception as e:
            raise CompressionError(f"Failed to open {path} for compressed reading: {e}") from e


class ZstdCompressor(BaseCompressor):
    """Zstandard compression implementation."""

    def __init__(self, level: Optional[int] = None):
        """Initialize Zstd compressor.

        Args:
            level: Compression level (1-22, default 3)
        """
        if not ZSTD_AVAILABLE:
            raise CompressionError("zstandard library not available. Install with: pip install zstandard")

        if level is None:
            level = 3
        if level < 1 or level > 22:
            raise ValueError(f"Zstd compression level must be 1-22, got {level}")
        super().__init__(level)

    def get_file_extension(self) -> str:
        return ".zst"

    def compress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Compress a file with zstandard."""
        if output_path is None:
            output_path = input_path.with_suffix(input_path.suffix + self.get_file_extension())

        try:
            cctx = zstd.ZstdCompressor(level=self.level)
            with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
                cctx.copy_stream(f_in, f_out)
            return output_path
        except Exception as e:
            raise CompressionError(f"Failed to compress {input_path}: {e}") from e

    def decompress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Decompress a zstd file."""
        if output_path is None:
            if input_path.suffix == self.get_file_extension():
                output_path = input_path.with_suffix("")
            else:
                output_path = input_path.with_suffix(".decompressed")

        try:
            dctx = zstd.ZstdDecompressor()
            with open(input_path, "rb") as f_in, open(output_path, "wb") as f_out:
                dctx.copy_stream(f_in, f_out)
            return output_path
        except Exception as e:
            raise CompressionError(f"Failed to decompress {input_path}: {e}") from e

    def open_for_write(self, path: Path, mode: str = "wt") -> Union[TextIO, BinaryIO]:
        """Open a file for zstd-compressed writing."""
        try:
            cctx = zstd.ZstdCompressor(level=self.level)
            if "t" in mode:
                # For text mode, use io.TextIOWrapper
                import io

                binary_writer = cctx.stream_writer(open(path, "wb"), closefd=True)
                return io.TextIOWrapper(binary_writer, encoding="utf-8")
            else:
                return cctx.stream_writer(open(path, "wb"), closefd=True)
        except Exception as e:
            raise CompressionError(f"Failed to open {path} for compressed writing: {e}") from e

    def open_for_read(self, path: Path, mode: str = "rt") -> Union[TextIO, BinaryIO]:
        """Open a zstd file for reading."""
        try:
            dctx = zstd.ZstdDecompressor()
            if "t" in mode:
                # For text mode, use io.TextIOWrapper
                import io

                binary_reader = dctx.stream_reader(open(path, "rb"), closefd=True)
                return io.TextIOWrapper(binary_reader, encoding="utf-8")
            else:
                return dctx.stream_reader(open(path, "rb"), closefd=True)
        except Exception as e:
            raise CompressionError(f"Failed to open {path} for compressed reading: {e}") from e


class NoCompressor(BaseCompressor):
    """No compression (pass-through) implementation."""

    def __init__(self, level: Optional[int] = None):
        """Initialize no compressor (level is ignored)."""
        super().__init__(None)

    def get_file_extension(self) -> str:
        return ""

    def compress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Copy file without compression."""
        if output_path is None:
            return input_path

        try:
            shutil.copy2(input_path, output_path)
            return output_path
        except Exception as e:
            raise CompressionError(f"Failed to copy {input_path}: {e}") from e

    def decompress_file(self, input_path: Path, output_path: Optional[Path] = None) -> Path:
        """Copy file without decompression."""
        if output_path is None:
            return input_path

        try:
            shutil.copy2(input_path, output_path)
            return output_path
        except Exception as e:
            raise CompressionError(f"Failed to copy {input_path}: {e}") from e

    def open_for_write(self, path: Path, mode: str = "wt") -> Union[TextIO, BinaryIO]:
        """Open a file for uncompressed writing."""
        try:
            return cast(Union[TextIO, BinaryIO], open(path, mode))
        except Exception as e:
            raise CompressionError(f"Failed to open {path} for writing: {e}") from e

    def open_for_read(self, path: Path, mode: str = "rt") -> Union[TextIO, BinaryIO]:
        """Open a file for uncompressed reading."""
        try:
            return cast(Union[TextIO, BinaryIO], open(path, mode))
        except Exception as e:
            raise CompressionError(f"Failed to open {path} for reading: {e}") from e


class CompressionManager:
    """Manager for compression operations."""

    def __init__(self):
        """Initialize compression manager."""
        self._compressors: dict[str, BaseCompressor] = {}
        self._register_default_compressors()

    def _register_default_compressors(self):
        """Register default compressors."""
        self._compressors["none"] = NoCompressor()
        self._compressors["gzip"] = GzipCompressor()
        if ZSTD_AVAILABLE:
            self._compressors["zstd"] = ZstdCompressor()

    def get_compressor(self, compression_type: str, level: Optional[int] = None) -> BaseCompressor:
        """Get a compressor by type.

        Args:
            compression_type: Type of compression ('none', 'gzip', 'zstd')
            level: Optional compression level

        Returns:
            Compressor instance

        Raises:
            CompressionError: If compression type is not supported
        """
        if compression_type not in self._compressors:
            available = list(self._compressors.keys())
            raise CompressionError(f"Unsupported compression type '{compression_type}'. Available: {available}")

        if level is not None:
            # Create new instance with specific level
            compressor_class = type(self._compressors[compression_type])
            return compressor_class(level=level)
        else:
            return self._compressors[compression_type]

    def get_available_compressors(self) -> list[str]:
        """Get list of available compression types."""
        return list(self._compressors.keys())

    def detect_compression(self, path: Path) -> Optional[str]:
        """Detect compression type from file extension.

        Uses centralized detection from benchbox.utils.file_format which
        recognizes all compression extensions (.zst, .gz, .bz2, .xz, .lz4, .snappy).

        Args:
            path: File path to analyze

        Returns:
            Detected compression type or "none" if uncompressed
        """
        compression_type = _detect_compression_from_path(path)
        return compression_type if compression_type is not None else "none"

    def get_compression_info(self, input_path: Path, output_path: Path) -> dict[str, Union[int, float]]:
        """Get compression information comparing two files.

        Args:
            input_path: Original file path
            output_path: Compressed file path

        Returns:
            Dictionary with compression statistics
        """
        try:
            input_size = input_path.stat().st_size
            output_size = output_path.stat().st_size

            compression_ratio = input_size / output_size if output_size > 0 else float("inf")
            space_savings = ((input_size - output_size) / input_size * 100) if input_size > 0 else 0.0

            return {
                "original_size": input_size,
                "compressed_size": output_size,
                "compression_ratio": compression_ratio,
                "space_savings_percent": space_savings,
            }
        except Exception as e:
            raise CompressionError(f"Failed to get compression info: {e}") from e
