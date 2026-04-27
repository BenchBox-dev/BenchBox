"""File format and compression detection utilities for BenchBox.

This module provides centralized utilities for detecting file formats and
compression types from file paths. It eliminates duplication across the
codebase where compression extension sets were hardcoded in multiple locations.

Usage:
    from benchbox.utils.file_format import (
        detect_data_format,
        detect_compression,
        strip_compression_suffix,
        is_compression_extension,
        is_tpc_format,
        is_parquet_format,
        is_csv_format,
        get_data_extension,
        get_delimiter_for_file,
        COMPRESSION_EXTENSIONS,
        DATA_FORMAT_EXTENSIONS,
    )

    # Detect format from compressed file
    detect_data_format(Path("data.tbl.zst"))  # Returns "tbl"

    # Detect compression type
    detect_compression(Path("data.csv.gz"))  # Returns "gzip"

    # Strip compression suffix
    strip_compression_suffix(Path("data.tbl.zst"))  # Returns Path("data.tbl")

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

logger = logging.getLogger(__name__)

# Recognized compression extensions
# This is the canonical set - all modules should import from here
COMPRESSION_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".zst",  # Zstandard
        ".gz",  # Gzip
        ".bz2",  # Bzip2
        ".xz",  # XZ/LZMA
        ".lz4",  # LZ4
        ".snappy",  # Snappy
    }
)

# Recognized data format extensions
DATA_FORMAT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".parquet",  # Apache Parquet
        ".vortex",  # Vortex columnar format
        ".tbl",  # TPC pipe-delimited
        ".csv",  # Comma-separated values
        ".dat",  # TPC-DS pipe-delimited (same format as .tbl)
    }
)

# Mapping from compression extension to canonical name
_COMPRESSION_NAMES: dict[str, str] = {
    ".zst": "zstd",
    ".gz": "gzip",
    ".bz2": "bzip2",
    ".xz": "xz",
    ".lz4": "lz4",
    ".snappy": "snappy",
}

# Mapping from data format extension to format name
_FORMAT_NAMES: dict[str, str] = {
    ".parquet": "parquet",
    ".vortex": "vortex",
    ".tbl": "tbl",
    ".csv": "csv",
    ".dat": "tbl",  # .dat files use same pipe-delimited format as .tbl
}


def is_compression_extension(suffix: str) -> bool:
    """Check if a suffix is a known compression extension.

    Args:
        suffix: File suffix to check (with or without leading dot)

    Returns:
        True if the suffix is a recognized compression extension

    Examples:
        >>> is_compression_extension(".zst")
        True
        >>> is_compression_extension("gz")
        True
        >>> is_compression_extension(".parquet")
        False
    """
    # Normalize: ensure leading dot and lowercase
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return suffix.lower() in COMPRESSION_EXTENSIONS


def is_data_format_extension(suffix: str) -> bool:
    """Check if a suffix is a known data format extension.

    Args:
        suffix: File suffix to check (with or without leading dot)

    Returns:
        True if the suffix is a recognized data format extension

    Examples:
        >>> is_data_format_extension(".parquet")
        True
        >>> is_data_format_extension("tbl")
        True
        >>> is_data_format_extension(".zst")
        False
    """
    # Normalize: ensure leading dot and lowercase
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    return suffix.lower() in DATA_FORMAT_EXTENSIONS


def detect_compression(path: Union[str, Path]) -> str | None:
    """Detect compression type from file extension.

    Examines the file's suffix to determine if it's compressed and
    returns the canonical compression name.

    Args:
        path: File path to analyze

    Returns:
        Compression type name ('zstd', 'gzip', 'bzip2', 'xz', 'lz4', 'snappy')
        or None if not compressed

    Examples:
        >>> detect_compression(Path("data.tbl.zst"))
        'zstd'
        >>> detect_compression(Path("data.csv.gz"))
        'gzip'
        >>> detect_compression(Path("data.parquet"))
        None
        >>> detect_compression("archive.tar.bz2")
        'bzip2'
    """
    path = Path(path)
    suffix = path.suffix.lower()
    return _COMPRESSION_NAMES.get(suffix)


def detect_data_format(path: Union[str, Path]) -> str:
    """Detect data format from path, handling compressed files.

    Examines file suffixes to determine the underlying data format,
    correctly handling compressed files by looking past compression
    extensions.

    Args:
        path: File path to analyze

    Returns:
        Format name: 'parquet', 'tbl', 'csv', or 'csv' as fallback

    Examples:
        >>> detect_data_format(Path("data.tbl.zst"))
        'tbl'
        >>> detect_data_format(Path("data.parquet"))
        'parquet'
        >>> detect_data_format(Path("data.csv.gz"))
        'csv'
        >>> detect_data_format(Path("customer.dat"))
        'tbl'
        >>> detect_data_format(Path("unknown.txt"))
        'csv'
    """
    path = Path(path)
    suffixes = [s.lower() for s in path.suffixes]

    # Check suffixes right-to-left (innermost extension last, outermost first
    # after stripping compression). This ensures that in compound names like
    # "table.dat.parquet", the rightmost data format (.parquet) wins.
    for suffix in reversed(suffixes):
        if suffix in COMPRESSION_EXTENSIONS:
            continue
        if suffix in _FORMAT_NAMES:
            return _FORMAT_NAMES[suffix]

    # Fallback to csv for unknown formats
    # Log at debug level to help diagnose unexpected file types
    if suffixes:
        # Only log if there were non-compression suffixes we couldn't recognize
        non_compression_suffixes = [s for s in suffixes if s not in COMPRESSION_EXTENSIONS]
        if non_compression_suffixes:
            logger.debug(f"Unknown format extension(s) {non_compression_suffixes} in '{path}', defaulting to csv")
    return "csv"


def strip_compression_suffix(path: Union[str, Path]) -> Path:
    """Remove compression suffix from path.

    If the path ends with a recognized compression extension, returns
    a new path with that extension removed. Otherwise returns the
    original path unchanged.

    Args:
        path: File path that may have compression suffix

    Returns:
        Path with compression suffix removed (if present)

    Examples:
        >>> strip_compression_suffix(Path("data.tbl.zst"))
        PosixPath('data.tbl')
        >>> strip_compression_suffix(Path("data.csv.gz"))
        PosixPath('data.csv')
        >>> strip_compression_suffix(Path("data.parquet"))
        PosixPath('data.parquet')
        >>> strip_compression_suffix("archive.tar.bz2")
        PosixPath('archive.tar')
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in COMPRESSION_EXTENSIONS:
        return path.with_suffix("")

    return path


