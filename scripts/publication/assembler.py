#!/usr/bin/env python3
"""Hermetic lane artifact builders and deterministic whole-site assembler (A4 w1, w3).

Builds immutable, content-addressed lane artifacts for prose, API docs, Explorer,
publisher, and corpus read models, then assembles them into a unified shadow site
tree with strict path ownership.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
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


class DigestMismatchError(Exception):
    """Raised when a lane source tree does not match the declared artifact identity."""


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


def verify_lane_digest(artifact: LaneArtifact, src_dir: Path) -> tuple[str, int, dict[str, str]]:
    """Verify src_dir against declared digest/manifest/size; return computed identity."""
    computed_digest, computed_size, computed_manifest = compute_tree_digest(src_dir)

    if not artifact.digest or artifact.digest != computed_digest:
        raise DigestMismatchError(
            f"Lane '{artifact.lane_name}' digest mismatch: declared={artifact.digest!r}, computed={computed_digest}"
        )

    if artifact.size_bytes > 0 and artifact.size_bytes != computed_size:
        raise DigestMismatchError(
            f"Lane '{artifact.lane_name}' size mismatch: declared={artifact.size_bytes}, computed={computed_size}"
        )

    if artifact.file_manifest:
        declared = artifact.file_manifest
        declared_paths = set(declared)
        computed_paths = set(computed_manifest)
        missing = sorted(declared_paths - computed_paths)
        extra = sorted(computed_paths - declared_paths)
        if missing or extra:
            raise DigestMismatchError(
                f"Lane '{artifact.lane_name}' file_manifest path mismatch: missing={missing}, extra={extra}"
            )
        mismatched = sorted(path for path, sha in declared.items() if computed_manifest.get(path) != sha)
        if mismatched:
            raise DigestMismatchError(f"Lane '{artifact.lane_name}' file_manifest hash mismatch for: {mismatched}")

    return computed_digest, computed_size, computed_manifest


class SiteAssembler:
    """Assembles lane artifacts into a deterministic, unified site tree with path ownership."""

    def __init__(self, output_dir: Path, receipt_path: Path | None = None) -> None:
        self.output_dir = output_dir
        self.receipt_path = receipt_path or (output_dir.parent / f"{output_dir.name}-receipt.json")
        self.claimed_paths: dict[str, str] = {}  # rel_path -> lane_name

    def mount_lane_artifact(self, artifact: LaneArtifact, src_dir: Path) -> None:
        """Mount files from a lane artifact into the output directory, enforcing path ownership."""
        if not src_dir.exists():
            raise FileNotFoundError(f"Source directory for lane '{artifact.lane_name}' not found: {src_dir}")

        verify_lane_digest(artifact, src_dir)

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
        shutil.copyfile(src, dest_path)

    def assemble(self, artifacts: list[tuple[LaneArtifact, Path]]) -> tuple[dict[str, Any], Path]:
        """Assemble all artifacts and write a receipt outside the hashed output tree."""
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

        receipt_path = self.receipt_path
        if (
            receipt_path.resolve() == self.output_dir.resolve()
            or self.output_dir.resolve() in receipt_path.resolve().parents
        ):
            raise ValueError(f"receipt_path must be outside hashed output tree: {receipt_path}")
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        with open(receipt_path, "w", encoding="utf-8") as f:
            json.dump(receipt, f, indent=2, sort_keys=True)

        return receipt, receipt_path


def _parse_lane_spec(spec: str) -> tuple[str, Path, str]:
    """Parse ``name=NAME,src=SRC,prefix=PREFIX`` into components."""
    parts: dict[str, str] = {}
    for chunk in spec.split(","):
        if "=" not in chunk:
            raise argparse.ArgumentTypeError(f"invalid lane spec chunk (expected key=value): {chunk!r} in {spec!r}")
        key, value = chunk.split("=", 1)
        parts[key.strip()] = value.strip()
    missing = [key for key in ("name", "src", "prefix") if key not in parts]
    if missing:
        raise argparse.ArgumentTypeError(f"lane spec missing {missing}: {spec!r}")
    return parts["name"], Path(parts["src"]), parts["prefix"]


def build_lane_artifact(name: str, src: Path, prefix: str) -> LaneArtifact:
    digest, size_bytes, file_manifest = compute_tree_digest(src)
    return LaneArtifact(
        lane_name=name,
        digest=digest,
        size_bytes=size_bytes,
        source_path=str(src),
        output_prefix=prefix,
        file_manifest=file_manifest,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--receipt-path", type=Path, required=True)
    parser.add_argument(
        "--lane",
        action="append",
        default=[],
        metavar="name=NAME,src=SRC,prefix=PREFIX",
        help="Repeatable lane mount spec",
    )
    args = parser.parse_args(argv)
    if not args.lane:
        print("ERROR: at least one --lane is required", file=sys.stderr)
        return 2

    try:
        artifacts: list[tuple[LaneArtifact, Path]] = []
        for spec in args.lane:
            name, src, prefix = _parse_lane_spec(spec)
            if not src.exists():
                print(f"ERROR: lane src not found: {src}", file=sys.stderr)
                return 1
            artifacts.append((build_lane_artifact(name, src, prefix), src))

        assembler = SiteAssembler(args.output_dir, receipt_path=args.receipt_path)
        receipt, receipt_path = assembler.assemble(artifacts)
        print(f"assembled digest={receipt['assembly_digest']} files={receipt['total_files']} receipt={receipt_path}")
        return 0
    except (DigestMismatchError, PathOwnershipError, ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
