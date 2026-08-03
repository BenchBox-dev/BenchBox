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


def test_capture_retains_usernames_until_the_export_boundary() -> None:
    values, _sources = build_platform_options_capture(
        requested_options={"username": "alice-sentinel", "password": "secret-sentinel"}
    )

    assert values["username"] == "alice-sentinel"
    assert values["password"] == REDACTED_VALUE


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


@pytest.mark.parametrize(
    "key",
    [
        # Provider-prefixed key-id spellings. `accessKeyId` already matched
        # because it contains "accesskey"; these do not, so they exported
        # verbatim until "key_id" joined _SECRET_KEY_PARTS.
        "s3_key_id",
        "kms_key_id",
        "KmsKeyId",
        "kmsKeyId",
        "key_id",
        "keyId",
    ],
)
def test_provider_prefixed_key_id_keys_are_redacted(key: str) -> None:
    """Regression: a *_key_id option reached exported result metadata in clear.

    Found by the credential-egress sweep on the DuckLake ATTACH leak (#1333):
    `--platform-option s3_key_id=AKIA...` was published as-is because the
    matcher only knew "access_key".
    """
    from benchbox.core.results.platform_options import is_secret_option_key

    assert is_secret_option_key(key), f"{key!r} should be classified as a secret key"


@pytest.mark.parametrize(
    "key",
    [
        # Data-modelling and tuning option names that merely contain "key".
        # The "keyid" part must not swallow these - over-redaction would strip
        # real, useful provenance out of published results.
        "sort_key",
        "sortKey",
        "partition_key",
        "primary_key",
        "clustering_key",
        "distkey",
        "distribution_key",
        "warehouse",
        "memory_limit",
    ],
)
def test_non_credential_key_names_are_not_redacted(key: str) -> None:
    from benchbox.core.results.platform_options import is_secret_option_key

    assert not is_secret_option_key(key), f"{key!r} must keep exporting its real value"


def test_sanitize_redacts_key_id_end_to_end_without_touching_sort_keys() -> None:
    """End-to-end companion: the sanitized payload hides key material and keeps
    the tuning options a reader needs to interpret the run."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {
            "s3_key_id": "AKIAIOSFODNN7EXAMPLE",
            "kms_key_id": "arn:aws:kms:us-east-1:111122223333:key/abcd",
            "s3_secret": "raw-secret",
            "sort_key": "l_shipdate",
            "partition_key": "l_orderkey",
        }
    )

    assert sanitized["s3_key_id"] == REDACTED_VALUE
    assert sanitized["kms_key_id"] == REDACTED_VALUE
    assert sanitized["s3_secret"] == REDACTED_VALUE
    assert sanitized["sort_key"] == "l_shipdate"
    assert sanitized["partition_key"] == "l_orderkey"


def test_credential_aliases_are_redacted_without_touching_paths_or_tuning_keys() -> None:
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {
            "passwd": "PASSWD_SECRET",
            "pwd": "PWD_SECRET",
            "pat": "PAT_SECRET",
            "path": "/tmp/data",
            "sort_key": "o_orderkey",
            "partition_key": "id",
            "primary_key": "id",
        }
    )

    assert sanitized["passwd"] == REDACTED_VALUE
    assert sanitized["pwd"] == REDACTED_VALUE
    assert sanitized["pat"] == REDACTED_VALUE
    assert sanitized["path"] == "/tmp/data"
    assert sanitized["sort_key"] == "o_orderkey"
    assert sanitized["partition_key"] == "id"
    assert sanitized["primary_key"] == "id"


def test_uri_userinfo_credentials_are_redacted_without_touching_public_values() -> None:
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {
            "database_path": "postgresql://user:URI_PASSWORD@db.example/db",
            "output_location": "https://user:URI_TOKEN@example.com/export",
            "url": "https://public.example/export",
            "path": "/tmp/data",
            "sort_key": "o_orderkey",
        }
    )

    assert sanitized["database_path"] == "postgresql://****@db.example/db"
    assert sanitized["output_location"] == "https://****@example.com/export"
    assert sanitized["url"] == "https://public.example/export"
    assert sanitized["path"] == "/tmp/data"
    assert sanitized["sort_key"] == "o_orderkey"


def test_uri_userinfo_redaction_consumes_an_unescaped_at_in_the_password() -> None:
    """Review follow-up: a password may legally contain an unescaped '@'.

    urlparse reads ``postgres://user:pa@ss@host/db`` as password ``pa@ss``, but a
    pattern that stopped at the FIRST '@' exported ``postgres://****@ss@host/db``
    -- still leaking the tail of the credential into result metadata. Redaction
    must run through the authority's LAST userinfo delimiter.
    """
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {
            "database_path": "postgres://user:pa@ss@host/db",
            # The authority ends at '?', so a later '@' in the query string must
            # not drag the host into the redaction.
            "output_location": "postgres://user:pw@host?opt=a@b",
        }
    )

    assert sanitized["database_path"] == "postgres://****@host/db"
    assert "ss@host" not in sanitized["database_path"]
    assert sanitized["output_location"] == "postgres://****@host?opt=a@b"


@pytest.mark.parametrize(
    "uri",
    [
        "abfss://container@account.dfs.core.windows.net/path",
        "abfs://container@account.dfs.core.windows.net/path",
        "wasbs://container@account.blob.core.windows.net/path",
        "wasb://container@account.blob.core.windows.net/path",
        "ABFSS://Container@account.dfs.core.windows.net/path",
    ],
)
def test_azure_storage_container_authority_is_preserved(uri: str) -> None:
    """Review follow-up: ``container@account`` is ABFS/WASB authority syntax, not
    credentials, so redacting it would strip the container (or Fabric workspace)
    identifier out of exported provenance while protecting nothing -- those
    schemes carry their secret in a separate account_key/sas option, which the
    key-name redaction already covers.
    """
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options({"staging_root": uri})

    assert sanitized["staging_root"] == uri


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


def test_sanitize_excludes_internal_keys_when_requested() -> None:
    """w1: exported paths must drop internal bookkeeping keys, matching
    ``_iter_public_options`` semantics, instead of publishing them."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {
            "warehouse": "WH",
            "tuning_config": object(),
            "unified_tuning_configuration": object(),
            "df_tuning_config": object(),
            "tuning_enabled": True,
            "_explicit_platform_options": {"warehouse": "WH"},
        },
        exclude_internal=True,
    )

    assert sanitized == {"warehouse": "WH"}
    assert "tuning_config" not in sanitized
    assert "unified_tuning_configuration" not in sanitized
    assert "df_tuning_config" not in sanitized
    assert "tuning_enabled" not in sanitized


