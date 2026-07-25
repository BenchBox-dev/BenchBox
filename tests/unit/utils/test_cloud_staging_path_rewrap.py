"""A CloudStagingPath must survive being handed back to create_path_handler.

``create_path_handler`` passes ``DatabricksPath`` through explicitly to avoid
double-wrapping, but had no equivalent guard for ``CloudStagingPath``. One fell
through to the local branch and was rebuilt as a plain ``Path`` of the staging
directory, silently discarding ``cloud_target`` — so a handler that had been
carrying its upload destination stopped doing so the moment anything re-wrapped
it (the benchmark ``output_dir`` setter does exactly that).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path

import pytest

from benchbox.utils.cloud_storage import (
    CloudStagingPath,
    DatabricksPath,
    create_path_handler,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Remote targets that reach CloudStagingPath through the orchestrator.
REMOTE_TARGETS = [
    "s3://bucket/benchbox",
    "gs://bucket/benchbox",
    "az://container/benchbox",
    "abfss://container@account.dfs.core.windows.net/benchbox",
    "@~/benchbox",
]


class TestRewrapPreservesCloudTarget:
    """The defect: re-wrapping dropped the upload destination."""

    @pytest.mark.parametrize("target", REMOTE_TARGETS)
    def test_rewrap_returns_the_same_object(self, target):
        """Pass-through, matching the DatabricksPath guard."""
        staging = CloudStagingPath("/tmp/cache", target)
        assert create_path_handler(staging) is staging

    @pytest.mark.parametrize("target", REMOTE_TARGETS)
    def test_rewrap_keeps_cloud_target(self, target):
        """The upload destination must survive the round trip."""
        staging = CloudStagingPath("/tmp/cache", target)
        assert create_path_handler(staging).cloud_target == target

    def test_rewrap_is_idempotent(self):
        """Repeated wrapping must not degrade or re-allocate."""
        staging = CloudStagingPath("/tmp/cache", "s3://bucket/p")
        assert create_path_handler(create_path_handler(staging)) is staging

    def test_rewrap_does_not_downgrade_to_a_plain_path(self):
        """The old behaviour returned PosixPath('/tmp/cache')."""
        staging = CloudStagingPath("/tmp/cache", "s3://bucket/p")
        result = create_path_handler(staging)
        assert not isinstance(result, Path)
        assert isinstance(result, CloudStagingPath)

    def test_databricks_passthrough_is_unchanged(self):
        """The behaviour this fix mirrors must keep working."""
        databricks = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        assert create_path_handler(databricks) is databricks


class TestStagingPathIsAFaithfulPathProxy:
    """Consumers that used to get a plain Path must keep working.

    The full set of attributes the codebase reads off ``output_dir`` is
    exists / glob / is_dir / joinpath / mkdir / parent / resolve / stat /
    suffix. Everything there must exist on CloudStagingPath now that one can
    reach those consumers directly.
    """

    REQUIRED_ATTRS = ["exists", "glob", "is_dir", "joinpath", "mkdir", "parent", "resolve", "stat", "suffix"]

    @pytest.mark.parametrize("attr", REQUIRED_ATTRS)
    def test_required_attribute_is_present(self, attr):
        """A missing attribute is an AttributeError in the runner."""
        assert hasattr(CloudStagingPath("/tmp/cache", "s3://b/p"), attr), attr

    def test_joinpath_matches_the_local_path(self):
        """The runner joins the datagen manifest onto output_dir."""
        staging = CloudStagingPath("/tmp/cache", "s3://b/p")
        assert staging.joinpath("_datagen_manifest.json") == Path("/tmp/cache/_datagen_manifest.json")

    def test_joinpath_accepts_multiple_components(self):
        """Parity with Path.joinpath's varargs signature."""
        staging = CloudStagingPath("/tmp/cache", "s3://b/p")
        assert staging.joinpath("a", "b") == Path("/tmp/cache/a/b")

    def test_joinpath_agrees_with_truediv(self):
        """Two spellings of the same operation must not diverge."""
        staging = CloudStagingPath("/tmp/cache", "s3://b/p")
        assert staging.joinpath("x") == staging / "x"

    def test_manifest_validation_is_not_silently_skipped(self):
        """runner.py guards on hasattr(output_dir, 'joinpath').

        Without joinpath the guard short-circuits and manifest validation is
        skipped without a word — a silent loss of checking, not a crash.
        """
        assert hasattr(CloudStagingPath("/tmp/cache", "s3://b/p"), "joinpath")

    def test_stat_reads_the_local_directory(self):
        """Disk-space probing calls stat() on the output dir."""
        with tempfile.TemporaryDirectory() as tmp:
            staging = CloudStagingPath(tmp, "s3://b/p")
            assert staging.stat().st_mode == Path(tmp).stat().st_mode

    def test_suffix_matches_the_local_path(self):
        """suffix is read off output_dir in the compare command."""
        assert CloudStagingPath("/tmp/a/b.parquet", "s3://b/p").suffix == ".parquet"

    def test_local_delegation_still_works_after_rewrap(self):
        """A re-wrapped handler is still usable for filesystem work."""
        with tempfile.TemporaryDirectory() as tmp:
            staging = create_path_handler(CloudStagingPath(Path(tmp) / "out", "s3://b/p"))
            staging.mkdir()
            assert staging.exists()
            assert staging.is_dir()
