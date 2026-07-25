"""The Snowflake output-location sources must agree with the run-path classifier.

The credential prompt advertised ``@~/benchbox`` as its default while
``get_cloud_path_examples("snowflake")`` listed only ``s3://``/``azure://``/
``gcs://``. A user who accepted the advertised default therefore stored a value
the documented examples never mentioned — and, before the stage-classification
fix, one the run path treated as a *local relative directory*.

These tests pin the agreement between the three sources so they cannot drift
apart again: the prompt's default, the registry's examples, and
``is_cloud_path`` (the classifier the run path actually gates on).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import inspect
from pathlib import Path

import pytest

from benchbox.core.platform_registry import SNOWFLAKE_DEFAULT_OUTPUT_LOCATION, PlatformRegistry
from benchbox.utils.cloud_storage import create_path_handler, is_cloud_path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


SNOWFLAKE_EXAMPLES = PlatformRegistry.get_cloud_path_examples("snowflake")


class TestPromptDefaultIsAcceptedByTheRunPath:
    """Whatever the prompt suggests must survive the run path's classifier."""

    def test_prompt_default_classifies_as_cloud(self):
        """The advertised default must not resolve to a local directory."""
        assert is_cloud_path(SNOWFLAKE_DEFAULT_OUTPUT_LOCATION)

    def test_prompt_default_never_becomes_a_relative_local_path(self):
        """The spill mode: a relative handler would write under cwd."""
        handler = create_path_handler(SNOWFLAKE_DEFAULT_OUTPUT_LOCATION)
        assert not (isinstance(handler, Path) and not handler.is_absolute()), handler

    def test_prompt_default_is_offered_as_a_registry_example(self):
        """The two sources name the same value, not merely compatible ones."""
        assert SNOWFLAKE_DEFAULT_OUTPUT_LOCATION in SNOWFLAKE_EXAMPLES

    def test_prompt_default_is_listed_first(self):
        """User stage leads, matching the prompt's 'Recommended' framing."""
        assert SNOWFLAKE_EXAMPLES[0] == SNOWFLAKE_DEFAULT_OUTPUT_LOCATION


class TestRegistryExamplesAreAllUsable:
    """Every documented example must be accepted by the same classifier."""

    @pytest.mark.parametrize("example", SNOWFLAKE_EXAMPLES)
    def test_every_snowflake_example_classifies_as_cloud(self, example):
        """An example the run path would treat as local is a documentation bug."""
        assert is_cloud_path(example), example

    @pytest.mark.parametrize("example", SNOWFLAKE_EXAMPLES)
    def test_no_example_resolves_to_a_relative_local_path(self, example):
        """No advertised value may put generated data under the cwd.

        The ``azure://`` and ``gcs://`` examples used to raise here, because
        cloudpathlib only registers ``az://`` / ``gs://`` / ``s3://``. The
        scheme aliases are now normalised at the hand-off, so every advertised
        example resolves and the raise no longer needs tolerating.
        """
        handler = create_path_handler(example)
        assert not (isinstance(handler, Path) and not handler.is_absolute()), (example, handler)

    def test_examples_still_cover_external_stages(self):
        """Must-preserve: external stage URIs remain valid output locations."""
        schemes = {e.split("://")[0] for e in SNOWFLAKE_EXAMPLES if "://" in e}
        assert {"s3", "azure", "gcs"} <= schemes, schemes


class TestPromptUsesTheSharedSources:
    """The prompt must derive from the registry rather than duplicating it."""

    def _prompt_source(self) -> str:
        from benchbox.platforms.credentials import snowflake as snowflake_credentials

        return inspect.getsource(snowflake_credentials._prompt_default_output_location)

    def test_prompt_defaults_to_the_shared_constant(self):
        """A duplicated literal is what let the two sides drift apart."""
        source = self._prompt_source()
        assert "SNOWFLAKE_DEFAULT_OUTPUT_LOCATION" in source
        assert 'default="@~/benchbox"' not in source

    def test_prompt_renders_examples_from_the_registry(self):
        """Example bullets come from get_cloud_path_examples, not hardcoded text."""
        source = self._prompt_source()
        assert 'get_cloud_path_examples("snowflake")' in source

    def test_prompt_validates_with_the_run_path_classifier(self):
        """The old startswith('@~') check was narrower than is_cloud_path.

        It rejected named, table and qualified stage forms that the run path
        accepts, so the prompt could refuse a value the run path would honour.
        """
        source = self._prompt_source()
        assert "is_cloud_path(" in source
        assert 'startswith("@~")' not in source


class TestOutputDirectoryConfigKeyIsGone:
    """The dead ``output.directory`` key must not come back."""

    def test_default_config_has_no_output_directory_key(self):
        """A key nothing reads makes users believe runs go somewhere they do not."""
        from benchbox.cli.config import ConfigManager

        default_config = ConfigManager._get_default_config(ConfigManager.__new__(ConfigManager))
        assert "directory" not in default_config.output

    def test_output_dir_env_var_is_not_mapped_into_config(self):
        """BENCHBOX_OUTPUT_DIR is resolved on the run path, not via config."""
        from benchbox.cli import config as config_module

        source = inspect.getsource(config_module)
        assert '"BENCHBOX_OUTPUT_DIR": ("output", "directory", str)' not in source

    def test_legacy_config_containing_the_key_still_loads(self, tmp_path):
        """Must-preserve: an older config file must not raise after removal."""
        import yaml

        from benchbox.cli.config import ConfigManager

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            yaml.safe_dump(
                {
                    "output": {"formats": ["json"], "directory": "./benchmark_runs/results"},
                    "database": {"preferred": "duckdb"},
                }
            )
        )

        manager = ConfigManager(config_path=config_path)

        # Loaded without raising, and the unknown key is carried through rather
        # than dropped, so nothing a user wrote is silently discarded.
        assert manager.config.output["directory"] == "./benchmark_runs/results"
        assert manager.config.database["preferred"] == "duckdb"
