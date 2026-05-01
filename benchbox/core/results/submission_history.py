"""Local hosted-submission history sidecars."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def submission_history_path(result_file: Path, *, idempotency_key: str | None = None) -> Path:
    """Return the hosted-submission sidecar path for a primary result JSON."""

    key_suffix = f".{_safe_filename_token(idempotency_key)}" if idempotency_key else ""
    return result_file.with_name(f"{result_file.stem}{key_suffix}.submission.json")


def record_hosted_submission(
    *,
    result_file: Path,
    service_url: str,
    manifest: Mapping[str, Any],
    status: str,
    idempotency_key: str,
    submission_id: str | None,
    public_result_id: str | None,
    public_url: str | None,
) -> Path:
    """Persist hosted-submission metadata without modifying the result bundle."""

    record = {
        "version": 1,
        "submitted_at": datetime.now(timezone.utc).isoformat(),
        "result_file": result_file.name,
        "bundle_file": manifest.get("bundle_file", result_file.name),
        "bundle_hash": manifest.get("bundle_hash"),
        "benchmark": manifest.get("benchmark"),
        "platform": manifest.get("platform"),
        "scale_factor": manifest.get("scale_factor"),
        "service_url": service_url,
        "status": status,
        "submission_id": submission_id,
        "public_result_id": public_result_id,
        "public_url": public_url,
        "idempotency_key": idempotency_key,
    }

    sidecar_path = submission_history_path(result_file, idempotency_key=idempotency_key)
    sidecar_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return sidecar_path


def list_hosted_submissions(results_dir: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    """List hosted-submission sidecars newest-first."""

    if not results_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for sidecar_path in results_dir.glob("*.submission.json"):
        try:
            data = json.loads(sidecar_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        data["file"] = sidecar_path
        records.append(data)

    sorted_records = sorted(records, key=lambda item: str(item.get("submitted_at", "")), reverse=True)
    return sorted_records[:limit] if limit is not None else sorted_records


def _safe_filename_token(value: str | None) -> str:
    if not value:
        return "unknown"
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value)
    return safe[:80].strip(".-") or "unknown"


__all__ = [
    "list_hosted_submissions",
    "record_hosted_submission",
    "submission_history_path",
]
