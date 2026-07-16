"""Unit tests for tuning resolution module.

Tests the transparent tuning configuration resolution system.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from benchbox.cli.config import ConfigManager
from benchbox.cli.tuning_resolver import (
    TuningMode,
    TuningResolution,
    TuningSource,
    display_tuning_list,
    display_tuning_resolution,
    get_tuning_template_paths,
    list_available_tuning_templates,
    resolve_template_reference,
    resolve_tuning,
    warn_sql_auto_mode,
)
from benchbox.core.tuning.packaged_templates import TEMPLATES_ROOT, packaged_template_path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def mock_console():
    """Create a mock console for testing."""
    console = MagicMock(spec=Console)
    return console


@pytest.fixture
def config_manager():
    """Create a config manager for testing."""
    return ConfigManager()


@pytest.mark.unit
class TestTuningMode:
    """Test TuningMode enum."""

    def test_tuning_mode_values(self):
        """Test that TuningMode has expected values."""
        assert TuningMode.TUNED.value == "tuned"
        assert TuningMode.NOTUNING.value == "notuning"
        assert TuningMode.AUTO.value == "auto"
        assert TuningMode.CUSTOM_FILE.value == "custom_file"


@pytest.mark.unit
class TestTuningSource:
    """Test TuningSource enum."""

    def test_tuning_source_values(self):
        """Test that TuningSource has expected values."""
        assert TuningSource.EXPLICIT_FILE.value == "explicit_file"
        assert TuningSource.AUTO_DISCOVERED.value == "auto_discovered"
        assert TuningSource.PACKAGED_RESOURCE.value == "packaged_resource"
        assert TuningSource.SMART_DEFAULTS.value == "smart_defaults"
        assert TuningSource.BASELINE.value == "baseline"
        assert TuningSource.INTERACTIVE_WIZARD.value == "wizard"
        assert TuningSource.FALLBACK.value == "fallback"


@pytest.mark.unit
class TestTuningResolution:
    """Test TuningResolution dataclass."""

    def test_resolution_defaults(self):
        """Test TuningResolution default values."""
        resolution = TuningResolution(
            mode=TuningMode.NOTUNING,
            source=TuningSource.BASELINE,
            enabled=False,
        )
        assert resolution.config_file is None
        assert resolution.searched_paths == []
        assert resolution.warnings == []
        assert resolution.info_messages == []

    def test_resolution_source_description_baseline(self):
        """Test source description for baseline mode."""
        resolution = TuningResolution(
            mode=TuningMode.NOTUNING,
            source=TuningSource.BASELINE,
            enabled=False,
        )
        assert "Baseline mode" in resolution.source_description

    def test_resolution_source_description_explicit_file(self):
        """Test source description for explicit file."""
        config_path = Path("/path/to/config.yaml")
        resolution = TuningResolution(
            mode=TuningMode.CUSTOM_FILE,
            source=TuningSource.EXPLICIT_FILE,
            enabled=True,
            config_file=config_path,
        )
        # Use as_posix() for consistent path comparison across platforms
        assert config_path.as_posix() in resolution.source_description.replace("\\", "/")

    def test_resolution_source_description_auto_discovered(self):
        """Test source description for auto-discovered template."""
        resolution = TuningResolution(
            mode=TuningMode.TUNED,
            source=TuningSource.AUTO_DISCOVERED,
            enabled=True,
            config_file=Path("/path/to/template.yaml"),
        )
        assert "Auto-discovered" in resolution.source_description

    def test_resolution_source_description_packaged_resource(self):
        """Test source description for the packaged-resource tier - must be
        textually distinct from the auto-discovered description so provenance
        readers can tell the two apart."""
        resolution = TuningResolution(
            mode=TuningMode.TUNED,
            source=TuningSource.PACKAGED_RESOURCE,
            enabled=True,
            config_file=Path("/site-packages/benchbox/core/tuning/templates/duckdb/tpch_tuned.yaml"),
        )
        assert "Packaged template resource" in resolution.source_description
        assert (
            resolution.source_description
            != TuningResolution(
                mode=TuningMode.TUNED,
                source=TuningSource.AUTO_DISCOVERED,
                enabled=True,
                config_file=resolution.config_file,
            ).source_description
        )


@pytest.mark.unit
class TestGetTuningTemplatePaths:
    """Test get_tuning_template_paths function."""

    def test_basic_paths(self):
        """Test basic path generation without env var."""
        paths = get_tuning_template_paths("duckdb", "tpch")

        # Should have at least the standard path (use as_posix for cross-platform)
        path_strs = [p.as_posix() for p in paths]
        assert any("examples/tunings/duckdb/tpch_tuned.yaml" in p for p in path_strs)

    def test_env_var_path(self):
        """Test that BENCHBOX_TUNING_PATH is respected."""
        with patch.dict(os.environ, {"BENCHBOX_TUNING_PATH": "/custom/path"}):
            paths = get_tuning_template_paths("duckdb", "tpch")

            # First path should be from env var (use as_posix for cross-platform)
            assert "/custom/path/duckdb/tpch_tuned.yaml" in paths[0].as_posix()

    def test_lowercase_platform_benchmark(self):
        """Test that platform and benchmark are lowercased."""
        paths = get_tuning_template_paths("DuckDB", "TPCH")

        path_strs = [p.as_posix() for p in paths]
        # Should be lowercase in paths
        assert any("duckdb/tpch_tuned.yaml" in p for p in path_strs)

    def test_packaged_tier_is_last(self):
        """The packaged-resource tier must be the last candidate (must_preserve:
        existing env/cwd precedence, packaged tier is LAST)."""
        paths = get_tuning_template_paths("duckdb", "tpch")

        assert paths[-1] == packaged_template_path("duckdb", "tpch")
        assert paths[-1].as_posix().endswith("benchbox/core/tuning/templates/duckdb/tpch_tuned.yaml")

    def test_packaged_tier_after_env_var(self):
        """Packaged tier stays last even when BENCHBOX_TUNING_PATH is set."""
        with patch.dict(os.environ, {"BENCHBOX_TUNING_PATH": "/custom/path"}):
            paths = get_tuning_template_paths("duckdb", "tpch")

        assert paths[-1] == packaged_template_path("duckdb", "tpch")


@pytest.mark.unit
class TestListAvailableTuningTemplates:
    """Test list_available_tuning_templates function."""

    def test_list_all_templates(self):
        """Test listing all templates."""
        templates = list_available_tuning_templates()

        # Should find templates in examples/tunings
        assert len(templates) > 0
        # Should have duckdb templates
        assert "duckdb" in templates

    def test_filter_by_platform(self):
        """Test filtering by platform."""
        templates = list_available_tuning_templates(platform="duckdb")

        # Should only have duckdb
        assert len(templates) == 1
        assert "duckdb" in templates

    def test_filter_by_benchmark(self):
        """Test filtering by benchmark."""
        templates = list_available_tuning_templates(benchmark="tpch")

        # All templates should be tpch-related
        for _platform, files in templates.items():
            for f in files:
                assert "tpch" in f.stem.lower()

    def test_filter_by_both(self):
        """Test filtering by both platform and benchmark."""
        templates = list_available_tuning_templates(platform="duckdb", benchmark="tpch")

        # Should only have duckdb tpch templates
        assert len(templates) == 1
        assert "duckdb" in templates
        for f in templates["duckdb"]:
            assert "tpch" in f.stem.lower()

    def test_nonexistent_platform(self):
        """Test filtering by nonexistent platform."""
        templates = list_available_tuning_templates(platform="nonexistent")

        assert len(templates) == 0


@pytest.mark.unit
class TestResolveTuning:
    """Test resolve_tuning function."""

    def test_notuning_mode(self, mock_console, config_manager):
        """Test notuning mode resolution."""
        resolution = resolve_tuning(
            tuning_arg="notuning",
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.NOTUNING
        assert resolution.source == TuningSource.BASELINE
        assert not resolution.enabled
        assert resolution.config_file is None

    def test_auto_mode(self, mock_console, config_manager):
        """Test auto mode resolution."""
        resolution = resolve_tuning(
            tuning_arg="auto",
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.AUTO
        assert resolution.source == TuningSource.SMART_DEFAULTS
        assert resolution.enabled

    def test_explicit_file_path(self, mock_console, config_manager):
        """Test explicit file path resolution."""
        # Use an existing tuning file
        file_path = "examples/tunings/duckdb/tpch_tuned.yaml"

        resolution = resolve_tuning(
            tuning_arg=file_path,
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.CUSTOM_FILE
        assert resolution.source == TuningSource.EXPLICIT_FILE
        assert resolution.enabled
        assert resolution.config_file is not None
        assert "tpch_tuned.yaml" in str(resolution.config_file)

    def test_tuned_mode_with_template(self, mock_console, config_manager):
        """Test tuned mode with existing template."""
        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.TUNED
        assert resolution.source == TuningSource.AUTO_DISCOVERED
        assert resolution.enabled
        assert resolution.config_file is not None
        assert "tpch_tuned.yaml" in str(resolution.config_file)

    def test_tuned_mode_without_template(self, mock_console, config_manager):
        """Test tuned mode when no template exists."""
        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="duckdb",
            benchmark="nonexistent_benchmark",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.TUNED
        assert resolution.source == TuningSource.FALLBACK
        assert resolution.enabled
        assert resolution.config_file is None
        assert len(resolution.warnings) > 0

    def test_tuned_mode_without_platform(self, mock_console, config_manager):
        """Test tuned mode without platform specified."""
        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform=None,
            benchmark=None,
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.TUNED
        assert resolution.source == TuningSource.FALLBACK
        assert len(resolution.warnings) > 0

    def test_invalid_keyword(self, mock_console, config_manager):
        """Test invalid keyword raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_tuning(
                tuning_arg="invalidkeyword",
                platform="duckdb",
                benchmark="tpch",
                config_manager=config_manager,
                console=mock_console,
            )

        message = str(exc_info.value)
        assert "Invalid tuning value" in message
        # The hint must point to the real command, not the invalid value itself.
        assert "benchbox tuning list" in message
        assert "--tuning list" not in message

    def test_file_not_found(self, mock_console, config_manager):
        """Test file not found raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            resolve_tuning(
                tuning_arg="/nonexistent/path.yaml",
                platform="duckdb",
                benchmark="tpch",
                config_manager=config_manager,
                console=mock_console,
            )

        message = str(exc_info.value)
        assert "not found" in message
        assert "benchbox tuning list" in message
        assert "--tuning list" not in message

    def test_case_insensitive_keywords(self, mock_console, config_manager):
        """Test that keywords are case-insensitive."""
        for keyword in ["NOTUNING", "NoTuning", "noTuning"]:
            resolution = resolve_tuning(
                tuning_arg=keyword,
                platform="duckdb",
                benchmark="tpch",
                config_manager=config_manager,
                console=mock_console,
            )
            assert resolution.mode == TuningMode.NOTUNING

    def test_tuned_keyword_not_shadowed_by_local_path(self, mock_console, config_manager, tmp_path, monkeypatch):
        """A local file/dir literally named 'tuned' must not shadow the keyword.

        Keyword checks run before the path-existence check, so --tuning tuned
        always resolves via auto-discovery/fallback, never as an explicit file
        pointing at a coincidentally-named local path.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "tuned").mkdir()

        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="nonexistent-platform",
            benchmark="nonexistent-benchmark",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.TUNED
        assert resolution.source != TuningSource.EXPLICIT_FILE

    def test_notuning_keyword_not_shadowed_by_local_path(self, mock_console, config_manager, tmp_path, monkeypatch):
        """A local file/dir literally named 'notuning' must not shadow the keyword."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "notuning").mkdir()

        resolution = resolve_tuning(
            tuning_arg="notuning",
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.NOTUNING
        assert resolution.source == TuningSource.BASELINE


@pytest.mark.unit
class TestDisplayFunctions:
    """Test display functions."""

    def test_display_tuning_resolution_baseline(self, mock_console):
        """Test display for baseline resolution."""
        resolution = TuningResolution(
            mode=TuningMode.NOTUNING,
            source=TuningSource.BASELINE,
            enabled=False,
            info_messages=["Tuning disabled"],
        )

        display_tuning_resolution(resolution, mock_console)

        # Should have called print at least once
        assert mock_console.print.called

    def test_display_tuning_resolution_with_warnings(self, mock_console):
        """Test display for resolution with warnings."""
        resolution = TuningResolution(
            mode=TuningMode.TUNED,
            source=TuningSource.FALLBACK,
            enabled=True,
            warnings=["No template found"],
            info_messages=["Using basic config"],
        )

        display_tuning_resolution(resolution, mock_console)

        # Should show warnings
        assert mock_console.print.called

    def test_display_tuning_resolution_verbose(self, mock_console):
        """Test verbose display shows searched paths."""
        resolution = TuningResolution(
            mode=TuningMode.TUNED,
            source=TuningSource.FALLBACK,
            enabled=True,
            searched_paths=[Path("path1"), Path("path2")],
            info_messages=["Using basic config"],
        )

        display_tuning_resolution(resolution, mock_console, verbose=True)

        # Should have multiple print calls for verbose output
        assert mock_console.print.call_count >= 2

    def test_display_tuning_list(self, mock_console):
        """Test display_tuning_list shows templates."""
        display_tuning_list(mock_console)

        # Should have printed the table
        assert mock_console.print.called

    def test_display_tuning_list_filtered(self, mock_console):
        """Test display_tuning_list with filters."""
        display_tuning_list(mock_console, platform="duckdb")

        assert mock_console.print.called


@pytest.mark.unit
class TestWarnSqlAutoMode:
    """Test warn_sql_auto_mode: the honest --tuning auto messaging on SQL platforms."""

    def _auto_resolution(self) -> TuningResolution:
        return TuningResolution(
            mode=TuningMode.AUTO,
            source=TuningSource.SMART_DEFAULTS,
            enabled=True,
        )

    def test_warns_on_sql_platform(self, mock_console):
        """SQL platforms resolving --tuning auto should get an explicit warning."""
        warn_sql_auto_mode(self._auto_resolution(), resolved_mode="sql", console=mock_console)

        assert mock_console.print.called
        printed = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "DataFrame-only" in printed

    def test_warning_does_not_call_the_config_untuned(self, mock_console):
        """The fallback UnifiedTuningConfiguration() this warning describes has
        primary/foreign/unique/check constraints enabled by default
        (ConstraintConfiguration.enabled defaults to True) -- calling it
        "untuned" misleads a user comparing against --tuning notuning, whose
        baseline has every constraint disabled.
        """
        warn_sql_auto_mode(self._auto_resolution(), resolved_mode="sql", console=mock_console)

        printed = " ".join(str(call) for call in mock_console.print.call_args_list)
        assert "basic (untuned) configuration" not in printed
        assert "constraints" in printed.lower()

    def test_no_warning_on_dataframe_platform(self, mock_console):
        """DataFrame platforms have real smart defaults elsewhere; no warning needed."""
        warn_sql_auto_mode(self._auto_resolution(), resolved_mode="dataframe", console=mock_console)

        assert not mock_console.print.called

    def test_no_warning_for_non_auto_mode(self, mock_console):
        """Only TuningMode.AUTO triggers the warning, regardless of resolved_mode."""
        resolution = TuningResolution(
            mode=TuningMode.NOTUNING,
            source=TuningSource.BASELINE,
            enabled=False,
        )

        warn_sql_auto_mode(resolution, resolved_mode="sql", console=mock_console)

        assert not mock_console.print.called

    def test_quiet_suppresses_console_output(self, mock_console):
        """quiet=True must not print, even on a SQL platform."""
        warn_sql_auto_mode(self._auto_resolution(), resolved_mode="sql", console=mock_console, quiet=True)

        assert not mock_console.print.called

    def test_logs_debug_regardless_of_platform(self):
        """The generic 'using basic unified config' debug log fires for both modes."""
        logger = MagicMock()

        warn_sql_auto_mode(self._auto_resolution(), resolved_mode="dataframe", console=MagicMock(), logger=logger)

        assert logger.debug.called

    def test_display_tuning_list_no_results(self, mock_console):
        """Test display_tuning_list with no matching templates."""
        display_tuning_list(mock_console, platform="nonexistent")

        # Should print "no templates found" message
        assert mock_console.print.called


@pytest.mark.unit
class TestEnvironmentVariableSupport:
    """Test BENCHBOX_TUNING_PATH environment variable support."""

    def test_env_var_adds_search_path(self):
        """Test that BENCHBOX_TUNING_PATH adds to search paths."""
        with patch.dict(os.environ, {"BENCHBOX_TUNING_PATH": "/custom/tuning"}):
            paths = get_tuning_template_paths("postgres", "tpch")

            # First path should be from env var (use as_posix for cross-platform)
            first_path = paths[0].as_posix()
            assert first_path.startswith("/custom/tuning")

    def test_env_var_takes_priority(self, mock_console, config_manager):
        """Test that BENCHBOX_TUNING_PATH takes priority over standard paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a custom tuning directory structure
            custom_path = Path(tmpdir)
            platform_dir = custom_path / "duckdb"
            platform_dir.mkdir(parents=True)
            custom_file = platform_dir / "tpch_tuned.yaml"
            custom_file.write_text("primary_keys:\n  enabled: true\n")

            with patch.dict(os.environ, {"BENCHBOX_TUNING_PATH": str(custom_path)}):
                resolution = resolve_tuning(
                    tuning_arg="tuned",
                    platform="duckdb",
                    benchmark="tpch",
                    config_manager=config_manager,
                    console=mock_console,
                )

                # Should find the custom template first
                assert resolution.config_file is not None
                # Resolve both paths to handle Windows short paths (e.g., RUNNER~1)
                resolved_tmpdir = Path(tmpdir).resolve()
                resolved_config = resolution.config_file.resolve()
                assert str(resolved_tmpdir) in str(resolved_config)


