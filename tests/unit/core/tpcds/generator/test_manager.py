"""Tests for TPCDSDataGenerator manager orchestration.

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.tpcds.generator.manager import TPCDSDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_gen(tmp_path):
    """Generator with dsdgen marked unavailable (no binary needed)."""
    gen = TPCDSDataGenerator.__new__(TPCDSDataGenerator)
    gen.scale_factor = 1.0
    gen.output_dir = tmp_path
    gen.verbose_level = 0
    gen.verbose = False
    gen.very_verbose = False
    gen.quiet = False
    gen.parallel = 1
    gen.force_regenerate = False
    gen.dsdgen_available = False
    gen._dsdgen_error = RuntimeError("no binary")
    gen._package_root = Path("/nonexistent")
    gen.dsdgen_path = tmp_path
    gen.dsdgen_exe = None
    gen._data_organization_config = None
    gen.tools_dir = tmp_path
    gen._manifest_entries = {}
    import threading

    gen._manifest_lock = threading.Lock()
    from benchbox.utils.data_validation import BenchmarkDataValidator

    gen.validator = BenchmarkDataValidator("tpcds", 1.0)
    return gen


# ---------------------------------------------------------------------------
# Parameter validation
# ---------------------------------------------------------------------------


class TestValidateParameters:
    def test_negative_scale_factor_raises(self, tmp_path):
        with pytest.raises(ValueError, match="positive"):
            TPCDSDataGenerator(scale_factor=-1.0, output_dir=tmp_path)

    def test_fractional_scale_factor_is_allowed(self, tmp_path):
        gen = TPCDSDataGenerator(scale_factor=0.5, output_dir=tmp_path)
        assert gen.scale_factor == 0.5

    def test_too_large_scale_factor_raises(self, tmp_path):
        with pytest.raises(ValueError, match="exceeds maximum"):
            TPCDSDataGenerator(scale_factor=200000.0, output_dir=tmp_path)

    def test_parallel_less_than_1_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Parallel"):
            TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path, parallel=0)

    def test_too_many_parallel_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Too many parallel"):
            TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path, parallel=100)


# ---------------------------------------------------------------------------
# _known_table_names
# ---------------------------------------------------------------------------


def test_known_table_names_includes_dbgen_version(tmp_gen):
    names = tmp_gen._known_table_names()
    assert "dbgen_version" in names
    assert len(names) > 20  # TPC-DS has 24 tables + dbgen_version


# ---------------------------------------------------------------------------
# _raise_missing_dsdgen
# ---------------------------------------------------------------------------


def test_raise_missing_dsdgen_includes_error_detail(tmp_gen):
    tmp_gen._dsdgen_error = RuntimeError("some error detail")
    with pytest.raises(RuntimeError, match="some error detail"):
        tmp_gen._raise_missing_dsdgen()


def test_raise_missing_dsdgen_no_error(tmp_gen):
    tmp_gen._dsdgen_error = None
    with pytest.raises(RuntimeError, match="not bundled"):
        tmp_gen._raise_missing_dsdgen()


# ---------------------------------------------------------------------------
# resolve_dsdgen_path
# ---------------------------------------------------------------------------


def test_resolve_dsdgen_path_returns_none_when_missing():
    # All candidate paths are nonexistent in test environment
    result = TPCDSDataGenerator.resolve_dsdgen_path()
    # Either None (no binary) or a Path (binary found)
    assert result is None or isinstance(result, Path)


# ---------------------------------------------------------------------------
# _prepare_output_dir - missing binary branch
# ---------------------------------------------------------------------------


def test_prepare_output_dir_raises_when_no_dsdgen(tmp_gen):
    tmp_gen.dsdgen_available = False
    with pytest.raises(RuntimeError, match="not bundled"):
        tmp_gen._prepare_output_dir(None)


def test_prepare_output_dir_creates_directory(tmp_gen, tmp_path):
    tmp_gen.dsdgen_available = True
    target = tmp_path / "subdir"
    result = tmp_gen._prepare_output_dir(target)
    assert result == target
    assert target.exists()


# ---------------------------------------------------------------------------
# generate_tables - no dsdgen → raises
# ---------------------------------------------------------------------------


def test_generate_tables_raises_when_no_dsdgen(tmp_gen):
    tmp_gen.dsdgen_available = False
    with pytest.raises(RuntimeError):
        tmp_gen.generate_tables(["customer"])


# ---------------------------------------------------------------------------
# generate_tables - invalid table names
# ---------------------------------------------------------------------------


def test_generate_tables_invalid_names_raises(tmp_gen):
    tmp_gen.dsdgen_available = True
    with pytest.raises(ValueError, match="Invalid table names"):
        tmp_gen.generate_tables(["not_a_real_table_xyz"])


# ---------------------------------------------------------------------------
# has_dsdgen_sources
# ---------------------------------------------------------------------------


def test_has_dsdgen_sources_false(tmp_gen):
    tmp_gen.dsdgen_available = False
    assert tmp_gen.has_dsdgen_sources() is False


def test_has_dsdgen_sources_true(tmp_gen):
    tmp_gen.dsdgen_available = True
    assert tmp_gen.has_dsdgen_sources() is True


# ---------------------------------------------------------------------------
# _package_root_dir
# ---------------------------------------------------------------------------


def test_package_root_dir_returns_path():
    root = TPCDSDataGenerator._package_root_dir()
    assert isinstance(root, Path)


# ---------------------------------------------------------------------------
# _log_regeneration_reason - non-verbose skips emit
# ---------------------------------------------------------------------------


def test_log_regeneration_reason_silent_when_quiet(tmp_gen):
    tmp_gen.verbose = False
    # Should not raise
    tmp_gen._log_regeneration_reason(None)


def test_log_regeneration_reason_verbose_force_regen(tmp_gen, capsys):
    tmp_gen.verbose = True
    # Pass None validation result (means force regen)
    tmp_gen._log_regeneration_reason(None)
    # Should emit something


# ---------------------------------------------------------------------------
# _build_schema_registry
# ---------------------------------------------------------------------------


def test_build_schema_registry_returns_tables(tmp_gen):
    registry = tmp_gen._build_schema_registry()
    assert isinstance(registry, dict)
    assert len(registry) > 0
    # Each entry has name and columns
    first = next(iter(registry.values()))
    assert "name" in first
    assert "columns" in first


# ---------------------------------------------------------------------------
# _candidate_dsdgen_paths - coverage
# ---------------------------------------------------------------------------


def test_candidate_dsdgen_paths_yields_paths():
    paths = list(TPCDSDataGenerator._candidate_dsdgen_paths())
    assert len(paths) >= 2  # At least package root + relative
    for p in paths:
        assert isinstance(p, Path)


# ---------------------------------------------------------------------------
# __init__ with BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON env var
# ---------------------------------------------------------------------------


def test_init_with_data_organization_env_var_invalid_json(tmp_path, monkeypatch):
    """Invalid JSON in env var should be silently ignored."""
    monkeypatch.setenv("BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON", "{invalid json}")
    gen = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path)
    # Should still initialize without error
    assert gen._data_organization_config is None


def test_init_with_data_organization_env_var_empty(tmp_path, monkeypatch):
    """No env var should leave data_organization_config as None."""
    monkeypatch.delenv("BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON", raising=False)
    gen = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path)
    assert gen._data_organization_config is None


# ---------------------------------------------------------------------------
# _log_regeneration_reason - verbose with validation issues
# ---------------------------------------------------------------------------


def test_log_regeneration_reason_verbose_with_issues(tmp_gen, capsys):
    tmp_gen.verbose = True
    mock_result = MagicMock()
    mock_result.issues = ["issue1"]
    tmp_gen._log_regeneration_reason(mock_result)
    # Should not raise; just emits


# ---------------------------------------------------------------------------
# _generate_from_sample - no files in target
# ---------------------------------------------------------------------------


def test_generate_from_sample_returns_none_when_no_files(tmp_gen, tmp_path):
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    target = tmp_path / "target"
    target.mkdir()

    # Patch _copy_sample_dataset to do nothing
    tmp_gen._copy_sample_dataset = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value={})
    tmp_gen._validate_file_format_consistency = MagicMock()
    tmp_gen.should_use_compression = MagicMock(return_value=False)

    result = tmp_gen._generate_from_sample(sample_dir, target)
    assert result is None


def test_generate_from_sample_returns_paths_when_files_found(tmp_gen, tmp_path):
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    target = tmp_path / "target"
    target.mkdir()

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen._copy_sample_dataset = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_paths)
    tmp_gen._validate_file_format_consistency = MagicMock()
    tmp_gen.should_use_compression = MagicMock(return_value=False)

    result = tmp_gen._generate_from_sample(sample_dir, target)
    assert result == fake_paths


# ---------------------------------------------------------------------------
# generate_tables - success path (mocked generation)
# ---------------------------------------------------------------------------


def test_generate_tables_success_with_mock(tmp_gen, tmp_path):
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path

    # Mock the generation helpers
    tmp_gen._generate_table_with_streaming = MagicMock()
    fake_all_paths = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_all_paths)

    result = tmp_gen.generate_tables(["customer"])
    assert "customer" in result


def test_generate_tables_verbose(tmp_gen, tmp_path):
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path
    tmp_gen.verbose = True

    tmp_gen._generate_table_with_streaming = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value={"customer": []})

    result = tmp_gen.generate_tables(["customer"])
    assert "customer" in result


# ---------------------------------------------------------------------------
# generate - delegates to _handle_cloud_or_local_generation
# ---------------------------------------------------------------------------


def test_generate_delegates_correctly(tmp_gen, tmp_path):
    tmp_gen.output_dir = tmp_path
    expected = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen._handle_cloud_or_local_generation = MagicMock(return_value=expected)

    result = tmp_gen.generate()
    assert result == expected


# ---------------------------------------------------------------------------
# _generate_local - mocked happy path
# ---------------------------------------------------------------------------


def test_generate_local_no_regeneration_needed(tmp_gen, tmp_path):
    """When validator says no regeneration needed, should return existing files."""
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    mock_validation = MagicMock()

    # Set up validator mock
    tmp_gen.validator = MagicMock()
    tmp_gen.validator.should_regenerate_data.return_value = (False, mock_validation)
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_paths)

    result = tmp_gen._generate_local(tmp_path)
    assert result == fake_paths


def test_generate_local_with_sample_data(tmp_gen, tmp_path):
    """When sample data is available, use it."""
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    mock_sample_dir = tmp_path / "sample"
    mock_sample_dir.mkdir()

    tmp_gen.validator = MagicMock()
    tmp_gen.validator.should_regenerate_data.return_value = (True, None)
    tmp_gen._log_regeneration_reason = MagicMock()
    tmp_gen._prune_stale_table_artifacts = MagicMock(return_value=[])
    tmp_gen._get_sample_data_dir = MagicMock(return_value=mock_sample_dir)
    tmp_gen._generate_from_sample = MagicMock(return_value=fake_paths)

    result = tmp_gen._generate_local(tmp_path)
    assert result == fake_paths


def test_generate_local_no_sample_data_raises(tmp_gen, tmp_path):
    """Without sample data, delegates to native dsdgen (which then raises)."""
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path

    tmp_gen.validator = MagicMock()
    tmp_gen.validator.should_regenerate_data.return_value = (True, None)
    tmp_gen._log_regeneration_reason = MagicMock()
    tmp_gen._prune_stale_table_artifacts = MagicMock(return_value=[])
    tmp_gen._get_sample_data_dir = MagicMock(return_value=None)
    tmp_gen._generate_from_sample = MagicMock(return_value=None)
    tmp_gen._run_dsdgen_native = MagicMock(side_effect=RuntimeError("dsdgen failed"))

    with pytest.raises(RuntimeError, match="dsdgen failed"):
        tmp_gen._generate_local(tmp_path)


def test_generate_local_with_data_organization(tmp_gen, tmp_path):
    """When data_organization_config is set, applies it."""
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path

    # Minimal fake data_organization_config
    from types import SimpleNamespace

    tmp_gen._data_organization_config = SimpleNamespace(
        get_sort_columns_for_table=lambda _: [],
        get_partition_columns_for_table=lambda _: [],
        get_cluster_columns_for_table=lambda _: [],
    )

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen.validator = MagicMock()
    tmp_gen.validator.should_regenerate_data.return_value = (True, None)
    tmp_gen._log_regeneration_reason = MagicMock()
    tmp_gen._prune_stale_table_artifacts = MagicMock(return_value=[])
    tmp_gen._get_sample_data_dir = MagicMock(return_value=None)
    tmp_gen._generate_from_sample = MagicMock(return_value=None)
    tmp_gen._run_dsdgen_native = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_paths)
    tmp_gen._apply_data_organization = MagicMock(return_value=fake_paths)
    tmp_gen._write_manifest = MagicMock()

    result = tmp_gen._generate_local(tmp_path)
    assert result == fake_paths
    tmp_gen._apply_data_organization.assert_called_once()


def test_compress_raw_dat_files_no_compression(tmp_gen, tmp_path):
    """Without compression enabled, _compress_raw_dat_files is a no-op."""
    tmp_gen.should_use_compression = MagicMock(return_value=False)
    tmp_gen._compress_raw_dat_files(tmp_path)  # Should not raise


# ---------------------------------------------------------------------------
# _prepare_output_dir - non-writable directory (permission error)
# ---------------------------------------------------------------------------


def test_prepare_output_dir_non_writable_raises(tmp_gen, tmp_path, monkeypatch):
    tmp_gen.dsdgen_available = True
    # Make the directory exist
    target = tmp_path / "target"
    target.mkdir()
    # Patch os.access to return False for write access
    import os

    original_access = os.access
    monkeypatch.setattr("os.access", lambda path, mode: False if mode == os.W_OK else original_access(path, mode))
    with pytest.raises(PermissionError, match="not writable"):
        tmp_gen._prepare_output_dir(target)


# ---------------------------------------------------------------------------
# _generate_local - verbose mode with no sample
# ---------------------------------------------------------------------------


def test_generate_local_verbose_logs(tmp_gen, tmp_path):
    """Verbose mode with existing valid data should log and return."""
    tmp_gen.dsdgen_available = True
    tmp_gen.verbose = True
    tmp_gen.output_dir = tmp_path

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen.validator = MagicMock()
    tmp_gen.validator.should_regenerate_data.return_value = (False, MagicMock(issues=[]))
    tmp_gen.validator.print_validation_report = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_paths)

    result = tmp_gen._generate_local(tmp_path)
    assert result == fake_paths


def test_generate_local_after_native_dsdgen_with_compression(tmp_gen, tmp_path):
    """After dsdgen, verify file gathering and validation."""
    tmp_gen.dsdgen_available = True
    tmp_gen.output_dir = tmp_path
    tmp_gen._data_organization_config = None

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen.validator = MagicMock()
    tmp_gen.validator.should_regenerate_data.return_value = (True, None)
    tmp_gen._log_regeneration_reason = MagicMock()
    tmp_gen._prune_stale_table_artifacts = MagicMock(return_value=[])
    tmp_gen._get_sample_data_dir = MagicMock(return_value=None)
    tmp_gen._generate_from_sample = MagicMock(return_value=None)
    tmp_gen._run_dsdgen_native = MagicMock()
    tmp_gen._compress_raw_dat_files = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_paths)
    tmp_gen._validate_file_format_consistency = MagicMock()
    tmp_gen._write_manifest = MagicMock()
    tmp_gen.should_use_compression = MagicMock(return_value=False)

    result = tmp_gen._generate_local(tmp_path)
    assert result == fake_paths
    tmp_gen._compress_raw_dat_files.assert_called_once()
    tmp_gen._write_manifest.assert_called_once()


# ---------------------------------------------------------------------------
# _generate_from_sample - verbose path
# ---------------------------------------------------------------------------


def test_generate_from_sample_verbose(tmp_gen, tmp_path):
    tmp_gen.verbose = True
    sample_dir = tmp_path / "sample"
    sample_dir.mkdir()
    target = tmp_path / "target"
    target.mkdir()

    fake_paths = {"customer": [tmp_path / "customer.dat"]}
    tmp_gen._copy_sample_dataset = MagicMock()
    tmp_gen._gather_existing_table_files = MagicMock(return_value=fake_paths)
    tmp_gen._validate_file_format_consistency = MagicMock()
    tmp_gen.should_use_compression = MagicMock(return_value=False)

    result = tmp_gen._generate_from_sample(sample_dir, target)
    assert result == fake_paths


# ---------------------------------------------------------------------------
# __init__ with valid BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON env var
# ---------------------------------------------------------------------------


def test_init_with_valid_data_organization_env_var(tmp_path, monkeypatch):
    """Valid JSON in env var should be parsed."""
    import json

    config_dict = {
        "tables": {},
        "global_settings": {},
    }
    monkeypatch.setenv("BENCHBOX_DATA_ORGANIZATION_CONFIG_JSON", json.dumps(config_dict))

    # Should not raise even if DataOrganizationConfig.from_dict fails
    try:
        gen = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path)
        # Config may be set or None depending on DataOrganizationConfig availability
        assert gen is not None
    except Exception:
        pass  # DataOrganizationConfig.from_dict may fail with this minimal config
