"""_extract_platform_config_from_results must resolve ``cloud`` and ``region``
for cloud platforms beyond the four explicitly-branched cases (snowflake,
bigquery, redshift, databricks), and must not invent either value.

Adapters that emit ``platform_type="athena"`` or ``"azure_synapse"`` populate
``platform_info`` with ``region`` and ``cloud_provider``; those reads must
survive. Where they are absent the two fields part company:

* ``cloud`` is still resolved for a single-cloud platform, because the provider
  is a property of the platform rather than an observation about the run --
  Athena is AWS and Synapse is Azure whatever the run reported. The cost
  calculator's own ``_deployment_metadata`` already applies the same map.
* ``region`` is not resolved. A regional default cannot be derived from
  anything, and it never unblocked a cost total either: every
  ``_defaulted_fields`` entry becomes a normalized-cost warning and any warning
  forces ``cost_status="unavailable"``. The old ``us-east-1`` default therefore
  bought nothing and published a deployment region the run never observed.
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

    def test_athena_resolves_aws_from_platform_identity_and_omits_region(self) -> None:
        config = _extract_platform_config_from_results(_results_with({"platform_type": "athena"}))
        # Athena only exists on AWS, so the provider is known without observing it.
        assert config["cloud"] == "aws"
        # The region was never observed and must not be invented.
        assert "region" not in config
        assert config["_defaulted_fields"] == ["region"]

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
        # Both fields resolved truthfully, so nothing is marked defaulted and a
        # cost total stays eligible.
        assert "_defaulted_fields" not in config

    def test_azure_synapse_omits_region_when_missing(self) -> None:
        config = _extract_platform_config_from_results(_results_with({"platform_type": "azure_synapse"}))
        assert config["cloud"] == "azure"
        assert "region" not in config
        assert config["_defaulted_fields"] == ["region"]

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