@pytest.mark.unit
class TestMockedFilesystem:
    """Tests using mocked filesystem to avoid dependency on examples/tunings."""

    def test_resolve_tuning_with_mocked_path_exists(self, mock_console):
        """Test tuned mode with mocked Path.exists()."""
        mock_config = MagicMock()
        mock_config.get.return_value = None  # No default config

        with patch.object(Path, "exists") as mock_exists:
            # First call for explicit path check (Case 3), second for template discovery
            mock_exists.side_effect = [False, True]  # Template found on second path

            with patch.object(Path, "resolve") as mock_resolve:
                mock_resolve.return_value = Path("/mocked/path/tpch_tuned.yaml")

                resolution = resolve_tuning(
                    tuning_arg="tuned",
                    platform="mockplatform",
                    benchmark="mockbench",
                    config_manager=mock_config,
                    console=mock_console,
                )

                assert resolution.mode == TuningMode.TUNED
                assert resolution.enabled

    def test_resolve_tuning_fallback_with_all_paths_missing(self, mock_console):
        """Test fallback when all template paths are missing."""
        mock_config = MagicMock()
        mock_config.get.return_value = None

        with patch.object(Path, "exists", return_value=False):
            resolution = resolve_tuning(
                tuning_arg="tuned",
                platform="nonexistent",
                benchmark="nonexistent",
                config_manager=mock_config,
                console=mock_console,
            )

            assert resolution.mode == TuningMode.TUNED
            assert resolution.source == TuningSource.FALLBACK
            assert len(resolution.warnings) > 0
            assert "No tuning template found" in resolution.warnings[0]

    def test_list_templates_with_mocked_directory(self):
        """Test list_available_tuning_templates with mocked directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            # Create mock structure
            (base / "platform1").mkdir()
            (base / "platform1" / "bench_tuned.yaml").touch()
            (base / "platform1" / "other_tuned.yaml").touch()
            (base / "platform2").mkdir()
            (base / "platform2" / "bench_tuned.yaml").touch()

            templates = list_available_tuning_templates(base_path=base)

            assert "platform1" in templates
            assert "platform2" in templates
            assert len(templates["platform1"]) == 2
            assert len(templates["platform2"]) == 1

    def test_config_default_takes_priority(self, mock_console):
        """Test that config file default takes priority over template discovery."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a default config file
            default_file = Path(tmpdir) / "default_tuning.yaml"
            default_file.write_text("primary_keys:\n  enabled: true\n")

            mock_config = MagicMock()
            mock_config.get.return_value = str(default_file)

            resolution = resolve_tuning(
                tuning_arg="tuned",
                platform="duckdb",
                benchmark="tpch",
                config_manager=mock_config,
                console=mock_console,
            )

            assert resolution.source == TuningSource.EXPLICIT_FILE
            assert resolution.config_file == default_file.resolve()
            assert "default config from benchbox.yaml" in resolution.info_messages[0]

    def test_config_default_missing_warns(self, mock_console):
        """Test that missing config file default generates a warning."""
        mock_config = MagicMock()
        mock_config.get.return_value = "/nonexistent/default.yaml"

        with patch.object(Path, "exists", return_value=False):
            resolution = resolve_tuning(
                tuning_arg="tuned",
                platform="test",
                benchmark="test",
                config_manager=mock_config,
                console=mock_console,
            )

            # Should warn about missing default and fall back
            assert any("not found" in w for w in resolution.warnings)
            assert resolution.source == TuningSource.FALLBACK


