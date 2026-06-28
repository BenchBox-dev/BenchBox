"""HTTP download primitive with progress, sha256 verification, retry.

Foundation w2 ships a thin synchronous downloader. The contract:

    download(url, dest_path, expected_sha256=None, *, session=None,
             max_retries=3, chunk_size=1<<20) -> Path

- Uses `requests` (already a project dep).
- Streams in 1 MiB chunks; computes sha256 incrementally.
- Writes to a process-unique `<dest>.<pid>.<token>.part` temp file and
  atomically `os.replace()`s it onto `dest` only after the checksum
  verifies. The final path therefore only ever appears as a complete,
  verified file — concurrent callers can never observe or corrupt a
  partially written archive at the shared destination.
- Resumes via Range header within a call if a transient failure left
  partial bytes in the temp file (best-effort; servers without Range
  support fall back to a fresh GET).
- Retries transient failures up to `max_retries` with exponential
  backoff (1s, 2s, 4s, ...).
- On sha256 mismatch (when expected_sha256 is supplied), moves the
  rejected bytes to `<dest>.rejected` (never the final path) and raises
  ChecksumMismatchError so the caller can inspect/delete them.

Tests use the optional `session` parameter to inject a mock — no
network required for unit-test coverage.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from .errors import ChecksumMismatchError, DownloadError

_DEFAULT_CHUNK_SIZE = 1 << 20  # 1 MiB
_BACKOFF_BASE = 1.0  # seconds


def sha256_of(path: Path, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
    """Compute sha256 of an existing file by streaming `chunk_size` bytes at a time."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def download(
    url: str,
    dest_path: str | Path,
    expected_sha256: str | None = None,
    *,
    session: Any | None = None,
    max_retries: int = 3,
    chunk_size: int = _DEFAULT_CHUNK_SIZE,
    sleep: Any = time.sleep,
) -> Path:
    """Stream-download `url` to `dest_path`, optionally checksum-verified.

    Args:
        url: HTTP(S) URL.
        dest_path: Destination file path. Parent dir is created if
            needed. The download streams to a process-unique temp file
            and is atomically published onto this path only after the
            checksum verifies.
        expected_sha256: If given, the final file's sha256 must match.
        session: Optional `requests.Session`-like object. When supplied,
            the downloader uses it instead of `requests` directly. Used
            by tests for mocking; production code passes None.
        max_retries: Retry attempts on transient failures
            (ConnectionError, Timeout, 5xx). Default 3.
        chunk_size: Streaming chunk size in bytes. Default 1 MiB.
        sleep: Sleep callable (testable seam).

    Returns:
        Resolved Path to the downloaded file.

    Raises:
        DownloadError: All retries exhausted.
        ChecksumMismatchError: Final sha256 != expected_sha256.
    """
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Stream to a process-unique temp file so two concurrent callers
    # targeting the same `dest` never write to the same bytes, and `dest`
    # itself is only ever created via an atomic replace of a verified file.
    tmp = dest.parent / f"{dest.name}.{os.getpid()}.{uuid.uuid4().hex}.part"

    sess = session or requests

    try:
        for attempt in range(max_retries):
            existing_size = tmp.stat().st_size if tmp.exists() else 0
            headers: dict[str, str] = {}
            if existing_size > 0:
                headers["Range"] = f"bytes={existing_size}-"

            try:
                with sess.get(url, headers=headers, stream=True, timeout=60) as resp:
                    # Server doesn't support Range — start fresh.
                    if resp.status_code == 200 and existing_size > 0:
                        existing_size = 0
                        tmp.unlink()
                    if resp.status_code not in (200, 206):
                        raise DownloadError(f"GET {url} returned status {resp.status_code}")
                    mode = "ab" if existing_size > 0 else "wb"
                    with tmp.open(mode) as fh:
                        for chunk in resp.iter_content(chunk_size=chunk_size):
                            if chunk:
                                fh.write(chunk)
                break
            except (requests.RequestException, DownloadError) as exc:
                if attempt + 1 == max_retries:
                    tmp.unlink(missing_ok=True)
                    raise DownloadError(f"download failed after {max_retries} attempts: {exc}") from exc
                sleep(_BACKOFF_BASE * (2**attempt))

        if expected_sha256 is not None:
            actual = sha256_of(tmp, chunk_size=chunk_size)
            if actual != expected_sha256:
                # Preserve the rejected bytes for inspection, but never at
                # the final path — keep `dest` absent so a corrupt download
                # can't masquerade as a verified archive.
                rejected = dest.parent / f"{dest.name}.rejected"
                os.replace(tmp, rejected)
                raise ChecksumMismatchError(
                    path=str(rejected),
                    expected_sha256=expected_sha256,
                    actual_sha256=actual,
                )

        # Atomic publish: `dest` appears only as the complete, verified file.
        os.replace(tmp, dest)
        return dest
    finally:
        # Never leak the temp file on an unexpected control-flow exit.
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
