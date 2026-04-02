"""Behavioral tests for DataFrame tuning configuration loader.

Tests targeting coverage gaps in tuning/loader.py:
- YAML/JSON config loading with real temp files
- Default merging via merge_configs and _deep_merge
- Template generation for all platforms
- Optimized and memory-constrained templates
- Save/load roundtrip with metadata
- Error paths: unsupported format, invalid config, save errors
- Convenience module-level functions

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    DataFrameTuningLoader,
    DataFrameTuningLoadError,
    DataFrameTuningSaveError,
    ExecutionConfiguration,
    MemoryConfiguration,
    ParallelismConfiguration,
    TuningMetadata,
    load_dataframe_tuning,
    save_dataframe_tuning,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# File format handling
# ---------------------------------------------------------------------------


class TestLoaderFileFormats:
    """Tests for loading different file formats."""

    def test_load_yml_extension(self, tmp_path):
        """YML extension (in addition to YAML) is supported."""
        config_path = tmp_path / "config.yml"
        with open(config_path, "w") as fh:
            yaml.dump({"parallelism": {"thread_count": 12}}, fh)

        loader = DataFrameTuningLoader()
        config = loader.load_config(config_path)

        assert config.parallelism.thread_count == 12

    def test_load_json_with_multiple_sections(self, tmp_path):
        """JSON file with multiple configuration sections loads correctly."""
        config_path = tmp_path / "config.json"
        data = {
            "parallelism": {"thread_count": 4, "worker_count": 2},
            "execution": {"streaming_mode": True, "lazy_evaluation": False},
            "memory": {"spill_to_disk": True},
        }
        with open(config_path, "w") as fh:
            json.dump(data, fh)

        loader = DataFrameTuningLoader()
        config = loader.load_config(config_path)

        assert config.parallelism.thread_count == 4
        assert config.parallelism.worker_count == 2
        assert config.execution.streaming_mode is True
        assert config.execution.lazy_evaluation is False
        assert config.memory.spill_to_disk is True

    def test_load_unsupported_extension_raises(self, tmp_path):
        """Unsupported file extension raises DataFrameTuningLoadError."""
        config_path = tmp_path / "config.toml"
        config_path.write_text("[parallelism]\nthread_count = 8\n")

        loader = DataFrameTuningLoader()
        with pytest.raises(DataFrameTuningLoadError, match="Unsupported file format"):
            loader.load_config(config_path)

    def test_load_empty_yaml_returns_default_config(self, tmp_path):
        """Empty YAML file returns default configuration."""
        config_path = tmp_path / "empty.yaml"
        config_path.write_text("")

        loader = DataFrameTuningLoader()
        config = loader.load_config(config_path)

        assert config.is_default() or config.metadata is None

    def test_save_unsupported_extension_raises(self, tmp_path):
        """Saving to unsupported extension raises DataFrameTuningSaveError."""
        config_path = tmp_path / "output.toml"
        config = DataFrameTuningConfiguration()

        loader = DataFrameTuningLoader()
        with pytest.raises(DataFrameTuningSaveError, match="Unsupported file format"):
            loader.save_config(config, config_path)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestLoaderErrorPaths:
    """Tests for loader error handling."""

    def test_file_not_found(self):
        """FileNotFoundError raised for missing file."""
        loader = DataFrameTuningLoader()
        with pytest.raises(FileNotFoundError, match="not found"):
            loader.load_config("/nonexistent/path/config.yaml")

    def test_invalid_yaml_raises_load_error(self, tmp_path):
        """Malformed YAML raises DataFrameTuningLoadError."""
        config_path = tmp_path / "bad.yaml"
        config_path.write_text("invalid: yaml: [unclosed")

        loader = DataFrameTuningLoader()
        with pytest.raises(DataFrameTuningLoadError, match="parse"):
            loader.load_config(config_path)

    def test_invalid_json_raises_load_error(self, tmp_path):
        """Malformed JSON raises DataFrameTuningLoadError."""
        config_path = tmp_path / "bad.json"
        config_path.write_text("{invalid json")

        loader = DataFrameTuningLoader()
        with pytest.raises(DataFrameTuningLoadError, match="parse"):
            loader.load_config(config_path)

    def test_string_path_converted_to_path(self, tmp_path):
        """String path argument is accepted and converted."""
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as fh:
            yaml.dump({"parallelism": {"thread_count": 6}}, fh)

        loader = DataFrameTuningLoader()
        config = loader.load_config(str(config_path))
        assert config.parallelism.thread_count == 6


# ---------------------------------------------------------------------------
# Save and roundtrip
# ---------------------------------------------------------------------------


class TestLoaderSaveRoundtrip:
    """Tests for save/load roundtrip integrity."""

    def test_yaml_roundtrip_preserves_values(self, tmp_path):
        """YAML save/load roundtrip preserves all configuration values."""
        config_path = tmp_path / "roundtrip.yaml"
        original = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=16, worker_count=4),
            execution=ExecutionConfiguration(streaming_mode=True),
            memory=MemoryConfiguration(spill_to_disk=True, chunk_size=50000),
        )

        loader = DataFrameTuningLoader()
        loader.save_config(original, config_path)
        loaded = loader.load_config(config_path)

        assert loaded.parallelism.thread_count == 16
        assert loaded.parallelism.worker_count == 4
        assert loaded.execution.streaming_mode is True
        assert loaded.memory.spill_to_disk is True
        assert loaded.memory.chunk_size == 50000

    def test_json_roundtrip_preserves_values(self, tmp_path):
        """JSON save/load roundtrip preserves all configuration values."""
        config_path = tmp_path / "roundtrip.json"
        original = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=8),
            execution=ExecutionConfiguration(lazy_evaluation=False),
        )

        loader = DataFrameTuningLoader()
        loader.save_config(original, config_path)
        loaded = loader.load_config(config_path)

        assert loaded.parallelism.thread_count == 8
        assert loaded.execution.lazy_evaluation is False

    def test_save_creates_parent_directories(self, tmp_path):
        """Save creates nested parent directories if they do not exist."""
        config_path = tmp_path / "nested" / "deep" / "config.yaml"
        config = DataFrameTuningConfiguration()

        loader = DataFrameTuningLoader()
        loader.save_config(config, config_path)

        assert config_path.exists()

    def test_save_with_metadata_populates_fields(self, tmp_path):
        """Save config fills metadata fields (created, generated_by)."""
        config_path = tmp_path / "meta.yaml"
        config = DataFrameTuningConfiguration()

        loader = DataFrameTuningLoader()
        loader.save_config(config, config_path, platform="polars", description="test desc")

        loaded = loader.load_config(config_path)
        assert loaded.metadata is not None
        assert loaded.metadata.platform == "polars"
        assert loaded.metadata.description == "test desc"
        assert loaded.metadata.generated_by == "benchbox"

    def test_save_with_include_defaults(self, tmp_path):
        """include_defaults=True serializes all sections."""
        config_path = tmp_path / "full.yaml"
        config = DataFrameTuningConfiguration()

        loader = DataFrameTuningLoader()
        loader.save_config(config, config_path, include_defaults=True)

        with open(config_path) as fh:
            data = yaml.safe_load(fh)

        # All top-level sections should be present
        assert "parallelism" in data
        assert "execution" in data
        assert "memory" in data

    def test_save_with_existing_metadata_preserves_platform(self, tmp_path):
        """When config already has metadata, save updates but preserves existing platform."""
        config_path = tmp_path / "existing_meta.yaml"
        config = DataFrameTuningConfiguration(
            metadata=TuningMetadata(platform="dask", description="original"),
        )

        loader = DataFrameTuningLoader()
        # Save without overriding platform
        loader.save_config(config, config_path)

        loaded = loader.load_config(config_path)
        assert loaded.metadata.platform == "dask"


# ---------------------------------------------------------------------------
# Templates – platform coverage
# ---------------------------------------------------------------------------


class TestTemplates:
    """Tests for get_template, get_optimized_template, get_memory_constrained_template."""

    @pytest.mark.parametrize("platform", ["polars", "pandas", "dask", "modin", "cudf"])
    def test_get_template_all_platforms(self, platform):
        """get_template returns valid config for all known platforms."""
        loader = DataFrameTuningLoader()
        config = loader.get_template(platform)

        assert isinstance(config, DataFrameTuningConfiguration)
        assert config.metadata is not None
        assert config.metadata.platform == platform

    def test_get_template_strips_df_suffix(self):
        """Platform 'polars-df' is normalized to 'polars'."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("polars-df")

        assert config.metadata.platform == "polars"

    def test_get_template_unknown_platform_returns_base(self):
        """Unknown platform returns base config without platform-specific settings."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("unknown_platform")

        assert isinstance(config, DataFrameTuningConfiguration)
        assert config.metadata.platform == "unknown_platform"

    @pytest.mark.parametrize("platform", ["polars", "pandas", "dask", "cudf"])
    def test_get_optimized_template_all_platforms(self, platform):
        """get_optimized_template returns config for known platforms."""
        loader = DataFrameTuningLoader()
        config = loader.get_optimized_template(platform)

        assert isinstance(config, DataFrameTuningConfiguration)
        assert "optimized" in config.metadata.description.lower()

    @pytest.mark.parametrize("platform", ["polars", "pandas", "dask", "cudf"])
    def test_get_memory_constrained_template_all_platforms(self, platform):
        """get_memory_constrained_template returns config for known platforms."""
        loader = DataFrameTuningLoader()
        config = loader.get_memory_constrained_template(platform)

        assert isinstance(config, DataFrameTuningConfiguration)
        assert "memory" in config.metadata.description.lower()

    def test_polars_template_has_lazy_evaluation(self):
        """Polars template enables lazy evaluation."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("polars")
        assert config.execution.lazy_evaluation is True

    def test_pandas_template_has_dtype_backend(self):
        """Pandas template sets dtype_backend."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("pandas")
        assert config.data_types.dtype_backend == "numpy_nullable"

    def test_dask_template_has_parallelism(self):
        """Dask template configures parallelism."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("dask")
        assert config.parallelism.threads_per_worker == 2

    def test_cudf_template_enables_gpu(self):
        """cuDF template enables GPU."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("cudf")
        assert config.gpu.enabled is True

    def test_modin_template_has_engine_affinity(self):
        """Modin template sets engine_affinity to ray."""
        loader = DataFrameTuningLoader()
        config = loader.get_template("modin")
        assert config.execution.engine_affinity == "ray"


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------


class TestMergeConfigs:
    """Tests for merge_configs and _deep_merge."""

    def test_override_takes_precedence(self):
        """Override values replace base values."""
        loader = DataFrameTuningLoader()

        base = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=4),
        )
        override = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=16),
        )

        merged = loader.merge_configs(base, override)
        assert merged.parallelism.thread_count == 16

    def test_base_values_preserved_when_not_overridden(self):
        """Base values survive when override has defaults for those fields."""
        loader = DataFrameTuningLoader()

        base = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=8),
            memory=MemoryConfiguration(spill_to_disk=True),
        )
        override = DataFrameTuningConfiguration(
            execution=ExecutionConfiguration(streaming_mode=True),
        )

        merged = loader.merge_configs(base, override)
        assert merged.parallelism.thread_count == 8
        assert merged.memory.spill_to_disk is True
        assert merged.execution.streaming_mode is True

    def test_deep_merge_nested_dicts(self):
        """_deep_merge handles nested dictionary merging."""
        loader = DataFrameTuningLoader()

        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 99, "z": 100}, "c": 4}

        result = loader._deep_merge(base, override)

        assert result["a"]["x"] == 1
        assert result["a"]["y"] == 99
        assert result["a"]["z"] == 100
        assert result["b"] == 3
        assert result["c"] == 4

    def test_deep_merge_non_dict_override(self):
        """_deep_merge replaces non-dict values even if base was dict."""
        loader = DataFrameTuningLoader()

        base = {"a": {"nested": True}}
        override = {"a": "replaced"}

        result = loader._deep_merge(base, override)
        assert result["a"] == "replaced"

    def test_merge_without_validation(self):
        """merge_configs with validate=False skips validation."""
        loader = DataFrameTuningLoader()

        base = DataFrameTuningConfiguration()
        override = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=999),
        )

        # Should not raise even with extreme values
        merged = loader.merge_configs(base, override, validate=False)
        assert merged.parallelism.thread_count == 999


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelFunctions:
    """Tests for load_dataframe_tuning and save_dataframe_tuning convenience wrappers."""

    def test_load_with_platform_validation(self, tmp_path):
        """load_dataframe_tuning with platform parameter works (logs warnings)."""
        config_path = tmp_path / "config.yaml"
        with open(config_path, "w") as fh:
            yaml.dump({"execution": {"streaming_mode": True}}, fh)

        config = load_dataframe_tuning(config_path, platform="polars")
        assert config.execution.streaming_mode is True

    def test_save_with_description(self, tmp_path):
        """save_dataframe_tuning with description populates metadata."""
        config_path = tmp_path / "config.yaml"
        config = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=4),
        )

        save_dataframe_tuning(config, config_path, platform="pandas", description="my desc")

        loaded = load_dataframe_tuning(config_path)
        assert loaded.metadata.description == "my desc"
        assert loaded.metadata.platform == "pandas"

    def test_save_and_load_full_cycle(self, tmp_path):
        """Full save -> load cycle with all parameters."""
        config_path = tmp_path / "full_cycle.yaml"

        original = DataFrameTuningConfiguration(
            parallelism=ParallelismConfiguration(thread_count=12, worker_count=3),
            execution=ExecutionConfiguration(streaming_mode=True, lazy_evaluation=False),
            memory=MemoryConfiguration(chunk_size=100_000),
        )

        save_dataframe_tuning(original, config_path, platform="dask", description="cycle test")
        loaded = load_dataframe_tuning(config_path)

        assert loaded.parallelism.thread_count == 12
        assert loaded.parallelism.worker_count == 3
        assert loaded.execution.streaming_mode is True
        assert loaded.execution.lazy_evaluation is False
        assert loaded.memory.chunk_size == 100_000
