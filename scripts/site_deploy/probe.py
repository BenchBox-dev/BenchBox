from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

VERIFY_LIVE = Path(__file__).resolve().parents[1] / "publication" / "verify_live.py"
DEEP_LINK = "/results/__site_deploy_probe__/deep/link"
FALLBACK_MARKER = "benchbox.results.redirect"
DEFAULT_ATTEMPTS = 6
DEFAULT_DELAY_SECONDS = 10.0

Sleeper = Callable[[float], None]


def write_manifest(path: Path, checksums: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"checksums": checksums}, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_verify_live(base_url: str, manifest: Path, endpoints: list[str], timeout: float) -> dict[str, Any]:
    command = [sys.executable, str(VERIFY_LIVE), "--base-url", base_url, "--manifest", str(manifest), "--json"]
    command += ["--timeout", str(timeout)]
    for endpoint in endpoints:
        command += ["--endpoint", endpoint]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        report = json.loads(result.stdout)
    except ValueError:
        return {
            "ok": False,
            "errors": [f"verify_live produced no JSON (exit {result.returncode}): {result.stderr[-400:]}"],
        }
    report["exit_code"] = result.returncode
    return report


def check_deep_link(base_url: str, timeout: float) -> dict[str, Any]:
    url = base_url.rstrip("/") + DEEP_LINK
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return {"ok": False, "status": response.status, "detail": "unknown results path answered 2xx"}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        ok = exc.code == 404 and FALLBACK_MARKER in body
        return {"ok": ok, "status": exc.code, "detail": "404 fallback served" if ok else "404 fallback body missing"}
    except (urllib.error.URLError, OSError) as exc:
        return {"ok": False, "status": None, "detail": str(exc)}


def probe(
    base_url: str,
    checksums: dict[str, str],
    work_dir: Path,
    attempts: int = DEFAULT_ATTEMPTS,
    delay: float = DEFAULT_DELAY_SECONDS,
    timeout: float = 30.0,
    sleep: Sleeper = time.sleep,
) -> dict[str, Any]:
    manifest = work_dir / "probe-checksums.json"
    write_manifest(manifest, checksums)
    endpoints = sorted(checksums)
    report: dict[str, Any] = {}
    used = 0
    for used in range(1, attempts + 1):
        report = run_verify_live(base_url, manifest, endpoints, timeout)
        if report.get("ok") is True:
            break
        if used < attempts:
            sleep(delay)
    deep_link = check_deep_link(base_url, timeout)
    return {
        "ok": report.get("ok") is True and deep_link["ok"],
        "base_url": base_url,
        "attempts": used,
        "endpoints": len(endpoints),
        "matched": len(report.get("matched_checksums", {})),
        "mismatched": report.get("mismatched_checksums", {}),
        "errors": report.get("errors", []),
        "deep_link": deep_link,
    }


def compare_live(base_url: str, checksums: dict[str, str], timeout: float = 30.0) -> dict[str, Any]:
    import hashlib

    matched: list[str] = []
    differing: dict[str, str] = {}
    unreachable: dict[str, str] = {}
    for path in sorted(checksums):
        try:
            with urllib.request.urlopen(base_url.rstrip("/") + path, timeout=timeout) as response:
                digest = hashlib.sha256(response.read()).hexdigest()
        except (urllib.error.URLError, OSError) as exc:
            unreachable[path] = str(exc)
            continue
        if digest == checksums[path]:
            matched.append(path)
        else:
            differing[path] = digest
    return {"base_url": base_url, "matched": matched, "differing": differing, "unreachable": unreachable}
