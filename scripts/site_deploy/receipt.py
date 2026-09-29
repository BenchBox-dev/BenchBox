"""Artifact identity and deployment receipts.

A receipt binds one assembled site to the commits it was built from and, after
deployment, to what the public origin served. The artifact identity is the sha256
of a deterministic tar of the site tree, so the same tree always hashes the same.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tarfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.site_deploy.generation import DeployedState, Generation, RollbackTarget

SCHEMA_VERSION = 1
RECEIPT_KIND = "site-deploy-receipt"
STATUS_CANDIDATE = "candidate"
STATUS_LIVE_VERIFIED = "live-verified"
STATUS_PREVIEW_VERIFIED = "preview-verified"
STATUS_PROBE_FAILED = "probe-failed"
STATUSES = (STATUS_CANDIDATE, STATUS_LIVE_VERIFIED, STATUS_PREVIEW_VERIFIED, STATUS_PROBE_FAILED)
TARGETS = ("preview", "production")
OPERATIONS = ("deploy", "rollback")

ARCHIVE_NAME = "site-artifact.tar"
RECEIPT_NAME = "receipt.json"
# Pages does not serve these as files, so they are never part of a probe set.
UNPROBED_FILES = frozenset({"CNAME", "404.html"})
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

DEPLOYMENT_DESCRIPTION_PREFIX = "site-deploy v1"
_DESCRIPTION_RE = re.compile(
    r"^site-deploy v1 st=(?P<st>ok|failed) g=(?P<index>\d+) rel=(?P<rel>v\d+\.\d+\.\d+) "
    r"trunk=(?P<trunk>[0-9a-f]{40}) run=(?P<run>\d+) art=(?P<art>[0-9a-f]{12})$"
)


class ReceiptError(ValueError):
    """A receipt or artifact failed validation."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def site_files(site_dir: Path) -> list[str]:
    """Sorted site-relative POSIX paths of every regular file; symlinks are refused."""
    found: list[str] = []
    for current, dirnames, filenames in os.walk(site_dir, followlinks=False):
        dirnames.sort()
        for name in dirnames:
            if (Path(current) / name).is_symlink():
                raise ReceiptError(f"symlinked directory in site tree: {Path(current) / name}")
        for name in sorted(filenames):
            path = Path(current) / name
            if path.is_symlink():
                raise ReceiptError(f"symlink in site tree: {path}")
            found.append(path.relative_to(site_dir).as_posix())
    return sorted(found)


@dataclass(frozen=True)
class TreeIdentity:
    file_digests: dict[str, str]
    total_bytes: int
    tree_digest: str

    @property
    def file_count(self) -> int:
        return len(self.file_digests)


def tree_identity(site_dir: Path) -> TreeIdentity:
    """Per-file sha256 plus one digest over ``path:sha256:size`` lines."""
    digests: dict[str, str] = {}
    total = 0
    outer = hashlib.sha256()
    for rel in site_files(site_dir):
        path = site_dir / rel
        size = path.stat().st_size
        digest = sha256_file(path)
        digests[rel] = digest
        total += size
        outer.update(f"{rel}:{digest}:{size}\n".encode())
    return TreeIdentity(digests, total, outer.hexdigest())


