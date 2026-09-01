"""Unit tests for live publication verification and receipt checking."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import urllib.error
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SCRIPT = Path(__file__).parents[4] / "scripts/publication/verify_live.py"
SPEC = importlib.util.spec_from_file_location("verify_live", SCRIPT)
assert SPEC and SPEC.loader
verify_live_mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_live_mod
SPEC.loader.exec_module(verify_live_mod)


class MockHTTPResponse:
    def __init__(
        self,
        body: bytes,
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self._body = io.BytesIO(body)
        self.status = status
        self.headers = headers or {"content-type": "application/octet-stream", "etag": '"test-etag"'}

    def read(self, size: int = -1) -> bytes:
        return self._body.read(size)

    def __enter__(self) -> MockHTTPResponse:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


def test_extract_expected_checksums_various_formats() -> None:
    # 1. Baseline format
    baseline_fmt = {
        "live_database": {
            "sha256": "aaaa111122223333444455556666777788889999000011112222333344445555",
            "url": "https://benchbox.dev/results/data/results.duckdb",
        }
    }
    extracted = verify_live_mod.extract_expected_checksums(baseline_fmt)
    assert (
        extracted["/results/data/results.duckdb"] == "aaaa111122223333444455556666777788889999000011112222333344445555"
    )

    # 2. Receipt format with checksums mapping
    receipt_fmt = {
        "checksums": {
            "/results/data/results.duckdb": "bbbb",
            "index.html": "cccc",
        }
    }
    extracted2 = verify_live_mod.extract_expected_checksums(receipt_fmt)
    assert extracted2["/results/data/results.duckdb"] == "bbbb"
    assert extracted2["/index.html"] == "cccc"

    # 3. Direct database_sha256 format
    direct_fmt = {"database_sha256": "dddd"}
    extracted3 = verify_live_mod.extract_expected_checksums(direct_fmt)
    assert extracted3["/results/data/results.duckdb"] == "dddd"

    # 4. Artifact list format
    artifact_fmt = {
        "artifacts": [
            {"path": "/results/data/results.duckdb", "sha256": "eeee"},
            {"path": "explorer.js", "sha256": "ffff"},
        ]
    }
    extracted4 = verify_live_mod.extract_expected_checksums(artifact_fmt)
    assert extracted4["/results/data/results.duckdb"] == "eeee"
    assert extracted4["/explorer.js"] == "ffff"


def test_probe_endpoint_success(monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"DuckDB database content payload"
    import hashlib

    expected_sha = hashlib.sha256(content).hexdigest()

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(content, status=200, headers={"etag": "abc"}),
    )

    probe = verify_live_mod.probe_endpoint("https://benchbox.dev", "/results/data/results.duckdb")
    assert probe.ok is True
    assert probe.status_code == 200
    assert probe.sha256 == expected_sha
    assert probe.content_length == len(content)
    assert probe.etag == "abc"
    assert probe.latency_ms >= 0


def test_probe_endpoint_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req, timeout=30):
        raise urllib.error.HTTPError(
            url="https://benchbox.dev/bad",
            code=404,
            msg="Not Found",
            hdrs={},
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    probe = verify_live_mod.probe_endpoint("https://benchbox.dev", "/bad")
    assert probe.ok is False
    assert probe.status_code == 404
    assert "HTTP 404" in probe.error


def test_probe_endpoint_network_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(req, timeout=30):
        raise urllib.error.URLError(reason="Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    probe = verify_live_mod.probe_endpoint("https://benchbox.dev", "/")
    assert probe.ok is False
    assert probe.status_code == 0
    assert "Connection refused" in probe.error


def test_verify_live_passes_matching_checksums(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"sample content"
    import hashlib

    sha = hashlib.sha256(content).hexdigest()

    manifest_file = tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": sha}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(content, status=200),
    )

    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_file,
        require_receipt=True,
        expect_noop=True,
    )

    assert report.ok is True
    assert len(report.errors) == 0
    assert "/results/data/results.duckdb" in report.matched_checksums


def test_verify_live_fails_mismatched_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live_content = b"live mutated content"
    manifest_file = tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": "expected_old_sha"}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(live_content, status=200),
    )

    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_file,
        require_receipt=True,
        expect_noop=False,
    )

    assert report.ok is False
    assert "/results/data/results.duckdb" in report.mismatched_checksums
    assert any("Receipt checksum mismatch" in err for err in report.errors)


def test_verify_live_expect_noop_fails_on_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    live_content = b"live mutated content"
    manifest_file = tmp_path / "baseline.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": "baseline_sha"}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(live_content, status=200),
    )

    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=manifest_file,
        require_receipt=True,
        expect_noop=True,
    )

    assert report.ok is False
    assert any("Unexpected mutation detected during no-op verification" in err for err in report.errors)


def test_verify_live_missing_manifest_when_required() -> None:
    report = verify_live_mod.verify_live(
        base_url="https://benchbox.dev",
        manifest_path=None,
        require_receipt=True,
    )
    assert report.ok is False
    assert any("Receipt verification was required" in err for err in report.errors)


def test_verify_live_main_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"sample content"
    import hashlib

    sha = hashlib.sha256(content).hexdigest()

    manifest_file = tmp_path / "receipt.json"
    manifest_file.write_text(json.dumps({"checksums": {"/results/data/results.duckdb": sha}}))

    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda req, timeout=30: MockHTTPResponse(content, status=200),
    )

    rc = verify_live_mod.main(
        [
            "--base-url",
            "https://benchbox.dev",
            "--manifest",
            str(manifest_file),
            "--require-receipt",
            "--expect-noop",
            "--json",
        ]
    )
    assert rc == 0
