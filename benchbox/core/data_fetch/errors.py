"""Exception hierarchy for data_fetch.

All exceptions are benchmark-agnostic by contract — joinorder-specific
exception subclasses are forbidden by the foundation TODO's
anti_patterns. Add a new error class here only if it represents a new
generic failure mode that any real-data benchmark could surface.
"""

from __future__ import annotations


class DataFetchError(Exception):
    """Base class for all data_fetch failures."""


class ManifestValidationError(DataFetchError):
    """data_manifest.toml is malformed, missing fields, or fails schema validation."""


class ChecksumMismatchError(DataFetchError):
    """Downloaded or pre-populated file does not match a manifest sha256.

    Attributes record what was expected vs observed so the caller can
    surface the diff without re-reading the file.
    """

    def __init__(self, *, path: str, expected_sha256: str, actual_sha256: str):
        self.path = path
        self.expected_sha256 = expected_sha256
        self.actual_sha256 = actual_sha256
        super().__init__(f"checksum mismatch for {path}: expected {expected_sha256}, got {actual_sha256}")


class DownloadError(DataFetchError):
    """HTTP-layer failure with no successful retry remaining."""