@pytest.mark.unit
class TestDisplayTuningShowNullSafety:
    """Test display_tuning_show handles None config correctly."""

    def test_display_with_none_config(self, mock_console):
        """Test that display_tuning_show handles None config gracefully."""
        from benchbox.cli.tuning_resolver import display_tuning_show

        resolution = TuningResolution(
            mode=TuningMode.TUNED,
            source=TuningSource.FALLBACK,
            enabled=True,
        )

        # Should not raise even with None config
        display_tuning_show(mock_console, None, resolution)

        # Should have printed the panel at minimum
        assert mock_console.print.called

    def test_display_with_valid_config(self, mock_console):
        """Test that display_tuning_show shows config when provided."""
        from benchbox.cli.tuning_resolver import display_tuning_show

        resolution = TuningResolution(
            mode=TuningMode.TUNED,
            source=TuningSource.AUTO_DISCOVERED,
            enabled=True,
            config_file=Path("/path/to/config.yaml"),
        )

        mock_config = MagicMock()
        mock_config.to_dict.return_value = {"primary_keys": {"enabled": True}}

        display_tuning_show(mock_console, mock_config, resolution)

        # Should have called to_dict on the config
        mock_config.to_dict.assert_called_once()


class TestResolveTemplateReference:
    """Tests for resolve_template_reference() - ADR-1's template-ref rule.

    Never a raw local path: repo-relative when under the repo root, otherwise
    basename + content hash.
    """

    def test_none_config_file_returns_none(self):
        assert resolve_template_reference(None) is None

    def test_repo_relative_path_for_file_under_repo_root(self, tmp_path):
        repo_root = tmp_path / "repo"
        template = repo_root / "examples" / "tunings" / "duckdb" / "tpch_tuned.yaml"
        template.parent.mkdir(parents=True)
        template.write_text("primary_keys:\n  enabled: true\n")

        ref = resolve_template_reference(template, repo_root=repo_root)

        assert ref == "examples/tunings/duckdb/tpch_tuned.yaml"
        assert not Path(ref).is_absolute()

    def test_basename_and_content_hash_for_file_outside_repo_root(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        outside_dir = tmp_path / "elsewhere"
        outside_dir.mkdir()
        template = outside_dir / "custom_tuning.yaml"
        template.write_text("primary_keys:\n  enabled: true\n")

        ref = resolve_template_reference(template, repo_root=repo_root)

        assert ref is not None
        assert not ref.startswith("/")
        assert str(outside_dir) not in ref
        assert ref.startswith("custom_tuning.yaml:")
        # 16 hex chars of content hash after the basename separator.
        digest = ref.split(":", 1)[1]
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)

    def test_outside_repo_reference_is_stable_for_identical_content(self, tmp_path):
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        template_a = tmp_path / "a" / "tuning.yaml"
        template_b = tmp_path / "b" / "tuning.yaml"
        template_a.parent.mkdir()
        template_b.parent.mkdir()
        template_a.write_text("same content\n")
        template_b.write_text("same content\n")

        assert resolve_template_reference(template_a, repo_root=repo_root) == resolve_template_reference(
            template_b, repo_root=repo_root
        )

    def test_packaged_template_resolves_to_repo_relative_ref_when_under_repo_root(self):
        """Composition point with #1188 (template packaging): the packaged
        resource tier's templates live under
        benchbox/core/tuning/templates/, inside the repo checkout, so a
        packaged-tier config_file must resolve to a repo-relative reference
        just like an examples/tunings/ template - never a raw absolute path,
        and never basename+hash (which would happen if TEMPLATES_ROOT were
        mistakenly treated as outside the repo)."""
        packaged_file = TEMPLATES_ROOT / "duckdb" / "tpch_tuned.yaml"
        assert packaged_file.exists(), "packaged template fixture must exist for this composition test"

        ref = resolve_template_reference(packaged_file)

        assert ref == "benchbox/core/tuning/templates/duckdb/tpch_tuned.yaml"
        assert not Path(ref).is_absolute()

    def test_packaged_template_resolves_to_basename_hash_when_repo_root_overridden_away(self, tmp_path):
        """When resolved against a repo_root that does NOT contain the
        packaged templates directory (simulating an installed package with
        no repo checkout at all), the packaged template still falls back to
        the basename+content-hash form - never leaks the installed
        site-packages path."""
        packaged_file = TEMPLATES_ROOT / "duckdb" / "tpch_tuned.yaml"
        assert packaged_file.exists()

        ref = resolve_template_reference(packaged_file, repo_root=tmp_path)

        assert ref is not None
        assert not ref.startswith("/")
        assert ref.startswith("tpch_tuned.yaml:")


