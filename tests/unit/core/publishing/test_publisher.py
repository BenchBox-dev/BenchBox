"""Tests for publishing pipeline module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
from pathlib import Path

import pytest

from benchbox.core.publishing.artifacts import (
    ArtifactMetadata,
    ArtifactStatus,
    ArtifactType,
)
from benchbox.core.publishing.config import (
    PublishFormat,
    PublishingConfig,
    StorageConfig,
    StorageProvider,
)
from benchbox.core.publishing.publisher import (
    PublishBatchResult,
    Publisher,
    PublishResult,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestPublishResult:
    """Tests for PublishResult dataclass."""

    def test_basic_creation(self):
        """Should create publish result."""
        result = PublishResult(success=True)
        assert result.success is True
        assert result.artifact is None
        assert result.permalink is None
        assert result.errors == []

    def test_with_errors(self):
        """Should include errors."""
        result = PublishResult(
            success=False,
            errors=["Error 1", "Error 2"],
        )
        assert result.success is False
        assert len(result.errors) == 2

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = PublishResult(
            success=True,
            published_paths={"json": "/path/to/file.json"},
        )
        d = result.to_dict()
        assert d["success"] is True
        assert "published_paths" in d
        assert "published_at" in d


class TestPublishBatchResult:
    """Tests for PublishBatchResult dataclass."""

    def test_basic_creation(self):
        """Should create batch result."""
        result = PublishBatchResult(total=5)
        assert result.total == 5
        assert result.successful == 0
        assert result.failed == 0

    def test_to_dict(self):
        """Should convert to dictionary."""
        result = PublishBatchResult(
            total=5,
            successful=3,
            failed=2,
        )
        d = result.to_dict()
        assert d["total"] == 5
        assert d["successful"] == 3
        assert d["failed"] == 2


class TestPublisher:
    """Tests for Publisher class."""

    @pytest.fixture
    def publisher(self, tmp_path):
        """Create publisher with temporary local storage."""
        config = PublishingConfig(
            primary_storage=StorageConfig(
                provider=StorageProvider.LOCAL,
                bucket=str(tmp_path / "published"),
            ),
            formats=[PublishFormat.JSON, PublishFormat.HTML],
            generate_permalinks=True,
        )
        return Publisher(config)

    @pytest.fixture
    def sample_result(self):
        """Create sample benchmark result."""
        return {
            "benchmark_name": "tpch",
            "platform": "duckdb",
            "scale_factor": 1.0,
            "execution_id": "test123",
            "timestamp": "2025-01-01T00:00:00Z",
            "query_results": [
                {"query_id": "q1", "execution_time_ms": 100, "status": "SUCCESS"},
                {"query_id": "q2", "execution_time_ms": 200, "status": "SUCCESS"},
            ],
        }

    def test_basic_creation(self, tmp_path):
        """Should create publisher with config."""
        config = PublishingConfig.for_local(str(tmp_path / "test"))
        publisher = Publisher(config)
        assert publisher.config is config

    def test_default_config(self):
        """Should use default config if not provided."""
        publisher = Publisher()
        assert isinstance(publisher.config, PublishingConfig)

    def test_creates_local_directory(self, tmp_path):
        """Should create local storage directory."""
        path = tmp_path / "new_dir"
        config = PublishingConfig.for_local(str(path))
        Publisher(config)
        assert path.exists()

    def test_publish_result(self, publisher, sample_result):
        """Should publish result."""
        result = publisher.publish_result(sample_result)
        assert result.success is True
        assert result.artifact is not None
        assert len(result.published_paths) >= 1
        assert "json" in result.published_paths

    def test_publish_result_with_metadata(self, publisher, sample_result):
        """Should publish with custom metadata."""
        metadata = ArtifactMetadata(
            benchmark_name="custom_bench",
            platform="custom_platform",
            tags=["test"],
        )
        result = publisher.publish_result(sample_result, metadata=metadata)
        assert result.success is True
        assert result.artifact.metadata.benchmark_name == "custom_bench"

    def test_publish_result_with_name(self, publisher, sample_result):
        """Should publish with custom name."""
        result = publisher.publish_result(sample_result, name="my_result")
        assert result.success is True
        assert "my_result" in result.artifact.name

    def test_publish_generates_permalink(self, publisher, sample_result):
        """Should generate permalink."""
        result = publisher.publish_result(sample_result)
        assert result.permalink is not None
        assert result.permalink.short_code.startswith("bx_")

    def test_publish_result_extracts_metadata(self, publisher, sample_result):
        """Should extract metadata from result."""
        result = publisher.publish_result(sample_result)
        assert result.artifact.metadata.benchmark_name == "tpch"
        assert result.artifact.metadata.platform == "duckdb"

    def test_publish_multiple_formats(self, publisher, sample_result):
        """Should publish to all configured formats."""
        result = publisher.publish_result(sample_result)
        assert "json" in result.published_paths
        assert "html" in result.published_paths

    def test_publish_file(self, publisher, tmp_path):
        """Should publish existing file."""
        source = tmp_path / "source.json"
        source.write_text(json.dumps({"test": "data"}))

        result = publisher.publish_file(
            source_path=source,
            artifact_type=ArtifactType.RESULT,
        )
        assert result.success is True
        assert result.artifact is not None
        assert result.permalink is not None

    def test_publish_file_not_found(self, publisher, tmp_path):
        """Should handle missing file."""
        result = publisher.publish_file(
            source_path=tmp_path / "nonexistent.json",
            artifact_type=ArtifactType.RESULT,
        )
        assert result.success is False
        assert "not found" in result.errors[0].lower()

    def test_publish_file_with_metadata(self, publisher, tmp_path):
        """Should publish file with metadata."""
        source = tmp_path / "source.json"
        source.write_text("{}")

        metadata = ArtifactMetadata(benchmark_name="test")
        result = publisher.publish_file(source, ArtifactType.RESULT, metadata=metadata)
        assert result.artifact.metadata.benchmark_name == "test"

    def test_publish_batch(self, publisher):
        """Should publish batch of results."""
        items = [
            ({"benchmark_name": "tpch", "platform": "duckdb"}, None),
            ({"benchmark_name": "tpcds", "platform": "duckdb"}, None),
            ({"benchmark_name": "ssb", "platform": "duckdb"}, None),
        ]
        batch_result = publisher.publish_batch(items)
        assert batch_result.total == 3
        assert batch_result.successful == 3
        assert batch_result.failed == 0

    def test_publish_batch_with_metadata(self, publisher):
        """Should publish batch with metadata."""
        items = [
            (
                {"benchmark_name": "tpch"},
                ArtifactMetadata(benchmark_name="tpch", tags=["test"]),
            ),
        ]
        batch_result = publisher.publish_batch(items)
        assert batch_result.successful == 1
        assert batch_result.results[0].artifact.metadata.tags == ["test"]

    def test_apply_retention(self, publisher, sample_result):
        """Should apply retention policy."""
        # Publish some results
        for _ in range(5):
            publisher.publish_result(sample_result)

        retention_result = publisher.apply_retention()
        assert "artifacts_archived" in retention_result
        assert "permalinks_expired" in retention_result

    def test_get_statistics(self, publisher, sample_result):
        """Should get publishing statistics."""
        publisher.publish_result(sample_result)
        stats = publisher.get_statistics()
        assert "artifacts" in stats
        assert "permalinks" in stats
        assert "storage" in stats
        assert stats["artifacts"]["total_artifacts"] >= 1

    def test_export_manifest(self, publisher, sample_result):
        """Should export manifest."""
        publisher.publish_result(sample_result)
        manifest = publisher.export_manifest()
        assert "generated_at" in manifest
        assert "config" in manifest
        assert "artifacts" in manifest
        assert "permalinks" in manifest
        assert "statistics" in manifest


class TestPublisherOutputFormats:
    """Tests for different output formats."""

    @pytest.fixture
    def publisher_all_formats(self, tmp_path):
        """Create publisher with all formats enabled."""
        config = PublishingConfig(
            primary_storage=StorageConfig(
                provider=StorageProvider.LOCAL,
                bucket=str(tmp_path / "published"),
            ),
            formats=[PublishFormat.JSON, PublishFormat.HTML, PublishFormat.CSV],
        )
        return Publisher(config)

    def test_json_output(self, publisher_all_formats):
        """Should generate valid JSON."""
        result = publisher_all_formats.publish_result({"benchmark_name": "test", "data": [1, 2, 3]})
        json_path = Path(result.published_paths["json"])
        assert json_path.exists()
        data = json.loads(json_path.read_text())
        assert data["benchmark_name"] == "test"
        assert "_published" in data

    def test_html_output(self, publisher_all_formats):
        """Should generate HTML report."""
        result = publisher_all_formats.publish_result({"benchmark_name": "test", "platform": "duckdb"})
        html_path = Path(result.published_paths["html"])
        assert html_path.exists()
        content = html_path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "test" in content

    def test_csv_output(self, publisher_all_formats):
        """Should generate CSV."""
        result = publisher_all_formats.publish_result({"benchmark_name": "test", "value": 123})
        csv_path = Path(result.published_paths["csv"])
        assert csv_path.exists()
        content = csv_path.read_text()
        assert "Key,Value" in content


class TestPublisherWithoutPermalinks:
    """Tests for publishing without permalinks."""

    @pytest.fixture
    def publisher(self, tmp_path):
        """Create publisher without permalink generation."""
        config = PublishingConfig(
            primary_storage=StorageConfig(
                provider=StorageProvider.LOCAL,
                bucket=str(tmp_path / "published"),
            ),
            generate_permalinks=False,
        )
        return Publisher(config)

    def test_no_permalink_generated(self, publisher):
        """Should not generate permalink."""
        result = publisher.publish_result({"test": "data"})
        assert result.success is True
        assert result.permalink is None


class TestPublisherEdgeCases:
    """Edge case tests for Publisher."""

    @pytest.fixture
    def publisher(self, tmp_path):
        """Create publisher."""
        config = PublishingConfig.for_local(str(tmp_path / "published"))
        return Publisher(config)

    def test_publish_empty_result(self, publisher):
        """Should handle empty result."""
        result = publisher.publish_result({})
        assert result.success is True

    def test_publish_complex_result(self, publisher):
        """Should handle complex nested result."""
        result = publisher.publish_result(
            {
                "nested": {"deep": {"value": [1, 2, {"a": "b"}]}},
                "timestamp": "2025-01-01T00:00:00",
            }
        )
        assert result.success is True

    def test_publish_result_object(self, publisher):
        """Should handle result objects with to_dict method."""

        class MockResult:
            def __init__(self):
                self.benchmark_name = "mock"
                self.platform = "mock_platform"
                self.scale_factor = 1.0
                self.execution_id = "mock123"

            def to_dict(self):
                return {
                    "benchmark_name": self.benchmark_name,
                    "platform": self.platform,
                }

        result = publisher.publish_result(MockResult())
        assert result.success is True
        assert result.artifact.metadata.benchmark_name == "mock"

    def test_publish_string_result(self, publisher):
        """Should handle string result."""
        result = publisher.publish_result("simple string result")
        assert result.success is True

    def test_artifact_marked_published(self, publisher):
        """Should mark artifact as published."""
        result = publisher.publish_result({"test": "data"})
        assert result.artifact.status == ArtifactStatus.PUBLISHED
        assert result.artifact.published_at is not None
        assert result.artifact.published_path != ""