def get_data_extension(path: Union[str, Path]) -> str | None:
    """Return the underlying data-format extension, transparent to compression.

    Walks all suffixes right-to-left and returns the first one that is a
    recognized data format (.tbl, .dat, .csv, .parquet, .vortex), skipping
    compression extensions (.zst, .gz, .bz2, .xz, .lz4, .snappy) and any other
    unrecognized suffixes (shard numbers, backup suffixes, etc.).

    Use this when an adapter needs to distinguish *between* TPC formats — e.g.
    ".tbl" (TPC-H, datavault: empty trailing field is delimiter, not NULL) vs
    ".dat" (TPC-DS: empty trailing field IS NULL).  detect_data_format()
    collapses both to "tbl" and is therefore wrong for that distinction.

    Args:
        path: File path to analyze

    Returns:
        Lowercase data extension including the leading dot (e.g. ".tbl"), or
        None if no recognised data extension is present.

    Examples:
        >>> get_data_extension(Path("lineitem.tbl"))
        '.tbl'
        >>> get_data_extension(Path("store_sales.dat.zst"))
        '.dat'
        >>> get_data_extension(Path("customer.tbl.7.zst"))
        '.tbl'
        >>> get_data_extension(Path("hits.csv.gz.bz2"))
        '.csv'
        >>> get_data_extension(Path("data.parquet"))
        '.parquet'
        >>> get_data_extension(Path("data.tbl.bak"))
        '.tbl'
        >>> get_data_extension(Path("README"))
    """
    path = Path(path)
    for suffix in reversed(path.suffixes):
        suffix_lower = suffix.lower()
        if suffix_lower in COMPRESSION_EXTENSIONS:
            continue
        if suffix_lower in DATA_FORMAT_EXTENSIONS:
            return suffix_lower
        # Unknown suffix (shard numbers, backup suffixes, etc.) — skip and keep walking
    return None


