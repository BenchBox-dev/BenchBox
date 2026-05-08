"""Canonical JSON serialization for result bundles and submission sidecars."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def canonical_json_text(payload: Any) -> str:
    """Serialize JSON payloads in the byte-stable BenchBox result form."""

    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def canonical_json_bytes(payload: Any) -> bytes:
    """Return canonical JSON as UTF-8 bytes."""

    return canonical_json_text(payload).encode("utf-8")


def canonical_json_file_bytes(path: Path) -> bytes:
    """Read a JSON file and return its canonical UTF-8 bytes."""

    return canonical_json_bytes(json.loads(path.read_text(encoding="utf-8")))


__all__ = [
    "canonical_json_bytes",
    "canonical_json_file_bytes",
    "canonical_json_text",
]