# Repo root, three levels up from tests/unit/cli/test_tuning_resolution.py.
_REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.unit
class TestPackagedTemplatesParity:
    """`benchbox/core/tuning/templates/` ships copies of the `examples/tunings/`
    dev-time source templates so they're bundled with the installed package
    (see benchbox/core/tuning/packaged_templates.py and templates/README.md).
    These must stay byte-identical - this test is the enforcement mechanism
    the README promises, catching a source template edit that forgot to
    re-sync the packaged copy.
    """

    # Platforms whose examples/tunings/<benchmark>_tuned.yaml naming is what
    # get_tuning_template_paths auto-discovers, and are therefore expected to
    # have a packaged counterpart for every such file (see
    # test_every_auto_discoverable_examples_template_is_packaged below).
    AUTO_DISCOVERY_PLATFORMS = ("duckdb", "databricks")

    # (platform, filename) pairs that textually match the `*_tuned.yaml` glob
    # but are deliberately NOT packaged, each with a reason so future
    # additions to this set are a deliberate decision, not a silent gap.
    EXCLUDED_AUTO_DISCOVERY_SOURCES = {
        ("databricks", "tpch_liquid_tuned.yaml"): (
            "Liquid Clustering AUTO variant selected via physical_rendering_id "
            "(see examples/tunings/README.md), not the <benchmark>_tuned.yaml "
            "auto-discovery pattern get_tuning_template_paths searches for - "
            "the discoverable stem for benchmark='tpch' is 'tpch_tuned', not "
            "'tpch_liquid_tuned'."
        ),
        ("databricks", "tpcds_liquid_tuned.yaml"): (
            "Liquid Clustering AUTO variant selected via physical_rendering_id "
            "(see examples/tunings/README.md), not the <benchmark>_tuned.yaml "
            "auto-discovery pattern get_tuning_template_paths searches for - "
            "the discoverable stem for benchmark='tpcds' is 'tpcds_tuned', not "
            "'tpcds_liquid_tuned'."
        ),
    }

    def test_packaged_templates_root_exists(self):
        assert TEMPLATES_ROOT.exists()
        assert TEMPLATES_ROOT.is_dir()

    def test_at_least_one_platform_is_packaged(self):
        platform_dirs = [p for p in TEMPLATES_ROOT.iterdir() if p.is_dir()]
        assert platform_dirs
        platform_names = {p.name for p in platform_dirs}
        # duckdb/databricks are the platforms whose auto-discovery naming
        # (<benchmark>_tuned.yaml) is packaged today.
        assert "duckdb" in platform_names

    def test_every_packaged_template_matches_its_examples_source(self):
        """Packaged -> source direction: every file actually packaged must
        mirror a real examples/tunings/ file, byte-for-byte."""
        examples_root = _REPO_ROOT / "examples" / "tunings"
        assert examples_root.exists(), "examples/tunings/ must exist to check parity"

        checked = 0
        for platform_dir in TEMPLATES_ROOT.iterdir():
            if not platform_dir.is_dir():
                continue
            for packaged_file in platform_dir.glob("*.yaml"):
                source_file = examples_root / platform_dir.name / packaged_file.name
                assert source_file.exists(), (
                    f"Packaged template {packaged_file} has no matching source "
                    f"file at {source_file} - packaged templates must mirror an "
                    f"examples/tunings/ file, not be authored independently."
                )
                packaged_text = packaged_file.read_text(encoding="utf-8")
                source_text = source_file.read_text(encoding="utf-8")
                assert packaged_text == source_text, (
                    f"{packaged_file} has drifted from its source {source_file}. "
                    f"Re-sync: cp {source_file} {packaged_file}"
                )
                checked += 1

        assert checked > 0, "Expected at least one packaged template to check"

    def test_every_auto_discoverable_examples_template_is_packaged(self):
        """Source -> packaged direction (bidirectional guard): every
        examples/tunings/{duckdb,databricks}/*_tuned.yaml file that matches
        the get_tuning_template_paths auto-discovery naming must have a
        byte-identical packaged counterpart, unless explicitly excluded
        above. Without this direction, a NEW auto-discoverable template
        added to examples/tunings/ without a packaged copy would ship
        silently - installed-package users would fall through to the
        fallback tier for it with no test catching the gap.
        """
        examples_root = _REPO_ROOT / "examples" / "tunings"
        assert examples_root.exists(), "examples/tunings/ must exist to check parity"

        checked = 0
        for platform in self.AUTO_DISCOVERY_PLATFORMS:
            platform_dir = examples_root / platform
            if not platform_dir.exists():
                continue
            for source_file in sorted(platform_dir.glob("*_tuned.yaml")):
                exclusion_reason = self.EXCLUDED_AUTO_DISCOVERY_SOURCES.get((platform, source_file.name))
                if exclusion_reason is not None:
                    continue

                packaged_file = TEMPLATES_ROOT / platform / source_file.name
                assert packaged_file.exists(), (
                    f"{source_file} matches the <benchmark>_tuned.yaml "
                    f"auto-discovery pattern but has no packaged counterpart at "
                    f"{packaged_file}. Either add the packaged copy (see "
                    f"benchbox/core/tuning/templates/README.md) or add "
                    f"('{platform}', '{source_file.name}') to "
                    f"EXCLUDED_AUTO_DISCOVERY_SOURCES with an explicit reason."
                )
                assert packaged_file.read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8"), (
                    f"{packaged_file} has drifted from its source {source_file}. "
                    f"Re-sync: cp {source_file} {packaged_file}"
                )
                checked += 1

        assert checked > 0, "Expected at least one auto-discoverable examples/tunings template to check"

    def test_excluded_auto_discovery_sources_are_real_and_have_reasons(self):
        """Guard the exclusion list itself: every excluded entry must exist
        in examples/tunings/ (no exclusions for files that don't exist) and
        carry a non-empty reason string."""
        examples_root = _REPO_ROOT / "examples" / "tunings"

        for (platform, filename), reason in self.EXCLUDED_AUTO_DISCOVERY_SOURCES.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"Exclusion ({platform!r}, {filename!r}) must carry a non-empty reason string"
            )
            excluded_source = examples_root / platform / filename
            assert excluded_source.exists(), (
                f"Excluded entry ({platform!r}, {filename!r}) does not exist at "
                f"{excluded_source} - remove the stale exclusion"
            )


