"""Tests for Snowflake stage path classification.

Snowflake stage references (``@~/...``) carry no URI scheme, so before this
classification existed they fell through to the local branch and resolved to a
*relative* directory under the current working directory — silently spilling
generated benchmark data into whatever checkout the run started from.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import tempfile
from pathlib import Path, PureWindowsPath

import pytest

from benchbox.utils.cloud_storage import (
    CloudStagingPath,
    create_path_handler,
    get_cloud_path_info,
    is_cloud_path,
    is_snowflake_stage_path,
    validate_cloud_credentials,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


STAGE_PATHS = [
    "@~",  # user stage root
    "@~/benchbox",  # user stage, the credential prompt's advertised default
    "@~/a/b/c",  # user stage, nested
    "@%orders",  # table stage
    "@%orders/part-0",  # table stage with sub-path
    '@%"My Table"',  # quoted table stage
    "@my_stage",  # named stage
    "@my_stage/data",  # named stage with sub-path
    "@my_db.my_schema.my_stage/data",  # qualified named stage
    '@"My Stage"/data',  # quoted named stage
    "@stage$name/data",  # '$' is legal in Snowflake identifiers
]

NON_STAGE_PATHS = [
    "abfss://container@account.dfs.core.windows.net/path",  # '@' inside a cloud URI
    "azure://container@account/path",
    "s3://bucket/prefix",
    "gs://bucket/prefix",
    "dbfs:/Volumes/catalog/schema/volume",
    "user@host:/remote/path",  # scp-style, '@' not leading
    "team@example.com",
    "/tmp/@~/already-spilled",  # '@~' present but not leading
    "@",  # bare sigil, no stage name
    "@/foo",  # missing stage name
    "@.",
    "@%",  # table sigil with no table
    "/local/path",
    "./relative/path",
    "~/home/path",
    "",
]


class TestIsSnowflakeStagePath:
    """The dedicated stage predicate, including the shapes it must reject."""

    @pytest.mark.parametrize("path", STAGE_PATHS)
    def test_recognises_stage_paths(self, path):
        """User, table, named and qualified-named stages all match."""
        assert is_snowflake_stage_path(path), f"{path!r} should classify as a stage"

    @pytest.mark.parametrize("path", NON_STAGE_PATHS)
    def test_rejects_non_stage_paths(self, path):
        """Cloud URIs containing '@' and ordinary local paths never match."""
        assert not is_snowflake_stage_path(path), f"{path!r} should not classify as a stage"

    def test_azure_uri_with_at_sign_is_not_a_stage(self):
        """Regression: the match is anchored, so abfss:// is never misrouted."""
        azure = "abfss://container@account.dfs.core.windows.net/path"
        assert not is_snowflake_stage_path(azure)
        # ...but it is still a cloud path, via the scheme branch.
        assert is_cloud_path(azure)

    def test_accepts_path_objects_and_rejects_non_string_input(self):
        """Path inputs are stringified; None/int are not stage paths."""
        assert is_snowflake_stage_path(Path("@~/benchbox"))
        assert not is_snowflake_stage_path(None)
        assert not is_snowflake_stage_path(123)

    def test_windows_flavoured_path_object_still_classifies_as_a_stage(self):
        """A Path carrying backslash separators is still a stage reference.

        ``str(WindowsPath("@~/benchbox"))`` is ``"@~\\benchbox"``, and the stage
        grammar requires ``/`` after the stage token, so on Windows this predicate
        silently returned False for a valid user-stage reference. PureWindowsPath
        reproduces it on any platform, so the regression is not Windows-only-visible.
        """
        assert is_snowflake_stage_path(PureWindowsPath("@~/benchbox"))
        assert is_snowflake_stage_path(PureWindowsPath("@my_stage/sub/dir"))

    def test_windows_flavoured_local_path_is_not_a_stage(self):
        """The separator normalization must not sweep ordinary local paths in."""
        assert not is_snowflake_stage_path(PureWindowsPath(r"C:\data\benchbox"))
        assert not is_snowflake_stage_path(PureWindowsPath(r"C:\data\@notastage"))


