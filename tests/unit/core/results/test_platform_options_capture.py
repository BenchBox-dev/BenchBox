"""Tests for sanitized platform-option capture in result metadata."""

from __future__ import annotations

from datetime import datetime

import pytest

from benchbox.core.results.builder import BenchmarkInfoInput, ResultBuilder, RunConfigInput
from benchbox.core.results.platform_info import PlatformInfoInput
from benchbox.core.results.platform_options import REDACTED_VALUE, build_platform_options_capture
from benchbox.core.results.query_normalizer import normalize_query_result
from benchbox.core.results.schema import build_result_payload
from benchbox.core.runner.runner import ValidationOptions, _build_run_config_from_options
from benchbox.core.schemas import BenchmarkConfig, DatabaseConfig
from benchbox.utils.verbosity import VerbositySettings

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def test_platform_options_capture_merges_values_and_records_sources() -> None:
    values, sources = build_platform_options_capture(
        requested_options={
            "warehouse": "CLI_WH",
            "cache_enabled": True,
            "password": "super-secret",
        },
        requested_sources={
            "warehouse": "cli_option",
            "cache_enabled": "registered_default",
            "password": "cli_option",
        },
        database_options={
            "warehouse": "SAVED_WH",
            "region": "us-east-1",
            "cache_enabled": True,
            "access_token": "saved-token",
            "verbose": True,
            "_explicit_platform_options": {"warehouse": "CLI_WH"},
        },
    )

    assert values == {
        "warehouse": "CLI_WH",
        "region": "us-east-1",
        "cache_enabled": True,
        "access_token": REDACTED_VALUE,
        "password": REDACTED_VALUE,
    }
    assert sources == {
        "warehouse": "cli_option",
        "region": "saved_config",
        "cache_enabled": "registered_default",
        "access_token": "saved_config",
        "password": "cli_option",
    }


def test_lifecycle_run_config_persists_sanitized_platform_options_with_provenance() -> None:
    benchmark_config = BenchmarkConfig(
        name="tpch",
        display_name="TPC-H",
        options={
            "platform_options": {
                "warehouse": "CLI_WH",
                "password": "super-secret",
            },
            "platform_option_sources": {
                "warehouse": "cli_option",
                "password": "cli_option",
            },
        },
    )
    database_config = DatabaseConfig(
        type="snowflake",
        name="Snowflake",
        options={
            "warehouse": "SAVED_WH",
            "region": "us-east-1",
            "access_token": "saved-token",
            "verbose": True,
        },
        warehouse_size="XSMALL",
    )

    run_config = _build_run_config_from_options(
        benchmark_config=benchmark_config,
        options=benchmark_config.options,
        platform_config={},
        database_config=database_config,
        validation_opts=ValidationOptions(),
        verbosity_settings=VerbositySettings.default(),
        test_type="power",
        table_format=None,
    )

    assert run_config.platform_options == {
        "warehouse": "CLI_WH",
        "region": "us-east-1",
        "warehouse_size": "XSMALL",
        "access_token": REDACTED_VALUE,
        "password": REDACTED_VALUE,
    }
    assert run_config.platform_option_sources == {
        "warehouse": "cli_option",
        "region": "saved_config",
        "warehouse_size": "saved_config",
        "access_token": "saved_config",
        "password": "cli_option",
    }


def test_result_payload_exports_platform_option_sources_from_run_config() -> None:
    builder = ResultBuilder(
        benchmark=BenchmarkInfoInput(name="TPC-H", scale_factor=0.01, benchmark_id="tpch"),
        platform=PlatformInfoInput(name="Snowflake", platform_version="8.0", client_library_version="3.0"),
        execution_id="platform-options-test",
    )
    builder.set_start_time(datetime(2026, 1, 1, 12, 0, 0))
    builder.set_run_config(
        RunConfigInput(
            platform_options={"warehouse": "CLI_WH", "password": REDACTED_VALUE},
            platform_option_sources={"warehouse": "cli_option", "password": "cli_option"},
        )
    )
    builder.add_query_result(
        normalize_query_result(
            {
                "query_id": "Q1",
                "execution_time_seconds": 0.1,
                "rows_returned": 1,
                "status": "SUCCESS",
                "run_type": "measurement",
            }
        )
    )

    payload = build_result_payload(builder.build())

    assert payload["config"]["platform_options"] == {"warehouse": "CLI_WH", "password": REDACTED_VALUE}
    assert payload["config"]["platform_option_sources"] == {
        "warehouse": "cli_option",
        "password": "cli_option",
    }