def test_sanitize_without_exclude_internal_preserves_existing_behavior() -> None:
    """Non-export call sites keep receiving internal keys unless they opt in,
    so this is an additive/opt-in change rather than a behavior break."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options({"warehouse": "WH", "tuning_enabled": True})

    assert sanitized["warehouse"] == "WH"
    assert sanitized["tuning_enabled"] is True


def test_sanitize_uses_to_dict_for_objects_that_support_it() -> None:
    """w2: an object with ``to_dict`` must serialize as that dict (recursively
    sanitized), never as a repr string."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    class _Config:
        def to_dict(self) -> dict[str, object]:
            return {"driver": "postgres", "password": "super-secret"}

    sanitized = sanitize_platform_options({"tuning_config": _Config()})

    assert sanitized["tuning_config"] == {"driver": "postgres", "password": REDACTED_VALUE}


def test_sanitize_marks_unserializable_values_instead_of_using_repr() -> None:
    """w2/w3: objects without ``to_dict`` become an explicit marker string,
    never a Python repr(), so capture gaps stay visible rather than opaque."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    class _Opaque:
        def __repr__(self) -> str:  # pragma: no cover - guards against leakage
            return "<Opaque object at 0x1234 with lots of internal repr text>"

    sanitized = sanitize_platform_options({"weird": _Opaque()})

    assert sanitized["weird"] == "<unserializable:_Opaque>"
    assert "0x" not in sanitized["weird"]
    assert "repr" not in sanitized["weird"]


def test_sanitize_never_raises_when_to_dict_itself_fails() -> None:
    """Bundle emission must never raise because an option value is unserializable."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    class _Broken:
        def to_dict(self) -> dict[str, object]:
            raise RuntimeError("boom")

    sanitized = sanitize_platform_options({"broken": _Broken()})

    assert sanitized["broken"] == "<unserializable:_Broken>"


def test_sanitize_never_raises_when_to_dict_lookup_itself_fails() -> None:
    """A ``to_dict`` descriptor that raises on attribute access (not just on
    call) must be caught too -- the ``getattr(value, "to_dict", None)`` lookup
    happens outside the call's try/except, so a raising property previously
    escaped uncaught."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    class _BrokenDescriptor:
        @property
        def to_dict(self):
            raise RuntimeError("boom during attribute access")

    sanitized = sanitize_platform_options({"broken": _BrokenDescriptor()})

    assert sanitized["broken"] == "<unserializable:_BrokenDescriptor>"


def test_secret_redaction_unaffected_by_internal_key_filtering() -> None:
    """Secret redaction must remain exact regardless of exclude_internal."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    sanitized = sanitize_platform_options(
        {"password": "super-secret", "tuning_config": "x"},
        exclude_internal=True,
    )

    assert sanitized == {"password": REDACTED_VALUE}


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


