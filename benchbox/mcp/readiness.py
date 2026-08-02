"""Revision-bound evidence gate for shared MCP endpoints."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CONFORMANCE_REVISION = "81eb1c3edaed87d7fd585d7b80186da7a2960660"
INSPECTOR_VERSION = "2.0.0"
INSPECTOR_REVISION = "7aebf168e6277ea26b1f04a7987a1cd11328ec83"
INSPECTOR_INTEGRITY = "sha512-uEoeEG7/+ZbrvccPF3EsgbfjcyJ3bWVJXT4pcZtpmDUhA0zdK4T4Tuj2oUphi2Huwl66LqVdo3Mx2PkS2SUHXA=="
CURRENT_PROTOCOL_VERSION = "2026-07-28"
SUPPORTED_LEGACY_VERSION = "2025-11-25"
MAX_AUTOMATED_EVIDENCE_AGE = timedelta(days=7)

AUTOMATED_GATES = frozenset({"conformance", "inspector", "compatibility", "multiworker", "telemetry_cache"})
EXTERNAL_GATES = frozenset({"tls_edge", "shared_storage_restore", "scaling_rollback_incident"})


@dataclass(frozen=True, slots=True)
class ReadinessEvidence:
    """Validated production-readiness evidence."""

    source_revision: str
    generated_at: datetime
    automated: Mapping[str, bool]
    external: Mapping[str, bool]
    protocol_version: str
    conformance_revision: str
    inspector_version: str
    inspector_revision: str
    inspector_integrity: str

    @classmethod
    def from_path(cls, path: Path) -> ReadinessEvidence:
        return cls.from_bytes(path.read_bytes())

    @classmethod
    def from_bytes(cls, raw: bytes) -> ReadinessEvidence:
        if len(raw) > 65_536:
            raise ValueError("MCP readiness evidence exceeds 64 KiB")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("MCP readiness evidence must be a JSON object")
        generated_at = datetime.fromisoformat(str(payload["generated_at"]).replace("Z", "+00:00"))
        if generated_at.tzinfo is None:
            raise ValueError("MCP readiness evidence timestamp must include a timezone")
        return cls(
            source_revision=str(payload["source_revision"]),
            generated_at=generated_at.astimezone(timezone.utc),
            automated=_boolean_map(payload.get("automated"), "automated"),
            external=_boolean_map(payload.get("external"), "external"),
            protocol_version=str(payload["protocol_version"]),
            conformance_revision=str(payload["conformance_revision"]),
            inspector_version=str(payload["inspector_version"]),
            inspector_revision=str(payload["inspector_revision"]),
            inspector_integrity=str(payload["inspector_integrity"]),
        )

    def validate(self, *, now: datetime, source_revision: str) -> None:
        """Reject stale, mismatched, incomplete, or failed evidence."""
        if self.source_revision != source_revision:
            raise ValueError("MCP readiness evidence does not match BENCHBOX_BUILD_SHA")
        if now.astimezone(timezone.utc) - self.generated_at > MAX_AUTOMATED_EVIDENCE_AGE:
            raise ValueError("MCP readiness evidence is stale")
        if self.generated_at > now.astimezone(timezone.utc) + timedelta(minutes=5):
            raise ValueError("MCP readiness evidence timestamp is in the future")
        expected_pins = (
            CURRENT_PROTOCOL_VERSION,
            CONFORMANCE_REVISION,
            INSPECTOR_VERSION,
            INSPECTOR_REVISION,
            INSPECTOR_INTEGRITY,
        )
        actual_pins = (
            self.protocol_version,
            self.conformance_revision,
            self.inspector_version,
            self.inspector_revision,
            self.inspector_integrity,
        )
        if actual_pins != expected_pins:
            raise ValueError("MCP readiness evidence uses unexpected protocol-tool pins")
        _require_passed(self.automated, AUTOMATED_GATES, "automated")
        _require_passed(self.external, EXTERNAL_GATES, "external")


def _boolean_map(value: Any, field: str) -> Mapping[str, bool]:
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, bool) for key, item in value.items()
    ):
        raise ValueError(f"MCP readiness evidence {field} gates must be boolean entries")
    return value


def _require_passed(values: Mapping[str, bool], expected: frozenset[str], field: str) -> None:
    if set(values) != expected or not all(values.values()):
        raise ValueError(f"MCP readiness evidence {field} gates are incomplete or failed")


def verify_publication_evidence(path: Path, env: Mapping[str, str]) -> ReadinessEvidence:
    """Validate evidence plus out-of-band digest and build revision bindings."""
    expected_digest = env.get("BENCHBOX_MCP_READINESS_SHA256")
    source_revision = env.get("BENCHBOX_BUILD_SHA")
    if not expected_digest or not source_revision:
        raise ValueError("Remote MCP publication requires BENCHBOX_BUILD_SHA and BENCHBOX_MCP_READINESS_SHA256")
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("BENCHBOX_BUILD_SHA must be a full lowercase Git SHA-1")
    raw = path.read_bytes()
    actual_digest = hashlib.sha256(raw).hexdigest()
    if actual_digest != expected_digest:
        raise ValueError("MCP readiness evidence digest mismatch")
    evidence = ReadinessEvidence.from_bytes(raw)
    evidence.validate(now=datetime.now(timezone.utc), source_revision=source_revision)
    return evidence
