"""TPC-DS parameter extraction from dsqgen binary output.

Extracts substitution parameter values from dsqgen-generated SQL so that DataFrame
query implementations can use identical parameters to their SQL counterparts for
a given seed, scale factor, and stream combination.

The extraction approach is generic: rather than writing per-query extractors for all
99 TPC-DS queries, we compare dsqgen output for the requested seed against the
default seed, and produce an override dict that maps query_id -> param_dict
matching the structure of TPCDS_DEFAULT_PARAMS.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Common parameter patterns found across TPC-DS queries.
# Each pattern maps a regex against SQL text to extract a (key, value) pair.
# These are applied generically to any query - the TPCDS_DEFAULT_PARAMS dict
# determines which keys are relevant for each query_id.

_YEAR_PATTERN = re.compile(r"d_year\s*=\s*(\d{4})", re.IGNORECASE)
_MONTH_PATTERN = re.compile(r"d_moy\s*=\s*(\d+)", re.IGNORECASE)
_MONTHS_PATTERN = re.compile(r"d_moy\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_DAY_PATTERN = re.compile(r"d_dom\s*=\s*(\d+)", re.IGNORECASE)
_QUARTER_PATTERN = re.compile(r"d_qoy\s*=\s*(\d+)", re.IGNORECASE)
_QUARTERS_PATTERN = re.compile(r"d_qoy\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_DAYS_PATTERN = re.compile(r"\b(?:days|day)\s*[<=>]+\s*(\d+)", re.IGNORECASE)
_STATE_PATTERN = re.compile(r"(?:s_state|ca_state)\s*=\s*'([A-Z]{2})'", re.IGNORECASE)
_STATES_PATTERN = re.compile(r"(?:s_state|ca_state)\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_CITY_PATTERN = re.compile(r"ca_city\s*=\s*'([^']+)'", re.IGNORECASE)
_CITIES_PATTERN = re.compile(r"ca_city\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_COUNTY_PATTERN = re.compile(r"s_county\s*=\s*'([^']+)'", re.IGNORECASE)
_CATEGORY_PATTERN = re.compile(r"i_category\s*=\s*'([^']+)'", re.IGNORECASE)
_CATEGORIES_PATTERN = re.compile(r"i_category\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_COLOR_PATTERN = re.compile(r"i_color\s*=\s*'([^']+)'", re.IGNORECASE)
_COLORS_PATTERN = re.compile(r"i_color\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_HOUR_RANGE_PATTERN = re.compile(r"t_hour\s+between\s+(\d+)\s+and\s+(\d+)", re.IGNORECASE)
_GENDER_PATTERN = re.compile(r"cd_gender\s*=\s*'([MF])'", re.IGNORECASE)
_MARITAL_PATTERN = re.compile(r"cd_marital_status\s*=\s*'([^']+)'", re.IGNORECASE)
_EDUCATION_PATTERN = re.compile(r"cd_education_status\s*=\s*'([^']+)'", re.IGNORECASE)
_MANUFACT_PATTERN = re.compile(r"i_manufact_id\s*=\s*(\d+)", re.IGNORECASE)
_MANUFACTURER_PATTERN = re.compile(r"i_manufact_id\s*=\s*(\d+)", re.IGNORECASE)
_MANUFACTURERS_PATTERN = re.compile(r"i_manufact_id\s+in\s*\(([^)]*)\)", re.IGNORECASE)
_MANAGER_PATTERN = re.compile(r"i_manager_id\s*=\s*(\d+)", re.IGNORECASE)
_MARKET_PATTERN = re.compile(r"s_market_id\s*=\s*(\d+)", re.IGNORECASE)
_STORE_PATTERN = re.compile(r"s_store_sk\s*=\s*(\d+)", re.IGNORECASE)
_WAREHOUSE_PATTERN = re.compile(r"w_warehouse_sk\s*=\s*(\d+)", re.IGNORECASE)
_CLASS_ID_PATTERN = re.compile(r"i_class_id\s*=\s*(\d+)", re.IGNORECASE)
_CATEGORY_ID_PATTERN = re.compile(r"i_category_id\s*=\s*(\d+)", re.IGNORECASE)
_MONTH_SEQ_PATTERN = re.compile(r"d_month_seq\s*=\s*(\d+)", re.IGNORECASE)
_GMT_OFFSET_PATTERN = re.compile(r"s_gmt_offset\s*=\s*(-?\d+(?:\.\d+)?)", re.IGNORECASE)
_INCOME_BAND_PATTERN = re.compile(r"ib_lower_bound\s*[>=]+\s*(\d+)", re.IGNORECASE)

# Keys intentionally unsupported by generic extraction. These rely on richer
# dsqgen logic or contextual expressions that are out-of-scope for this layer.
_INTENTIONALLY_UNSUPPORTED_KEYS = {
    "agg_field",
    "agg_column",
    "channel_promo",
    "promo_channel",
    "channel",
    "channel_type",
    "ship_carriers",
    "web_names",
    "buy_potential",
    "null_col",
    "dates",
    "zip_codes",
    "zip_prefix",
    "reason",
}


def _parse_str_list(raw: str) -> list[str]:
    return re.findall(r"'([^']+)'", raw)


def _parse_int_list(raw: str) -> list[int]:
    return [int(m) for m in re.findall(r"-?\d+", raw)]


_SUPPORTED_PARAMETER_KEYS = {
    "year",
    "month",
    "months",
    "day",
    "days",
    "quarter",
    "quarters",
    "state",
    "states",
    "city",
    "cities",
    "county",
    "category",
    "categories",
    "item_categories",
    "color",
    "colors",
    "hours",
    "gender",
    "cd_gender",
    "marital_status",
    "cd_marital_status",
    "education",
    "cd_education_status",
    "manufact_id",
    "manufacturer_id",
    "manufact_ids",
    "manufacturer_ids",
    "manager_id",
    "market_id",
    "store_sk",
    "warehouse_id",
    "class_id",
    "category_id",
    "d_month_seq",
    "gmt_offset",
    "income_band",
}


def extract_tpcds_parameters(
    seed: int,
    scale_factor: float = 1.0,
    stream_id: Optional[int] = None,
    query_ids: list[int] | None = None,
) -> dict[int, dict[str, Any]]:
    """Extract TPC-DS substitution parameters from dsqgen output.

    Runs the dsqgen binary with the given seed/SF/stream and parses the
    generated SQL to extract parameter values. Only extracts parameters
    for keys that exist in TPCDS_DEFAULT_PARAMS.

    Args:
        seed: Random number generator seed.
        scale_factor: Scale factor for parameter calculations.
        stream_id: Stream identifier for multi-stream execution.
        query_ids: Specific queries to extract (default: all 1-99).

    Returns:
        Dict mapping query_id to parameter dict. Only includes queries
        where extraction succeeded and produced non-empty results.

    Raises:
        RuntimeError: If dsqgen binary is not available.
    """
    from benchbox.core.tpcds.c_tools import DSQGenBinary
    from benchbox.core.tpcds.dataframe_queries.parameters import TPCDS_DEFAULT_PARAMS

    dsqgen = DSQGenBinary()
    params: dict[int, dict[str, Any]] = {}

    if query_ids is None:
        query_ids = list(range(1, 100))

    for query_id in query_ids:
        # Skip queries with no default params
        if query_id not in TPCDS_DEFAULT_PARAMS:
            continue

        default_keys = set(TPCDS_DEFAULT_PARAMS[query_id].keys())
        if not default_keys:
            continue

        try:
            sql = dsqgen.generate(query_id, seed=seed, scale_factor=scale_factor, stream_id=stream_id)
            extracted = _extract_common_params(sql, default_keys)
            if extracted:
                params[query_id] = extracted
        except Exception:
            logger.warning("Failed to extract parameters for TPC-DS Q%d with seed=%d", query_id, seed)

    return params


def _parse_int_g1(m: re.Match) -> int:
    """Parse group(1) as int."""
    return int(m.group(1))


def _parse_float_g1(m: re.Match) -> float:
    """Parse group(1) as float."""
    return float(m.group(1))


def _parse_str_g1(m: re.Match) -> str:
    """Return group(1) as-is."""
    return m.group(1)


def _parse_int_list_g1(m: re.Match) -> list[int] | None:
    """Parse group(1) as a list of ints; return None if empty."""
    result = _parse_int_list(m.group(1))
    return result if result else None


def _parse_str_list_g1(m: re.Match) -> list[str] | None:
    """Parse group(1) as a list of quoted strings; return None if empty."""
    result = _parse_str_list(m.group(1))
    return result if result else None


# Declarative extraction table: (key_name, compiled_pattern, parser_fn).
# The parser receives the Match object and returns a value to store.
# A None return means "skip this key" (e.g. empty list).
_PARAM_EXTRACTORS: list[tuple[str, re.Pattern[str], Any]] = [
    ("year", _YEAR_PATTERN, _parse_int_g1),
    ("month", _MONTH_PATTERN, _parse_int_g1),
    ("months", _MONTHS_PATTERN, _parse_int_list_g1),
    ("day", _DAY_PATTERN, _parse_int_g1),
    ("days", _DAYS_PATTERN, _parse_int_g1),
    ("quarter", _QUARTER_PATTERN, _parse_int_g1),
    ("quarters", _QUARTERS_PATTERN, _parse_int_list_g1),
    ("state", _STATE_PATTERN, _parse_str_g1),
    ("states", _STATES_PATTERN, _parse_str_list_g1),
    ("city", _CITY_PATTERN, _parse_str_g1),
    ("cities", _CITIES_PATTERN, _parse_str_list_g1),
    ("county", _COUNTY_PATTERN, _parse_str_g1),
    ("category", _CATEGORY_PATTERN, _parse_str_g1),
    ("color", _COLOR_PATTERN, _parse_str_g1),
    ("colors", _COLORS_PATTERN, _parse_str_list_g1),
    ("manufact_id", _MANUFACT_PATTERN, _parse_int_g1),
    ("manufacturer_id", _MANUFACTURER_PATTERN, _parse_int_g1),
    ("manager_id", _MANAGER_PATTERN, _parse_int_g1),
    ("market_id", _MARKET_PATTERN, _parse_int_g1),
    ("store_sk", _STORE_PATTERN, _parse_int_g1),
    ("warehouse_id", _WAREHOUSE_PATTERN, _parse_int_g1),
    ("class_id", _CLASS_ID_PATTERN, _parse_int_g1),
    ("category_id", _CATEGORY_ID_PATTERN, _parse_int_g1),
    ("d_month_seq", _MONTH_SEQ_PATTERN, _parse_int_g1),
    ("gmt_offset", _GMT_OFFSET_PATTERN, _parse_float_g1),
    ("income_band", _INCOME_BAND_PATTERN, _parse_int_g1),
]

# Alias groups: one pattern populates multiple output keys.
# (alias_keys, compiled_pattern, parser_fn)
_PARAM_ALIAS_EXTRACTORS: list[tuple[tuple[str, ...], re.Pattern[str], Any]] = [
    (("categories", "item_categories"), _CATEGORIES_PATTERN, _parse_str_list_g1),
    (("manufact_ids", "manufacturer_ids"), _MANUFACTURERS_PATTERN, _parse_int_list_g1),
]

# Preferred-key groups: the first matching key in expected_keys wins.
# (candidate_keys, compiled_pattern, parser_fn)
_PARAM_PREFERRED_EXTRACTORS: list[tuple[tuple[str, ...], re.Pattern[str], Any]] = [
    (("cd_gender", "gender"), _GENDER_PATTERN, _parse_str_g1),
    (("cd_marital_status", "marital_status"), _MARITAL_PATTERN, _parse_str_g1),
    (("cd_education_status", "education"), _EDUCATION_PATTERN, _parse_str_g1),
]


def _extract_common_params(sql: str, expected_keys: set[str]) -> dict[str, Any]:
    """Extract parameters from SQL using common TPC-DS patterns.

    Only extracts values for keys that are expected (present in defaults).
    """
    result: dict[str, Any] = {}

    _extract_simple_params(sql, expected_keys, result)
    _extract_alias_params(sql, expected_keys, result)
    _extract_preferred_params(sql, expected_keys, result)
    _extract_hour_ranges(sql, expected_keys, result)

    return result


def _extract_simple_params(sql: str, expected_keys: set[str], result: dict[str, Any]) -> None:
    """Extract simple 1:1 key -> pattern -> parser parameters."""
    for key, pattern, parser in _PARAM_EXTRACTORS:
        if key not in expected_keys:
            continue
        m = pattern.search(sql)
        if m:
            value = parser(m)
            if value is not None:
                result[key] = value


def _extract_alias_params(sql: str, expected_keys: set[str], result: dict[str, Any]) -> None:
    """Extract alias groups: one pattern populates all matching expected keys."""
    for alias_keys, pattern, parser in _PARAM_ALIAS_EXTRACTORS:
        if not any(k in expected_keys for k in alias_keys):
            continue
        m = pattern.search(sql)
        if m:
            value = parser(m)
            if value is not None:
                for k in alias_keys:
                    if k in expected_keys:
                        result[k] = value


def _extract_preferred_params(sql: str, expected_keys: set[str], result: dict[str, Any]) -> None:
    """Extract preferred-key groups: first matching expected key gets the value."""
    for candidates, pattern, parser in _PARAM_PREFERRED_EXTRACTORS:
        if not any(k in expected_keys for k in candidates):
            continue
        m = pattern.search(sql)
        if m:
            value = parser(m)
            if value is not None:
                for k in candidates:
                    if k in expected_keys:
                        result[k] = value
                        break


def _extract_hour_ranges(sql: str, expected_keys: set[str], result: dict[str, Any]) -> None:
    """Extract hour range parameters using finditer (multi-match extraction)."""
    if "hours" not in expected_keys:
        return
    ranges = [(int(match.group(1)), int(match.group(2))) for match in _HOUR_RANGE_PATTERN.finditer(sql)]
    if ranges:
        result["hours"] = ranges


def get_supported_parameter_keys() -> set[str]:
    """Return parameter keys currently supported by generic extraction."""
    return set(_SUPPORTED_PARAMETER_KEYS)


def get_unsupported_parameter_keys() -> set[str]:
    """Return known parameter keys that currently fall back to static defaults."""
    from benchbox.core.tpcds.dataframe_queries.parameters import TPCDS_DEFAULT_PARAMS

    all_keys = {key for query_params in TPCDS_DEFAULT_PARAMS.values() for key in query_params}
    return (all_keys - _SUPPORTED_PARAMETER_KEYS) | _INTENTIONALLY_UNSUPPORTED_KEYS


def get_parameter_key_coverage() -> list[dict[str, Any]]:
    """Return key coverage inventory ranked by query impact and support status."""
    from benchbox.core.tpcds.dataframe_queries.parameters import TPCDS_DEFAULT_PARAMS

    counts: dict[str, int] = {}
    for params in TPCDS_DEFAULT_PARAMS.values():
        for key in params:
            counts[key] = counts.get(key, 0) + 1

    coverage: list[dict[str, Any]] = []
    for key, count in counts.items():
        coverage.append(
            {
                "key": key,
                "queries": count,
                "supported": key in _SUPPORTED_PARAMETER_KEYS,
                "risk": "high" if count >= 4 else "medium" if count >= 2 else "low",
            }
        )
    return sorted(coverage, key=lambda item: (-item["queries"], item["key"]))


# -- Cache -----------------------------------------------------------------

_cache: dict[tuple[int, float, Optional[int]], dict[int, dict[str, Any]]] = {}


def get_tpcds_extracted_parameters(
    seed: int,
    scale_factor: float = 1.0,
    stream_id: Optional[int] = None,
    *,
    use_cache: bool = True,
) -> dict[int, dict[str, Any]]:
    """Get TPC-DS parameters extracted from dsqgen, with caching.

    This is the primary entry point. Results are cached per
    (seed, scale_factor, stream_id) to avoid redundant binary invocations.

    Args:
        seed: Random number generator seed.
        scale_factor: Scale factor for parameter calculations.
        stream_id: Stream identifier.
        use_cache: Whether to use cached results.

    Returns:
        Dict mapping query_id to parameter dict.

    Raises:
        RuntimeError: If dsqgen binary is not available.
    """
    cache_key = (seed, scale_factor, stream_id)
    if use_cache and cache_key in _cache:
        return _cache[cache_key]

    params = extract_tpcds_parameters(seed, scale_factor, stream_id)
    if use_cache:
        _cache[cache_key] = params
    return params


def clear_cache() -> None:
    """Clear the parameter extraction cache."""
    _cache.clear()