class TestUsernameRedactionInternalPath:
    """Connection usernames must not ride into internal bundles verbatim.

    They are identity, not secrets: the public path pseudonymizes them for
    grouping, but the internal capture path has no pseudonymizer, so it
    redacts them instead. Exact normalized match only, so user_agent-class
    option keys keep their real values.
    """

    def test_username_keys_are_redacted(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        result = sanitize_platform_options(
            {"username": "alice-sentinel", "user": "bob-sentinel", "pg_user": "carol-sentinel"}
        )
        assert result["username"] == REDACTED_VALUE
        assert result["user"] == REDACTED_VALUE
        assert result["pg_user"] == REDACTED_VALUE

    def test_user_lookalike_keys_are_not_over_redacted(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        result = sanitize_platform_options({"user_agent": "ua/1.0", "num_users": 7, "users_table": "users"})
        assert result["user_agent"] == "ua/1.0"
        assert result["num_users"] == 7
        assert result["users_table"] == "users"

    def test_secret_keys_keep_current_behavior(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        result = sanitize_platform_options({"password": "pw-sentinel", "s3_key_id": "AKIA-sentinel"})
        assert result["password"] == REDACTED_VALUE
        assert result["s3_key_id"] == REDACTED_VALUE

    def test_nested_username_is_redacted(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        result = sanitize_platform_options({"connection": {"username": "alice-sentinel", "host": "db.internal"}})
        assert result["connection"]["username"] == REDACTED_VALUE
        assert result["connection"]["host"] == "db.internal"


class TestServiceAccountRedaction:
    """service_account carries an IAM principal email (dataproc); the public
    layer caught it only when the VALUE was email-shaped, and the internal
    layer exported it verbatim."""

    def test_service_account_is_redacted_internally(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        out = sanitize_platform_options({"service_account": "svc-bench@proj.iam.gserviceaccount.com"})
        assert out["service_account"] != "svc-bench@proj.iam.gserviceaccount.com"

    def test_non_email_service_account_is_pseudonymized_publicly(self):
        import json

        from benchbox.core.results.anonymization import AnonymizationManager

        out = AnonymizationManager().anonymize_result_payload(
            {"platform_metadata": {"platform_raw_config": {"service_account": "SA-SENTINEL-NOT-AN-EMAIL"}}}
        )["platform_metadata"]["platform_raw_config"]
        assert "SA-SENTINEL-NOT-AN-EMAIL" not in json.dumps(out, default=str)

    def test_auth_method_lookalikes_keep_real_values(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        out = sanitize_platform_options({"auth_method": "service_principal", "runtime_version": "1.2"})
        assert out["auth_method"] == "service_principal"
        assert out["runtime_version"] == "1.2"


class TestApiKeyAndAccountKeyRedaction:
    """api_key and *_account_key are credentials and must never export
    verbatim (2026-07-31 sentinel-sweep finding: they leaked through both
    the internal and the public layer)."""

    def test_api_key_variants_are_redacted(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        result = sanitize_platform_options(
            {"api_key": "APIKEY-SENTINEL", "onehouse_api_key": "OH-SENTINEL", "apiKey": "CAMEL-SENTINEL"}
        )
        assert result["api_key"] == REDACTED_VALUE
        assert result["onehouse_api_key"] == REDACTED_VALUE
        assert result["apiKey"] == REDACTED_VALUE

    def test_storage_account_key_is_redacted(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        assert sanitize_platform_options({"storage_account_key": "AZKEY-SENTINEL"})["storage_account_key"] == (
            REDACTED_VALUE
        )

    def test_data_modelling_keys_still_export(self):
        from benchbox.core.results.platform_options import sanitize_platform_options

        result = sanitize_platform_options(
            {"sort_key": "l_shipdate", "partition_key": "l_orderkey", "primary_key": "id", "account": "acct-1"}
        )
        assert result["sort_key"] == "l_shipdate"
        assert result["partition_key"] == "l_orderkey"
        assert result["primary_key"] == "id"
        assert result["account"] == "acct-1"


@pytest.mark.parametrize(
    "key",
    [
        "dsn",
        "database_dsn",
        "spark.hadoop.fs.azure.sas.container.account.blob.core.windows.net",
    ],
)
def test_dsn_and_sas_credential_keys_are_redacted(key: str) -> None:
    """Connection DSNs and Azure SAS settings can both carry bearer secrets."""
    from benchbox.core.results.platform_options import sanitize_platform_options

    assert sanitize_platform_options({key: "CREDENTIAL-SENTINEL"})[key] == REDACTED_VALUE