def get_base_name_without_compression(path: Union[str, Path]) -> str:
    """Get the base filename without compression extension.

    Similar to strip_compression_suffix but returns just the filename
    string, not a Path object.

    Args:
        path: File path that may have compression suffix

    Returns:
        Filename without compression suffix

    Examples:
        >>> get_base_name_without_compression(Path("/data/file.tbl.zst"))
        'file.tbl'
        >>> get_base_name_without_compression("file.csv.gz")
        'file.csv'
    """
    path = Path(path)
    stripped = strip_compression_suffix(path)
    return stripped.name


def normalize_format_extension(suffix: str) -> str:
    """Normalize a format extension to its canonical form.

    Handles cases where different extensions represent the same format
    (e.g., .dat and .tbl are both pipe-delimited TPC formats).

    Args:
        suffix: File suffix (with or without leading dot)

    Returns:
        Canonical format name

    Examples:
        >>> normalize_format_extension(".dat")
        'tbl'
        >>> normalize_format_extension("parquet")
        'parquet'
        >>> normalize_format_extension(".unknown")
        'csv'
    """
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    suffix = suffix.lower()
    return _FORMAT_NAMES.get(suffix, "csv")


# TPC benchmark file extensions (pipe-delimited format)
TPC_FORMAT_EXTENSIONS: frozenset[str] = frozenset({".tbl", ".dat"})


def is_tpc_format(path: Union[str, Path]) -> bool:
    """Check if a file is in TPC benchmark format (.tbl or .dat).

    TPC-H uses .tbl files and TPC-DS uses .dat files. Both are pipe-delimited
    with a trailing delimiter on each line.

    Args:
        path: File path or string to check

    Returns:
        True if the file has a TPC format extension

    Examples:
        >>> is_tpc_format("lineitem.tbl")
        True
        >>> is_tpc_format("store_sales.dat")
        True
        >>> is_tpc_format("data.csv")
        False
        >>> is_tpc_format(Path("lineitem.tbl.zst"))
        True
    """
    path = Path(path)
    # Check suffixes in order, skipping compression extensions
    for suffix in path.suffixes:
        suffix_lower = suffix.lower()
        if suffix_lower in COMPRESSION_EXTENSIONS:
            continue
        return suffix_lower in TPC_FORMAT_EXTENSIONS
    return False


def get_delimiter_for_file(path: Union[str, Path]) -> str:
    """Get the appropriate CSV delimiter for a file based on its format.

    TPC benchmark files (.tbl, .dat) use pipe (|) delimiter.
    All other formats default to comma (,).

    Args:
        path: File path to analyze

    Returns:
        Delimiter character: "|" for TPC formats, "," otherwise

    Examples:
        >>> get_delimiter_for_file("lineitem.tbl")
        '|'
        >>> get_delimiter_for_file("store_sales.dat.zst")
        '|'
        >>> get_delimiter_for_file("data.csv")
        ','
        >>> get_delimiter_for_file("unknown.txt")
        ','
    """
    return "|" if is_tpc_format(path) else ","


# Canonical dummy column name for trailing delimiter handling.
# TPC data files use | as a field terminator (not separator), creating an
# extra empty field when split. This constant standardizes the dummy column
# name across all adapters.
TRAILING_DUMMY_COLUMN: str = "_trailing_delimiter_"


def has_trailing_delimiter(
    path: Union[str, Path],
    delimiter: str,
    column_names: list[str] | None = None,
) -> bool:
    """Check if a delimited file has an extra trailing field beyond the schema columns.

    TPC data files use field-terminating delimiters (each field ends with |),
    so a line with N values has N delimiter characters and splits into N+1
    elements (the last being empty). A dummy column is needed only when the
    split field count exceeds the expected column count.

    For example, TPC-H region (3 columns):
      ``0|AFRICA|comment|``  ->  split gives 4 elements  ->  4 > 3  ->  True

    But TPC-DS time_dim (10 columns, dsdgen emits 9 values):
      ``0|AAA...|0|0|0|0|AM|third|night|``  ->  split gives 10  ->  10 == 10  ->  False

    When column_names is None, falls back to checking whether the first
    non-empty line ends with the delimiter character.

    Args:
        path: Path to the data file (may be compressed)
        delimiter: Field delimiter character
        column_names: Expected column names (if known). When provided, uses
            smart field-count comparison. When None, uses simple ends-with check.

    Returns:
        True if the file has a trailing delimiter that requires a dummy column
    """
    from benchbox.utils.compression import CompressionError, CompressionManager

    path = Path(path)

    if column_names is not None:
        expected = len(column_names)
        checker = lambda line: len(line.rstrip("\n").split(delimiter)) > expected  # noqa: E731
    else:
        checker = lambda line: line.rstrip("\n").endswith(delimiter)  # noqa: E731

    return _check_first_nonempty_line(path, checker, CompressionError, CompressionManager)


