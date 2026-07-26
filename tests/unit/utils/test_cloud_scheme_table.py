"""One scheme table drives classification, staging, credentials and gating.

Scheme identity used to be spelled out in five places -- ``is_cloud_path``'s
literal list, the cloudpathlib alias map, the ADLS predicate, the credential
env-var map, and ``azure_synapse``'s provider gate. Adding a scheme to one left
the others behind, which produced three live defects:

* ``abfs://`` classified as **local**, so it resolved to a *relative* path and
  spilled generated data into the cwd -- the same mechanism as the 319 MB
  ``@~/`` incident;
* ``azure://`` reported provider ``"azure"``, which Synapse rejected even
  though it is a documented output-location form;
* ``az://`` had no entry in the credential map, so the canonical spelling
  skipped its Azure env-var check while its alias got one.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import pytest

from benchbox.utils.cloud_storage import (
    _CLOUD_SCHEMES,
    _SCHEME_BY_NAME,
    CloudStagingPath,
    cloud_provider_family,
    create_path_handler,
    is_adls_path,
    is_cloud_path,
    validate_cloud_credentials,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


ALL_SPELLINGS = [
    ("s3://bucket/x", "aws"),
    ("gs://bucket/x", "gcp"),
    ("gcs://bucket/x", "gcp"),
    ("az://container/x", "azure"),
    ("azure://container/x", "azure"),
    ("abfss://container@account.dfs.core.windows.net/x", "azure"),
    ("abfs://container@account.dfs.core.windows.net/x", "azure"),
    ("dbfs:/Volumes/catalog/schema/volume", "databricks"),
]


class TestEverySchemeIsWiredEverywhere:
    """The invariant the table exists to enforce."""

    @pytest.mark.parametrize(("path", "family"), ALL_SPELLINGS)
    def test_recognised_scheme_classifies_as_cloud(self, path, family):
        """A scheme in the table is never treated as a local path."""
        assert is_cloud_path(path), path

    @pytest.mark.parametrize(("path", "family"), ALL_SPELLINGS)
    def test_recognised_scheme_never_yields_a_relative_path(self, path, family):
        """The spill mode: a relative handler writes under the cwd."""
        handler = create_path_handler(path)
        assert not (isinstance(handler, Path) and not handler.is_absolute()), (path, handler)

    @pytest.mark.parametrize(("path", "family"), ALL_SPELLINGS)
    def test_recognised_scheme_reports_its_family(self, path, family):
        """Platform gates key off the family, so every scheme must have one."""
        assert cloud_provider_family(path) == family, path

    @pytest.mark.parametrize(("path", "family"), ALL_SPELLINGS)
    def test_scheme_with_credentials_declares_env_vars(self, path, family):
        """A scheme that needs credentials must not silently skip its check."""
        if family == "databricks":  # validated by the Databricks adapter
            pytest.skip("dbfs credentials are checked by the adapter")
        assert validate_cloud_credentials(path)["env_vars"], path


class TestAbfsNoLongerSpillsToCwd:
    """The headline defect: abfs:// was classified local."""

    ABFS = "abfs://container@account.dfs.core.windows.net/data"

    def test_abfs_is_cloud(self):
        assert is_cloud_path(self.ABFS)

    def test_abfs_stages_locally_like_abfss(self):
        """Both ADLS spellings carry the account, so both stage rather than rewrite."""
        assert is_adls_path(self.ABFS)
        handler = create_path_handler(self.ABFS)
        assert isinstance(handler, CloudStagingPath)
        assert handler.cloud_target == self.ABFS

    def test_abfs_is_not_remapped_to_azure_blob(self):
        """Rewriting would drop the account in the authority."""
        handler = create_path_handler(self.ABFS)
        assert "account.dfs.core.windows.net" in handler.cloud_target
        assert not str(handler).startswith("az://")

    def test_abfs_creates_no_directory_in_cwd(self, tmp_path, monkeypatch):
        """Regression for the spill itself."""
        monkeypatch.chdir(tmp_path)
        create_path_handler(self.ABFS)
        assert list(tmp_path.iterdir()) == []


class TestAliasesAreLossless:
    """An alias must behave exactly like its canonical spelling."""

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [("gcs://bucket/a/b", "gs://bucket/a/b"), ("azure://container/a/b", "az://container/a/b")],
    )
    def test_alias_matches_canonical_handler(self, alias, canonical):
        assert type(create_path_handler(alias)) is type(create_path_handler(canonical))
        assert str(create_path_handler(alias)) == str(create_path_handler(canonical))

    @pytest.mark.parametrize(
        ("alias", "canonical"),
        [
            ("gcs://b/x", "gs://b/x"),
            ("azure://c/x", "az://c/x"),
            ("abfs://c@a.dfs.core.windows.net/x", "abfss://c@a.dfs.core.windows.net/x"),
        ],
    )
    def test_alias_matches_canonical_family_and_credentials(self, alias, canonical):
        """Family and credential requirements must not depend on spelling."""
        assert cloud_provider_family(alias) == cloud_provider_family(canonical)
        assert validate_cloud_credentials(alias)["env_vars"] == validate_cloud_credentials(canonical)["env_vars"]


class TestTableIsWellFormed:
    """Guardrails on the table itself, so a future entry cannot be half-wired."""

    def test_no_duplicate_spellings(self):
        """A spelling must map to exactly one scheme."""
        spellings = [n for s in _CLOUD_SCHEMES for n in (s.canonical, *s.aliases)]
        assert len(spellings) == len(set(spellings)), spellings

    def test_every_spelling_resolves_to_its_entry(self):
        for scheme in _CLOUD_SCHEMES:
            for name in (scheme.canonical, *scheme.aliases):
                assert _SCHEME_BY_NAME[name] is scheme, name

    def test_unknown_scheme_is_still_local(self):
        """The table must not accidentally widen what counts as cloud."""
        assert not is_cloud_path("ftp://host/path")
        assert cloud_provider_family("ftp://host/path") is None
        assert create_path_handler("ftp://host/path") == Path("ftp://host/path")

    def test_snowflake_stage_still_routes_to_staging(self):
        """Must-preserve: stage handling is independent of the scheme table."""
        handler = create_path_handler("@~/benchbox")
        assert isinstance(handler, CloudStagingPath)
        assert handler.cloud_target == "@~/benchbox"
