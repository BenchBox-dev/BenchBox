from __future__ import annotations

import hashlib
import os
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from .errors import ChecksumMismatchError, DownloadError

_DEFAULT_CHUNK_SIZE = 1 << 20
_BACKOFF_BASE = 1.0


def sha256_of(path: Path, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> str:
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
    dest = Path(dest_path)
    dest.parent.mkdir(parents=True, exist_ok=True)

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
                rejected = dest.parent / f"{dest.name}.rejected"
                os.replace(tmp, rejected)
                raise ChecksumMismatchError(
                    path=str(rejected),
                    expected_sha256=expected_sha256,
                    actual_sha256=actual,
                )

        os.replace(tmp, dest)
        return dest
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
