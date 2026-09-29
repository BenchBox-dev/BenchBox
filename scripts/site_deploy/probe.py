"""Post-deploy probes: fetch the served bytes and compare them with the receipt.

The comparison logic is ``scripts/publication/verify_live.py``; this module adds a
retry window for CDN propagation and a local static server so the same probes run
in dry-run mode without touching Pages.
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

from scripts.site_deploy.gates import load_publication_script


def probe_once(base_url: str, receipt_path: Path, endpoints: Sequence[str], timeout: float = 30.0) -> dict[str, Any]:
    """Probe every endpoint and checksum named by the receipt and summarize the report."""
    verify_live = load_publication_script("verify_live")
    report = verify_live.verify_live(
        base_url=base_url,
        manifest_path=receipt_path,
        endpoints=list(endpoints),
        require_receipt=True,
        timeout=timeout,
    )
    return {
        "ok": bool(report.ok),
        "base_url": base_url,
        "checked": len(report.probes),
        "matched": len(report.matched_checksums),
        "mismatched": report.mismatched_checksums,
        "errors": list(report.errors),
        "probes": [
            {"path": p.path, "status": p.status_code, "ok": p.ok, "sha256": p.sha256, "latency_ms": p.latency_ms}
            for p in report.probes
        ],
    }


def probe_with_retries(
    base_url: str,
    receipt_path: Path,
    endpoints: Sequence[str],
    *,
    attempts: int = 1,
    delay_seconds: float = 20.0,
    timeout: float = 30.0,
    sleep: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Probe until green or out of attempts; Pages can serve the old site briefly after a deploy."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    summary: dict[str, Any] = {}
    for attempt in range(1, attempts + 1):
        summary = probe_once(base_url, receipt_path, endpoints, timeout=timeout)
        summary["attempt"] = attempt
        if summary["ok"]:
            break
        if attempt < attempts:
            sleep(delay_seconds)
    summary["attempts"] = attempts
    return summary


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


@contextlib.contextmanager
def serve_directory(directory: Path) -> Iterator[str]:
    """Serve ``directory`` on an ephemeral localhost port and yield its base URL."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
