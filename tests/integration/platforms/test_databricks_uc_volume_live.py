"""Live integration tests for Databricks UC Volume upload/download functionality.

These tests require actual Databricks credentials and will create/cleanup resources.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from benchbox.platforms.databricks.adapter import DatabricksAdapter
from benchbox.utils.cloud_storage import DatabricksPath

# Skip all tests if Databricks credentials not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
    pytest.mark.skipif(
        not all(
            [
                os.getenv("DATABRICKS_SERVER_HOSTNAME"),
                os.getenv("DATABRICKS_HTTP_PATH"),
                os.getenv("DATABRICKS_ACCESS_TOKEN"),
            ]
        ),
        reason="Databricks credentials not configured (need DATABRICKS_SERVER_HOSTNAME, DATABRICKS_HTTP_PATH, DATABRICKS_ACCESS_TOKEN)",
    ),
]


@pytest.fixture
def databricks_adapter():
    """Create a DatabricksAdapter using environment credentials."""
    adapter = DatabricksAdapter(
        server_hostname=os.getenv("DATABRICKS_SERVER_HOSTNAME"),
        http_path=os.getenv("DATABRICKS_HTTP_PATH"),
        access_token=os.getenv("DATABRICKS_ACCESS_TOKEN"),
        catalog=os.getenv("DATABRICKS_CATALOG", "workspace"),
        schema="benchbox_test_uc_volume",
        uc_catalog=os.getenv("DATABRICKS_CATALOG", "workspace"),
        uc_schema="benchbox_test_uc_volume",
        uc_volume="test_upload",
        very_verbose=True,
    )
    return adapter


@pytest.fixture
def test_data_files(tmp_path: Path) -> dict[str, Path]:
    """Create test data files with known content."""
    data_dir = tmp_path / "test_data"
    data_dir.mkdir()

    # Create single file (small - 100 bytes)
    single_file = data_dir / "customer.tbl.zst"
    single_file.write_bytes(b"C" * 100)

    # Create sharded files (small - 50 bytes each)
    shard1 = data_dir / "orders.tbl.1.zst"
    shard1.write_bytes(b"O1" * 25)

    shard2 = data_dir / "orders.tbl.2.zst"
    shard2.write_bytes(b"O2" * 25)

    return {
        "data_dir": data_dir,
        "single": single_file,
        "shard1": shard1,
        "shard2": shard2,
    }


def test_uc_volume_single_file_upload_and_download(
    databricks_adapter: DatabricksAdapter, test_data_files: dict[str, Path], tmp_path: Path
):
    """Test uploading a single file to UC Volume and downloading it back to verify content.

    This test:
    1. Creates a small test file with known content
    2. Uploads it to UC Volume using _upload_to_uc_volume
    3. Downloads it back using Databricks SDK
    4. Verifies the content matches
    5. Cleans up the UC Volume file
    """
    from databricks.sdk import WorkspaceClient

    data_dir = test_data_files["data_dir"]
    single_file = test_data_files["single"]
    original_content = single_file.read_bytes()

    # Setup UC Volume path
    uc_volume_path = (
        f"dbfs:/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}"
    )

    # Create connection and ensure UC Volume exists
    connection = databricks_adapter.create_connection()
    try:
        databricks_adapter._ensure_uc_volume_exists(uc_volume_path, connection)

        # Create DatabricksPath to simulate real scenario
        databricks_path = DatabricksPath(local_path=data_dir, dbfs_target=uc_volume_path)

        # Upload the file
        data_files = {"customer": single_file}
        result = databricks_adapter._upload_to_uc_volume(
            data_files=data_files,
            data_dir=databricks_path,
            uc_volume_path=uc_volume_path,
        )

        # Verify upload result
        assert "customer" in result
        expected_uri = f"{uc_volume_path}/customer.tbl.zst"
        assert result["customer"] == expected_uri

        # Download the file back to verify content
        workspace = WorkspaceClient(
            host=f"https://{databricks_adapter.server_hostname}",
            token=databricks_adapter.access_token,
        )

        # Download from UC Volume
        download_path = f"/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}/customer.tbl.zst"

        # Read back the uploaded content
        with workspace.files.download(download_path) as download_response:  # ty: ignore[invalid-context-manager]
            downloaded_content = download_response.contents.read()

        # Verify content matches
        assert downloaded_content == original_content, (
            f"Downloaded content does not match original. Expected {len(original_content)} bytes, got {len(downloaded_content)} bytes"
        )

        # Cleanup - delete the uploaded file
        workspace.files.delete(download_path)

    finally:
        databricks_adapter.close_connection(connection)


def test_uc_volume_sharded_files_upload_and_download(
    databricks_adapter: DatabricksAdapter, test_data_files: dict[str, Path], tmp_path: Path
):
    """Test uploading sharded files to UC Volume and downloading them back.

    This test:
    1. Creates multiple shard files with known content
    2. Uploads them using _upload_to_uc_volume (which should detect all shards)
    3. Downloads each shard back
    4. Verifies all shard contents match
    5. Verifies the returned URI uses wildcard pattern
    6. Cleans up all shard files
    """
    from databricks.sdk import WorkspaceClient

    data_dir = test_data_files["data_dir"]
    shard1 = test_data_files["shard1"]
    shard2 = test_data_files["shard2"]

    shard1_content = shard1.read_bytes()
    shard2_content = shard2.read_bytes()

    # Setup UC Volume path
    uc_volume_path = (
        f"dbfs:/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}"
    )

    # Create connection and ensure UC Volume exists
    connection = databricks_adapter.create_connection()
    try:
        databricks_adapter._ensure_uc_volume_exists(uc_volume_path, connection)

        # Create DatabricksPath to simulate real scenario
        databricks_path = DatabricksPath(local_path=data_dir, dbfs_target=uc_volume_path)

        # Upload - provide only first shard, should detect and upload all
        data_files = {"orders": shard1}
        result = databricks_adapter._upload_to_uc_volume(
            data_files=data_files,
            data_dir=databricks_path,
            uc_volume_path=uc_volume_path,
        )

        # Verify upload result uses wildcard pattern
        assert "orders" in result
        expected_pattern = f"{uc_volume_path}/orders.tbl.*.zst"
        assert result["orders"] == expected_pattern

        # Download the files back to verify content
        workspace = WorkspaceClient(
            host=f"https://{databricks_adapter.server_hostname}",
            token=databricks_adapter.access_token,
        )

        # Download shard 1
        shard1_path = f"/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}/orders.tbl.1.zst"
        with workspace.files.download(shard1_path) as download_response:  # ty: ignore[invalid-context-manager]
            downloaded_shard1 = download_response.contents.read()

        # Download shard 2
        shard2_path = f"/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}/orders.tbl.2.zst"
        with workspace.files.download(shard2_path) as download_response:  # ty: ignore[invalid-context-manager]
            downloaded_shard2 = download_response.contents.read()

        # Verify contents match
        assert downloaded_shard1 == shard1_content, (
            f"Shard 1 content mismatch. Expected {len(shard1_content)} bytes, got {len(downloaded_shard1)} bytes"
        )
        assert downloaded_shard2 == shard2_content, (
            f"Shard 2 content mismatch. Expected {len(shard2_content)} bytes, got {len(downloaded_shard2)} bytes"
        )

        # Cleanup - delete both shard files
        workspace.files.delete(shard1_path)
        workspace.files.delete(shard2_path)

    finally:
        databricks_adapter.close_connection(connection)


def test_uc_volume_empty_file_is_not_uploaded(databricks_adapter: DatabricksAdapter, test_data_files: dict[str, Path]):
    """Test that empty files are skipped during upload.

    This test:
    1. Creates an empty file
    2. Attempts to upload it
    3. Verifies it was not uploaded (result should be empty)
    4. Verifies the file does not exist in UC Volume
    """
    from databricks.sdk import WorkspaceClient

    data_dir = test_data_files["data_dir"]

    # Create an empty file
    empty_file = data_dir / "empty.tbl.zst"
    empty_file.write_bytes(b"")

    # Setup UC Volume path
    uc_volume_path = (
        f"dbfs:/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}"
    )

    # Create connection and ensure UC Volume exists
    connection = databricks_adapter.create_connection()
    try:
        databricks_adapter._ensure_uc_volume_exists(uc_volume_path, connection)

        # Create DatabricksPath
        databricks_path = DatabricksPath(local_path=data_dir, dbfs_target=uc_volume_path)

        # Attempt to upload empty file
        data_files = {"empty": empty_file}
        result = databricks_adapter._upload_to_uc_volume(
            data_files=data_files,
            data_dir=databricks_path,
            uc_volume_path=uc_volume_path,
        )

        # Verify result is empty (file was skipped)
        assert result == {}, f"Expected empty result for empty file, got: {result}"

        # Verify file does not exist in UC Volume
        workspace = WorkspaceClient(
            host=f"https://{databricks_adapter.server_hostname}",
            token=databricks_adapter.access_token,
        )

        empty_file_path = f"/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}/empty.tbl.zst"

        # Try to check if file exists - should not exist
        file_exists = False
        try:
            workspace.files.get_status(empty_file_path)
            file_exists = True
        except Exception:
            # File doesn't exist - this is expected
            pass

        assert not file_exists, "Empty file should not have been uploaded to UC Volume"

    finally:
        databricks_adapter.close_connection(connection)


def test_uc_volume_nonexistent_file_is_skipped(databricks_adapter: DatabricksAdapter, test_data_files: dict[str, Path]):
    """Test that nonexistent files are logged and skipped, while valid files are still uploaded.

    This test:
    1. Creates one valid file and references one nonexistent file
    2. Attempts to upload both
    3. Verifies only the valid file was uploaded
    4. Verifies the valid file content is correct
    5. Cleans up the valid file
    """
    from databricks.sdk import WorkspaceClient

    data_dir = test_data_files["data_dir"]
    valid_file = test_data_files["single"]
    valid_content = valid_file.read_bytes()

    # Reference a nonexistent file
    nonexistent_file = data_dir / "nonexistent.tbl.zst"

    # Setup UC Volume path
    uc_volume_path = (
        f"dbfs:/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}"
    )

    # Create connection and ensure UC Volume exists
    connection = databricks_adapter.create_connection()
    try:
        databricks_adapter._ensure_uc_volume_exists(uc_volume_path, connection)

        # Create DatabricksPath
        databricks_path = DatabricksPath(local_path=data_dir, dbfs_target=uc_volume_path)

        # Attempt to upload both files
        data_files = {
            "nonexistent": nonexistent_file,
            "customer": valid_file,
        }
        result = databricks_adapter._upload_to_uc_volume(
            data_files=data_files,
            data_dir=databricks_path,
            uc_volume_path=uc_volume_path,
        )

        # Verify only valid file was uploaded
        assert "customer" in result
        assert "nonexistent" not in result

        # Download and verify content
        workspace = WorkspaceClient(
            host=f"https://{databricks_adapter.server_hostname}",
            token=databricks_adapter.access_token,
        )

        customer_path = f"/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}/customer.tbl.zst"
        with workspace.files.download(customer_path) as download_response:  # ty: ignore[invalid-context-manager]
            downloaded_content = download_response.contents.read()

        assert downloaded_content == valid_content

        # Verify nonexistent file was not uploaded
        nonexistent_path = f"/Volumes/{databricks_adapter.uc_catalog}/{databricks_adapter.uc_schema}/{databricks_adapter.uc_volume}/nonexistent.tbl.zst"
        file_exists = False
        try:
            workspace.files.get_status(nonexistent_path)
            file_exists = True
        except Exception:
            pass

        assert not file_exists, "Nonexistent file should not have been uploaded"

        # Cleanup
        workspace.files.delete(customer_path)

    finally:
        databricks_adapter.close_connection(connection)