@pytest.mark.unit
class TestSimulatedInstalledEnvironmentDiscovery:
    """Simulate running benchbox from an installed package outside a
    repository checkout: no cwd-relative examples/tunings/ directory exists.
    The packaged-resource tier must still resolve a real template.
    """

    def test_get_tuning_template_paths_packaged_candidate_exists_without_repo_cwd(self, tmp_path, monkeypatch):
        """From a cwd with no examples/tunings/, the packaged-tier candidate
        path returned by get_tuning_template_paths must still point at a real,
        existing file (it lives inside the installed benchbox package, not
        relative to cwd)."""
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "examples" / "tunings").exists()

        paths = get_tuning_template_paths("duckdb", "tpch")

        packaged_candidate = paths[-1]
        assert packaged_candidate.exists()

    def test_resolve_tuning_tuned_resolves_packaged_tier_without_repo_cwd(
        self, mock_console, config_manager, tmp_path, monkeypatch
    ):
        """--tuning tuned, run from a cwd with no examples/tunings/, must
        resolve via the packaged tier rather than falling back to a basic
        untuned configuration."""
        monkeypatch.chdir(tmp_path)

        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.TUNED
        assert resolution.source == TuningSource.PACKAGED_RESOURCE
        assert resolution.enabled
        assert resolution.config_file is not None
        assert resolution.config_file.exists()
        assert "templates/duckdb/tpch_tuned.yaml" in resolution.config_file.as_posix()
        assert not resolution.warnings
        assert any("packaged" in msg.lower() for msg in resolution.info_messages)

    def test_resolve_tuning_still_falls_back_when_no_packaged_template_either(
        self, mock_console, config_manager, tmp_path, monkeypatch
    ):
        """A platform/benchmark with no packaged template must still fall
        through to the basic-config fallback, not raise."""
        monkeypatch.chdir(tmp_path)

        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="duckdb",
            benchmark="nonexistent_benchmark",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.source == TuningSource.FALLBACK
        assert resolution.config_file is None
        assert len(resolution.warnings) > 0

    def test_list_available_tuning_templates_falls_back_to_packaged_tier(self, tmp_path, monkeypatch):
        """`tuning list` (list_available_tuning_templates with the default
        base_path) must fall back to packaged templates when no cwd-relative
        examples/tunings/ directory exists, instead of reporting nothing."""
        monkeypatch.chdir(tmp_path)

        templates = list_available_tuning_templates()

        assert "duckdb" in templates
        assert any(f.name == "tpch_tuned.yaml" for f in templates["duckdb"])

    def test_list_available_tuning_templates_explicit_missing_base_path_stays_empty(self, tmp_path):
        """An explicitly-passed base_path that doesn't exist must NOT trigger
        the packaged-tier fallback - only the default (cwd examples/tunings/)
        path does. Preserves pre-existing behavior for explicit callers."""
        missing = tmp_path / "does-not-exist"

        templates = list_available_tuning_templates(base_path=missing)

        assert templates == {}

    def test_display_tuning_list_does_not_crash_without_repo_cwd(self, mock_console, tmp_path, monkeypatch):
        """display_tuning_list (the `benchbox tuning list` command body) must
        not error out when run outside a repository checkout."""
        monkeypatch.chdir(tmp_path)

        display_tuning_list(mock_console, platform="duckdb")

        assert mock_console.print.called


