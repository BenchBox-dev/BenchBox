from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "site-deploy-receipt/v1"
STATUS_PREFIX = "site-deploy receipt"
STATUS_PATTERN = re.compile(rf"^{STATUS_PREFIX} sha256:(?P<sha>[0-9a-f]{{64}}) run:(?P<run>\d+)$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
REQUIRED_KEYS = (
    "schema",
    "generation",
    "mode",
    "target",
    "run_id",
    "deployment_id",
    "trunk_sha",
    "release_tag",
    "release_sha",
    "corpus_sha",
    "routes",
    "artifact",
    "versions",
    "gates",
    "probes",
    "parent",
    "rollback_order",
)
ROLLBACK_ORDER = (
    "restore the explorer UI before the snapshot",
    "ui-first artifact: restored UI over the current snapshot",
    "full artifact: restored UI and restored snapshot",
)


class ReceiptError(ValueError):
    pass


def canonical_bytes(receipt: dict[str, Any]) -> bytes:
    return (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8")


def receipt_sha256(receipt_bytes: bytes) -> str:
    return hashlib.sha256(receipt_bytes).hexdigest()


def status_description(sha256: str, run_id: int) -> str:
    return f"{STATUS_PREFIX} sha256:{sha256} run:{run_id}"


def parse_status_description(description: str) -> tuple[str, int] | None:
    match = STATUS_PATTERN.match(description or "")
    if not match:
        return None
    return match.group("sha"), int(match.group("run"))


def parent_summary(receipt: dict[str, Any], receipt_sha: str) -> dict[str, Any]:
    return {
        "run_id": receipt["run_id"],
        "generation": receipt["generation"],
        "receipt_sha256": receipt_sha,
        "trunk_sha": receipt["trunk_sha"],
        "release_tag": receipt["release_tag"],
        "corpus_sha": receipt["corpus_sha"],
        "artifact_sha256": receipt["artifact"]["sha256"],
    }


def build_receipt(
    *,
    mode: str,
    target: str,
    run_id: int,
    deployment_id: int | None,
    trunk_sha: str,
    release_tag: str,
    release_sha: str,
    corpus_sha: str,
    assembly: dict[str, Any],
    artifact_name: str,
    versions: dict[str, Any],
    gates: dict[str, Any],
    probes: dict[str, Any],
    parent: dict[str, Any] | None,
    certifying_run_id: int | None,
    rollback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    generation = (int(parent["generation"]) + 1) if parent else 1
    return {
        "schema": SCHEMA,
        "generation": generation,
        "mode": mode,
        "target": target,
        "run_id": run_id,
        "deployment_id": deployment_id,
        "trunk_sha": trunk_sha,
        "release_tag": release_tag,
        "release_sha": release_sha,
        "corpus_sha": corpus_sha,
        "certifying_run_id": certifying_run_id,
        "routes": assembly["routes"],
        "artifact": {
            "name": artifact_name,
            "sha256": assembly["tree_sha256"],
            "total_bytes": assembly["total_bytes"],
            "total_files": assembly["total_files"],
        },
        "versions": versions,
        "gates": {
            "ok": gates["ok"],
            "results": {name: result["status"] for name, result in gates["results"].items()},
            "gates_sha256": gates.get("gates_sha256"),
        },
        "probes": probes,
        "parent": parent,
        "link_baseline": (gates["results"].get("links") or {}).get("link_baseline"),
        "rollback": rollback,
        "rollback_order": list(ROLLBACK_ORDER),
    }


def validate_receipt(receipt: Any) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise ReceiptError("receipt is not an object")
    missing = [key for key in REQUIRED_KEYS if key not in receipt]
    if missing:
        raise ReceiptError(f"receipt is missing keys: {missing}")
    if receipt["schema"] != SCHEMA:
        raise ReceiptError(f"unsupported receipt schema {receipt['schema']!r}")
    if not isinstance(receipt["generation"], int) or receipt["generation"] < 1:
        raise ReceiptError("receipt generation must be a positive integer")
    for key in ("trunk_sha", "release_sha"):
        if not HEX40.match(str(receipt[key])):
            raise ReceiptError(f"receipt {key} is not a full SHA")
    artifact = receipt["artifact"]
    if not isinstance(artifact, dict) or not HEX64.match(str(artifact.get("sha256", ""))):
        raise ReceiptError("receipt artifact digest is malformed")
    if not isinstance(receipt["probes"], dict) or "ok" not in receipt["probes"]:
        raise ReceiptError("receipt probes are missing an ok flag")
    return receipt


def is_last_known_good(receipt: dict[str, Any], target: str = "github-pages") -> bool:
    return (
        receipt["probes"].get("ok") is True
        and receipt["gates"].get("ok") is True
        and receipt["target"] == target
        and receipt["mode"] in ("deploy", "rollback")
    )
