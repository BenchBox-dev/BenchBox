from __future__ import annotations

import pytest

from benchbox.core.tuning.capability_registry import (
    DEFAULT_FALLBACK_DESCRIPTION,
    PLATFORM_FALLBACK_DESCRIPTIONS,
    PLATFORM_TUNING_CAPABILITIES,
    get_fallback_description,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.mark.parametrize(
    ("platform", "expected"),
    [
        ("duckdb", "basic constraints"),
        ("polars", "engine runtime defaults (streaming)"),
        ("polars-df", "engine runtime defaults (streaming)"),
        ("Polars", "engine runtime defaults (streaming)"),
        ("clickhouse", "OLAP session pack"),
        ("clickhouse-local", "OLAP session pack"),
        ("clickhouse:cloud", "OLAP session pack"),
        ("chdb", "OLAP session pack"),
        ("pandas-df", "engine runtime defaults"),
        ("snowflake", "basic constraints"),
    ],
)
def test_fallback_description_per_platform(platform, expected):
    assert get_fallback_description(platform) == expected


@pytest.mark.parametrize("platform", [None, "", "no-such-platform"])
def test_unknown_or_missing_platform_gets_default(platform):
    assert get_fallback_description(platform) == DEFAULT_FALLBACK_DESCRIPTION == "basic constraints"


def test_descriptions_are_not_one_fixed_string():
    assert len({get_fallback_description(p) for p in ("duckdb", "polars", "clickhouse")}) == 3


def test_sql_override_keys_are_canonical_registry_platforms():
    sql_overrides = {key for key in PLATFORM_FALLBACK_DESCRIPTIONS if key in PLATFORM_TUNING_CAPABILITIES}

    assert sql_overrides == {"clickhouse"}
