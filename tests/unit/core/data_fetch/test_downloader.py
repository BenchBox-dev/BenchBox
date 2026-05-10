"""Tests for benchbox.core.data_fetch.downloader (mocked HTTP).

No network access. Sessions are simulated via tiny stand-ins that
match the requests-style `get(...).iter_content(...)` API the
downloader uses.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable

import pytest
import requests

from benchbox.core.data_fetch import ChecksumMismatchError, DownloadError
from benchbox.core.data_fetch.downloader import _sha256_of, download

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _Resp:
    """Stand-in for a requests Response usable as a context manager."""

    def __init__(self, status_code: int, body: bytes):
        self.status_code = status_code
        self._body = body

    def __enter__(self):  # noqa: D401
        return self

    def __exit__(self, *exc):
        return False

    def iter_content(self, chunk_size: int) -> Iterable[bytes]:
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]


class _Session:
    def __init__(self, responses):
        # responses is a list of (status_code, body) or Exception.
        self._responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, headers=None, stream=False, timeout=None):
        self.calls.append({"url": url, "headers": dict(headers or {})})
        nxt = self._responses.pop(0)
        if isinstance(nxt, BaseException):
            raise nxt
        return _Resp(nxt[0], nxt[1])


def test_download_writes_payload_and_returns_path(tmp_path: Path) -> None:
    body = b"hello data_fetch world"
    sha = hashlib.sha256(body).hexdigest()
    sess = _Session([(200, body)])
    out = download("https://x.test/blob", tmp_path / "blob", expected_sha256=sha, session=sess)
    assert out.read_bytes() == body
    assert _sha256_of(out) == sha


def test_download_checksum_mismatch_raises(tmp_path: Path) -> None:
    body = b"payload"
    sess = _Session([(200, body)])
    with pytest.raises(ChecksumMismatchError) as excinfo:
        download(
            "https://x.test/blob",
            tmp_path / "blob",
            expected_sha256="0" * 64,
            session=sess,
        )
    err = excinfo.value
    assert err.expected_sha256 == "0" * 64
    assert err.actual_sha256 == hashlib.sha256(body).hexdigest()


def test_download_retries_then_succeeds(tmp_path: Path) -> None:
    sleeps: list[float] = []
    body = b"recovered"
    sess = _Session(
        [
            requests.ConnectionError("boom"),
            (200, body),
        ]
    )
    out = download(
        "https://x.test/blob",
        tmp_path / "blob",
        expected_sha256=None,
        session=sess,
        max_retries=3,
        sleep=lambda s: sleeps.append(s),
    )
    assert out.read_bytes() == body
    assert sleeps == [1.0]  # one backoff before the success


def test_download_retries_exhausted_raises(tmp_path: Path) -> None:
    sleeps: list[float] = []
    sess = _Session(
        [
            requests.ConnectionError("boom1"),
            requests.ConnectionError("boom2"),
            requests.ConnectionError("boom3"),
        ]
    )
    with pytest.raises(DownloadError, match="failed after 3 attempts"):
        download(
            "https://x.test/blob",
            tmp_path / "blob",
            expected_sha256=None,
            session=sess,
            max_retries=3,
            sleep=lambda s: sleeps.append(s),
        )
    assert sleeps == [1.0, 2.0]


def test_download_resumes_with_range_header(tmp_path: Path) -> None:
    full = b"abcdef" * 100
    dest = tmp_path / "blob"
    dest.write_bytes(full[:100])  # pretend partial download already on disk
    rest = full[100:]
    sess = _Session([(206, rest)])
    download(
        "https://x.test/blob",
        dest,
        expected_sha256=hashlib.sha256(full).hexdigest(),
        session=sess,
    )
    assert dest.read_bytes() == full
    assert sess.calls[0]["headers"]["Range"] == "bytes=100-"


def test_download_handles_server_without_range_support(tmp_path: Path) -> None:
    full = b"abcdef" * 100
    dest = tmp_path / "blob"
    dest.write_bytes(full[:50])
    # Server returns 200 OK ignoring the Range header — downloader must restart.
    sess = _Session([(200, full)])
    download(
        "https://x.test/blob",
        dest,
        expected_sha256=hashlib.sha256(full).hexdigest(),
        session=sess,
    )
    assert dest.read_bytes() == full
