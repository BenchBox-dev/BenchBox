#!/usr/bin/env python3
"""Publication manifest schema, validation, and serialization (A3 w1).

Defines the desired-state manifest contract for independent publication,
including monotonic generation, parent commit linkage for CAS, complete
build closure pins, and immutable artifact digests.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

SCHEMA_VERSION = 2
HEX_40_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
HEX_64_RE = re.compile(r"^(sha256:)?[0-9a-f]{64}$", re.IGNORECASE)

REQUIRED_BUILD_CLOSURE_FIELDS = (
    "os_image",
    "python_version",
    "node_version",
    "uv_version",
    "lockfile_sha256",
    "workflow_sha",
    "action_shas",
    "read_model_version",
)

REQUIRED_ARTIFACT_NAMES = (
    "prose_site",
    "api_docs",
    "explorer_app",
    "publisher_bundle",
    "corpus_database",
    "pages_assembly",
)


@dataclass(frozen=True)
class BuildClosure:
    os_image: str
    python_version: str
    node_version: str
    uv_version: str
    lockfile_sha256: str
    workflow_sha: str
    action_shas: dict[str, str]
    read_model_version: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArtifactEntry:
    digest: str
    size: int
    path: str
    bundle_count: int | None = None
    inventory_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "digest": self.digest,
            "size": self.size,
            "path": self.path,
        }
        if self.bundle_count is not None:
            d["bundle_count"] = self.bundle_count
        if self.inventory_digest is not None:
            d["inventory_digest"] = self.inventory_digest
        return d


@dataclass(frozen=True)
class CorpusSummary:
    bundle_count: int
    inventory_sha256: str
    read_model_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PublicationManifest:
    generation: int
    parent_sha: str | None
    parent_generation: int | None
    source_commit: str
    source_branch: str
    build_closure: BuildClosure
    artifacts: dict[str, ArtifactEntry]
    corpus: CorpusSummary
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    schema_version: int = SCHEMA_VERSION
    signature: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "generation": self.generation,
            "parent_sha": self.parent_sha,
            "parent_generation": self.parent_generation,
            "source_commit": self.source_commit,
            "source_branch": self.source_branch,
            "created_at": self.created_at,
            "build_closure": self.build_closure.to_dict(),
            "artifacts": {k: v.to_dict() for k, v in self.artifacts.items()},
            "corpus": self.corpus.to_dict(),
            "signature": self.signature,
        }

    def compute_digest(self) -> str:
        """Compute canonical SHA-256 digest of the manifest content excluding signature."""
        data = self.to_dict()
        data["signature"] = None
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def _is_valid_sha40(val: Any) -> bool:
    return isinstance(val, str) and bool(HEX_40_RE.match(val))


def _is_valid_sha64(val: Any) -> bool:
    return isinstance(val, str) and bool(HEX_64_RE.match(val))


def _validate_generation_and_parent(data: dict[str, Any], errors: list[str]) -> None:
    gen = data.get("generation")
    if not isinstance(gen, int) or gen < 1:
        errors.append(f"generation must be a positive integer >= 1, got {gen}")
        return

    parent_sha = data.get("parent_sha")
    parent_gen = data.get("parent_generation")

    if gen == 1:
        if parent_sha is not None:
            errors.append(f"genesis manifest (generation 1) must have parent_sha=None, got {parent_sha}")
        if parent_gen is not None:
            errors.append(f"genesis manifest (generation 1) must have parent_generation=None, got {parent_gen}")
    else:
        if not _is_valid_sha40(parent_sha):
            errors.append(f"parent_sha must be a 40-char hex string for generation {gen}, got {parent_sha}")
        if not isinstance(parent_gen, int) or parent_gen != gen - 1:
            errors.append(f"parent_generation must be {gen - 1} for generation {gen}, got {parent_gen}")


def _validate_source(data: dict[str, Any], errors: list[str]) -> None:
    source_commit = data.get("source_commit")
    if not _is_valid_sha40(source_commit):
        errors.append(f"source_commit must be a 40-char hex string, got {source_commit}")

    source_branch = data.get("source_branch")
    if not isinstance(source_branch, str) or not source_branch.strip():
        errors.append(f"source_branch must be a non-empty string, got {source_branch}")


def _validate_build_closure(data: dict[str, Any], errors: list[str]) -> None:
    closure = data.get("build_closure")
    if not isinstance(closure, dict):
        errors.append("build_closure must be a dictionary")
        return

    for fld in REQUIRED_BUILD_CLOSURE_FIELDS:
        if fld not in closure or closure[fld] is None:
            errors.append(f"build_closure missing required field: '{fld}'")

    if closure.get("lockfile_sha256") and not _is_valid_sha64(closure["lockfile_sha256"]):
        errors.append(
            f"build_closure.lockfile_sha256 must be a 64-char hex digest, got {closure.get('lockfile_sha256')}"
        )
    if closure.get("workflow_sha") and not _is_valid_sha40(closure["workflow_sha"]):
        errors.append(f"build_closure.workflow_sha must be a 40-char hex commit, got {closure.get('workflow_sha')}")

    action_shas = closure.get("action_shas")
    if not isinstance(action_shas, dict) or not action_shas:
        errors.append("build_closure.action_shas must be a non-empty dictionary of pinned actions")
    else:
        for act, sha in action_shas.items():
            if not _is_valid_sha40(sha):
                errors.append(f"action '{act}' must have a 40-char hex SHA, got {sha}")


def _validate_artifacts(data: dict[str, Any], errors: list[str]) -> None:
    artifacts = data.get("artifacts")
    if not isinstance(artifacts, dict):
        errors.append("artifacts must be a dictionary")
        return

    for name in REQUIRED_ARTIFACT_NAMES:
        if name not in artifacts:
            errors.append(f"artifacts missing required entry: '{name}'")
            continue
        art = artifacts[name]
        if not isinstance(art, dict):
            errors.append(f"artifact '{name}' must be a dictionary")
            continue
        if not _is_valid_sha64(art.get("digest")):
            errors.append(f"artifact '{name}' has invalid digest: {art.get('digest')}")
        if not isinstance(art.get("size"), int) or art.get("size") < 0:
            errors.append(f"artifact '{name}' has invalid size: {art.get('size')}")
        if not isinstance(art.get("path"), str) or not art.get("path").strip():
            errors.append(f"artifact '{name}' has invalid path: {art.get('path')}")


def _validate_corpus(data: dict[str, Any], errors: list[str]) -> None:
    corpus = data.get("corpus")
    if not isinstance(corpus, dict):
        errors.append("corpus must be a dictionary")
        return

    cnt = corpus.get("bundle_count")
    if not isinstance(cnt, int) or cnt < 0:
        errors.append(f"corpus.bundle_count must be a non-negative integer, got {cnt}")
    if not _is_valid_sha64(corpus.get("inventory_sha256")):
        errors.append(f"corpus.inventory_sha256 must be a 64-char hex digest, got {corpus.get('inventory_sha256')}")
    if not _is_valid_sha64(corpus.get("read_model_sha256")):
        errors.append(f"corpus.read_model_sha256 must be a 64-char hex digest, got {corpus.get('read_model_sha256')}")


def validate_manifest_dict(data: dict[str, Any]) -> list[str]:
    """Validate a raw manifest dictionary and return a list of error strings."""
    errors: list[str] = []

    if data.get("schema_version") != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}, got {data.get('schema_version')}")

    _validate_generation_and_parent(data, errors)
    _validate_source(data, errors)
    _validate_build_closure(data, errors)
    _validate_artifacts(data, errors)
    _validate_corpus(data, errors)

    return errors


def serialize_manifest(manifest: PublicationManifest, indent: int = 2) -> str:
    """Serialize a publication manifest to JSON string."""
    errors = validate_manifest_dict(manifest.to_dict())
    if errors:
        raise ValueError(f"Cannot serialize invalid manifest: {'; '.join(errors)}")
    return json.dumps(manifest.to_dict(), indent=indent, sort_keys=True) + "\n"


def deserialize_manifest(raw: str | dict[str, Any]) -> PublicationManifest:
    """Deserialize JSON string or dictionary into a PublicationManifest."""
    data = json.loads(raw) if isinstance(raw, str) else raw
    errors = validate_manifest_dict(data)
    if errors:
        raise ValueError(f"Invalid publication manifest: {'; '.join(errors)}")

    closure_data = data["build_closure"]
    build_closure = BuildClosure(
        os_image=closure_data["os_image"],
        python_version=closure_data["python_version"],
        node_version=closure_data["node_version"],
        uv_version=closure_data["uv_version"],
        lockfile_sha256=closure_data["lockfile_sha256"],
        workflow_sha=closure_data["workflow_sha"],
        action_shas=dict(closure_data["action_shas"]),
        read_model_version=closure_data["read_model_version"],
    )

    artifacts: dict[str, ArtifactEntry] = {}
    for name, art_data in data["artifacts"].items():
        artifacts[name] = ArtifactEntry(
            digest=art_data["digest"],
            size=art_data["size"],
            path=art_data["path"],
            bundle_count=art_data.get("bundle_count"),
            inventory_digest=art_data.get("inventory_digest"),
        )

    corpus_data = data["corpus"]
    corpus = CorpusSummary(
        bundle_count=corpus_data["bundle_count"],
        inventory_sha256=corpus_data["inventory_sha256"],
        read_model_sha256=corpus_data["read_model_sha256"],
    )

    return PublicationManifest(
        schema_version=data["schema_version"],
        generation=data["generation"],
        parent_sha=data["parent_sha"],
        parent_generation=data["parent_generation"],
        source_commit=data["source_commit"],
        source_branch=data["source_branch"],
        created_at=data["created_at"],
        build_closure=build_closure,
        artifacts=artifacts,
        corpus=corpus,
        signature=data.get("signature"),
    )
