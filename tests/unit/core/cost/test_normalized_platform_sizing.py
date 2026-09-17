"""Cost extraction must read sizing from the normalized platform blocks.

Live Databricks and Snowflake runs published ``normalized_cost.deployment`` with
``warehouse_size: null`` and ``cluster_size: null`` while the same bundle's
``platform.compute`` block carried the observed ``2X-Small`` / ``X-Small``
warehouse. Two independent causes, both covered here:

* The v2 result builder stores the adapter's ``get_platform_info()`` mapping
  under ``platform_info["configuration"]``, so a top-level ``platform_type``
  read returned ``None`` and every run fell through to the generic branch. A
  bundle round-tripped through the loader has no ``platform_type`` at all,
  because the exported ``platform.config`` block drops it.
* Sizing was read from ``platform_info["compute_configuration"]``, which the
  builder never populates. ``platform.compute`` is where the normalized,
  provenance-stamped warehouse metadata actually lands.

Provenance matters as much as the value: the Databricks adapter falls back to
``cluster_size="Medium"`` whatever the warehouse is, so a value from a block
marked anything other than ``observed`` must stay out of a published total.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for
details.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from benchbox.core.cost.integration import (
    _extract_platform_config_from_results,
    add_cost_estimation_to_results,
    canonical_cost_platform_key,
)
from benchbox.core.results.models import BenchmarkResults

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _results(**overrides: object) -> BenchmarkResults:
    base: dict[str, object] = {
        "benchmark_name": "TPC-H",
        "platform": "Databricks",
        "scale_factor": 0.1,
        "execution_id": "deadbeef",
        "timestamp": datetime(2026, 9, 17, 13, 48, 51),
        "duration_seconds": 160.76,
        "total_queries": 22,
        "successful_queries": 22,
        "failed_queries": 0,
    }
    base.update(overrides)
    return BenchmarkResults(**base)  # type: ignore[arg-type]


class TestCanonicalPlatformKey:
    def test_reads_platform_type_nested_under_configuration(self) -> None:
        """The v2 builder leaves platform_type one level down, not at the top."""
        results = _results(
            platform_info={"platform_name": "Databricks", "configuration": {"platform_type": "databricks"}}
        )
        assert canonical_cost_platform_key(results) == "databricks"

    def test_falls_back_to_display_name_when_no_platform_type_survives(self) -> None:
        """A loader-reconstructed bundle carries only the display name."""
        results = _results(platform="Databricks", platform_info={"name": "Databricks"})
        assert canonical_cost_platform_key(results) == "databricks"

    @pytest.mark.parametrize(
        ("display_name", "expected"),
        [
            ("ClickHouse Local", "clickhouse-local"),
            ("ClickHouse Server", "clickhouse-server"),
            ("Snowflake", "snowflake"),
            ("DuckDB (DataFrame)", "duckdb"),
            ("azure_synapse", "synapse"),
            ("fabric-dw", "fabric_dw"),
        ],
    )
    def test_normalizes_display_names_to_registry_keys(self, display_name: str, expected: str) -> None:
        assert canonical_cost_platform_key(_results(platform=display_name)) == expected


class TestLocalPlatformClassification:
    def test_clickhouse_local_is_classified_as_local_not_a_cloud_run(self) -> None:
        """ "ClickHouse Local".lower() never matched the "clickhouse-local" key.

        Every published ClickHouse bundle therefore carried
        ``cost_status="unavailable"`` plus a fabricated ``aws`` / ``us-east-1``
        deployment for an engine with no cloud cost at all.
        """
        results = _results(platform="ClickHouse Local", platform_info={"name": "ClickHouse Local"})
        add_cost_estimation_to_results(results)

        normalized = (results.cost_summary or {})["normalized_cost"]
        assert normalized["cost_status"] == "not_applicable_local"
        assert normalized["billing_unit"] == "not_applicable"
        assert normalized["deployment"]["cloud_provider"] is None
        assert normalized["deployment"]["cloud_region"] is None


class TestDatabricksSizingFromNormalizedCompute:
    def test_observed_warehouse_size_reaches_the_cost_model(self) -> None:
        results = _results(
            platform_info={"name": "Databricks", "configuration": {"platform_type": "databricks"}},
            platform_compute={
                "warehouse_size": "2X-Small",
                "warehouse_type": "SERVERLESS",
                "source": "observed",
                "collection_status": "available",
            },
        )

        config = _extract_platform_config_from_results(results)

        assert config["warehouse_size"] == "2X-Small"
        assert config["cluster_size_dbu_per_hour"] == 1.0
        assert config["workload_type"] == "serverless_sql"
        assert "warehouse_size" not in config.get("_defaulted_fields", [])

    def test_requested_warehouse_size_is_used_but_marked_defaulted(self) -> None:
        """A "requested" size is the adapter's "Medium" constructor default.

        It is still worth a rough per-query estimate, but it must not back a
        published total, so it lands in ``_defaulted_fields``.
        """
        results = _results(
            platform_info={"name": "Databricks", "configuration": {"platform_type": "databricks"}},
            platform_compute={
                "warehouse_size": "Medium",
                "source": "requested",
                "collection_status": "partial",
            },
        )

        config = _extract_platform_config_from_results(results)

        assert config["warehouse_size"] == "Medium"
        assert config["cluster_size_dbu_per_hour"] == 8.0
        assert "warehouse_size" in config["_defaulted_fields"]

    def test_published_deployment_carries_the_observed_size(self) -> None:
        results = _results(
            platform_info={"name": "Databricks", "configuration": {"platform_type": "databricks"}},
            platform_cloud={"provider": "aws", "region": "us-east-1", "source": "observed"},
            platform_compute={
                "warehouse_size": "2X-Small",
                "warehouse_type": "SERVERLESS",
                "source": "observed",
                "collection_status": "available",
            },
        )
        add_cost_estimation_to_results(results)

        deployment = (results.cost_summary or {})["normalized_cost"]["deployment"]
        assert deployment["warehouse_size"] == "2X-Small"
        assert deployment["cluster_size"] == "1.0"
        assert deployment["cloud_region"] == "us-east-1"


class TestSnowflakeSizingFromNormalizedCompute:
    def test_observed_warehouse_size_reaches_the_cost_model(self) -> None:
        results = _results(
            platform="Snowflake",
            platform_info={"name": "Snowflake", "configuration": {"platform_type": "snowflake"}},
            platform_compute={
                "warehouse_size": "X-Small",
                "source": "observed",
                "collection_status": "available",
            },
        )

        config = _extract_platform_config_from_results(results)

        assert config["warehouse_size"] == "X-Small"
        assert "warehouse_size" not in config.get("_defaulted_fields", [])


class TestRegionIsNeverInvented:
    def test_unobserved_region_stays_absent_from_the_published_deployment(self) -> None:
        """No observed region anywhere: the field must publish as null.

        ``platform.cloud`` on a live Databricks run carries
        ``region_collection_status: "unavailable"``, and a Snowflake run carries
        no region key at all -- yet both bundles published
        ``pricing_region: "us-east-1"``.
        """
        results = _results(
            platform_info={"name": "Databricks", "configuration": {"platform_type": "databricks"}},
            platform_cloud={
                "provider": "aws",
                "region_collection_status": "unavailable",
                "source": "inferred",
            },
            platform_compute={
                "warehouse_size": "2X-Small",
                "source": "observed",
                "collection_status": "available",
            },
        )
        add_cost_estimation_to_results(results)

        normalized = (results.cost_summary or {})["normalized_cost"]
        assert normalized["deployment"]["cloud_region"] is None
        assert normalized["cost_status"] == "unavailable"
        # The observed size still survives alongside the honest region gap.
        assert normalized["deployment"]["warehouse_size"] == "2X-Small"
