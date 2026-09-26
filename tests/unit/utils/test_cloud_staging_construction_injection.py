"""Benchmark constructors must not stringify cloud staging handlers.

Several benchmarks stored the orchestrator-resolved ``output_dir`` via
``Path(...)``. A ``CloudStagingPath``/``DatabricksPath`` stringifies to its
local cache directory, so the cloud upload target resolved at construction
time was silently discarded: datagen ran locally and the adapter never
learned the remote destination. These tests pin the construction-time
injection edge: passing an already-built handler into each benchmark keeps
the handler (and its target) intact, while plain strings still become
``Path``.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from pathlib import Path

import pytest

from benchbox.utils.cloud_storage import (
    CloudStagingPath,
    DatabricksPath,
    normalize_output_dir,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestNormalizeOutputDir:
    """The shared coercion used by the converted constructors."""

    def test_none_stays_none(self):
        """None means not configured yet; the runner rejects it later."""
        assert normalize_output_dir(None) is None

    def test_cloud_staging_handler_passes_through(self):
        """The defect: Path(...) would reduce this to its local cache."""
        staging = CloudStagingPath("/tmp/cache", "s3://bucket/benchbox")
        assert normalize_output_dir(staging) is staging

    def test_databricks_handler_passes_through(self):
        """Same edge for the Databricks wrapper."""
        staging = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        assert normalize_output_dir(staging) is staging

    def test_plain_path_passes_through(self):
        """Local runs keep their existing behaviour."""
        local = Path("/tmp/cache")
        assert normalize_output_dir(local) is local

    def test_plain_string_becomes_path(self):
        """Strings still coerce to Path."""
        result = normalize_output_dir("/tmp/cache")
        assert result == Path("/tmp/cache")
        assert isinstance(result, Path)


class TestBenchmarkConstructorsPreserveHandlers:
    """Each converted benchmark keeps the handler it is constructed with."""

    @staticmethod
    def _staging():
        return CloudStagingPath("/tmp/cache", "s3://bucket/benchbox")

    def test_ai_primitives(self):
        """AIPrimitivesBenchmark reuses TPC-H data under cloud staging."""
        from benchbox.core.ai_primitives.benchmark import AIPrimitivesBenchmark

        staging = self._staging()
        benchmark = AIPrimitivesBenchmark(scale_factor=0.01, output_dir=staging)
        assert benchmark.output_dir is staging

    def test_datavault(self):
        """DataVaultBenchmark must not reduce the handler to Path."""
        from benchbox.core.datavault.benchmark import DataVaultBenchmark

        staging = self._staging()
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=staging)
        assert benchmark.output_dir is staging

    def test_tpcds_obt(self):
        """TPCDSOBTBenchmark keeps both the OBT and source handlers."""
        from benchbox.core.tpcds_obt.benchmark import TPCDSOBTBenchmark

        staging = self._staging()
        source = CloudStagingPath("/tmp/tpcds", "s3://bucket/tpcds")
        benchmark = TPCDSOBTBenchmark(scale_factor=1.0, output_dir=staging, tpcds_source_dir=source)
        assert benchmark.output_dir is staging
        assert benchmark.tpcds_source_dir is source

    def test_transaction_primitives(self):
        """TransactionPrimitivesBenchmark forwards the handler to its generator."""
        from benchbox.core.transaction_primitives.benchmark import TransactionPrimitivesBenchmark

        staging = self._staging()
        benchmark = TransactionPrimitivesBenchmark(scale_factor=0.01, output_dir=staging)
        assert benchmark.output_dir is staging

    def test_write_primitives(self):
        """WritePrimitivesBenchmark forwards the handler to its generator."""
        from benchbox.core.write_primitives.benchmark import WritePrimitivesBenchmark

        staging = self._staging()
        benchmark = WritePrimitivesBenchmark(scale_factor=0.01, output_dir=staging)
        assert benchmark.output_dir is staging

    def test_tpcdi_config(self):
        """TPCDIConfig post-init must not reduce the handler to Path."""
        from benchbox.core.tpcdi.config import TPCDIConfig

        staging = self._staging()
        config = TPCDIConfig(scale_factor=1.0, output_dir=staging)
        assert config.output_dir is staging

    def test_tpch_skew_generator(self):
        """TPCHSkewDataGenerator keeps the handler for its file layout."""
        from benchbox.core.tpch_skew.generator import TPCHSkewDataGenerator

        staging = self._staging()
        generator = TPCHSkewDataGenerator(scale_factor=0.01, output_dir=staging)
        assert generator.output_dir is staging

    def test_tsbs_devops_generator(self):
        """TSBSDevOpsDataGenerator keeps the handler for its file layout."""
        from benchbox.core.tsbs_devops.generator import TSBSDevOpsDataGenerator

        staging = self._staging()
        generator = TSBSDevOpsDataGenerator(scale_factor=0.01, output_dir=staging)
        assert generator.output_dir is staging

    def test_databricks_target_survives_construction(self):
        """The Databricks target must reach the adapter, not just the type."""
        from benchbox.core.datavault.benchmark import DataVaultBenchmark

        staging = DatabricksPath("/tmp/cache", "dbfs:/Volumes/c/s/v")
        benchmark = DataVaultBenchmark(scale_factor=0.01, output_dir=staging)
        assert benchmark.output_dir.dbfs_target == "dbfs:/Volumes/c/s/v"
