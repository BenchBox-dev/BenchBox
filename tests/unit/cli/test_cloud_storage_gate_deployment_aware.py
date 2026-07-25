"""The run-path cloud-storage gates follow the deployment, not the category.

``requires_cloud_storage()`` answers a *platform category* question, so
firebolt (whose default deployment is the local Core container), motherduck and
starburst all answer True even though their default deployment stages nothing
through cloud storage. Gating the run path on that answer pulled a cloud output
location into runs that never needed one.

These tests are driven from the registry rather than a hardcoded platform list,
so they keep holding when a platform's ``deployment_modes`` block is edited.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import ast
import inspect
from pathlib import Path

import pytest

from benchbox.cli import orchestrator as orchestrator_module
from benchbox.cli.orchestrator import resolved_deployment_mode
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.core.schemas import DatabaseConfig

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _all_platforms() -> list[str]:
    """Every registered platform name, straight from the registry."""
    PlatformRegistry._platform_metadata = PlatformRegistry._platform_metadata or (
        PlatformRegistry._build_platform_metadata()
    )
    return sorted(PlatformRegistry._platform_metadata)


ALL_PLATFORMS = _all_platforms()

# Run-path modules whose cloud-storage gates must all be deployment-aware.
RUN_PATH_SOURCES = [
    Path(inspect.getfile(orchestrator_module)),
    Path(inspect.getfile(orchestrator_module)).parent / "commands" / "run.py",
]


class TestRunPathGateMatchesDeployment:
    """The gate answer must equal the deployment-aware registry answer."""

    @pytest.mark.parametrize("platform", ALL_PLATFORMS)
    def test_gate_matches_deployment_answer_for_every_platform(self, platform):
        """For each platform's default deployment, the gate agrees with the registry."""
        expected = PlatformRegistry.requires_cloud_storage_for_deployment(platform)
        # The run path calls the same helper with the run's resolved mode; with
        # no explicit deployment_mode that is None, i.e. the default deployment.
        config = DatabaseConfig(type=platform, name=platform)
        actual = PlatformRegistry.requires_cloud_storage_for_deployment(platform, resolved_deployment_mode(config))
        assert actual == expected, platform

    def test_known_divergence_is_still_exactly_the_three_platforms(self):
        """Pins the premise: category and deployment answers differ for these only.

        If this list changes, a platform's deployment_modes block moved and the
        gate's behaviour changed with it — which is the point of gating on the
        registry rather than a hardcoded skip-list.
        """
        diverging = {
            name
            for name in ALL_PLATFORMS
            if PlatformRegistry.requires_cloud_storage(name)
            != PlatformRegistry.requires_cloud_storage_for_deployment(name)
        }
        assert diverging == {"firebolt", "motherduck", "starburst"}, sorted(diverging)

    @pytest.mark.parametrize("platform", ["firebolt", "motherduck", "starburst"])
    def test_locally_deploying_cloud_platforms_are_not_gated_as_cloud(self, platform):
        """The defect: these are cloud-category but do not stage remotely by default."""
        assert PlatformRegistry.requires_cloud_storage(platform) is True
        assert PlatformRegistry.requires_cloud_storage_for_deployment(platform) is False

    @pytest.mark.parametrize("platform", ["snowflake", "bigquery", "databricks", "redshift", "athena", "synapse"])
    def test_genuinely_remote_platforms_keep_pulling_their_default(self, platform):
        """Must-preserve: platforms that really stage remotely are unaffected."""
        if platform not in ALL_PLATFORMS:
            pytest.skip(f"{platform} is not registered")
        assert PlatformRegistry.requires_cloud_storage_for_deployment(platform) is True


class TestResolvedDeploymentMode:
    """The run's deployment mode is threaded when the run selected one."""

    def test_explicit_deployment_mode_is_threaded(self):
        """An explicit platform option reaches the registry call."""
        config = DatabaseConfig(type="clickhouse", name="ch", options={"deployment_mode": "local"})
        assert resolved_deployment_mode(config) == "local"

    def test_missing_deployment_mode_means_platform_default(self):
        """No explicit mode resolves to None so the registry uses the default."""
        assert resolved_deployment_mode(DatabaseConfig(type="duckdb", name="d")) is None

    def test_empty_deployment_mode_means_platform_default(self):
        """An empty string must not be threaded as a real mode."""
        config = DatabaseConfig(type="duckdb", name="d", options={"deployment_mode": ""})
        assert resolved_deployment_mode(config) is None

    def test_missing_config_is_tolerated(self):
        """A None database_config resolves to the default, never raises."""
        assert resolved_deployment_mode(None) is None

    def test_threaded_mode_can_flip_the_gate(self):
        """Selecting a cloud-storage deployment re-enables the gate."""
        assert PlatformRegistry.requires_cloud_storage_for_deployment("firebolt") is False
        assert PlatformRegistry.requires_cloud_storage_for_deployment("firebolt", "cloud") is True


class TestNoCategoryGatesRemainOnTheRunPath:
    """No run-path gate may still call the category-level check.

    A leftover category gate is what makes the interactive flow incoherent:
    cloud setup is skipped, the local-output prompt is skipped too, and the run
    then hard-errors demanding --output with no way to supply it.
    """

    @pytest.mark.parametrize("source", RUN_PATH_SOURCES, ids=lambda p: p.name)
    def test_run_path_never_calls_requires_cloud_storage_directly(self, source):
        """Every gate in these modules uses the deployment-aware variant."""
        tree = ast.parse(source.read_text())
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute) and node.attr == "requires_cloud_storage"
        ]
        assert not offenders, f"{source.name} still gates on requires_cloud_storage at lines {offenders}"
