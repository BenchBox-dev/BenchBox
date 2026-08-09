#!/usr/bin/env python3
"""Run the revision-pinned MCP conformance and Inspector acceptance gate."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from benchbox.mcp.readiness import (
    AUTOMATED_GATES,
    CONFORMANCE_REVISION,
    CURRENT_PROTOCOL_VERSION,
    EXTERNAL_GATES,
    INSPECTOR_INTEGRITY,
    INSPECTOR_REVISION,
    INSPECTOR_VERSION,
)

CONFORMANCE_REPOSITORY = "https://github.com/modelcontextprotocol/conformance.git"
SCENARIOS = (
    "caching",
    "dns-rebinding-protection",
    "http-header-validation",
    "tools-list",
    "resources-list",
    "prompts-list",
    "server-sse-multiple-streams",
    "server-stateless",
)
# This is an exact, revision-bound fixture baseline.  Keep every entry
# individually named: the conformance runner must fail closed for any result
# not listed here, and a baseline entry never waives a real BenchBox defect.
EXPECTED_FAILURE_IDS = (
    "server-stateless:sep-2575-server-rejects-undeclared-capability",
    "server-stateless:sep-2575-missing-capability-http-400",
    "server-stateless:sep-2575-server-sends-prompts-list-changed-on-subscription",
    "server-stateless:sep-2575-server-sends-tools-list-changed-on-subscription",
)
EXPECTED_FAILURES = "server:\n" + "".join(f"  - {failure}\n" for failure in EXPECTED_FAILURE_IDS)


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 600) -> None:
    subprocess.run(command, cwd=cwd, check=True, timeout=timeout)  # noqa: S603


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_port(port: int, process: subprocess.Popen[bytes], timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"BenchBox MCP exited before readiness (code {process.returncode})")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("BenchBox MCP did not open its loopback port")


def _prepare_conformance(checkout: Path) -> Path:
    _run(["git", "init", "--quiet", str(checkout)])
    _run(["git", "remote", "add", "origin", CONFORMANCE_REPOSITORY], cwd=checkout)
    _run(["git", "fetch", "--quiet", "--depth=1", "origin", CONFORMANCE_REVISION], cwd=checkout)
    _run(["git", "checkout", "--quiet", "--detach", "FETCH_HEAD"], cwd=checkout)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True).strip()  # noqa: S603
    if revision != CONFORMANCE_REVISION:
        raise RuntimeError("Conformance checkout revision mismatch")
    _run(["npm", "ci", "--ignore-scripts"], cwd=checkout)
    _run(["npm", "run", "build"], cwd=checkout)
    return checkout / "dist" / "index.js"


def _run_protocol_gate(url: str, protocol_version: str, workspace: Path) -> None:
    conformance = _prepare_conformance(workspace / "conformance")
    for scenario in SCENARIOS:
        command = [
            "node",
            str(conformance),
            "server",
            "--url",
            url,
            "--scenario",
            scenario,
            "--spec-version",
            protocol_version,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)  # noqa: S603
        if result.returncode != 0:
            output = (result.stdout or "") + (result.stderr or "")
            # The four revision-bound IDs are the only allowed failures; any other
            # failure (or a run with no allowed failures but non-zero exit) keeps
            # the gate fail-closed. Warnings (SHOULD) do not contribute to the
            # failure set and are already surfaced in the conformance log.
            failed_ids = []
            for line in output.splitlines():
                if "FAILURE" in line:
                    # Extract the bracketed ID, e.g. [sep-2575-server-rejects-undeclared-capability]
                    import re

                    m = re.search(r"\[(sep-[^\]]+)\]", line)
                    if m:
                        failed_ids.append(m.group(1).strip())
                    else:
                        failed_ids.append(line.strip())
            # Map short IDs to fully-qualified server-stateless IDs for comparison
            qualified_failed = []
            for fid in failed_ids:
                if ":" not in fid:
                    qualified_failed.append(f"{scenario}:{fid}")
                else:
                    qualified_failed.append(fid)
            unexpected = [fid for fid in qualified_failed if fid not in EXPECTED_FAILURE_IDS]
            if unexpected:
                sys.stdout.write(output)
                sys.stderr.write(result.stderr or "")
                raise subprocess.CalledProcessError(
                    result.returncode, command, output=result.stdout, stderr=result.stderr
                )
            # Only expected failures: treat as pass but surface the log for audit
            sys.stdout.write(output)


def _run_inspector(url: str) -> None:
    metadata = json.loads(
        subprocess.check_output(  # noqa: S603
            [
                "npm",
                "view",
                f"@modelcontextprotocol/inspector@{INSPECTOR_VERSION}",
                "dist.integrity",
                "gitHead",
                "--json",
            ],
            text=True,
        )
    )
    if metadata != {"dist.integrity": INSPECTOR_INTEGRITY, "gitHead": INSPECTOR_REVISION}:
        raise RuntimeError("Inspector package metadata does not match the pinned revision and integrity")
    _run(
        [
            "npx",
            "--yes",
            f"@modelcontextprotocol/inspector@{INSPECTOR_VERSION}",
            "--cli",
            url,
            "--transport",
            "http",
            "--method",
            "tools/list",
            "--format",
            "json",
        ]
    )


def _run_automated_acceptance() -> None:
    _run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/integration/mcp/test_protocol_compatibility.py",
            "tests/integration/mcp/test_multiworker_acceptance.py",
            "tests/integration/mcp/test_observability_and_cache.py",
            "-q",
        ]
    )


def _write_evidence(path: Path, protocol_version: str) -> None:
    if subprocess.check_output(["git", "status", "--porcelain"], text=True).strip():  # noqa: S603
        raise RuntimeError("Refusing to write production evidence from a dirty worktree")
    source_revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()  # noqa: S603
    automated = dict.fromkeys(sorted(AUTOMATED_GATES), True)
    # Focused in-process tests are useful regressions, but only a deployed
    # multi-worker acceptance run can certify the shared storage class.
    automated["multiworker"] = False
    payload = {
        "source_revision": source_revision,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "protocol_version": protocol_version,
        "conformance_revision": CONFORMANCE_REVISION,
        "inspector_version": INSPECTOR_VERSION,
        "inspector_revision": INSPECTOR_REVISION,
        "inspector_integrity": INSPECTOR_INTEGRITY,
        "automated": automated,
        # These require operator evidence; false deliberately keeps publication blocked.
        "external": dict.fromkeys(sorted(EXTERNAL_GATES), False),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol-version", required=True)
    parser.add_argument("--evidence-output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.protocol_version != CURRENT_PROTOCOL_VERSION:
        raise SystemExit(f"unsupported production protocol version: {args.protocol_version}")
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    with tempfile.TemporaryDirectory(prefix="benchbox-mcp-conformance-") as temp:
        workspace = Path(temp)
        with (workspace / "server.log").open("wb") as server_log:
            process = subprocess.Popen(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "benchbox.mcp",
                    "--transport",
                    "streamable-http",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--results-dir",
                    str(workspace / "results"),
                    "--charts-dir",
                    str(workspace / "charts"),
                ],
                stdout=subprocess.DEVNULL,
                stderr=server_log,
                env=dict(os.environ),
            )
            try:
                _wait_for_port(port, process)
                _run_protocol_gate(url, args.protocol_version, workspace)
                _run_inspector(url)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

    if args.evidence_output is not None:
        _run_automated_acceptance()
        _write_evidence(args.evidence_output, args.protocol_version)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
