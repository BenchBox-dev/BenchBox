"""w2 regression: _extract_platform_config_from_results must extract
``cloud`` and ``region`` for cloud platform_types beyond the four explicitly-
branched cases (snowflake, bigquery, redshift, databricks).

Without a generic fallback, adapters that emit ``platform_type="athena"`` or
``"azure_synapse"`` (and future cloud adapters) fall through with no
region/cloud fields, so ``calculate_normalized_benchmark_cost`` warns
``pricing region metadata missing`` and forces ``cost_status="unavailable"``,
blocking public cost totals in submission validation even when the adapter
populated ``platform_info``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.cost.integration import _extract_platform_config_from_results

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _results_with(platform_info: dict[str, object]) -> SimpleNamespace:
    return SimpleNamespace(platform_info=platform_info)


class TestGenericCloudRegionFallback:
    def test_athena_extracts_cloud_aws_and_region_from_platform_info(self) -> None:
        config = _extract_platform_config_from_results(
            _results_with(
                {
                    "platform_type": "athena",
                    "cloud_provider": "aws",
                    "region": "us-west-2",
                }
            )
        )
        assert config["platform_type"] == "athena"
        assert config["cloud"] == "aws"
        assert config["region"] == "us-west-2"
        assert "_defaulted_fields" not in config

    def test_athena_falls_back_to_aws_default_when_cloud_missing(self) -> None:
        config = _extract_platform_config_from_results(_results_with({"platform_type": "athena"}))
        assert config["cloud"] == "aws"
        assert config["region"] == "us-east-1"
        assert config["_defaulted_fields"] == ["cloud", "region"]

    def test_azure_synapse_extracts_azure_cloud(self) -> None:
        config = _extract_platform_config_from_results(
            _results_with(
                {
                    "platform_type": "azure_synapse",
                    "region": "westeurope",
                }
            )
        )
        assert config["cloud"] == "azure"
        assert config["region"] == "westeurope"
        # cloud_provider was missing; gets defaulted via the generic branch.
        assert "cloud" in config["_defaulted_fields"]

    def test_azure_synapse_default_region_when_missing(self) -> None:
        config = _extract_platform_config_from_results(_results_with({"platform_type": "azure_synapse"}))
        assert config["cloud"] == "azure"
        assert config["region"] == "eastus"

    def test_existing_snowflake_branch_still_runs(self) -> None:
        """Sanity check: the new generic branch is in the `else` clause so the
        existing per-platform branches still take precedence."""
        config = _extract_platform_config_from_results(
            _results_with(
                {
                    "platform_type": "snowflake",
                    "cloud_provider": "aws",
                    "region": "us-east-1",
                    "edition": "enterprise",
                    "configuration": {"warehouse_size": "MEDIUM"},
                }
            )
        )
        assert config["platform_type"] == "snowflake"
        assert config["edition"] == "enterprise"
        assert config["warehouse_size"] == "MEDIUM"
        assert config["cloud"] == "aws"
        assert config["region"] == "us-east-1"
