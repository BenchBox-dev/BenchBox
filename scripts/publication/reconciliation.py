#!/usr/bin/env python3
"""Desired-Built-Deployed-Observed reconciliation and drift detector (A11 w1).

Performs 4-way reconciliation across publication lifecycle states:
1. Desired: Publication manifest pinning target generation, source commit, and artifacts.
2. Built: Immutable assembly receipt with artifact digests and provenance.
3. Deployed: Hosting provider deployment acknowledgement receipt.
4. Observed: External attested live-observation receipt with public route probes.

This tool never fabricates any of the four states. Every state must be supplied
as a real input file. When a required input is absent, malformed, or collapses
onto another state, the run fails closed (exit 1 or 2) and never reports a
reconciled result. Per ``docs/operations/independent-publication-contract.md``
lines 22-25, a green run of this canary does not prove live publication; it only
proves that the four supplied receipts agree.

Detects and classifies drift:
- MANIFEST_DRIFT: manifest digests, source commits, or build closures mismatch.
- ARTIFACT_DRIFT: manifest-required artifacts missing from the build, unexpected
  extra artifacts, or built/observed checksums differ from manifest definitions.
- GENERATION_DRIFT: deployed or observed generation lags or mismatches desired.
- STALE_RECEIPT: live observation receipt is missing, undated, future-dated, or
  exceeds max age.
- RECEIPT_INCOMPLETE: the live receipt omits a field the contract mandates
  (schema version, receipt ID, target, manifest digest, both source SHAs,
  artifact identity, required route set with per-route status, nonce, freshness
  window, attestor identity, or signature).
- MISSING_OBSERVATION: no live-observation receipt or no public route probes.

Exit codes:
  0 - Fully reconciled, zero drift detected, all four real states supplied.
  1 - Drift or reconciliation violation detected.
  2 - Configuration, file reading, or argument error (including any missing
      required input).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE_URL = "https://benchbox.dev"
DEFAULT_MAX_AGE_HOURS = 24.0
DEFAULT_TIMEOUT_SECONDS = 15.0
# Clock-skew tolerance for future-dated receipts before it counts as a violation.
FUTURE_SKEW_SECONDS = 300.0

DEFAULT_PROBE_PATHS = (
    "/",
    "/results/",
    "/results/data/results.duckdb",
)

# Receipt file names expected inside --receipts-dir. These are documented in
# docs/operations/independent-publication-contract.md ("Reconciliation inputs").
ASSEMBLY_RECEIPT_NAME = "assembly-receipt.json"
DEPLOYMENT_RECEIPT_NAME = "deployment-receipt.json"
LIVE_RECEIPT_NAME = "live-receipt.json"

# This is a public verification key. The corresponding private key is held
# only by the GitHub Actions secret documented in the operations contract.
DEFAULT_ATTESTOR_PUBLIC_KEY = REPO_ROOT / "docs/operations/publication-attestor-public-key.pem"
ATTESTOR_SIGNATURE_ALGORITHM = "ed25519"

# Fields the contract (independent-publication-contract.md, "Required live
# receipt fields") mandates on an attested live-observation receipt.
REQUIRED_RECEIPT_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("schema version", ("schema_version", "schemaVersion")),
    ("receipt ID", ("receipt_id", "id")),
    ("target", ("target",)),
    ("generation", ("generation",)),
    ("observation timestamp", ("timestamp", "observed_at", "created_at")),
    ("publication manifest digest", ("manifest_digest", "manifest_sha256")),
    ("develop SHA", ("develop_sha", "source_commit", "develop_commit")),
    ("published-results SHA", ("published_results_sha", "published_results_commit")),
    ("artifact identity", ("artifacts", "artifact")),
    ("required route set", ("routes", "probes")),
    ("nonce", ("nonce",)),
    ("freshness window", ("freshness_window", "freshness_window_hours", "max_age_hours")),
    ("attestor identity", ("attestor", "attestor_identity", "attested_by")),
    ("attestor signature", ("signature", "attestor_signature")),
)


@dataclass(frozen=True)
class DriftFinding:
    """Individual drift finding with classification and expected vs actual values."""

    drift_type: str
    description: str
    expected: Any = None
    actual: Any = None
    severity: str = "ERROR"

    def to_dict(self) -> dict[str, Any]:
        return {
            "drift_type": self.drift_type,
            "description": self.description,
            "expected": self.expected,
            "actual": self.actual,
            "severity": self.severity,
        }


@dataclass
class EndpointObservation:
    """External probe result for a publication route."""

    path: str
    url: str
    status_code: int = 0
    ok: bool = False
    sha256: str | None = None
    latency_ms: float = 0.0
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationReport:
    """Structured 4-way reconciliation and drift report."""

    reconciled: bool = True
    desired_generation: int | None = None
    deployed_generation: int | None = None
    observed_generation: int | None = None
    desired_commit: str | None = None
    deployed_commit: str | None = None
    drift_count: int = 0
    drifts: list[DriftFinding] = field(default_factory=list)
    probes: list[EndpointObservation] = field(default_factory=list)
    receipt_age_hours: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "reconciled": self.reconciled,
            "desired_generation": self.desired_generation,
            "deployed_generation": self.deployed_generation,
            "observed_generation": self.observed_generation,
            "desired_commit": self.desired_commit,
            "deployed_commit": self.deployed_commit,
            "drift_count": len(self.drifts),
            "drifts": [d.to_dict() for d in self.drifts],
            "probes": [p.to_dict() for p in self.probes],
            "receipt_age_hours": self.receipt_age_hours,
            "timestamp": self.timestamp,
        }


class ReconciliationInputError(ValueError):
    """Raised when the four reconciliation states are missing or not distinct."""


def parse_iso_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO-8601 UTC timestamp string."""
    if not ts_str:
        return None
    cleaned = ts_str.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _normalize_generation(value: Any) -> int | str | None:
    """Coerce a generation value to int, tolerating string encodings."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            # Workflow receipts deliberately use an opaque, validated label
            # (for example publication-123-1).  Treat it as a real value, not
            # as an absent generation that can silently evade comparison.
            return value.strip()
    return None


def _first_present(data: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in data and data[key] not in (None, "", [], {}):
            return data[key]
    return None


def canonical_live_receipt_payload(receipt: dict[str, Any]) -> bytes:
    """Return the deterministic byte payload an attestor signs for a receipt.

    Signatures never sign themselves. Both accepted signature field spellings
    are excluded so aliases cannot change the verified payload.
    """
    payload = dict(receipt)
    payload.pop("signature", None)
    payload.pop("attestor_signature", None)
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def verify_live_receipt_signature(receipt: dict[str, Any], public_key_path: Path | None = None) -> tuple[bool, str]:
    """Verify an Ed25519 receipt signature with the repository public key.

    ``openssl pkeyutl`` is available on GitHub-hosted runners and avoids adding
    a cryptography dependency solely for this verification boundary.
    """
    public_key_path = public_key_path or DEFAULT_ATTESTOR_PUBLIC_KEY
    signature = _first_present(receipt, ("signature", "attestor_signature"))
    if not isinstance(signature, str) or not signature.strip():
        return False, "receipt signature is missing or empty"
    if receipt.get("signature_algorithm") != ATTESTOR_SIGNATURE_ALGORITHM:
        return False, f"receipt signature algorithm must be {ATTESTOR_SIGNATURE_ALGORITHM!r}"
    if not public_key_path.is_file():
        return False, f"attestor public key is unavailable: {public_key_path}"
    try:
        signature_bytes = base64.b64decode(signature, validate=True)
    except (ValueError, TypeError) as exc:
        return False, f"receipt signature is not valid base64: {exc}"
    if not signature_bytes:
        return False, "receipt signature is empty"

    with tempfile.TemporaryDirectory(prefix="benchbox-receipt-") as temp_dir:
        temp = Path(temp_dir)
        payload_path = temp / "receipt-payload.json"
        signature_path = temp / "receipt.sig"
        payload_path.write_bytes(canonical_live_receipt_payload(receipt))
        signature_path.write_bytes(signature_bytes)
        try:
            completed = subprocess.run(
                [
                    "openssl",
                    "pkeyutl",
                    "-verify",
                    "-pubin",
                    "-inkey",
                    str(public_key_path),
                    "-rawin",
                    "-in",
                    str(payload_path),
                    "-sigfile",
                    str(signature_path),
                ],
                capture_output=True,
                check=False,
                text=True,
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            return False, f"openssl binary execution failed: {exc}"
    if completed.returncode != 0:
        return False, "receipt signature does not verify against the configured attestor public key"
    return True, ""


def probe_live_endpoint(
    base_url: str,
    path: str,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> EndpointObservation:
    """Probe an external HTTP endpoint and compute status, latency, and SHA-256."""
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    t0 = time.perf_counter()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BenchBox-Publication-Reconciliation/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            latency = (time.perf_counter() - t0) * 1000.0
            digest = hashlib.sha256(body).hexdigest()
            return EndpointObservation(
                path=path,
                url=url,
                status_code=resp.status,
                ok=200 <= resp.status < 300,
                sha256=digest,
                latency_ms=round(latency, 2),
            )
    except urllib.error.HTTPError as e:
        latency = (time.perf_counter() - t0) * 1000.0
        return EndpointObservation(
            path=path,
            url=url,
            status_code=e.code,
            ok=False,
            latency_ms=round(latency, 2),
            error=f"HTTP {e.code}: {e.reason}",
        )
    except Exception as e:
        latency = (time.perf_counter() - t0) * 1000.0
        return EndpointObservation(
            path=path,
            url=url,
            status_code=0,
            ok=False,
            latency_ms=round(latency, 2),
            error=str(e),
        )


def extract_artifact_digests(manifest_or_receipt: dict[str, Any]) -> dict[str, str]:
    """Extract path -> sha256 mapping from various manifest/receipt schemas."""
    digests: dict[str, str] = {}

    artifacts = manifest_or_receipt.get("artifacts")
    if isinstance(artifacts, dict):
        for name, entry in artifacts.items():
            if isinstance(entry, dict) and "digest" in entry:
                p = entry.get("path", name)
                digests[p] = str(entry["digest"]).lower().removeprefix("sha256:")
    elif isinstance(artifacts, list):
        for item in artifacts:
            if isinstance(item, dict) and "sha256" in item:
                p = item.get("path", "")
                digests[p] = str(item["sha256"]).lower().removeprefix("sha256:")

    checksums = manifest_or_receipt.get("checksums")
    if isinstance(checksums, dict):
        for p, h in checksums.items():
            digests[p] = str(h).lower().removeprefix("sha256:")

    live_db = manifest_or_receipt.get("live_database")
    if isinstance(live_db, dict) and "sha256" in live_db:
        digests["/results/data/results.duckdb"] = str(live_db["sha256"]).lower().removeprefix("sha256:")

    if "database_sha256" in manifest_or_receipt:
        digests["/results/data/results.duckdb"] = (
            str(manifest_or_receipt["database_sha256"]).lower().removeprefix("sha256:")
        )

    return digests


def _check_generation_drift(
    des_gen: int | None,
    dep_gen: int | None,
    obs_gen: int | None,
) -> list[DriftFinding]:
    """Detect generation lag or mismatch across desired, deployed, and observed.

    All three pairwise comparisons are made so a missing intermediate value
    cannot mask a desired<->observed mismatch.
    """
    drifts: list[DriftFinding] = []
    pairs = (
        ("desired", des_gen, "deployed", dep_gen),
        ("deployed", dep_gen, "observed", obs_gen),
        ("desired", des_gen, "observed", obs_gen),
    )
    for a_name, a_val, b_name, b_val in pairs:
        if a_val is not None and b_val is not None and a_val != b_val:
            drifts.append(
                DriftFinding(
                    drift_type="GENERATION_DRIFT",
                    description=(
                        f"{b_name.capitalize()} generation ({b_val}) does not match {a_name} generation ({a_val})"
                    ),
                    expected=a_val,
                    actual=b_val,
                )
            )
    return drifts


def _check_manifest_drift(
    desired: dict[str, Any],
    built: dict[str, Any],
    deployed: dict[str, Any],
) -> list[DriftFinding]:
    """Detect commit or build closure drift across desired, built, and deployed."""
    drifts: list[DriftFinding] = []
    binding_fields = (
        ("target", ("target",)),
        ("develop SHA", ("develop_sha", "source_commit", "develop_commit")),
        ("published-results SHA", ("published_results_sha", "published_results_commit")),
        ("manifest digest", ("manifest_digest", "manifest_sha256")),
    )
    states = (("desired", desired), ("built", built), ("deployed", deployed))
    for label, keys in binding_fields:
        values = [(name, _first_present(state, keys)) for name, state in states]
        present = [(name, value) for name, value in values if value is not None]
        if len(present) >= 2:
            first_name, first_value = present[0]
            for name, value in present[1:]:
                if value != first_value:
                    drifts.append(
                        DriftFinding(
                            drift_type="MANIFEST_DRIFT",
                            description=f"{label} mismatch between {first_name} and {name}",
                            expected=first_value,
                            actual=value,
                        )
                    )

    # Artifact identity is part of the binding, not merely descriptive
    # assembly metadata.  Compare the complete identity wherever a state
    # supplies it so crossed receipts cannot reconcile successfully.
    identity_fields = (
        ("artifact_name", "artifact identity name"),
        ("artifact_run_id", "artifact workflow run"),
    )
    for key, label in identity_fields:
        values = [(name, state.get(key)) for name, state in states if state.get(key) not in (None, "")]
        if len(values) >= 2:
            first_name, first_value = values[0]
            for name, value in values[1:]:
                if value != first_value:
                    drifts.append(
                        DriftFinding(
                            drift_type="ARTIFACT_DRIFT",
                            description=f"{label} mismatch between {first_name} and {name}",
                            expected=first_value,
                            actual=value,
                        )
                    )

    des_commit = _first_present(desired, ("develop_sha", "source_commit", "develop_commit"))
    dep_commit = _first_present(deployed, ("develop_sha", "source_commit", "commit_sha"))

    if des_commit and dep_commit and des_commit != dep_commit:
        drifts.append(
            DriftFinding(
                drift_type="MANIFEST_DRIFT",
                description=f"Deployed commit ({dep_commit}) differs from desired source commit ({des_commit})",
                expected=des_commit,
                actual=dep_commit,
            )
        )

    desired_closure = desired.get("build_closure")
    built_closure = built.get("build_closure")
    if isinstance(desired_closure, dict) and isinstance(built_closure, dict):
        for k in ("lockfile_sha256", "workflow_sha", "read_model_version"):
            v_des = desired_closure.get(k)
            v_bld = built_closure.get(k)
            if v_des and v_bld and v_des != v_bld:
                drifts.append(
                    DriftFinding(
                        drift_type="MANIFEST_DRIFT",
                        description=f"Build closure mismatch on '{k}': desired={v_des}, built={v_bld}",
                        expected=v_des,
                        actual=v_bld,
                    )
                )
    return drifts


def _check_built_vs_desired(desired_digests: dict[str, str], built_digests: dict[str, str]) -> list[DriftFinding]:
    """Full set comparison of manifest vs build artifact digests (not the intersection)."""
    if not desired_digests:
        return []
    drifts: list[DriftFinding] = []
    for path in sorted(set(desired_digests) - set(built_digests)):
        drifts.append(
            DriftFinding(
                drift_type="ARTIFACT_DRIFT",
                description=f"Manifest-required artifact '{path}' is absent from the build",
                expected=desired_digests[path],
                actual=None,
            )
        )
    for path in sorted(set(built_digests) - set(desired_digests)):
        drifts.append(
            DriftFinding(
                drift_type="ARTIFACT_DRIFT",
                description=f"Built artifact '{path}' is not present in the desired manifest",
                expected=None,
                actual=built_digests[path],
            )
        )
    for path in sorted(set(desired_digests) & set(built_digests)):
        if desired_digests[path] != built_digests[path]:
            drifts.append(
                DriftFinding(
                    drift_type="ARTIFACT_DRIFT",
                    description=f"Built artifact digest for '{path}' differs from desired manifest",
                    expected=desired_digests[path],
                    actual=built_digests[path],
                )
            )
    return drifts


def _run_live_probes(
    base_url: str, desired_digests: dict[str, str], built_digests: dict[str, str]
) -> tuple[list[DriftFinding], list[EndpointObservation]]:
    drifts: list[DriftFinding] = []
    probes: list[EndpointObservation] = []
    for p in DEFAULT_PROBE_PATHS:
        probe = probe_live_endpoint(base_url, p)
        probes.append(probe)
        if not probe.ok:
            drifts.append(
                DriftFinding(
                    drift_type="ARTIFACT_DRIFT",
                    description=f"External endpoint probe failed for '{p}': {probe.error or f'HTTP {probe.status_code}'}",
                    expected="HTTP 200 OK",
                    actual=f"HTTP {probe.status_code}",
                )
            )
        elif probe.sha256:
            expected_sha = desired_digests.get(p) or built_digests.get(p)
            if expected_sha and probe.sha256.lower() != expected_sha.lower():
                drifts.append(
                    DriftFinding(
                        drift_type="ARTIFACT_DRIFT",
                        description=f"Observed endpoint hash for '{p}' does not match expected artifact hash",
                        expected=expected_sha,
                        actual=probe.sha256,
                    )
                )
    return drifts, probes


def _observation_to_probe(pr: dict[str, Any]) -> tuple[EndpointObservation | None, DriftFinding | None]:
    """Convert one receipt probe record to an observation, or a drift if it lacks status."""
    path = pr.get("path") or pr.get("route") or ""
    status_code = pr.get("status_code")
    ok_field = pr.get("ok")
    if "status" in pr and ok_field is None:
        ok_field = str(pr["status"]).lower() in ("ok", "pass", "passed", "200")
    if status_code is None and ok_field is None:
        return None, DriftFinding(
            drift_type="MISSING_OBSERVATION",
            description=f"Probe record for '{path}' omits both 'status_code' and 'ok'/'status'",
            expected="explicit status_code and ok",
            actual="neither present",
        )
    numeric = isinstance(status_code, (int, str)) and str(status_code).isdigit()
    obs = EndpointObservation(
        path=path,
        url=pr.get("url", ""),
        status_code=int(status_code) if numeric else 0,
        ok=bool(ok_field) if ok_field is not None else (numeric and 200 <= int(status_code) < 300),
        sha256=pr.get("sha256") or pr.get("content_digest"),
        latency_ms=float(pr.get("latency_ms", 0.0) or 0.0),
        error=pr.get("error"),
    )
    return obs, None


def _check_observed_probes(
    observed: dict[str, Any] | None,
) -> tuple[list[DriftFinding], list[EndpointObservation]]:
    """Non-live path: the receipt must carry real probe records; never synthesize a pass."""
    drifts: list[DriftFinding] = []
    probes: list[EndpointObservation] = []

    observed_probes = observed.get("probes") or observed.get("routes") if observed else None
    if not isinstance(observed_probes, list) or not observed_probes:
        drifts.append(
            DriftFinding(
                drift_type="MISSING_OBSERVATION",
                description="Live-observation receipt carries no public route probe records",
                expected="non-empty 'routes'/'probes' array with per-route status",
                actual=type(observed_probes).__name__ if observed_probes is not None else "None",
            )
        )
        return drifts, probes

    seen_paths: set[str] = set()
    for pr in observed_probes:
        if not isinstance(pr, dict):
            drifts.append(
                DriftFinding(
                    drift_type="MISSING_OBSERVATION",
                    description="Live-observation receipt contains a non-object probe record",
                    expected="probe object",
                    actual=type(pr).__name__,
                )
            )
            continue
        seen_paths.add(pr.get("path") or pr.get("route") or "")
        obs_p, missing = _observation_to_probe(pr)
        if missing is not None:
            drifts.append(missing)
            continue
        assert obs_p is not None
        probes.append(obs_p)
        if not obs_p.ok:
            drifts.append(
                DriftFinding(
                    drift_type="ARTIFACT_DRIFT",
                    description=f"Observed receipt indicates probe failure on '{obs_p.path}'",
                    expected="ok=True",
                    actual=f"ok=False ({obs_p.error})",
                )
            )

    # Partial route success fails closed (contract line 61-62).
    for required in DEFAULT_PROBE_PATHS:
        if required not in seen_paths:
            drifts.append(
                DriftFinding(
                    drift_type="MISSING_OBSERVATION",
                    description=f"Required public route '{required}' has no probe record in the live receipt",
                    expected="probe record present",
                    actual="absent",
                )
            )
    return drifts, probes


def _check_artifact_drift(
    desired_digests: dict[str, str],
    built_digests: dict[str, str],
    observed_digests: dict[str, str],
    base_url: str,
    live: bool,
    observed: dict[str, Any] | None,
) -> tuple[list[DriftFinding], list[EndpointObservation]]:
    """Detect checksum and endpoint response drift across built and observed targets."""
    drifts = _check_built_vs_desired(desired_digests, built_digests)

    if live:
        live_drifts, probes = _run_live_probes(base_url, desired_digests, built_digests)
        return drifts + live_drifts, probes

    obs_drifts, probes = _check_observed_probes(observed)
    drifts.extend(obs_drifts)

    for path, obs_hash in observed_digests.items():
        exp_hash = desired_digests.get(path) or built_digests.get(path)
        if exp_hash and obs_hash.lower() != exp_hash.lower():
            drifts.append(
                DriftFinding(
                    drift_type="ARTIFACT_DRIFT",
                    description=f"Observed receipt digest for '{path}' differs from desired state",
                    expected=exp_hash,
                    actual=obs_hash,
                )
            )

    return drifts, probes


def _check_receipt_contract_fields(observed: dict[str, Any] | None) -> list[DriftFinding]:
    """Verify the live receipt carries every contract-mandated field."""
    drifts: list[DriftFinding] = []
    if observed is None:
        drifts.append(
            DriftFinding(
                drift_type="MISSING_OBSERVATION",
                description="No attested live-observation receipt supplied; only a live receipt proves publication",
                expected="live-observation receipt",
                actual="None",
            )
        )
        return drifts

    for label, keys in REQUIRED_RECEIPT_FIELDS:
        if _first_present(observed, keys) is None:
            drifts.append(
                DriftFinding(
                    drift_type="RECEIPT_INCOMPLETE",
                    description=f"Live receipt is missing the contract-mandated {label} field",
                    expected=f"one of {keys}",
                    actual="absent or empty",
                )
            )

    # Route-set completeness with per-route status.
    routes = observed.get("routes") or observed.get("probes")
    if isinstance(routes, list) and routes:
        for pr in routes:
            if isinstance(pr, dict) and pr.get("status_code") is None and pr.get("ok") is None and "status" not in pr:
                drifts.append(
                    DriftFinding(
                        drift_type="RECEIPT_INCOMPLETE",
                        description="Live receipt route record omits per-route status",
                        expected="status_code / ok / status per route",
                        actual="absent",
                    )
                )
                break

    signature_valid, signature_error = verify_live_receipt_signature(observed)
    if not signature_valid:
        drifts.append(
            DriftFinding(
                drift_type="RECEIPT_SIGNATURE_INVALID",
                description=f"Live receipt attestor signature verification failed: {signature_error}",
                expected="valid Ed25519 signature from the configured attestor key",
                actual="missing, malformed, or unverifiable signature",
            )
        )
    return drifts


def _check_receipt_freshness(
    observed: dict[str, Any] | None,
    live: bool,
    max_age_hours: float,
    now: datetime,
) -> tuple[list[DriftFinding], float | None]:
    """Verify live observation receipt freshness and age (fails closed)."""
    drifts: list[DriftFinding] = []
    receipt_age_hours: float | None = None

    if observed is None:
        drifts.append(
            DriftFinding(
                drift_type="STALE_RECEIPT",
                description="No live-observation receipt to age-check",
                expected=f"receipt <= {max_age_hours}h old",
                actual="None",
            )
        )
        return drifts, None

    obs_timestamp_str = _first_present(observed, ("timestamp", "observed_at", "created_at"))
    if not obs_timestamp_str:
        drifts.append(
            DriftFinding(
                drift_type="STALE_RECEIPT",
                description="Live receipt missing valid observation timestamp",
                expected="ISO-8601 UTC timestamp",
                actual="None",
            )
        )
        return drifts, None

    obs_dt = parse_iso_timestamp(str(obs_timestamp_str))
    if obs_dt is None:
        drifts.append(
            DriftFinding(
                drift_type="STALE_RECEIPT",
                description=f"Live receipt observation timestamp is unparseable: {obs_timestamp_str!r}",
                expected="ISO-8601 UTC timestamp",
                actual=str(obs_timestamp_str),
            )
        )
        return drifts, None

    age_sec = (now - obs_dt).total_seconds()
    if age_sec < -FUTURE_SKEW_SECONDS:
        drifts.append(
            DriftFinding(
                drift_type="STALE_RECEIPT",
                description=(
                    f"Live receipt observation timestamp is in the future by "
                    f"{abs(age_sec) / 3600.0:.2f}h (beyond {FUTURE_SKEW_SECONDS}s skew tolerance)"
                ),
                expected="timestamp <= now",
                actual=str(obs_timestamp_str),
            )
        )
        return drifts, round(age_sec / 3600.0, 2)

    receipt_age_hours = round(age_sec / 3600.0, 2)
    if receipt_age_hours > max_age_hours:
        drifts.append(
            DriftFinding(
                drift_type="STALE_RECEIPT",
                description=(
                    f"Live observation receipt is stale: age {receipt_age_hours}h exceeds "
                    f"maximum threshold of {max_age_hours}h"
                ),
                expected=f"<= {max_age_hours}h",
                actual=f"{receipt_age_hours}h",
            )
        )

    return drifts, receipt_age_hours


def reconcile_states(
    desired: dict[str, Any],
    built: dict[str, Any] | None,
    deployed: dict[str, Any] | None,
    observed: dict[str, Any] | None,
    base_url: str = DEFAULT_BASE_URL,
    live: bool = False,
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    now_dt: datetime | None = None,
) -> ReconciliationReport:
    """Perform 4-way reconciliation across desired, built, deployed, and observed states.

    ``desired`` is required. ``built``, ``deployed``, and ``observed`` may be
    ``None`` (each absence is recorded as fail-closed drift), but when supplied
    they must be *distinct* objects from ``desired`` and from each other: a
    reconciliation that compares a state against itself proves nothing.
    """
    if not isinstance(desired, dict):
        raise ReconciliationInputError("desired manifest must be a JSON object")

    supplied = {
        "built": built,
        "deployed": deployed,
        "observed": observed,
        "desired": desired,
    }
    seen: list[tuple[str, int]] = []
    for name, obj in supplied.items():
        if obj is None:
            continue
        for other_name, other_id in seen:
            if id(obj) == other_id:
                raise ReconciliationInputError(
                    f"reconciliation requires distinct sources: '{name}' and '{other_name}' "
                    f"are the same object; a state cannot be reconciled against itself"
                )
        seen.append((name, id(obj)))

    drifts: list[DriftFinding] = []
    now = now_dt or datetime.now(timezone.utc)

    des_gen = _normalize_generation(desired.get("generation"))
    dep_gen = _normalize_generation(deployed.get("generation")) if deployed else None
    obs_gen = _normalize_generation(observed.get("generation")) if observed else None
    des_commit = _first_present(desired, ("develop_sha", "source_commit", "develop_commit"))
    dep_commit = _first_present(deployed, ("develop_sha", "source_commit", "commit_sha")) if deployed else None

    if built is None:
        drifts.append(
            DriftFinding(
                drift_type="MANIFEST_DRIFT",
                description="No assembly (built) receipt supplied",
                expected="assembly receipt",
                actual="None",
            )
        )
    if deployed is None:
        drifts.append(
            DriftFinding(
                drift_type="GENERATION_DRIFT",
                description="No deployment receipt supplied",
                expected="deployment acknowledgement receipt",
                actual="None",
            )
        )

    drifts.extend(_check_generation_drift(des_gen, dep_gen, obs_gen))
    drifts.extend(_check_manifest_drift(desired, built or {}, deployed or {}))

    desired_digests = extract_artifact_digests(desired)
    built_digests = extract_artifact_digests(built or {})
    observed_digests = extract_artifact_digests(observed or {})
    art_drifts, probes = _check_artifact_drift(
        desired_digests, built_digests, observed_digests, base_url, live, observed
    )
    drifts.extend(art_drifts)

    drifts.extend(_check_receipt_contract_fields(observed))

    stale_drifts, receipt_age_hours = _check_receipt_freshness(observed, live, max_age_hours, now)
    drifts.extend(stale_drifts)

    return ReconciliationReport(
        reconciled=len(drifts) == 0,
        desired_generation=des_gen,
        deployed_generation=dep_gen,
        observed_generation=obs_gen,
        desired_commit=des_commit,
        deployed_commit=dep_commit,
        drift_count=len(drifts),
        drifts=drifts,
        probes=probes,
        receipt_age_hours=receipt_age_hours,
        timestamp=now.isoformat(),
    )


def load_json_file(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk, raising on missing file or non-object payload."""
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(data).__name__}")
    return data


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="4-way Desired-Built-Deployed-Observed reconciliation and drift detector (A11 w1)."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Path to the desired publication manifest JSON (REQUIRED).",
    )
    parser.add_argument(
        "--receipts-dir",
        type=Path,
        default=None,
        help=(
            "Directory containing the real built/deployed/observed receipts "
            f"({ASSEMBLY_RECEIPT_NAME}, {DEPLOYMENT_RECEIPT_NAME}, {LIVE_RECEIPT_NAME}). REQUIRED."
        ),
    )
    parser.add_argument(
        "--base-url",
        type=str,
        default=DEFAULT_BASE_URL,
        help=f"Base URL for external endpoint probes (default: {DEFAULT_BASE_URL}).",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Execute active external network probes against the live base URL.",
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=DEFAULT_MAX_AGE_HOURS,
        help=f"Maximum allowed age for live receipts in hours (default: {DEFAULT_MAX_AGE_HOURS}).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured reconciliation report as JSON to stdout.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if args.manifest is None:
        sys.stderr.write(
            "Error: --manifest is required. This canary cannot verify publication "
            "without a real desired manifest and real built/deployed/observed receipts. "
            "A green run of this canary does not prove live publication "
            "(independent-publication-contract.md lines 22-25).\n"
        )
        return 2
    if args.receipts_dir is None:
        sys.stderr.write(
            f"Error: --receipts-dir is required and must contain {ASSEMBLY_RECEIPT_NAME}, "
            f"{DEPLOYMENT_RECEIPT_NAME}, and {LIVE_RECEIPT_NAME}.\n"
        )
        return 2

    try:
        desired_data = load_json_file(args.manifest)
    except Exception as e:
        sys.stderr.write(f"Error loading manifest file {args.manifest}: {e}\n")
        return 2

    receipts_dir = args.receipts_dir
    if not receipts_dir.is_dir():
        sys.stderr.write(f"Receipts directory not found: {receipts_dir}\n")
        return 2

    required = {
        "built": receipts_dir / ASSEMBLY_RECEIPT_NAME,
        "deployed": receipts_dir / DEPLOYMENT_RECEIPT_NAME,
        "observed": receipts_dir / LIVE_RECEIPT_NAME,
    }
    loaded: dict[str, dict[str, Any]] = {}
    for name, path in required.items():
        if not path.is_file():
            sys.stderr.write(f"Error: required {name} receipt missing: {path}\n")
            return 2
        try:
            loaded[name] = load_json_file(path)
        except Exception as e:
            sys.stderr.write(f"Error loading {name} receipt {path}: {e}\n")
            return 2

    try:
        report = reconcile_states(
            desired=desired_data,
            built=loaded["built"],
            deployed=loaded["deployed"],
            observed=loaded["observed"],
            base_url=args.base_url,
            live=args.live,
            max_age_hours=args.max_age_hours,
        )
    except ReconciliationInputError as e:
        sys.stderr.write(f"Error: {e}\n")
        return 2

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        status_str = "PASS - RECONCILED" if report.reconciled else "FAIL - DRIFT DETECTED"
        print(f"Publication 4-Way Reconciliation: {status_str}")
        print(f"  Desired Generation : {report.desired_generation}")
        print(f"  Deployed Generation: {report.deployed_generation}")
        print(f"  Observed Generation: {report.observed_generation}")
        print(f"  Drifts Detected    : {report.drift_count}")
        if report.receipt_age_hours is not None:
            print(f"  Receipt Age (hours): {report.receipt_age_hours:.1f}h")

        if report.drifts:
            print("\nDrift Details:")
            for d in report.drifts:
                print(f"  - [{d.drift_type}] {d.description}")
                if d.expected is not None or d.actual is not None:
                    print(f"      Expected: {d.expected}")
                    print(f"      Actual  : {d.actual}")

    return 0 if report.reconciled else 1


if __name__ == "__main__":
    sys.exit(main())
