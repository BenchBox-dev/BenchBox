"""Utilities for loading expected results from answer set files.

This module provides functions to parse TPC-H and TPC-DS answer set files
and extract expected row counts for query validation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_tpch_answer_file(answer_file_path: Path) -> int:
    """Parse a TPC-H answer file and extract the row count.

    TPC-H answer files have the format:
    ```
    column_name1|column_name2|...|column_name_n
    value1|value2|...|value_n
    value1|value2|...|value_n
    ...
    ```

    The first line is the header with column names separated by |.
    Subsequent lines are data rows.

    Args:
        answer_file_path: Path to the TPC-H answer file (e.g., q1.out)

    Returns:
        Number of data rows in the answer file

    Raises:
        FileNotFoundError: If the answer file doesn't exist
        ValueError: If the answer file format is invalid
    """
    if not answer_file_path.exists():
        raise FileNotFoundError(f"TPC-H answer file not found: {answer_file_path}")

    try:
        with open(answer_file_path, encoding="utf-8") as f:
            lines = f.readlines()

        # Filter out empty lines
        non_empty_lines = [line.strip() for line in lines if line.strip()]

        if len(non_empty_lines) < 1:
            raise ValueError(f"TPC-H answer file is empty: {answer_file_path}")

        # First line is header, remaining lines are data
        # Count data rows (excluding header)
        row_count = len(non_empty_lines) - 1

        logger.debug(f"Parsed TPC-H answer file {answer_file_path.name}: {row_count} rows")
        return row_count

    except Exception as e:
        logger.error(f"Failed to parse TPC-H answer file {answer_file_path}: {e}")
        raise


def parse_tpcds_answer_file(answer_file_path: Path) -> int:
    """Parse a TPC-DS answer file and extract the row count.

    TPC-DS answer files have the format:
    ```
    COLUMN_NAME
    ----------------
    value1
    value2
    ...
    ```

    The first line is the column name.
    The second line is a separator line (dashes).
    Subsequent lines are data rows.

    Args:
        answer_file_path: Path to the TPC-DS answer file (e.g., 1.ans)

    Returns:
        Number of data rows in the answer file

    Raises:
        FileNotFoundError: If the answer file doesn't exist
        ValueError: If the answer file format is invalid
    """
    if not answer_file_path.exists():
        raise FileNotFoundError(f"TPC-DS answer file not found: {answer_file_path}")

    # Try UTF-8 first, fall back to latin-1 if UTF-8 fails
    # Some TPC-DS answer files (e.g., 30.ans) contain non-UTF-8 characters
    encodings_to_try = ["utf-8", "latin-1"]

    for encoding in encodings_to_try:
        try:
            with open(answer_file_path, encoding=encoding) as f:
                lines = f.readlines()

            # Filter out empty lines
            non_empty_lines = [line.strip() for line in lines if line.strip()]

            if len(non_empty_lines) < 2:
                raise ValueError(f"TPC-DS answer file has insufficient lines: {answer_file_path}")

            # First line is column name, second line is separator, rest are data
            # Count data rows (excluding header and separator)
            row_count = len(non_empty_lines) - 2

            if encoding != "utf-8":
                logger.debug(f"Used {encoding} encoding for {answer_file_path.name}")

            logger.debug(f"Parsed TPC-DS answer file {answer_file_path.name}: {row_count} rows")
            return row_count

        except UnicodeDecodeError:
            if encoding == encodings_to_try[-1]:
                # Last encoding failed, re-raise
                logger.error(f"Failed to decode TPC-DS answer file {answer_file_path} with any encoding")
                raise
            # Try next encoding
            continue
        except Exception as e:
            logger.error(f"Failed to parse TPC-DS answer file {answer_file_path}: {e}")
            raise

    # This should be unreachable - all encodings either return or raise
    raise RuntimeError(f"Unexpected: no encoding worked for {answer_file_path}")


def _find_tpch_answers_dir() -> Path:
    """Locate the TPC-H answer files directory.

    Checks in order:
    1. _sources/ directory (development / sdist installs)
    2. Local cache (~/.cache/benchbox/answers/tpch/)
    3. Trigger on-demand download if cache miss and download not disabled

    Returns:
        Path to directory containing q1.out .. q22.out

    Raises:
        FileNotFoundError: If answer files are not available and cannot be downloaded
    """
    from benchbox.core.expected_results.download import (
        download_tpch_answers,
        get_tpch_cache_dir,
        is_download_disabled,
    )

    # 1. Check _sources/ (development / sdist)
    try:
        import benchbox

        package_root = Path(benchbox.__file__).parent.parent
        src_dir = package_root / "_sources" / "tpc-h" / "dbgen" / "answers"
        if src_dir.exists():
            return src_dir
    except (AttributeError, TypeError):
        pass

    # 2. Check local cache
    cache_dir = get_tpch_cache_dir()
    if cache_dir.exists() and any(cache_dir.glob("q*.out")):
        return cache_dir

    # 3. Attempt on-demand download
    if not is_download_disabled():
        logger.info("TPC-H answer files not found locally; attempting on-demand download...")
        result = download_tpch_answers()
        if result is not None and result.exists():
            return result

    raise FileNotFoundError(
        "TPC-H answer files not found. "
        "They are included in source distributions but not in wheel installs. "
        "To download them: benchbox download-answers --benchmark tpch"
    )


def load_tpch_expected_results(scale_factor: float = 1.0) -> dict[str, int]:
    """Load expected row counts for all TPC-H queries at a given scale factor.

    Args:
        scale_factor: Scale factor (currently only SF=1 is supported from answer files)

    Returns:
        Dictionary mapping query IDs (as strings) to expected row counts

    Raises:
        ValueError: If scale_factor != 1.0 (answer files are only for SF=1)
        FileNotFoundError: If answer files directory not found and download unavailable
    """
    if scale_factor != 1.0:
        raise ValueError(
            f"TPC-H expected results are only available for scale factor 1.0. "
            f"Requested: {scale_factor}. "
            f"To use other scale factors, disable validation with validate_results=False."
        )

    answers_dir = _find_tpch_answers_dir()

    # Parse all answer files (q1.out through q22.out)
    expected_results = {}
    for query_num in range(1, 23):
        answer_file = answers_dir / f"q{query_num}.out"
        if answer_file.exists():
            try:
                row_count = parse_tpch_answer_file(answer_file)
                expected_results[str(query_num)] = row_count
            except Exception as e:
                logger.warning(f"Failed to parse TPC-H answer file for query {query_num}: {e}")
        else:
            logger.warning(f"TPC-H answer file not found for query {query_num}: {answer_file}")

    logger.info(f"Loaded expected results for {len(expected_results)} TPC-H queries at SF={scale_factor}")
    return expected_results


def _find_tpcds_answers_dir() -> Path:
    """Locate the TPC-DS answer files directory.

    Checks in order:
    1. _sources/ directory (development / sdist installs)
    2. Local cache (~/.cache/benchbox/answers/tpcds/)
    3. Trigger on-demand download if cache miss and download not disabled

    Returns:
        Path to directory containing 1.ans .. 99.ans

    Raises:
        FileNotFoundError: If answer files are not available and cannot be downloaded
    """
    from benchbox.core.expected_results.download import (
        download_tpcds_answers,
        get_tpcds_cache_dir,
        is_download_disabled,
    )

    # 1. Check _sources/ (development / sdist)
    try:
        import benchbox

        package_root = Path(benchbox.__file__).parent.parent
        src_dir = package_root / "_sources" / "tpc-ds" / "answer_sets"
        if src_dir.exists():
            return src_dir
    except (AttributeError, TypeError):
        pass

    # 2. Check local cache
    cache_dir = get_tpcds_cache_dir()
    if cache_dir.exists() and any(cache_dir.glob("*.ans")):
        return cache_dir

    # 3. Attempt on-demand download
    if not is_download_disabled():
        logger.info("TPC-DS answer files not found locally; attempting on-demand download...")
        result = download_tpcds_answers()
        if result is not None and result.exists():
            return result

    raise FileNotFoundError(
        "TPC-DS answer files not found. "
        "They are included in source distributions but not in wheel installs. "
        "To download them: benchbox download-answers --benchmark tpcds"
    )


def load_tpcds_expected_results(scale_factor: float = 1.0) -> dict[str, int]:
    """Load expected row counts for all TPC-DS queries at a given scale factor.

    Args:
        scale_factor: Scale factor (currently only SF=1 is supported from answer files)

    Returns:
        Dictionary mapping query IDs (as strings) to expected row counts

    Raises:
        ValueError: If scale_factor != 1.0 (answer files are only for SF=1)
        FileNotFoundError: If answer files directory not found and download unavailable
    """
    if scale_factor != 1.0:
        raise ValueError(
            f"TPC-DS expected results are only available for scale factor 1.0. "
            f"Requested: {scale_factor}. "
            f"To use other scale factors, disable validation with validate_results=False."
        )

    answers_dir = _find_tpcds_answers_dir()

    # Parse all answer files (1.ans through 99.ans)
    # Note: Some queries have variants (e.g., 1_NULLS_FIRST.ans, 1_NULLS_LAST.ans)
    # For simplicity, we'll use the base query number and prefer files without suffixes
    expected_results = {}

    for query_num in range(1, 100):
        # Try the base answer file first (e.g., 1.ans)
        answer_file = answers_dir / f"{query_num}.ans"

        if answer_file.exists():
            try:
                row_count = parse_tpcds_answer_file(answer_file)
                expected_results[str(query_num)] = row_count
            except Exception as e:
                logger.warning(f"Failed to parse TPC-DS answer file for query {query_num}: {e}")
        else:
            # If base file doesn't exist, try NULLS_FIRST variant as fallback
            answer_file_variant = answers_dir / f"{query_num}_NULLS_FIRST.ans"
            if answer_file_variant.exists():
                try:
                    row_count = parse_tpcds_answer_file(answer_file_variant)
                    expected_results[str(query_num)] = row_count
                    logger.debug(f"Using NULLS_FIRST variant for TPC-DS query {query_num}")
                except Exception as e:
                    logger.warning(f"Failed to parse TPC-DS answer file variant for query {query_num}: {e}")

    # Register multi-part query variants as aliases (they share the base query's answer file)
    # TPC-DS spec: queries 14 and 23 have multi-part templates (a/b variants)
    # These variants use the same answer file as the base query but represent different
    # query template parts (e.g., 14a and 14b are both derived from query 14's template)
    MULTI_PART_QUERIES = {
        "14": ["14a", "14b"],  # Query 14 has a/b variants
        "23": ["23a", "23b"],  # Query 23 has a/b variants
        # Note: 24a/b and 39a/b are NOT official TPC-DS spec variants
        # They are dsqgen template-level variants, not separate queries
    }

    for base_query, variants in MULTI_PART_QUERIES.items():
        if base_query in expected_results:
            base_count = expected_results[base_query]
            for variant in variants:
                expected_results[variant] = base_count  # Alias variant to base count
                logger.debug(
                    f"Registered TPC-DS variant {variant} with base query {base_query} expected row count: {base_count}"
                )

    logger.info(f"Loaded expected results for {len(expected_results)} TPC-DS queries at SF={scale_factor}")
    return expected_results