class TestStageClassification:
    """is_cloud_path / get_cloud_path_info treat stages as non-local."""

    @pytest.mark.parametrize("path", STAGE_PATHS)
    def test_stage_paths_are_not_local(self, path):
        """The core defect: a stage path must never classify as local."""
        assert is_cloud_path(path), f"{path!r} still classifies as local"

    def test_existing_schemes_are_unchanged(self):
        """Every previously-supported scheme keeps classifying as today."""
        for path in [
            "s3://bucket/p",
            "gs://bucket/p",
            "gcs://bucket/p",
            "az://container/p",
            "abfss://container@account.dfs.core.windows.net/p",
            "azure://container/p",
            "dbfs:/Volumes/c/s/v",
        ]:
            assert is_cloud_path(path), path
        for path in ["/local/path", "./rel", "~/home", "", "C:\\Windows\\path"]:
            assert not is_cloud_path(path), path

    def test_get_cloud_path_info_reports_stage_provider(self):
        """The info dict names the stage provider and splits stage from sub-path."""
        info = get_cloud_path_info("@my_stage/data/part-0")
        assert info["is_cloud"] is True
        assert info["provider"] == "snowflake_stage"
        assert info["bucket"] == "my_stage"
        assert info["path"] == "data/part-0"
        assert info["stage_info"] == {"stage": "my_stage", "sub_path": "data/part-0"}

    def test_get_cloud_path_info_user_stage_without_sub_path(self):
        """A bare user stage reports an empty sub-path rather than failing."""
        info = get_cloud_path_info("@~")
        assert info["provider"] == "snowflake_stage"
        assert info["bucket"] == "~"
        assert info["path"] == ""

    def test_quoted_stage_identifier_supports_escaped_quotes(self):
        info = get_cloud_path_info('@"My ""Stage"""/data')

        assert info["provider"] == "snowflake_stage"
        assert info["bucket"] == '"My ""Stage"""'
        assert info["path"] == "data"

    @pytest.mark.parametrize(
        ("path", "stage", "sub_path"),
        [
            ("@~/benchbox", "~", "benchbox"),
            ("@%orders/part-0", "%orders", "part-0"),
            ("@my_db.my_schema.my_stage/data", "my_db.my_schema.my_stage", "data"),
            # A '/' inside a quoted identifier belongs to the stage name, not
            # the sub-path; a naive split on the first '/' gets this wrong.
            ('@"My/Stage"/data', '"My/Stage"', "data"),
            ('@"My Stage"', '"My Stage"', ""),
        ],
    )
    def test_stage_and_sub_path_split_matches_the_grammar(self, path, stage, sub_path):
        """The regex is the single source of truth for matching and splitting."""
        info = get_cloud_path_info(path)
        assert info["stage_info"] == {"stage": stage, "sub_path": sub_path}
        assert info["bucket"] == stage
        assert info["path"] == sub_path


class TestStagePathHandler:
    """create_path_handler must never hand back a relative local directory."""

    @pytest.mark.parametrize("path", STAGE_PATHS)
    def test_handler_is_never_a_relative_path(self, path):
        """This is the property that makes the cwd spill structurally impossible."""
        handler = create_path_handler(path)
        assert not (isinstance(handler, Path) and not handler.is_absolute()), handler

    def test_handler_is_a_staging_path_carrying_the_stage_target(self):
        """Stages stage locally and keep the remote target for the adapter."""
        handler = create_path_handler("@~/benchbox")
        assert isinstance(handler, CloudStagingPath)
        assert handler.cloud_target == "@~/benchbox"
        assert Path(str(handler)).is_absolute()

    def test_resolving_a_stage_creates_no_directory_in_cwd(self, tmp_path, monkeypatch):
        """Regression for the 319 MB '@~/' spill: nothing lands under cwd."""
        monkeypatch.chdir(tmp_path)
        create_path_handler("@~/benchbox")
        assert not (tmp_path / "@~").exists()
        assert list(tmp_path.iterdir()) == []

    def test_stage_handler_does_not_require_cloudpathlib(self, monkeypatch):
        """cloudpathlib stays lazy: a stage path must not trigger the import."""
        import benchbox.utils.cloud_storage as cs

        def _fail():  # pragma: no cover - invoked only on regression
            raise AssertionError("cloudpathlib must not be loaded for stage paths")

        monkeypatch.setattr(cs, "_load_cloudpathlib", _fail)
        handler = cs.create_path_handler("@~/benchbox")
        assert isinstance(handler, CloudStagingPath)

    def test_stage_credential_validation_does_not_require_cloudpathlib(self, monkeypatch):
        """Credential validation follows the adapter-owned stage path too."""
        import benchbox.utils.cloud_storage as cs

        monkeypatch.setattr(cs, "_load_cloudpathlib", lambda: (_ for _ in ()).throw(AssertionError("must stay lazy")))

        result = validate_cloud_credentials("@~/benchbox")

        assert result["valid"] is True
        assert result["provider"] == "snowflake_stage"

    def test_local_paths_still_return_plain_paths(self):
        """Genuine local paths are untouched by the stage branch."""
        with tempfile.TemporaryDirectory() as tmp:
            assert create_path_handler(tmp) == Path(tmp)
        assert create_path_handler("./rel") == Path("./rel")
        assert create_path_handler(os.path.expanduser("~")) == Path(os.path.expanduser("~"))
