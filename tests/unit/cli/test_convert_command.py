"""Unit tests for the convert CLI command."""

import json
import sys
import sys as _sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from benchbox.cli.commands.convert import convert

# benchbox.cli.commands.__init__ re-exports `convert` (a Click Command) under
# the same name as the convert submodule.  On Python 3.10 mock's string-based
# patch() resolves the target via getattr(benchbox.cli.commands, "convert"),
# which returns the Command object, not the submodule.  Seeding sys.modules
# here via __import__ and using patch.object() avoids the ambiguity on all
# Python versions.
__import__("benchbox.cli.commands.convert")
_convert_module = _sys.modules["benchbox.cli.commands.convert"]

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="Click command mock.patch requires Python 3.11+ for attribute access",
    ),
]


@pytest.fixture
def cli_runner():
    """Create a CLI runner for testing."""
    return CliRunner()


@pytest.fixture
def mock_manifest_v2(tmp_path):
    """Create a mock v2 manifest file."""
    manifest_data = {
        "version": 2,
        "benchmark": "tpch",
        "scale_factor": 0.01,
        "format_preference": ["tbl"],
        "tables": {
            "customer": {
                "formats": {
                    "tbl": [
                        {
                            "path": "customer.tbl",
                            "size_bytes": 1000,
                            "row_count": 10,
                        }
                    ]
                }
            },
            "orders": {
                "formats": {
                    "tbl": [
                        {
                            "path": "orders.tbl",
                            "size_bytes": 2000,
                            "row_count": 20,
                        }
                    ]
                }
            },
        },
    }

    manifest_path = tmp_path / "_datagen_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f)

    return tmp_path


class TestConvertCommand:
    """Tests for the convert CLI command."""

    def test_convert_help(self, cli_runner):
        """Test that help text is displayed."""
        result = cli_runner.invoke(convert, ["--help"])
        assert result.exit_code == 0
        assert "Convert benchmark data to optimized table formats" in result.output
        assert "--format" in result.output
        assert "--compression" in result.output

    def test_convert_requires_input(self, cli_runner):
        """Test that --input is required."""
        result = cli_runner.invoke(convert, ["--format", "parquet"])
        assert result.exit_code != 0
        assert "Missing option '--input'" in result.output

    def test_convert_requires_format(self, cli_runner, tmp_path):
        """Test that --format is required."""
        # Create empty manifest
        manifest_path = tmp_path / "_datagen_manifest.json"
        manifest_path.write_text("{}")

        result = cli_runner.invoke(convert, ["--input", str(tmp_path)])
        assert result.exit_code != 0
        assert "Missing option '--format'" in result.output

    def test_convert_invalid_format(self, cli_runner, tmp_path):
        """Test that invalid format is rejected."""
        # Create empty manifest
        manifest_path = tmp_path / "_datagen_manifest.json"
        manifest_path.write_text("{}")

        result = cli_runner.invoke(convert, ["--input", str(tmp_path), "--format", "invalid"])
        assert result.exit_code != 0
        assert "Invalid value for '--format'" in result.output

    def test_convert_missing_manifest(self, cli_runner, tmp_path):
        """Test error when manifest is missing."""
        result = cli_runner.invoke(convert, ["--input", str(tmp_path), "--format", "parquet"])
        assert result.exit_code != 0
        assert "Manifest not found" in result.output

    def test_convert_compression_options(self, cli_runner):
        """Test that all compression options are accepted."""
        result = cli_runner.invoke(convert, ["--help"])
        assert "snappy" in result.output
        assert "gzip" in result.output
        assert "zstd" in result.output
        assert "none" in result.output

    def test_convert_partition_multiple(self, cli_runner, mock_manifest_v2):
        """Test that multiple partition columns can be specified."""
        with patch.object(_convert_module, "_get_schemas_from_manifest") as mock_schemas:
            mock_schemas.return_value = {
                "customer": {"columns": [{"name": "c_custkey", "type": "INTEGER"}]},
            }

            with patch.object(_convert_module, "FormatConversionOrchestrator") as mock_orch:
                mock_instance = MagicMock()
                mock_instance.convert_benchmark_tables.return_value = {}
                mock_orch.return_value = mock_instance

                cli_runner.invoke(
                    convert,
                    [
                        "--input",
                        str(mock_manifest_v2),
                        "--format",
                        "parquet",
                        "--partition",
                        "col1",
                        "--partition",
                        "col2",
                    ],
                )

                # Check partition_cols were passed
                call_kwargs = mock_instance.convert_benchmark_tables.call_args[1]
                assert "col1" in call_kwargs["options"].partition_cols
                assert "col2" in call_kwargs["options"].partition_cols

    def test_convert_validate_flag(self, cli_runner, mock_manifest_v2):
        """Test that --validate and --no-validate flags work."""
        with patch.object(_convert_module, "_get_schemas_from_manifest") as mock_schemas:
            mock_schemas.return_value = {
                "customer": {"columns": [{"name": "c_custkey", "type": "INTEGER"}]},
            }

            with patch.object(_convert_module, "FormatConversionOrchestrator") as mock_orch:
                mock_instance = MagicMock()
                mock_instance.convert_benchmark_tables.return_value = {}
                mock_orch.return_value = mock_instance

                # Test --no-validate
                cli_runner.invoke(
                    convert,
                    [
                        "--input",
                        str(mock_manifest_v2),
                        "--format",
                        "parquet",
                        "--no-validate",
                    ],
                )

                call_kwargs = mock_instance.convert_benchmark_tables.call_args[1]
                assert call_kwargs["options"].validate_row_count is False

    def test_convert_verbose_flag(self, cli_runner, mock_manifest_v2):
        """Test that --verbose flag works."""
        with patch.object(_convert_module, "_get_schemas_from_manifest") as mock_schemas:
            mock_schemas.return_value = {
                "customer": {"columns": [{"name": "c_custkey", "type": "INTEGER"}]},
            }

            with patch.object(_convert_module, "FormatConversionOrchestrator") as mock_orch:
                mock_instance = MagicMock()
                mock_instance.convert_benchmark_tables.return_value = {}
                mock_orch.return_value = mock_instance

                cli_runner.invoke(
                    convert,
                    [
                        "--input",
                        str(mock_manifest_v2),
                        "--format",
                        "parquet",
                        "-v",
                    ],
                )

                # Should not fail with verbose
                # Note: actual verbose behavior is logging configuration


class TestConvertCommandSchemaLookup:
    """Tests for schema lookup in convert command."""

    def test_get_schemas_uses_manifest_benchmark(self, mock_manifest_v2):
        """Test that benchmark is auto-detected from manifest."""
        with patch("benchbox.core.benchmark_loader.get_benchmark_class") as mock_get_benchmark:
            mock_benchmark = MagicMock()
            mock_benchmark.return_value.get_schema.return_value = {"columns": [{"name": "id", "type": "INTEGER"}]}
            mock_get_benchmark.return_value = mock_benchmark

            from benchbox.cli.commands.convert import _get_schemas_from_manifest
            from benchbox.core.manifest import load_manifest

            manifest = load_manifest(mock_manifest_v2 / "_datagen_manifest.json")

            # Convert v1 to v2 if needed
            from benchbox.core.manifest import ManifestV1, upgrade_v1_to_v2

            if isinstance(manifest, ManifestV1):
                manifest = upgrade_v1_to_v2(manifest)

            # Should use "tpch" from manifest
            _get_schemas_from_manifest(manifest, None)
            mock_get_benchmark.assert_called_with("tpch")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