def _check_first_nonempty_line(path: Path, checker, CompressionError, CompressionManager) -> bool:
    """Read the first non-empty line from a (possibly compressed) file and apply checker."""
    compression_type = detect_compression(path)
    try:
        if compression_type:
            manager = CompressionManager()
            compressor = manager.get_compressor(compression_type)
            with compressor.open_for_read(path, mode="rt") as handle:
                for line in handle:
                    if line.strip():
                        return checker(line)
            return False
        with path.open("rt", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.strip():
                    return checker(line)
        return False
    except Exception:
        return False


def get_column_names_with_trailing(column_names: list[str], has_trailing: bool) -> list[str]:
    """Append the canonical trailing dummy column name when needed.

    Args:
        column_names: Original column names from the schema
        has_trailing: Whether the file has a trailing delimiter

    Returns:
        column_names unchanged if has_trailing is False, or
        column_names + [TRAILING_DUMMY_COLUMN] if True
    """
    if has_trailing:
        return column_names + [TRAILING_DUMMY_COLUMN]
    return column_names


def is_parquet_format(path: Union[str, Path]) -> bool:
    """Check if a file is in Parquet format.

    Handles compressed files by looking past compression extensions.

    Args:
        path: File path or string to check

    Returns:
        True if the file has a .parquet extension

    Examples:
        >>> is_parquet_format("data.parquet")
        True
        >>> is_parquet_format(Path("data.parquet.zst"))
        True
        >>> is_parquet_format("data.csv")
        False
        >>> is_parquet_format("data.tbl")
        False
    """
    path = Path(path)
    # Check suffixes in order, skipping compression extensions
    for suffix in path.suffixes:
        suffix_lower = suffix.lower()
        if suffix_lower in COMPRESSION_EXTENSIONS:
            continue
        return suffix_lower == ".parquet"
    return False


def is_csv_format(path: Union[str, Path]) -> bool:
    """Check if a file is in CSV format.

    Handles compressed files by looking past compression extensions.

    Args:
        path: File path or string to check

    Returns:
        True if the file has a .csv extension

    Examples:
        >>> is_csv_format("data.csv")
        True
        >>> is_csv_format(Path("data.csv.gz"))
        True
        >>> is_csv_format("data.parquet")
        False
        >>> is_csv_format("data.tbl")
        False
    """
    path = Path(path)
    # Check suffixes in order, skipping compression extensions
    for suffix in path.suffixes:
        suffix_lower = suffix.lower()
        if suffix_lower in COMPRESSION_EXTENSIONS:
            continue
        return suffix_lower == ".csv"
    return False


def validate_tbl_compression_consistency(target_dir: Path, file_extension: str) -> None:
    """Validate .tbl output directory is consistent with compression enabled.

    Raises ``RuntimeError`` if raw .tbl files exist alongside compressed files
    or if compressed files are empty. Callers should only invoke this after
    confirming compression is enabled for the current generator.

    Args:
        target_dir: Directory containing generated .tbl files.
        file_extension: Compressor extension (e.g., ``.zst``, ``.gz``).

    Raises:
        RuntimeError: When the directory fails consistency checks.
    """
    raw_tbl = list(target_dir.glob("*.tbl"))
    if raw_tbl:
        names = ", ".join(f.name for f in raw_tbl[:5])
        more = "..." if len(raw_tbl) > 5 else ""
        raise RuntimeError(
            f"File format consistency violation: Found raw .tbl files with compression enabled: {names}{more}"
        )
    compressed = list(target_dir.glob(f"*.tbl{file_extension}"))
    empties = [f for f in compressed if f.stat().st_size <= (9 if file_extension == ".zst" else 20)]
    if empties:
        names = ", ".join(f.name for f in empties[:5])
        more = "..." if len(empties) > 5 else ""
        raise RuntimeError(f"File format consistency violation: Found empty compressed files: {names}{more}")