@pytest.mark.unit
class TestPackagedTemplatesParity:
    """`benchbox/core/tuning/templates/` ships copies of the `examples/tunings/`
    dev-time source templates so they're bundled with the installed package
    (see benchbox/core/tuning/packaged_templates.py and templates/README.md).
    These must stay byte-identical - this test is the enforcement mechanism
    the README promises, catching a source template edit that forgot to
    re-sync the packaged copy.
    """

    # Platforms whose examples/tunings/<benchmark>_tuned.yaml naming is what
    # get_tuning_template_paths auto-discovers, and are therefore expected to
    # have a packaged counterpart for every such file (see
    # test_every_auto_discoverable_examples_template_is_packaged below).
    AUTO_DISCOVERY_PLATFORMS = ("duckdb", "databricks")

    # (platform, filename) pairs that textually match the `*_tuned.yaml` glob
    # but are deliberately NOT packaged, each with a reason so future
    # additions to this set are a deliberate decision, not a silent gap.
    EXCLUDED_AUTO_DISCOVERY_SOURCES = {
        ("databricks", "tpch_liquid_tuned.yaml"): (
            "Liquid Clustering AUTO variant selected via physical_rendering_id "
            "(see examples/tunings/README.md), not the <benchmark>_tuned.yaml "
            "auto-discovery pattern get_tuning_template_paths searches for - "
            "the discoverable stem for benchmark='tpch' is 'tpch_tuned', not "
            "'tpch_liquid_tuned'."
        ),
        ("databricks", "tpcds_liquid_tuned.yaml"): (
            "Liquid Clustering AUTO variant selected via physical_rendering_id "
            "(see examples/tunings/README.md), not the <benchmark>_tuned.yaml "
            "auto-discovery pattern get_tuning_template_paths searches for - "
            "the discoverable stem for benchmark='tpcds' is 'tpcds_tuned', not "
            "'tpcds_liquid_tuned'."
        ),
    }

    def test_packaged_templates_root_exists(self):
        assert TEMPLATES_ROOT.exists()
        assert TEMPLATES_ROOT.is_dir()

    def test_at_least_one_platform_is_packaged(self):
        platform_dirs = [p for p in TEMPLATES_ROOT.iterdir() if p.is_dir()]
        assert platform_dirs
        platform_names = {p.name for p in platform_dirs}
        # duckdb/databricks are the platforms whose auto-discovery naming
        # (<benchmark>_tuned.yaml) is packaged today.
        assert "duckdb" in platform_names

    def test_every_packaged_template_matches_its_examples_source(self):
        """Packaged -> source direction: every file actually packaged must
        mirror a real examples/tunings/ file, byte-for-byte."""
        examples_root = _REPO_ROOT / "examples" / "tunings"
        assert examples_root.exists(), "examples/tunings/ must exist to check parity"

        checked = 0
        for platform_dir in TEMPLATES_ROOT.iterdir():
            if not platform_dir.is_dir():
                continue
            for packaged_file in platform_dir.glob("*.yaml"):
                source_file = examples_root / platform_dir.name / packaged_file.name
                assert source_file.exists(), (
                    f"Packaged template {packaged_file} has no matching source "
                    f"file at {source_file} - packaged templates must mirror an "
                    f"examples/tunings/ file, not be authored independently."
                )
                packaged_text = packaged_file.read_text(encoding="utf-8")
                source_text = source_file.read_text(encoding="utf-8")
                assert packaged_text == source_text, (
                    f"{packaged_file} has drifted from its source {source_file}. "
                    f"Re-sync: cp {source_file} {packaged_file}"
                )
                checked += 1

        assert checked > 0, "Expected at least one packaged template to check"

    def test_every_auto_discoverable_examples_template_is_packaged(self):
        """Source -> packaged direction (bidirectional guard): every
        examples/tunings/{duckdb,databricks}/*_tuned.yaml file that matches
        the get_tuning_template_paths auto-discovery naming must have a
        byte-identical packaged counterpart, unless explicitly excluded
        above. Without this direction, a NEW auto-discoverable template
        added to examples/tunings/ without a packaged copy would ship
        silently - installed-package users would fall through to the
        fallback tier for it with no test catching the gap.
        """
        examples_root = _REPO_ROOT / "examples" / "tunings"
        assert examples_root.exists(), "examples/tunings/ must exist to check parity"

        checked = 0
        for platform in self.AUTO_DISCOVERY_PLATFORMS:
            platform_dir = examples_root / platform
            if not platform_dir.exists():
                continue
            for source_file in sorted(platform_dir.glob("*_tuned.yaml")):
                exclusion_reason = self.EXCLUDED_AUTO_DISCOVERY_SOURCES.get((platform, source_file.name))
                if exclusion_reason is not None:
                    continue

                packaged_file = TEMPLATES_ROOT / platform / source_file.name
                assert packaged_file.exists(), (
                    f"{source_file} matches the <benchmark>_tuned.yaml "
                    f"auto-discovery pattern but has no packaged counterpart at "
                    f"{packaged_file}. Either add the packaged copy (see "
                    f"benchbox/core/tuning/templates/README.md) or add "
                    f"('{platform}', '{source_file.name}') to "
                    f"EXCLUDED_AUTO_DISCOVERY_SOURCES with an explicit reason."
                )
                assert packaged_file.read_text(encoding="utf-8") == source_file.read_text(encoding="utf-8"), (
                    f"{packaged_file} has drifted from its source {source_file}. "
                    f"Re-sync: cp {source_file} {packaged_file}"
                )
                checked += 1

        assert checked > 0, "Expected at least one auto-discoverable examples/tunings template to check"

    def test_excluded_auto_discovery_sources_are_real_and_have_reasons(self):
        """Guard the exclusion list itself: every excluded entry must exist
        in examples/tunings/ (no exclusions for files that don't exist) and
        carry a non-empty reason string."""
        examples_root = _REPO_ROOT / "examples" / "tunings"

        for (platform, filename), reason in self.EXCLUDED_AUTO_DISCOVERY_SOURCES.items():
            assert isinstance(reason, str) and reason.strip(), (
                f"Exclusion ({platform!r}, {filename!r}) must carry a non-empty reason string"
            )
            excluded_source = examples_root / platform / filename
            assert excluded_source.exists(), (
                f"Excluded entry ({platform!r}, {filename!r}) does not exist at "
                f"{excluded_source} - remove the stale exclusion"
            )


