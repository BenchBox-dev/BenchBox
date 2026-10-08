from __future__ import annotations


class DataFetchError(Exception):
    pass


class ManifestValidationError(DataFetchError):
    pass


class ChecksumMismatchError(DataFetchError):
    def __init__(self, *, path: str, expected_sha256: str, actual_sha256: str):
        self.path = path
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256
        super().__init__(f"checksum mismatch for {path}: expected {expected_sha256}, got {actual_sha256}")


class DownloadError(DataFetchError):
    pass
