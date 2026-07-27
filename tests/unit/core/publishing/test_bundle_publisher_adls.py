"""ADLS publishing uses a remote file client instead of local staging wrappers."""

from __future__ import annotations

import sys
from types import ModuleType

import pytest

from benchbox.core.publishing.bundle_publisher import _copy_to_cloud

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def test_copy_to_cloud_uploads_adls_files_directly(tmp_path, monkeypatch):
    uploaded: list[tuple[str, bytes, bool]] = []

    class FileClient:
        def __init__(self, path: str) -> None:
            self.path = path

        def upload_data(self, payload: bytes, *, overwrite: bool) -> None:
            uploaded.append((self.path, payload, overwrite))

    class FileSystem:
        def get_file_client(self, path: str) -> FileClient:
            return FileClient(path)

    class Service:
        def __init__(self, *, account_url: str, credential: object) -> None:
            assert account_url == "https://account.dfs.core.windows.net"
            assert credential == "credential"

        def get_file_system_client(self, container: str) -> FileSystem:
            assert container == "container"
            return FileSystem()

    azure = ModuleType("azure")
    azure.__path__ = []  # type: ignore[attr-defined]
    identity = ModuleType("azure.identity")
    identity.DefaultAzureCredential = lambda: "credential"  # type: ignore[attr-defined]
    storage = ModuleType("azure.storage")
    storage.__path__ = []  # type: ignore[attr-defined]
    filedatalake = ModuleType("azure.storage.filedatalake")
    filedatalake.DataLakeServiceClient = Service  # type: ignore[attr-defined]
    monkeypatch.setitem(
        sys.modules,
        "azure",
        azure,
    )
    monkeypatch.setitem(sys.modules, "azure.identity", identity)
    monkeypatch.setitem(sys.modules, "azure.storage", storage)
    monkeypatch.setitem(sys.modules, "azure.storage.filedatalake", filedatalake)

    source = tmp_path / "bundle.json"
    source.write_bytes(b"bundle")

    _copy_to_cloud([source], "abfss://container@account.dfs.core.windows.net/prefix")

    assert uploaded == [("prefix/bundle.json", b"bundle", True)]
