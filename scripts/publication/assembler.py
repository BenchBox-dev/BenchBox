#!/usr/bin/env python3
"""Hermetic lane artifact builders and deterministic whole-site assembler (A4 w1, w3).

Builds immutable, content-addressed lane artifacts for prose, API docs, Explorer,
publisher, and corpus read models, then assembles them into a unified shadow site
tree with strict path ownership.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class LaneArtifact:
    lane_name: str
    digest: str
    size_bytes: int
    source_path: str
    output_prefix: str
    file_manifest: dict[str, str] = field(default_factory=dict)  # rel_path -> sha256

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PathOwnershipError(Exception):
    """Raised when multiple publication lanes claim ownership of the same output path."""


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 digest of a single file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def compute_tree_digest(tree_dir: Path) -> tuple[str, int, dict[str, str]]:
    """Compute tree digest, total byte size, and file-by-file manifest for a directory."""
    if not tree_dir.exists():
        return hashlib.sha256(b"").hexdigest(), 0, {}

    if tree_dir.is_file():
        sha = compute_file_sha256(tree_dir)
        size = tree_dir.stat().st_size
        return sha, size, {tree_dir.name: sha}

    manifest: dict[str, str] = {}
    total_size = 0
    h = hashlib.sha256()

    for root, _, files in sorted(os.walk(tree_dir)):
        for f in sorted(files):
            full_path = Path(root) / f
            rel_path = full_path.relative_to(tree_dir).as_posix()
            file_sha = compute_file_sha256(full_path)
            file_size = full_path.stat().st_size
            manifest[rel_path] = file_sha
            total_size += file_size
            h.update(f"{rel_path}:{file_sha}:{file_size}\n".encode())

    return h.hexdigest(), total_size, manifest


class SiteAssembler:
    """Assembles lane artifacts into a deterministic, unified site tree with path ownership."""

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.claimed_paths: dict[str, str] = {}  # rel_path -> lane_name

    def mount_lane_artifact(self, artifact: LaneArtifact, src_dir: Path) -> None:
        """Mount files from a lane artifact into the output directory, enforcing path ownership."""
        if not src_dir.exists():
            raise FileNotFoundError(f"Source directory for lane '{artifact.lane_name}' not found: {src_dir}")

        prefix = artifact.output_prefix.strip("/")

        if src_dir.is_file():
            rel_dest = prefix if prefix else src_dir.name
            self._claim_and_copy_file(src_dir, rel_dest, artifact.lane_name)
            return

        for root, _, files in sorted(os.walk(src_dir)):
            for f in sorted(files):
                full_src = Path(root) / f
                sub_rel = full_src.relative_to(src_dir).as_posix()
                rel_dest = f"{prefix}/{sub_rel}" if prefix else sub_rel
                self._claim_and_copy_file(full_src, rel_dest, artifact.lane_name)

    def _claim_and_copy_file(self, src: Path, rel_dest: str, lane_name: str) -> None:
        if rel_dest in self.claimed_paths:
            existing_lane = self.claimed_paths[rel_dest]
            raise PathOwnershipError(
                f"Path collision on '{rel_dest}': claimed by '{lane_name}', already owned by '{existing_lane}'"
            )

        self.claimed_paths[rel_dest] = lane_name
        dest_path = self.output_dir / rel_dest
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_path)

    def assemble(self, artifacts: list[tuple[LaneArtifact, Path]]) -> dict[str, Any]:
        """Assemble all artifacts and produce a summary receipt."""
        if self.output_dir.exists():
            shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.claimed_paths.clear()

        for art, src in artifacts:
            self.mount_lane_artifact(art, src)

        tree_digest, total_bytes, manifest = compute_tree_digest(self.output_dir)

        receipt = {
            "assembly_digest": tree_digest,
            "total_bytes": total_bytes,
            "total_files": len(manifest),
            "lanes": [art.lane_name for art, _ in artifacts],
            "file_manifest": manifest,
        }

        receipt_path = self.output_dir / "publication-receipt.json"
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2, sort_keys=True)

        return receipt
