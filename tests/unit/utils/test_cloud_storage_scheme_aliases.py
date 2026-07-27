"""Every scheme is_cloud_path accepts must produce a usable handler.

``is_cloud_path`` accepted ``[s3, gs, gcs, az, abfss, azure, dbfs]``, but
cloudpathlib only registers ``az://``, ``gs://`` and ``s3://``. So ``gcs://``,
``azure://`` and ``abfss://`` classified as cloud and then raised
``ValueError: Invalid cloud path format`` at handler construction — any caller
that classifies first and constructs second accepted a path and then blew up.

``gcs``/``azure`` are spelling aliases and are rewritten losslessly.
``abfss`` is not: it encodes the storage account in the authority, which the
``az://container/path`` form cannot carry, so it is staged locally like
``dbfs://`` and Snowflake stages instead of being silently remapped.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import pytest

from benchbox.utils.cloud_storage import (
    CloudStagingPath,
    create_path_handler,
    get_cloud_path_info,
    is_adls_path,
    is_cloud_path,
    validate_cloud_credentials,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Every scheme is_cloud_path() accepts, with a representative path.
ALL_ACCEPTED_SCHEMES = [
    "s3://bucket/prefix",
    "gs://bucket/prefix",
    "gcs://bucket/prefix",
    "az://container/prefix",
    "azure://container/prefix",
    "abfss://container@account.dfs.core.windows.net/prefix",
    "dbfs:/Volumes/catalog/schema/volume",
]

ALIAS_EQUIVALENTS = [
    ("gcs://bucket/a/b", "gs://bucket/a/b"),
    ("azure://container/a/b", "az://container/a/b"),
]


class TestEveryAcceptedSchemeResolves:
    """The core invariant: classify-then-construct must never raise."""

    @pytest.mark.parametrize("path", ALL_ACCEPTED_SCHEMES)
    def test_accepted_scheme_produces_a_handler(self, path):
        """A scheme is_cloud_path accepts must not blow up in the handler."""
        assert is_cloud_path(path), path
        handler = create_path_handler(path)
        assert handler is not None

    @pytest.mark.parametrize("path", ALL_ACCEPTED_SCHEMES)
    def test_accepted_scheme_never_yields_a_relative_local_path(self, path):
        """A relative handler would write generated data under the cwd."""
        handler = create_path_handler(path)
        assert not (isinstance(handler, Path) and not handler.is_absolute()), handler


class TestSchemeAliasesAreLossless:
    """gcs:// and azure:// are spellings of gs:// and az://."""

    @pytest.mark.parametrize(("alias", "canonical"), ALIAS_EQUIVALENTS)
    def test_alias_resolves_to_the_same_handler_as_the_canonical_scheme(self, alias, canonical):
        """Same class and same rendered path — nothing is dropped."""
        alias_handler = create_path_handler(alias)
        canonical_handler = create_path_handler(canonical)
        assert type(alias_handler) is type(canonical_handler)
        assert str(alias_handler) == str(canonical_handler)

    @pytest.mark.parametrize(("alias", "canonical"), ALIAS_EQUIVALENTS)
    def test_alias_preserves_container_and_key(self, alias, canonical):
        """The bucket/container and key survive the rewrite."""
        assert str(create_path_handler(alias)).endswith("/a/b")

    def test_uppercase_alias_scheme_is_normalised(self):
        """Scheme comparison is case-insensitive, as URI schemes are."""
        assert str(create_path_handler("GCS://bucket/a")) == str(create_path_handler("gs://bucket/a"))

    def test_alias_rewrite_does_not_touch_other_schemes(self):
        """s3:// and friends pass through untouched."""
        assert str(create_path_handler("s3://bucket/a")) == "s3://bucket/a"

    def test_alias_inside_a_path_is_not_rewritten(self):
        """Only a leading scheme is rewritten, not the word appearing later."""
        handler = create_path_handler("s3://bucket/azure://nested")
        assert "azure://nested" in str(handler)

    def test_get_cloud_path_info_still_reports_the_original_provider(self):
        """The rewrite is confined to the cloudpathlib hand-off.

        Provider identity is consumed elsewhere (azure_synapse checks it), so
        normalising it here would change behaviour well outside this fix.
        """
        assert get_cloud_path_info("gcs://bucket/p")["provider"] == "gcs"
        assert get_cloud_path_info("azure://container/p")["provider"] == "azure"


