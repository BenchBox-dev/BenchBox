"""HTTP download primitive with progress, sha256 verification, retry.

Foundation w2 ships a thin synchronous downloader. The contract:

    download(url, dest_path, expected_sha256=None, *, session=None,
             max_retries=3, chunk_size=1<<20) -> Path

- Uses `requests` (already a project dep).
- Streams in 1 MiB chunks; computes sha256 incrementally.
- Resumes via Range header if the destination exists and is partial
  (best-effort; servers without Range support fall back to fresh GET).
- Retries transient failures up to `max_retries` with exponential
  backoff (1s, 2s, 4s, ...).
- On sha256 mismatch (when expected_sha256 is supplied), raises
  ChecksumMismatchError after the file is fully written so the caller
  can inspect/delete it.

Tests use the optional `session` parameter to inject a mock — no
network required for unit-test coverage.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

import requests

from .errors import ChecksumMismatchError, DownloadError

_DEFAULT_CHUNK_SIZE = 1 << 20  # 1 MiB
_BACKOFF_BASE = 1.0  # seconds


def _sha256_of(path: Path, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
    """Compute sha256 of an existing file."""
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
            needed. Resumes from existing partial bytes if present.
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

    sess = session or requests

    for attempt in range(max_retries):
        existing_size = dest.stat().st_size if dest.exists() else 0
        headers: dict[str, str] = {}
        if existing_size > 0:
            headers["Range"] = f"bytes={existing_size}-"

        try:
            with sess.get(url, headers=headers, stream=True, timeout=60) as resp:
                # Server doesn't support Range — start fresh.
                if resp.status_code == 200 and existing_size > 0:
                    existing_size = 0
                    dest.unlink()
                if resp.status_code not in (200, 206):
                    raise DownloadError(f"GET {url} returned status {resp.status_code}")
                mode = "ab" if existing_size > 0 else "wb"
                with dest.open(mode) as fh:
                    for chunk in resp.iter_content(chunk_size=chunk_size):
                        if chunk:
                            fh.write(chunk)
            break
        except (requests.RequestException, DownloadError) as exc:
            if attempt + 1 == max_retries:
                raise DownloadError(f"download failed after {max_retries} attempts: {exc}") from exc
            sleep(_BACKOFF_BASE * (2**attempt))

    if expected_sha256 is not None:
        actual = _sha256_of(dest, chunk_size=chunk_size)
        if actual != expected_sha256:
            raise ChecksumMismatchError(
                path=str(dest),
                expected_sha256=expected_sha256,
                actual_sha256=actual,
            )

    return dest
