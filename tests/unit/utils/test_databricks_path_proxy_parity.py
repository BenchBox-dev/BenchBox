"""DatabricksPath must proxy a Path as completely as CloudStagingPath does.

``create_path_handler`` passes a ``DatabricksPath`` straight through, so a
Databricks run's ``benchmark.output_dir`` *is* one. It had no ``joinpath``, and
the runner reaches the datagen manifest through ``output_dir.joinpath(...)``
behind a ``hasattr(output_dir, "joinpath")`` guard. The result was not a crash
but two silent wrong answers for every Databricks run:

* ``_run_manifest_validation`` reported "Benchmark output directory not
  configured; cannot validate manifest" — false, it was configured;
* ``_read_datagen_stats_from_manifest`` returned ``{}``, so the result record
  carried no table/row/byte counts.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from benchbox.utils.cloud_storage import CloudStagingPath, DatabricksPath, create_path_handler

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# Every attribute the codebase reads off `output_dir`.
OUTPUT_DIR_ATTRS = ["exists", "glob", "is_dir", "joinpath", "mkdir", "parent", "resolve", "stat", "suffix"]


# The full TPC-H table set: manifest validation checks completeness, so a
# partial manifest fails for a real reason unrelated to the proxy surface.
TPCH_TABLES = ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"]
ROWS_PER_TABLE = 150
BYTES_PER_TABLE = 120


def _write_manifest(directory: Path) -> None:
    """Write a complete v1 datagen manifest for TPC-H."""
    tables = {}
    for name in TPCH_TABLES:
        data_file = directory / f"{name}.tbl"
        data_file.write_text("x" * BYTES_PER_TABLE)
        tables[name] = [{"path": str(data_file), "size_bytes": BYTES_PER_TABLE, "row_count": ROWS_PER_TABLE}]
    manifest = {
        "version": 1,
        "benchmark": "tpch",
        "scale_factor": 0.01,
        "tables": tables,
    }
    (directory / "_datagen_manifest.json").write_text(json.dumps(manifest))


class TestDatabricksPathProxySurface:
    """The wrapper must not be missing attributes its consumers rely on."""

    @pytest.mark.parametrize("attr", OUTPUT_DIR_ATTRS)
    def test_required_attribute_is_present(self, attr):
        """A missing attribute silently changes what the runner does."""
        assert hasattr(DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v"), attr), attr

    def test_surface_matches_cloud_staging_path(self):
        """The two staging wrappers must not drift apart again."""
        databricks = {m for m in dir(DatabricksPath) if not m.startswith("_")} - {"dbfs_target"}
        staging = {m for m in dir(CloudStagingPath) if not m.startswith("_")} - {"cloud_target"}
        assert databricks == staging

    def test_joinpath_matches_the_local_path(self):
        """The runner joins the manifest filename onto output_dir."""
        wrapper = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        assert wrapper.joinpath("_datagen_manifest.json") == Path("/tmp/cache/_datagen_manifest.json")

    def test_joinpath_agrees_with_truediv(self):
        """Two spellings of the same operation must not diverge."""
        wrapper = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        assert wrapper.joinpath("x") == wrapper / "x"

    def test_joinpath_accepts_multiple_components(self):
        """Parity with Path.joinpath's varargs signature."""
        wrapper = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        assert wrapper.joinpath("a", "b") == Path("/tmp/cache/a/b")

    def test_stat_reads_the_local_directory(self):
        """Disk-space probing calls stat() on the output dir."""
        with tempfile.TemporaryDirectory() as tmp:
            assert DatabricksPath(tmp, "dbfs:/x").stat().st_mode == Path(tmp).stat().st_mode

    def test_suffix_matches_the_local_path(self):
        """suffix is read off output_dir in the compare command."""
        assert DatabricksPath("/tmp/a/b.parquet", "dbfs:/x").suffix == ".parquet"


class TestDatabricksUploadContractUnchanged:
    """Must-preserve: this is the local proxy surface only."""

    def test_dbfs_target_is_untouched(self):
        """The upload destination still round-trips."""
        wrapper = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        assert wrapper.dbfs_target == "dbfs:/Volumes/c/s/v"
        assert create_path_handler(wrapper) is wrapper

    def test_dbfs_scheme_still_builds_a_databricks_path(self):
        """create_path_handler routing is unchanged."""
        handler = create_path_handler("dbfs:/Volumes/c/s/v")
        assert isinstance(handler, DatabricksPath)
        assert handler.dbfs_target == "dbfs:/Volumes/c/s/v"


class TestRunnerNoLongerMisreadsDatabricksOutput:
    """The two behaviours the missing attribute silently changed."""

    def test_datagen_stats_match_a_plain_path(self):
        """Previously {} for Databricks; now identical to every other handler."""
        from benchbox.core.runner.runner import _read_datagen_stats_from_manifest

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_manifest(directory)
            expected = {
                "tables_generated": len(TPCH_TABLES),
                "total_rows": len(TPCH_TABLES) * ROWS_PER_TABLE,
                "total_size_bytes": len(TPCH_TABLES) * BYTES_PER_TABLE,
            }

            for output_dir in (
                directory,
                DatabricksPath(directory, "dbfs:/Volumes/c/s/v"),
                CloudStagingPath(directory, "s3://bucket/p"),
            ):
                benchmark = SimpleNamespace(output_dir=output_dir)
                assert _read_datagen_stats_from_manifest(benchmark) == expected, type(output_dir).__name__

    def test_manifest_validation_no_longer_claims_the_dir_is_unconfigured(self):
        """The old error blamed configuration for a missing attribute."""
        from benchbox.core.config import BenchmarkConfig
        from benchbox.core.runner.runner import _run_manifest_validation

        with tempfile.TemporaryDirectory() as tmp:
            benchmark = SimpleNamespace(output_dir=DatabricksPath(tmp, "dbfs:/Volumes/c/s/v"))
            result = _run_manifest_validation(benchmark, BenchmarkConfig(name="tpch", display_name="TPC-H"))

            joined = " ".join(result.errors)
            assert "output directory not configured" not in joined
            # It now reports the real problem, naming the path it looked at.
            assert "_datagen_manifest.json" in joined

    def test_manifest_validation_passes_when_the_manifest_is_present(self):
        """Databricks runs actually validate now, rather than short-circuiting."""
        from benchbox.core.config import BenchmarkConfig
        from benchbox.core.runner.runner import _run_manifest_validation

        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            _write_manifest(directory)
            benchmark = SimpleNamespace(output_dir=DatabricksPath(directory, "dbfs:/Volumes/c/s/v"))

            result = _run_manifest_validation(benchmark, BenchmarkConfig(name="tpch", display_name="TPC-H"))

            assert result.is_valid, result.errors