def write_deterministic_tar(site_dir: Path, archive: Path) -> str:
    """Write a byte-reproducible tar of ``site_dir`` and return its sha256."""
    archive.parent.mkdir(parents=True, exist_ok=True)
    with archive.open("wb") as handle, tarfile.open(fileobj=handle, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for rel in site_files(site_dir):
            source = site_dir / rel
            info = tarfile.TarInfo(name=rel)
            info.size = source.stat().st_size
            info.mtime = 0
            info.mode = 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with source.open("rb") as body:
                tar.addfile(info, body)
    return sha256_file(archive)


def extract_tar_safely(archive: Path, destination: Path) -> None:
    """Extract a site archive, refusing anything but plain files inside ``destination``."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with tarfile.open(archive, mode="r") as tar:
        members = tar.getmembers()
        for member in members:
            target = (root / member.name).resolve()
            if not member.isfile():
                raise ReceiptError(f"archive member is not a regular file: {member.name}")
            if member.name.startswith("/") or root not in target.parents:
                raise ReceiptError(f"archive member escapes the destination: {member.name}")
        for member in members:
            target = root / member.name
            target.parent.mkdir(parents=True, exist_ok=True)
            source = tar.extractfile(member)
            assert source is not None
            with target.open("wb") as out:
                out.write(source.read())


def _entry_file(mount: str) -> str:
    rel = mount.strip("/")
    return f"{rel}/index.html" if rel else "index.html"


def build_probe_set(
    site_dir: Path,
    identity: TreeIdentity,
    mounts: Iterable[str],
    *,
    sample_per_route: int = 40,
) -> dict[str, str]:
    """URL path -> sha256 for the bytes the public origin must serve.

    Every route's entry page is always included (as its directory URL and its file
    URL), the Results snapshot is always included, and a deterministic sample of the
    remaining files under each route is added. The sample is keyed to the tree
    digest, so it changes when the site changes but is stable for a given artifact.
    """
    checksums: dict[str, str] = {}
    ordered_mounts = sorted(set(mounts), key=lambda m: (-len(m), m))
    for mount in sorted(set(mounts)):
        entry = _entry_file(mount)
        if entry not in identity.file_digests:
            raise ReceiptError(f"route {mount} has no entry page {entry}")
        checksums[mount] = identity.file_digests[entry]
        checksums[f"/{entry}"] = identity.file_digests[entry]

    def owning_mount(rel: str) -> str:
        for mount in ordered_mounts:
            if mount == "/" or f"/{rel}".startswith(mount):
                return mount
        return "/"

    buckets: dict[str, list[str]] = {mount: [] for mount in ordered_mounts}
    for rel in identity.file_digests:
        if rel in UNPROBED_FILES or any(part.startswith(".") for part in rel.split("/")):
            continue
        buckets[owning_mount(rel)].append(rel)
    for mount, files in buckets.items():
        files.sort(key=lambda rel: sha256_bytes(f"{identity.tree_digest}:{rel}".encode()))
        for rel in files[:sample_per_route]:
            checksums[f"/{rel}"] = identity.file_digests[rel]
    snapshot = "results/data/results.duckdb"
    if snapshot in identity.file_digests:
        checksums[f"/{snapshot}"] = identity.file_digests[snapshot]
    return dict(sorted(checksums.items()))


def deployment_description(generation: Generation, run_id: int | str, artifact_sha256: str, *, verified: bool) -> str:
    """The <=140 character text stored on the Deployment status that indexes a receipt.

    ``st=failed`` marks a deployment that went live but did not pass its post-deploy
    probes, so the next run orders against it instead of an older healthy one.
    """
    text = (
        f"{DEPLOYMENT_DESCRIPTION_PREFIX} st={'ok' if verified else 'failed'} "
        f"g={generation.trunk_index} rel={generation.release_tag} "
        f"trunk={generation.trunk_sha} run={run_id} art={artifact_sha256[:12]}"
    )
    if len(text) > 140:
        raise ReceiptError(f"deployment description exceeds 140 characters: {len(text)}")
    return text


def parse_deployment_description(text: str | None) -> dict[str, str] | None:
    match = _DESCRIPTION_RE.match(text or "")
    return match.groupdict() if match else None


def new_receipt(
    *,
    receipt_id: str,
    operation: str,
    target: str,
    generation: Generation,
    routes: list[dict[str, Any]],
    identity_evidence: dict[str, Any],
    identity: TreeIdentity,
    archive_sha256: str,
    explorer: dict[str, Any],
    gates: list[dict[str, Any]],
    checksums: Mapping[str, str],
    quarantine: tuple[Iterable[str], Iterable[str]],
    workflow: dict[str, Any],
    created_at: str,
    rollback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if operation not in OPERATIONS or target not in TARGETS:
        raise ReceiptError(f"invalid operation/target: {operation!r}/{target!r}")
    return {
        "kind": RECEIPT_KIND,
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "operation": operation,
        "target": target,
        "status": STATUS_CANDIDATE,
        "created_at": created_at,
        "workflow": workflow,
        "generation": generation.to_dict(),
        "routes": routes,
        "candidate_identity": identity_evidence,
        "artifact": {
            "archive": ARCHIVE_NAME,
            "sha256": archive_sha256,
            "tree_digest": identity.tree_digest,
            "file_count": identity.file_count,
            "total_bytes": identity.total_bytes,
        },
        "explorer": explorer,
        "gates": gates,
        "checksums": dict(checksums),
        "quarantine": {
            "trunk_shas": sorted(set(quarantine[0])),
            "release_tags": sorted(set(quarantine[1])),
        },
        "rollback": rollback,
        "deployment": {"confirmed": False},
        "probes": None,
    }


def finalize_receipt(
    receipt: dict[str, Any],
    *,
    probes: dict[str, Any],
    deployment: dict[str, Any],
    observed_at: str,
) -> dict[str, Any]:
    """Return a copy of ``receipt`` recording deployment and probe outcomes."""
    final = json.loads(json.dumps(receipt))
    final["deployment"] = deployment
    final["probes"] = {**probes, "observed_at": observed_at}
    if not probes.get("ok"):
        final["status"] = STATUS_PROBE_FAILED
    elif receipt["target"] == "production" and deployment.get("confirmed"):
        final["status"] = STATUS_LIVE_VERIFIED
    elif receipt["target"] == "preview":
        final["status"] = STATUS_PREVIEW_VERIFIED
    else:
        final["status"] = STATUS_PROBE_FAILED
    return final


def validate_receipt(receipt: object) -> list[str]:
    """Structural problems in a receipt; empty means it is well formed."""
    if not isinstance(receipt, dict):
        return ["receipt is not a JSON object"]
    problems: list[str] = []
    if receipt.get("kind") != RECEIPT_KIND:
        problems.append(f"kind must be {RECEIPT_KIND!r}")
    if receipt.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"unsupported schema_version {receipt.get('schema_version')!r}")
    if receipt.get("operation") not in OPERATIONS:
        problems.append("invalid operation")
    if receipt.get("target") not in TARGETS:
        problems.append("invalid target")
    if receipt.get("status") not in STATUSES:
        problems.append("invalid status")
    if not isinstance(receipt.get("receipt_id"), str) or not receipt.get("receipt_id"):
        problems.append("receipt_id is missing")
    try:
        Generation.from_dict(receipt.get("generation"))
    except ValueError as exc:
        problems.append(f"generation: {exc}")
    artifact = receipt.get("artifact")
    if not isinstance(artifact, dict) or not SHA256_RE.match(str(artifact.get("sha256", ""))):
        problems.append("artifact.sha256 is missing or malformed")
    if not isinstance(receipt.get("checksums"), dict) or not receipt.get("checksums"):
        problems.append("checksums are missing")
    if not isinstance(receipt.get("routes"), list) or not receipt.get("routes"):
        problems.append("routes are missing")
    return problems


def _require_valid(receipt: object) -> dict[str, Any]:
    problems = validate_receipt(receipt)
    if problems:
        raise ReceiptError("invalid receipt: " + "; ".join(problems))
    assert isinstance(receipt, dict)
    return receipt


def deployed_state_from_receipt(receipt: object) -> DeployedState:
    data = _require_valid(receipt)
    quarantine = data.get("quarantine") or {}
    return DeployedState(
        generation=Generation.from_dict(data["generation"]),
        receipt_id=str(data["receipt_id"]),
        artifact_sha256=str(data["artifact"]["sha256"]),
        quarantined_trunk_shas=frozenset(quarantine.get("trunk_shas", [])),
        quarantined_release_tags=frozenset(quarantine.get("release_tags", [])),
    )


def rollback_target_from_receipt(receipt: object) -> RollbackTarget:
    data = _require_valid(receipt)
    probes = data.get("probes") or {}
    deployment = data.get("deployment") or {}
    return RollbackTarget(
        receipt_id=str(data["receipt_id"]),
        generation=Generation.from_dict(data["generation"]),
        artifact_sha256=str(data["artifact"]["sha256"]),
        target=str(data["target"]),
        status=str(data["status"]),
        probes_ok=bool(probes.get("ok")),
        deployment_confirmed=bool(deployment.get("confirmed")),
    )


def explorer_versions_from_receipt(receipt: object) -> tuple[int, int] | None:
    """(UI read-model version, snapshot read-model version) recorded in a receipt."""
    data = _require_valid(receipt)
    explorer = data.get("explorer") or {}
    ui = explorer.get("ui_read_model_version")
    snapshot = explorer.get("snapshot_read_model_version")
    if isinstance(ui, int) and isinstance(snapshot, int):
        return ui, snapshot
    return None


def verify_archive(archive: Path, receipt: object) -> None:
    """Refuse an archive whose bytes are not the ones the receipt names."""
    data = _require_valid(receipt)
    actual = sha256_file(archive)
    expected = str(data["artifact"]["sha256"])
    if actual != expected:
        raise ReceiptError(f"archive sha256 {actual} does not match receipt {expected}")


def verify_extracted_tree(site_dir: Path, receipt: object) -> TreeIdentity:
    """Confirm an extracted tree matches the receipt's tree digest and probe checksums."""
    data = _require_valid(receipt)
    identity = tree_identity(site_dir)
    expected = data["artifact"]["tree_digest"]
    if identity.tree_digest != expected:
        raise ReceiptError(f"extracted tree digest {identity.tree_digest} does not match receipt {expected}")
    for url_path, digest in data["checksums"].items():
        rel = _entry_file(url_path) if url_path.endswith("/") else url_path.lstrip("/")
        if identity.file_digests.get(rel) != digest:
            raise ReceiptError(f"extracted file {rel} does not match receipt checksum for {url_path}")
    return identity


def dumps(receipt: Mapping[str, Any]) -> str:
    return json.dumps(receipt, indent=2, sort_keys=True) + "\n"


def read_receipt(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReceiptError(f"cannot read receipt {path}: {exc}") from exc
    _require_valid(data)
    return data
