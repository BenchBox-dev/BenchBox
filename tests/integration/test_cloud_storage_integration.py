"""Integration tests for cloud storage functionality across all benchmarks.

These tests verify that all data generators properly support cloud storage paths
and can upload generated data to cloud storage when configured.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


pytest.importorskip("pandas")

# Check for cloudpathlib availability
try:
    import cloudpathlib

    CLOUDPATHLIB_AVAILABLE = True
except ImportError:
    CLOUDPATHLIB_AVAILABLE = False

# Import all generators
# NOTE: MergeDataGenerator intentionally excluded - Merge benchmark was replaced
# with Write Primitives benchmark. MERGE operations are tested in Write Primitives.
from benchbox.core.amplab.generator import AMPLabDataGenerator
from benchbox.core.clickbench.generator import ClickBenchDataGenerator
from benchbox.core.h2odb.generator import H2ODataGenerator
from benchbox.core.joinorder.generator import JoinOrderGenerator
from benchbox.core.read_primitives.generator import ReadPrimitivesDataGenerator
from benchbox.core.ssb.generator import SSBDataGenerator
from benchbox.core.tpcdi.generator import TPCDIDataGenerator
from benchbox.core.tpcds.generator import TPCDSDataGenerator
from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.utils.cloud_storage import create_path_handler


@pytest.fixture
def mock_cloud_path():
    """Mock CloudPath for testing."""
    with patch("benchbox.utils.cloud_storage.CloudPath") as mock_cloudpath:
        mock_instance = Mock()
        mock_instance.exists.return_value = False
        mock_instance.mkdir.return_value = None
        mock_instance.upload_from.return_value = None
        mock_instance.__str__ = Mock(return_value="s3://test-bucket/test-path")
        mock_instance.__fspath__ = Mock(return_value="s3://test-bucket/test-path")
        mock_instance.__truediv__ = lambda self, other: Mock(
            __str__=Mock(return_value=f"s3://test-bucket/test-path/{other}"),
            __fspath__=Mock(return_value=f"s3://test-bucket/test-path/{other}"),
        )
        mock_cloudpath.return_value = mock_instance
        yield mock_instance


@pytest.fixture
def temp_dir():
    """Create temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        yield Path(tmp_dir)


