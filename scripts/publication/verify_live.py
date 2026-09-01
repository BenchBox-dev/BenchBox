#!/usr/bin/env python3
"""Verify live publication endpoints, receipts, and no-op deployment invariants.

This script inspects live publication endpoints (e.g. public documentation,
Results Explorer, and the public DuckDB database), comparing live checksums
and headers against a deployment receipt or publication baseline.

Contract:
- Probes required publication endpoints for responsiveness (200 OK) and latency.
- When --require-receipt is provided, requires a valid manifest/receipt and
  verifies that live endpoint hashes match expected values.
- When --expect-noop is provided, verifies that live deployment checksums match
  the baseline/receipt and no unexpected mutation occurred.
- Outputs structured diagnostic summary with timing and status codes.

Exit codes:
  0 - All live probes and receipt verifications passed.
  1 - Verification failure (HTTP error, checksum mismatch, unexpected mutation).
  2 - Configuration or usage error (unreadable manifest, invalid arguments).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://benchbox.dev"
DEFAULT_TIMEOUT = 30.0
DEFAULT_ENDPOINTS = (
    "/",
    "/results/",
    "/results/data/results.duckdb",
)


@dataclass
class EndpointProbeResult:
    path: str
    url: str
    status_code: int = 0
    ok: bool = False
    latency_ms: float = 0.0
    sha256: str | None = None
    content_length: int | None = None
    etag: str | None = None
    last_modified: str | None = None
    cache_control: str | None = None
    error: str | None = None


@dataclass
class VerificationReport:
    base_url: str
    ok: bool = True
    expect_noop: bool = False
    require_receipt: bool = False
    errors: list[str] = field(default_factory=list)
    probes: list[EndpointProbeResult] = field(default_factory=list)
    matched_checksums: dict[str, str] = field(default_factory=dict)
    mismatched_checksums: dict[str, dict[str, str]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "ok": self.ok,
            "expect_noop": self.expect_noop,
            "require_receipt": self.require_receipt,
            "errors": self.errors,
            "matched_checksums": self.matched_checksums,
            "mismatched_checksums": self.mismatched_checksums,
            "probes": [asdict(p) for p in self.probes],
        }


def extract_expected_checksums(manifest_data: dict[str, Any]) -> dict[str, str]:
    """Extract expected path -> sha256 checksums from various manifest/receipt formats."""
    expected: dict[str, str] = {}

    # Format 1: Publication baseline schema (e.g. publication-baseline-2026-08-31.json)
    if "live_database" in manifest_data and isinstance(manifest_data["live_database"], dict):
        db_info = manifest_data["live_database"]
        if "sha256" in db_info and db_info["sha256"]:
            expected["/results/data/results.duckdb"] = db_info["sha256"]

    # Format 2: Direct receipt format with checksums / files mapping
    if "checksums" in manifest_data and isinstance(manifest_data["checksums"], dict):
        for raw_path, sha in manifest_data["checksums"].items():
            norm_path = raw_path if raw_path.startswith("/") else f"/{raw_path}"
            expected[norm_path] = str(sha).strip()

    if "database_sha256" in manifest_data and manifest_data["database_sha256"]:
        expected["/results/data/results.duckdb"] = str(manifest_data["database_sha256"]).strip()

    if "artifacts" in manifest_data and isinstance(manifest_data["artifacts"], list):
        for artifact in manifest_data["artifacts"]:
            if isinstance(artifact, dict) and "path" in artifact and "sha256" in artifact:
                p = artifact["path"]
                norm_p = p if p.startswith("/") else f"/{p}"
                expected[norm_p] = str(artifact["sha256"]).strip()

    return expected


def probe_endpoint(
    base_url: str,
    path: str,
    timeout: float = DEFAULT_TIMEOUT,
    compute_hash: bool = True,
) -> EndpointProbeResult:
    """Probe a single endpoint over HTTP/HTTPS, computing latency, status, and SHA-256."""
    norm_path = path if path.startswith("/") else f"/{path}"
    full_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", norm_path.lstrip("/"))
    result = EndpointProbeResult(path=norm_path, url=full_url)

    start_time = time.monotonic()
    req = urllib.request.Request(
        full_url,
        headers={"User-Agent": "BenchBox-verify-live/1.0"},
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:  # noqa: S310
            elapsed = (time.monotonic() - start_time) * 1000.0
            result.latency_ms = round(elapsed, 2)
            result.status_code = getattr(response, "status", 200)
            headers = {k.lower(): v for k, v in response.headers.items()}
            result.etag = headers.get("etag")
            result.last_modified = headers.get("last-modified")
            result.cache_control = headers.get("cache-control")

            if compute_hash:
                hasher = hashlib.sha256()
                total_bytes = 0
                while chunk := response.read(65536):
                    hasher.update(chunk)
                    total_bytes += len(chunk)
                result.sha256 = hasher.hexdigest()
                result.content_length = total_bytes
            else:
                if "content-length" in headers:
                    try:
                        result.content_length = int(headers["content-length"])
                    except ValueError:
                        pass

            result.ok = 200 <= result.status_code < 300

    except urllib.error.HTTPError as exc:
        result.latency_ms = round((time.monotonic() - start_time) * 1000.0, 2)
        result.status_code = exc.code
        result.ok = False
        result.error = f"HTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        result.latency_ms = round((time.monotonic() - start_time) * 1000.0, 2)
        result.ok = False
        result.error = f"Network URL error: {exc.reason}"
    except Exception as exc:
        result.latency_ms = round((time.monotonic() - start_time) * 1000.0, 2)
        result.ok = False
        result.error = f"Probe error: {type(exc).__name__}: {exc}"

    return result


def verify_live(
    base_url: str,
    manifest_path: Path | None = None,
    require_receipt: bool = False,
    expect_noop: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    endpoints: list[str] | None = None,
) -> VerificationReport:
    """Perform comprehensive live verification against base_url and manifest."""
    report = VerificationReport(
        base_url=base_url,
        expect_noop=expect_noop,
        require_receipt=require_receipt,
    )

    expected_checksums: dict[str, str] = {}
    if manifest_path is not None:
        if not manifest_path.is_file():
            report.ok = False
            report.errors.append(f"Manifest file not found: {manifest_path}")
            return report
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_checksums = extract_expected_checksums(manifest_data)
        except Exception as exc:
            report.ok = False
            report.errors.append(f"Failed to parse manifest {manifest_path}: {exc}")
            return report
    elif require_receipt:
        report.ok = False
        report.errors.append("Receipt verification was required (--require-receipt), but no --manifest was provided.")
        return report

    paths_to_probe = list(endpoints or DEFAULT_ENDPOINTS)
    # Ensure any endpoints named in manifest are also probed
    for path in expected_checksums:
        if path not in paths_to_probe:
            paths_to_probe.append(path)

    probe_map: dict[str, EndpointProbeResult] = {}
    for path in paths_to_probe:
        probe = probe_endpoint(base_url, path, timeout=timeout, compute_hash=True)
        report.probes.append(probe)
        probe_map[probe.path] = probe

        if not probe.ok:
            report.ok = False
            report.errors.append(
                f"Endpoint probe failed for {probe.path}: {probe.error or f'HTTP {probe.status_code}'}"
            )

    # Check receipt / checksum invariants
    if expected_checksums:
        for path, exp_sha in expected_checksums.items():
            probe = probe_map.get(path)
            if probe is None or not probe.ok or not probe.sha256:
                report.ok = False
                report.errors.append(f"Cannot verify checksum for {path}: probe was unsuccessful or missing")
                continue

            if probe.sha256.lower() == exp_sha.lower():
                report.matched_checksums[path] = probe.sha256
            else:
                report.ok = False
                report.mismatched_checksums[path] = {
                    "expected": exp_sha,
                    "actual": probe.sha256,
                }
                if expect_noop:
                    report.errors.append(
                        f"Unexpected mutation detected during no-op verification for {path}: "
                        f"expected SHA-256 {exp_sha}, live endpoint returned {probe.sha256}"
                    )
                else:
                    report.errors.append(
                        f"Receipt checksum mismatch for {path}: expected {exp_sha}, got {probe.sha256}"
                    )
    elif require_receipt:
        report.ok = False
        report.errors.append("No expected checksums found in manifest to satisfy --require-receipt.")

    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of publication target (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to deployment receipt or publication baseline JSON file",
    )
    parser.add_argument(
        "--require-receipt",
        action="store_true",
        help="Require valid receipt and verify endpoint checksums match exactly",
    )
    parser.add_argument(
        "--expect-noop",
        action="store_true",
        help="Assert that no unexpected mutation occurred against the manifest/baseline",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT,
        help=f"HTTP request timeout in seconds (default: {DEFAULT_TIMEOUT})",
    )
    parser.add_argument(
        "--endpoint",
        action="append",
        dest="endpoints",
        help="Additional specific endpoint path(s) to probe",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output full verification report in JSON format",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    report = verify_live(
        base_url=args.base_url,
        manifest_path=args.manifest,
        require_receipt=args.require_receipt,
        expect_noop=args.expect_noop,
        timeout=args.timeout,
        endpoints=args.endpoints,
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print(f"=== Live Publication Verification for {args.base_url} ===")
        print(f"Status: {'PASS' if report.ok else 'FAIL'}")
        print(f"Mode: expect_noop={args.expect_noop}, require_receipt={args.require_receipt}")
        print("\nEndpoint Probes:")
        for p in report.probes:
            status_desc = f"HTTP {p.status_code}" if p.status_code else "ERR"
            hash_desc = f" (sha256: {p.sha256[:12]}...)" if p.sha256 else ""
            print(f"  [{'OK' if p.ok else 'FAIL'}] {p.path} -> {status_desc} ({p.latency_ms:.1f}ms){hash_desc}")
            if p.error:
                print(f"       Error: {p.error}")

        if report.matched_checksums:
            print("\nVerified Checksums:")
            for path, sha in report.matched_checksums.items():
                print(f"  ✓ {path}: {sha}")

        if report.errors:
            print("\nVerification Errors:", file=sys.stderr)
            for err in report.errors:
                print(f"  ✗ {err}", file=sys.stderr)

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
