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
        # cache_enabled was already populated from database_options; a registered
        # default that happens to match must not rewrite the saved_config
        # provenance.
        "cache_enabled": "saved_config",
        "access_token": "saved_config",
        "password": "cli_option",
    }


def test_registered_default_does_not_overwrite_saved_config_provenance() -> None:
    """w17 regression: when a saved value matches a registered default, the
    source must remain ``saved_config`` so debugging/audit flows that rely on
    origin tracking aren't misled."""
    values, sources = build_platform_options_capture(
        requested_options={"foo": "bar"},
        requested_sources={"foo": "registered_default"},
        database_options={"foo": "bar"},
    )

    assert values == {"foo": "bar"}
    assert sources == {"foo": "saved_config"}


def test_registered_default_recorded_when_no_saved_value() -> None:
    """w17: registered defaults should still be recorded as such when there is
    no prior saved_config value to preserve."""
    values, sources = build_platform_options_capture(
        requested_options={"foo": "bar"},
        requested_sources={"foo": "registered_default"},
        database_options=None,
    )

    assert values == {"foo": "bar"}
    assert sources == {"foo": "registered_default"}


@pytest.mark.parametrize(
    "key",
    [
        "sessionToken",
        "SessionToken",
        "session-token",
        "session.token",
        "AccessKeyId",
        "accessKeyId",
        "access-key-id",
        "ConnectionString",
        "connectionString",
        "connection-string",
        "PrivateKey",
        "privateKey",
        "private-key",
        "Credential",
        "AwsCredentials",
    ],
)
def test_camelcase_kebabcase_secret_keys_are_redacted(key: str) -> None:
    """w3 regression: secret-key matching must collapse non-alphanumerics so
    camelCase / PascalCase / kebab-case credential keys are detected."""
    from benchbox.core.results.platform_options import is_secret_option_key

    assert is_secret_option_key(key), f"{key!r} should be classified as a secret key"


def test_sanitize_redacts_camelcase_secret_values() -> None:
    """w3 regression: end-to-end check that camelCase secret keys are redacted
    in the sanitized output."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {
            "sessionToken": "raw-session",
            "accessKeyId": "AKIA-RAW",
            "ConnectionString": "Server=...;Pwd=raw",
            "warehouse": "WH",
        }
    )

    assert sanitized["sessionToken"] == REDACTED_VALUE
    assert sanitized["accessKeyId"] == REDACTED_VALUE
    assert sanitized["ConnectionString"] == REDACTED_VALUE
    assert sanitized["warehouse"] == "WH"


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
