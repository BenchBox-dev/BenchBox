# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def parse_tpch_answer_file(answer_file_path: Path) -> int:
    if not answer_file_path.exists():
        raise FileNotFoundError(f"TPC-H answer file not found: {answer_file_path}")

    try:
        with open(answer_file_path, encoding="utf-8") as f:
            lines = f.readlines()

        non_empty_lines = [line.strip() for line in lines if line.strip()]

        if len(non_empty_lines) < 1:
            raise ValueError(f"TPC-H answer file is empty: {answer_file_path}")

        row_count = len(non_empty_lines) - 1

        logger.debug(f"Parsed TPC-H answer file {answer_file_path.name}: {row_count} rows")
        return row_count

    except Exception as e:
        logger.error(f"Failed to parse TPC-H answer file {answer_file_path}: {e}")
        raise


def parse_tpcds_answer_file(answer_file_path: Path) -> int:
    if not answer_file_path.exists():
        raise FileNotFoundError(f"TPC-DS answer file not found: {answer_file_path}")

    encodings_to_try = ["utf-8", "latin-1"]

    for encoding in encodings_to_try:
        try:
            with open(answer_file_path, encoding=encoding) as f:
                lines = f.readlines()

            non_empty_lines = [line.strip() for line in lines if line.strip()]

            if len(non_empty_lines) < 2:
                raise ValueError(f"TPC-DS answer file has insufficient lines: {answer_file_path}")

            row_count = len(non_empty_lines) - 2

            if encoding != "utf-8":
                logger.debug(f"Used {encoding} encoding for {answer_file_path.name}")

            logger.debug(f"Parsed TPC-DS answer file {answer_file_path.name}: {row_count} rows")
            return row_count

        except UnicodeDecodeError:
            if encoding == encodings_to_try[-1]:
                logger.error(f"Failed to decode TPC-DS answer file {answer_file_path} with any encoding")
                raise
            continue
        except Exception as e:
            logger.error(f"Failed to parse TPC-DS answer file {answer_file_path}: {e}")
            raise

    raise RuntimeError(f"Unexpected: no encoding worked for {answer_file_path}")


def _find_tpch_answers_dir() -> Path:
    from benchbox.core.expected_results.download import (
        download_tpch_answers,
        get_tpch_cache_dir,
        is_download_disabled,
    )

    try:
        import benchbox

        package_root = Path(benchbox.__file__).parent.parent
        src_dir = package_root / "_sources" / "tpc-h" / "dbgen" / "answers"
        if src_dir.exists():
            return src_dir
    except (AttributeError, TypeError):
        pass

    cache_dir = get_tpch_cache_dir()
    if cache_dir.exists() and any(cache_dir.glob("q*.out")):
        return cache_dir

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
    if scale_factor != 1.0:
        raise ValueError(
            f"TPC-H expected results are only available for scale factor 1.0. "
            f"Requested: {scale_factor}. "
            f"To use other scale factors, disable validation with validate_results=False."
        )

    answers_dir = _find_tpch_answers_dir()

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


def load_tpch_value_digests(scale_factor: float = 1.0) -> dict[str, str]:
    if scale_factor != 1.0:
        return {}

    digest_file = Path(__file__).with_name("reference_digests") / "tpch_value_digests_sf1.json"
    if not digest_file.exists():
        logger.warning("TPC-H value-digest reference file not found: %s", digest_file)
        return {}

    import json

    try:
        payload = json.loads(digest_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read TPC-H value-digest reference file %s: %s", digest_file, exc)
        return {}

    digests = payload.get("digests", {})
    return {str(query_id): str(digest) for query_id, digest in digests.items()}


def _find_tpcds_answers_dir() -> Path:
    from benchbox.core.expected_results.download import (
        download_tpcds_answers,
        get_tpcds_cache_dir,
        is_download_disabled,
    )

    try:
        import benchbox

        package_root = Path(benchbox.__file__).parent.parent
        src_dir = package_root / "_sources" / "tpc-ds" / "answer_sets"
        if src_dir.exists():
            return src_dir
    except (AttributeError, TypeError):
        pass

    cache_dir = get_tpcds_cache_dir()
    if cache_dir.exists() and any(cache_dir.glob("*.ans")):
        return cache_dir

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
    if scale_factor != 1.0:
        raise ValueError(
            f"TPC-DS expected results are only available for scale factor 1.0. "
            f"Requested: {scale_factor}. "
            f"To use other scale factors, disable validation with validate_results=False."
        )

    answers_dir = _find_tpcds_answers_dir()

    expected_results = {}

    for query_num in range(1, 100):
        answer_file = answers_dir / f"{query_num}.ans"

        if answer_file.exists():
            try:
                row_count = parse_tpcds_answer_file(answer_file)
                expected_results[str(query_num)] = row_count
            except Exception as e:
                logger.warning(f"Failed to parse TPC-DS answer file for query {query_num}: {e}")
        else:
            answer_file_variant = answers_dir / f"{query_num}_NULLS_FIRST.ans"
            if answer_file_variant.exists():
                try:
                    row_count = parse_tpcds_answer_file(answer_file_variant)
                    expected_results[str(query_num)] = row_count
                    logger.debug(f"Using NULLS_FIRST variant for TPC-DS query {query_num}")
                except Exception as e:
                    logger.warning(f"Failed to parse TPC-DS answer file variant for query {query_num}: {e}")

    MULTI_PART_QUERIES = {
        "14": ["14a", "14b"],
        "23": ["23a", "23b"],
    }

    for base_query, variants in MULTI_PART_QUERIES.items():
        if base_query in expected_results:
            base_count = expected_results[base_query]
            for variant in variants:
                expected_results[variant] = base_count
                logger.debug(
                    f"Registered TPC-DS variant {variant} with base query {base_query} expected row count: {base_count}"
                )

    logger.info(f"Loaded expected results for {len(expected_results)} TPC-DS queries at SF={scale_factor}")
    return expected_results