class TestAdlsPathsStageLocally:
    """abfss:// encodes an account that az:// cannot represent."""

    def test_is_adls_path_matches_only_abfss(self):
        """The predicate is scheme-exact."""
        assert is_adls_path("abfss://c@a.dfs.core.windows.net/p")
        assert not is_adls_path("az://c/p")
        assert not is_adls_path("s3://b/p")
        assert not is_adls_path("/local/abfss")
        assert not is_adls_path(None)

    def test_abfss_stages_locally_and_keeps_the_full_uri(self):
        """The account-bearing URI must survive verbatim for the adapter."""
        uri = "abfss://container@account.dfs.core.windows.net/path/to/data"
        handler = create_path_handler(uri)
        assert isinstance(handler, CloudStagingPath)
        assert handler.cloud_target == uri
        assert Path(str(handler)).is_absolute()

    def test_abfss_is_not_remapped_to_an_azure_blob_path(self):
        """Remapping would silently retarget whatever account the creds name."""
        handler = create_path_handler("abfss://container@account.dfs.core.windows.net/p")
        assert "account.dfs.core.windows.net" in handler.cloud_target
        assert not str(handler).startswith("az://")

    def test_abfss_creates_no_directory_in_cwd(self, tmp_path, monkeypatch):
        """Staging must not spill into the current working directory."""
        monkeypatch.chdir(tmp_path)
        create_path_handler("abfss://c@a.dfs.core.windows.net/p")
        assert list(tmp_path.iterdir()) == []


class TestCredentialValidationHandlesAliases:
    """validate_cloud_credentials builds a CloudPath too — same alias trap.

    Its construction is guarded by a broad ``except Exception`` that reports
    every failure as a credential problem, so an unnormalised alias surfaced a
    scheme error dressed up as "Cloud path validation failed". That path is only
    reached once credentials are actually configured, which is exactly the
    real-user case.
    """

    @pytest.mark.parametrize(("alias", "canonical"), ALIAS_EQUIVALENTS)
    def test_alias_validates_identically_to_the_canonical_scheme(self, alias, canonical, monkeypatch):
        """Same verdict and same error class, not a prefix complaint."""
        for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "GOOGLE_APPLICATION_CREDENTIALS"):
            monkeypatch.setenv(var, "dummy")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "acct")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "key")

        alias_result = validate_cloud_credentials(alias)
        canonical_result = validate_cloud_credentials(canonical)

        assert alias_result["valid"] == canonical_result["valid"]
        assert "does not begin with a known prefix" not in str(alias_result["error"])

    def test_adls_is_not_probed_with_cloudpathlib(self, monkeypatch):
        """abfss:// cannot be opened, so probing it would fake a cred failure."""
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_NAME", "acct")
        monkeypatch.setenv("AZURE_STORAGE_ACCOUNT_KEY", "key")

        import benchbox.utils.cloud_storage as cs

        monkeypatch.setattr(cs, "_load_cloudpathlib", lambda: (_ for _ in ()).throw(AssertionError("must stay lazy")))

        result = validate_cloud_credentials("abfss://c@a.dfs.core.windows.net/p")

        assert result["valid"] is True
        assert result["error"] is None

    def test_adls_still_reports_missing_azure_env_vars(self, monkeypatch):
        """Skipping the probe must not skip the env-var check."""
        monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_NAME", raising=False)
        monkeypatch.delenv("AZURE_STORAGE_ACCOUNT_KEY", raising=False)

        result = validate_cloud_credentials("abfss://c@a.dfs.core.windows.net/p")

        assert result["valid"] is False
        assert "AZURE_STORAGE_ACCOUNT_NAME" in result["error"]

    def test_snowflake_stage_validation_stays_independent_of_cloudpathlib(self, monkeypatch):
        import benchbox.utils.cloud_storage as cs

        monkeypatch.setattr(cs, "_load_cloudpathlib", lambda: (_ for _ in ()).throw(AssertionError("must stay lazy")))

        result = validate_cloud_credentials("@~/benchbox")

        assert result == {
            "valid": True,
            "provider": "snowflake_stage",
            "error": None,
            "env_vars": [],
        }


class TestExistingBehaviourUnchanged:
    """The schemes that already worked must keep working identically."""

    def test_dbfs_still_returns_a_databricks_path(self):
        """dbfs:// keeps its DatabricksPath temp-dir behaviour."""
        from benchbox.utils.cloud_storage import DatabricksPath

        handler = create_path_handler("dbfs:/Volumes/c/s/v")
        assert isinstance(handler, DatabricksPath)
        assert handler.dbfs_target == "dbfs:/Volumes/c/s/v"

    def test_snowflake_stage_still_returns_a_staging_path(self):
        """Stage paths are unaffected by the alias work."""
        handler = create_path_handler("@~/benchbox")
        assert isinstance(handler, CloudStagingPath)
        assert handler.cloud_target == "@~/benchbox"

    def test_local_paths_are_untouched(self):
        """Local paths still return plain Path objects."""
        assert create_path_handler("/local/path") == Path("/local/path")
        assert create_path_handler("./rel") == Path("./rel")

    def test_unknown_scheme_still_classifies_as_local(self):
        """The accepted-scheme list is not widened by this change."""
        assert not is_cloud_path("ftp://host/path")
        assert create_path_handler("ftp://host/path") == Path("ftp://host/path")