@pytest.mark.unit
class TestSimulatedInstalledEnvironmentDiscovery:
    """Simulate running benchbox from an installed package outside a
    repository checkout: no cwd-relative examples/tunings/ directory exists.
    The packaged-resource tier must still resolve a real template.
    """

    def test_get_tuning_template_paths_packaged_candidate_exists_without_repo_cwd(self, tmp_path, monkeypatch):
        """From a cwd with no examples/tunings/, the packaged-tier candidate
        path returned by get_tuning_template_paths must still point at a real,
        existing file (it lives inside the installed benchbox package, not
        relative to cwd)."""
        monkeypatch.chdir(tmp_path)
        assert not (tmp_path / "examples" / "tunings").exists()

        paths = get_tuning_template_paths("duckdb", "tpch")

        packaged_candidate = paths[-1]
        assert packaged_candidate.exists()

    def test_resolve_tuning_tuned_resolves_packaged_tier_without_repo_cwd(
        self, mock_console, config_manager, tmp_path, monkeypatch
    ):
        """--tuning tuned, run from a cwd with no examples/tunings/, must
        resolve via the packaged tier rather than falling back to a basic
        untuned configuration."""
        monkeypatch.chdir(tmp_path)

        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="duckdb",
            benchmark="tpch",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.mode == TuningMode.TUNED
        assert resolution.source == TuningSource.PACKAGED_RESOURCE
        assert resolution.enabled
        assert resolution.config_file is not None
        assert resolution.config_file.exists()
        assert "templates/duckdb/tpch_tuned.yaml" in resolution.config_file.as_posix()
        assert not resolution.warnings
        assert any("packaged" in msg.lower() for msg in resolution.info_messages)

    def test_resolve_tuning_still_falls_back_when_no_packaged_template_either(
        self, mock_console, config_manager, tmp_path, monkeypatch
    ):
        """A platform/benchmark with no packaged template must still fall
        through to the basic-config fallback, not raise."""
        monkeypatch.chdir(tmp_path)

        resolution = resolve_tuning(
            tuning_arg="tuned",
            platform="duckdb",
            benchmark="nonexistent_benchmark",
            config_manager=config_manager,
            console=mock_console,
        )

        assert resolution.source == TuningSource.FALLBACK
        assert resolution.config_file is None
        assert len(resolution.warnings) > 0

    def test_list_available_tuning_templates_falls_back_to_packaged_tier(self, tmp_path, monkeypatch):
        """`tuning list` (list_available_tuning_templates with the default
        base_path) must fall back to packaged templates when no cwd-relative
        examples/tunings/ directory exists, instead of reporting nothing."""
        monkeypatch.chdir(tmp_path)

        templates = list_available_tuning_templates()

        assert "duckdb" in templates
        assert any(f.name == "tpch_tuned.yaml" for f in templates["duckdb"])

    def test_list_available_tuning_templates_explicit_missing_base_path_stays_empty(self, tmp_path):
        """An explicitly-passed base_path that doesn't exist must NOT trigger
        the packaged-tier fallback - only the default (cwd examples/tunings/)
        path does. Preserves pre-existing behavior for explicit callers."""
        missing = tmp_path / "does-not-exist"

        templates = list_available_tuning_templates(base_path=missing)

        assert templates == {}

    def test_display_tuning_list_does_not_crash_without_repo_cwd(self, mock_console, tmp_path, monkeypatch):
        """display_tuning_list (the `benchbox tuning list` command body) must
        not error out when run outside a repository checkout."""
        monkeypatch.chdir(tmp_path)

        display_tuning_list(mock_console, platform="duckdb")

        assert mock_console.print.called