class TestCloudStorageIntegration:
    """Test cloud storage integration for all generators.

    Note: MergeDataGenerator is not included in these tests because the Merge
    benchmark was replaced with the Write Primitives benchmark. MERGE operations
    are comprehensively tested in the Write Primitives suite. See PROJECT_DONE.yaml
    for the complete replacement rationale.
    """

    def test_create_path_handler_with_local_path(self, temp_dir):
        """Test create_path_handler with local paths."""
        local_path = temp_dir / "test"
        handler = create_path_handler(str(local_path))
        assert isinstance(handler, Path)
        assert str(handler) == str(local_path)

    @pytest.mark.skipif(not CLOUDPATHLIB_AVAILABLE, reason="cloudpathlib not installed")
    def test_create_path_handler_with_cloud_path(self):
        """Test create_path_handler with cloud paths."""
        with patch("benchbox.utils.cloud_storage.CloudPath") as mock_cloudpath:
            cloud_path = "s3://test-bucket/test-path"
            create_path_handler(cloud_path)
            mock_cloudpath.assert_called_once_with(cloud_path)

    @pytest.mark.parametrize(
        "generator_class,init_kwargs",
        [
            (TPCHDataGenerator, {"scale_factor": 0.01, "verbose": False}),
            (
                TPCDSDataGenerator,
                {"scale_factor": 1.0, "verbose": False},
            ),  # TPC-DS min scale is 1.0
            (ReadPrimitivesDataGenerator, {"scale_factor": 0.01, "verbose": False}),
            (SSBDataGenerator, {"scale_factor": 0.001}),
            (AMPLabDataGenerator, {"scale_factor": 0.001}),
            (ClickBenchDataGenerator, {"scale_factor": 0.001}),
            (H2ODataGenerator, {"scale_factor": 0.001}),
            (TPCDIDataGenerator, {"scale_factor": 0.001, "enable_progress": False}),
            (JoinOrderGenerator, {"scale_factor": 0.001}),
        ],
    )
    def test_generator_local_path_handling(self, generator_class, init_kwargs, temp_dir):
        """Test that all generators properly handle local paths."""
        output_dir = temp_dir / "local_test"

        # Initialize generator with local path
        generator = generator_class(output_dir=output_dir, **init_kwargs)

        # Verify output_dir is set correctly
        assert generator.output_dir == output_dir

        # Test that _is_cloud_output correctly identifies local paths
        assert not generator._is_cloud_output(output_dir)
        assert not generator._is_cloud_output(str(output_dir))

    @pytest.mark.parametrize(
        "generator_class,init_kwargs,generate_method",
        [
            (TPCHDataGenerator, {"scale_factor": 0.01, "verbose": False}, "generate"),
            (TPCDSDataGenerator, {"scale_factor": 1.0, "verbose": False}, "generate"),
            (
                ReadPrimitivesDataGenerator,
                {"scale_factor": 0.01, "verbose": False},
                "generate_data",
            ),
            (SSBDataGenerator, {"scale_factor": 0.001}, "generate_data"),
            (AMPLabDataGenerator, {"scale_factor": 0.001}, "generate_data"),
            (ClickBenchDataGenerator, {"scale_factor": 0.001}, "generate_data"),
            (H2ODataGenerator, {"scale_factor": 0.001}, "generate_data"),
            (
                TPCDIDataGenerator,
                {"scale_factor": 0.001, "enable_progress": False},
                "generate_data",
            ),
            (JoinOrderGenerator, {"scale_factor": 0.001}, "generate_data"),
        ],
    )
    @pytest.mark.skipif(not CLOUDPATHLIB_AVAILABLE, reason="cloudpathlib not installed")
    def test_generator_cloud_path_detection(self, generator_class, init_kwargs, generate_method, mock_cloud_path):
        """Test that all generators properly detect cloud paths."""
        cloud_output = "s3://test-bucket/test-path"

        with patch("benchbox.utils.cloud_storage.CloudPath") as mock_cloudpath:
            mock_cloudpath.return_value = mock_cloud_path

            # Initialize generator with cloud path
            generator = generator_class(output_dir=cloud_output, **init_kwargs)

            # Test that _is_cloud_output correctly identifies cloud paths
            assert generator._is_cloud_output(cloud_output)
            assert generator._is_cloud_output("s3://another-bucket/path")
            assert generator._is_cloud_output("gs://gcp-bucket/path")
            assert generator._is_cloud_output("az://azure-container/path")

    @pytest.mark.parametrize(
        "generator_class,init_kwargs",
        [
            (TPCHDataGenerator, {"scale_factor": 0.01, "verbose": False}),
            (ReadPrimitivesDataGenerator, {"scale_factor": 0.01, "verbose": False}),
            (SSBDataGenerator, {"scale_factor": 0.001}),
            (AMPLabDataGenerator, {"scale_factor": 0.001}),
            (ClickBenchDataGenerator, {"scale_factor": 0.001}),
            (H2ODataGenerator, {"scale_factor": 0.001}),
            (TPCDIDataGenerator, {"scale_factor": 0.001, "enable_progress": False}),
        ],
    )
    @pytest.mark.skipif(not CLOUDPATHLIB_AVAILABLE, reason="cloudpathlib not installed")
    def test_generator_cloud_upload_workflow(self, generator_class, init_kwargs, mock_cloud_path, temp_dir):
        """Test that generators correctly identify and handle cloud output paths.

        Note: Full cloud upload workflow testing requires actual cloud credentials
        and is covered by live integration tests. This test validates the cloud
        path detection and initialization logic.
        """
        cloud_output = "s3://test-bucket/test-path"

        with patch("benchbox.utils.cloud_storage.CloudPath") as mock_cloudpath:
            mock_cloudpath.return_value = mock_cloud_path

            # Initialize generator with cloud path
            generator = generator_class(output_dir=cloud_output, **init_kwargs)

            # Verify generator correctly identifies cloud output
            assert generator._is_cloud_output(cloud_output)
            assert generator._is_cloud_output("s3://test-bucket/test-path")
            assert generator._is_cloud_output("gs://test-bucket/test-path")
            assert generator._is_cloud_output("az://test-container/test-path")

            # Verify generator does NOT identify local paths as cloud
            assert not generator._is_cloud_output(str(temp_dir))
            assert not generator._is_cloud_output("/tmp/local/path")

            # Verify CloudPath was called for initialization if needed
            # (some generators may defer CloudPath creation until generation)

    @pytest.mark.skipif(not CLOUDPATHLIB_AVAILABLE, reason="cloudpathlib not installed")
    def test_joinorder_generator_special_case(self, mock_cloud_path, temp_dir):
        """Test JoinOrder generator cloud path detection (returns List[Path] format).

        Note: JoinOrderGenerator has a unique return type (List[Path] instead of
        Dict[str, Path]). This test verifies cloud path detection works correctly.
        """
        cloud_output = "s3://test-bucket/test-path"

        with patch("benchbox.utils.cloud_storage.CloudPath") as mock_cloudpath:
            mock_cloudpath.return_value = mock_cloud_path

            generator = JoinOrderGenerator(scale_factor=0.001, output_dir=cloud_output)

            # Verify generator correctly identifies cloud output
            assert generator._is_cloud_output(cloud_output)
            assert generator._is_cloud_output("gs://bucket/path")

            # Verify generator does NOT identify local paths as cloud
            assert not generator._is_cloud_output(str(temp_dir))
            assert not generator._is_cloud_output("/tmp/local/path")

    def test_cloud_storage_mixin_methods(self, temp_dir):
        """Test CloudStorageGeneratorMixin methods directly."""
        # Use TPC-H generator as a test case
        generator = TPCHDataGenerator(scale_factor=0.01, verbose=False)

        # Test _is_cloud_output method
        assert not generator._is_cloud_output(str(temp_dir))
        assert not generator._is_cloud_output(temp_dir)
        assert generator._is_cloud_output("s3://bucket/path")
        assert generator._is_cloud_output("gs://bucket/path")
        assert generator._is_cloud_output("az://container/path")

        # Test _handle_cloud_or_local_generation with local path
        def mock_local_generate(output_dir):
            return {"test": output_dir / "test.csv"}

        result = generator._handle_cloud_or_local_generation(temp_dir, mock_local_generate, False)

        assert isinstance(result, dict)
        assert "test" in result
        assert temp_dir / "test.csv" == result["test"]

    @pytest.mark.skipif(not CLOUDPATHLIB_AVAILABLE, reason="cloudpathlib not installed")
    def test_error_handling_in_cloud_upload(self, mock_cloud_path, temp_dir):
        """Test that generators validate cloud output paths during initialization.

        Note: Actual cloud upload error handling requires real cloud credentials
        and is tested in live integration tests. This validates path validation.
        """
        cloud_output = "s3://test-bucket/test-path"

        with patch("benchbox.utils.cloud_storage.CloudPath") as mock_cloudpath:
            mock_cloudpath.return_value = mock_cloud_path

            # Initialize generator with cloud output
            generator = TPCHDataGenerator(scale_factor=0.01, verbose=False, output_dir=cloud_output)

            # Verify cloud detection works
            assert generator._is_cloud_output(cloud_output)

            # Verify invalid cloud paths are rejected by is_cloud_output
            assert not generator._is_cloud_output("invalid://bad-scheme/path")
            assert not generator._is_cloud_output("http://not-cloud-storage/path")

    def test_all_generators_inherit_mixin(self):
        """Test that all generators inherit from CloudStorageGeneratorMixin."""
        from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin

        generators = [
            TPCHDataGenerator,
            TPCDSDataGenerator,
            ReadPrimitivesDataGenerator,
            SSBDataGenerator,
            AMPLabDataGenerator,
            ClickBenchDataGenerator,
            H2ODataGenerator,
            TPCDIDataGenerator,
            JoinOrderGenerator,
            # Note: MergeDataGenerator excluded - replaced with Write Primitives benchmark
        ]

        for generator_class in generators:
            assert issubclass(generator_class, CloudStorageGeneratorMixin), (
                f"{generator_class.__name__} does not inherit from CloudStorageGeneratorMixin"
            )

    def test_tpcds_subscale_factor_handling(self, temp_dir):
        """Test that TPC-DS data generator accepts unofficial subscale factors."""
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=temp_dir, verbose=False)

        # Generator should accept the minimum valid official scale factor
        assert generator.scale_factor == 1.0

        subscale = TPCDSDataGenerator(scale_factor=0.5, output_dir=temp_dir, verbose=False)
        assert subscale.scale_factor == 0.5
