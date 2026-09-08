#!/usr/bin/env python3
"""Validate the immutable artifact selected for a publication.

The GitHub artifact ID is the operator-facing selector.  This module validates
the producing workflow, manifest, complete required route coverage, and the
unpacked site tree before the approval gate or journal writer is reached.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from scripts.publication.assembler import compute_tree_digest
from scripts.publication.manifest import validate_manifest_dict
from scripts.publication.verify_live import REQUIRED_ROUTE_CHECKSUMS

EXPECTED_WORKFLOW_NAME = "Publication Control Plane Deployment"
EXPECTED_WORKFLOW_PATH = ".github/workflows/publication-deploy.yml"
MAX_CANDIDATE_MEMBERS = 100_000
MAX_CANDIDATE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024


class CandidateValidationError(ValueError):
    """Raised when a selected artifact cannot be trusted as a candidate."""


def _sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _commit_sha(value: str) -> bool:
    return len(value) == 40 and all(char in "0123456789abcdef" for char in value)


def archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateValidationError(f"invalid JSON at {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise CandidateValidationError(f"expected JSON object at {path}")
    return data


def manifest_digest(manifest: dict[str, Any]) -> str:
    """Compute the digest used by publication manifests."""
    payload = dict(manifest)
    payload.pop("manifest_digest", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def validate_route_checksums(manifest: dict[str, Any]) -> dict[str, str]:
    """Require every public route used by the publication contract."""
    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        raise CandidateValidationError("candidate manifest must contain a checksums object")
    missing = [path for path in REQUIRED_ROUTE_CHECKSUMS if path not in checksums]
    if missing:
        raise CandidateValidationError(f"candidate manifest is missing required route checksums: {missing}")
    malformed = [
        path
        for path in REQUIRED_ROUTE_CHECKSUMS
        if not isinstance(checksums[path], str) or not _sha256(checksums[path])
    ]
    if malformed:
        raise CandidateValidationError(f"candidate manifest has malformed route checksums: {malformed}")
    return {str(path): str(value) for path, value in checksums.items()}


def _validate_zip_member(name: str) -> None:
    path = Path(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise CandidateValidationError(f"candidate archive contains unsafe path: {name!r}")


def extract_candidate_archive(archive: Path, output_dir: Path) -> Path:
    """Safely extract a candidate archive and return its root directory."""
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)
    try:
        with zipfile.ZipFile(archive) as bundle:
            if len(bundle.infolist()) > MAX_CANDIDATE_MEMBERS:
                raise CandidateValidationError("candidate archive contains too many members")
            total_size = sum(member.file_size for member in bundle.infolist())
            if total_size > MAX_CANDIDATE_UNCOMPRESSED_BYTES:
                raise CandidateValidationError("candidate archive exceeds the uncompressed size limit")
            seen_names: set[str] = set()
            for member in bundle.infolist():
                _validate_zip_member(member.filename)
                normalized_name = member.filename.replace("\\", "/")
                if normalized_name in seen_names:
                    raise CandidateValidationError(f"candidate archive contains a duplicate path: {member.filename!r}")
                seen_names.add(normalized_name)
                # Unix mode 0120000 denotes a symlink.  Reject links before
                # extraction so an untrusted artifact cannot escape the root.
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise CandidateValidationError(f"candidate archive contains a symlink: {member.filename!r}")
            bundle.extractall(output_dir)
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateValidationError(f"candidate artifact is not a valid ZIP archive: {exc}") from exc

    roots = [child for child in output_dir.iterdir() if child.name != "__MACOSX"]
    if len(roots) == 1 and roots[0].is_dir():
        return roots[0]
    return output_dir


@dataclass(frozen=True)
class CandidateSummary:
    artifact_id: int
    producer_run_id: str
    producer_workflow: str
    producer_workflow_path: str
    producer_head_sha: str
    target: str
    develop_sha: str
    published_results_sha: str
    manifest_digest: str
    site_tree_sha256: str
    route_checksums: dict[str, str]
    expected_parent_sha: str | None
    expected_parent_generation: int | None
    archive_sha256: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_candidate_directory(  # noqa: C901 - this is one fail-closed validation boundary
    root: Path,
    *,
    artifact_id: int,
    run_metadata: dict[str, Any],
    artifact_metadata: dict[str, Any],
    expected_develop_sha: str | None = None,
    expected_published_results_sha: str | None = None,
    expected_generation: int | None = None,
    expected_parent_sha: str | None = None,
    expected_parent_generation: int | None = None,
) -> CandidateSummary:
    """Validate an extracted candidate bundle and its GitHub provenance."""
    if artifact_metadata.get("expired") is True:
        raise CandidateValidationError("candidate artifact has expired")
    try:
        metadata_artifact_id = int(artifact_metadata.get("id", artifact_id))
    except (TypeError, ValueError) as exc:
        raise CandidateValidationError("candidate artifact metadata ID is invalid") from exc
    if metadata_artifact_id != artifact_id:
        raise CandidateValidationError("candidate artifact metadata ID does not match the selected ID")

    workflow_run = artifact_metadata.get("workflow_run")
    workflow_run = workflow_run if isinstance(workflow_run, dict) else {}
    run_id = str(run_metadata.get("id") or workflow_run.get("id") or "")
    if not run_id.isdigit() or int(run_id) <= 0:
        raise CandidateValidationError("candidate producer run ID is missing or invalid")
    if run_metadata.get("status") != "completed" or run_metadata.get("conclusion") != "success":
        raise CandidateValidationError("candidate producer run did not complete successfully")
    if run_metadata.get("event") != "workflow_dispatch" or run_metadata.get("head_branch") != "develop":
        raise CandidateValidationError("candidate producer must be a successful develop workflow dispatch")
    if run_metadata.get("name") != EXPECTED_WORKFLOW_NAME:
        raise CandidateValidationError(f"candidate producer workflow is not {EXPECTED_WORKFLOW_NAME!r}")
    producer_path = str(run_metadata.get("path") or "")
    if producer_path != EXPECTED_WORKFLOW_PATH:
        raise CandidateValidationError(f"candidate producer workflow path is not {EXPECTED_WORKFLOW_PATH!r}")

    metadata = _load_object(root / "candidate.json")
    manifest = _load_object(root / "desired-manifest.json")
    assembly = _load_object(root / "assembly-receipt.json")
    errors = validate_manifest_dict(manifest)
    if errors:
        raise CandidateValidationError("invalid candidate manifest: " + "; ".join(errors))

    claimed_manifest_digest = manifest.get("manifest_digest")
    if not isinstance(claimed_manifest_digest, str) or claimed_manifest_digest != manifest_digest(manifest):
        raise CandidateValidationError("candidate manifest digest does not recompute")
    if manifest.get("target") != "benchbox.dev" or manifest.get("source_branch") != "develop":
        raise CandidateValidationError("candidate target or source branch is invalid")
    if manifest.get("source_commit") != manifest.get("develop_sha"):
        raise CandidateValidationError("candidate source_commit and develop_sha differ")
    if expected_develop_sha and manifest.get("develop_sha") != expected_develop_sha:
        raise CandidateValidationError("candidate develop SHA is stale")
    if expected_published_results_sha and manifest.get("published_results_sha") != expected_published_results_sha:
        raise CandidateValidationError("candidate published-results SHA is stale")
    if expected_generation is not None and manifest.get("generation") != expected_generation:
        raise CandidateValidationError("candidate generation is stale")
    producer_head = str(run_metadata.get("head_sha") or "")
    if not _commit_sha(producer_head):
        raise CandidateValidationError("candidate producer head SHA is missing or malformed")
    if producer_head != manifest.get("develop_sha"):
        raise CandidateValidationError("candidate producer head and manifest source differ")

    route_checksums = validate_route_checksums(manifest)
    site = root / "site"
    if not site.is_dir() or not (site / "index.html").is_file():
        raise CandidateValidationError("candidate site is missing or incomplete")
    for path in site.rglob("*"):
        if path.is_symlink():
            raise CandidateValidationError(f"candidate site contains a symlink: {path.relative_to(site)}")
    site_digest, _, _ = compute_tree_digest(site)
    expected_site_digest = manifest.get("artifacts", {}).get("pages_assembly", {}).get("digest")
    if site_digest != expected_site_digest:
        raise CandidateValidationError(
            f"candidate site tree digest mismatch: expected={expected_site_digest!r} actual={site_digest!r}"
        )
    if assembly.get("candidate_mode") not in {"candidate-only", "no-op-rehearsal"}:
        raise CandidateValidationError("candidate was not produced by a no-write rehearsal")
    if str(assembly.get("artifact_run_id")) != run_id:
        raise CandidateValidationError("candidate receipt is not bound to its producer run")

    metadata_expectations = {
        "producer_workflow": EXPECTED_WORKFLOW_NAME,
        "producer_workflow_path": EXPECTED_WORKFLOW_PATH,
        "producer_run_id": run_id,
        "manifest_digest": claimed_manifest_digest,
        "site_tree_sha256": site_digest,
        "develop_sha": manifest["develop_sha"],
        "published_results_sha": manifest["published_results_sha"],
    }
    if metadata.get("schema_version") != 1:
        raise CandidateValidationError("candidate metadata schema version is unsupported")
    if metadata.get("artifact_id") not in (None, artifact_id):
        raise CandidateValidationError("candidate metadata field 'artifact_id' does not match selected artifact")
    for key, expected in metadata_expectations.items():
        if metadata.get(key) != expected:
            raise CandidateValidationError(f"candidate metadata field {key!r} does not match trusted content")
    if metadata.get("route_checksums") != route_checksums:
        raise CandidateValidationError("candidate metadata route checksums do not match the manifest")

    parent_sha = manifest.get("parent_sha")
    parent_generation = manifest.get("parent_generation")
    if parent_sha is not None and (not isinstance(parent_sha, str) or len(parent_sha) != 40):
        raise CandidateValidationError("candidate parent_sha is malformed")
    if parent_generation is not None and (not isinstance(parent_generation, int) or parent_generation < 1):
        raise CandidateValidationError("candidate parent_generation is malformed")
    if expected_parent_sha is not None and parent_sha != expected_parent_sha:
        raise CandidateValidationError("candidate parent SHA is stale")
    if expected_parent_generation is not None and parent_generation != expected_parent_generation:
        raise CandidateValidationError("candidate parent generation is stale")
    if expected_generation is not None:
        if expected_generation == 1 and (parent_sha is not None or parent_generation is not None):
            raise CandidateValidationError("genesis candidate must not declare a parent")
        if expected_generation > 1 and (parent_sha is None or parent_generation is None):
            raise CandidateValidationError("candidate is missing the required durable parent binding")

    return CandidateSummary(
        artifact_id=artifact_id,
        producer_run_id=run_id,
        producer_workflow=EXPECTED_WORKFLOW_NAME,
        producer_workflow_path=producer_path,
        producer_head_sha=producer_head,
        target="benchbox.dev",
        develop_sha=str(manifest["develop_sha"]),
        published_results_sha=str(manifest["published_results_sha"]),
        manifest_digest=claimed_manifest_digest,
        site_tree_sha256=site_digest,
        route_checksums=route_checksums,
        expected_parent_sha=parent_sha,
        expected_parent_generation=parent_generation,
    )


def create_candidate_metadata(
    manifest_path: Path,
    assembly_path: Path,
    site_dir: Path,
    *,
    artifact_id: int | None,
    producer_run_id: str,
    producer_workflow: str = EXPECTED_WORKFLOW_NAME,
    producer_workflow_path: str = EXPECTED_WORKFLOW_PATH,
    output: Path,
) -> CandidateSummary:
    """Create the metadata file included in a candidate bundle."""
    manifest = _load_object(manifest_path)
    assembly = _load_object(assembly_path)
    errors = validate_manifest_dict(manifest)
    if errors:
        raise CandidateValidationError("cannot package an invalid candidate manifest: " + "; ".join(errors))
    claimed_manifest_digest = manifest.get("manifest_digest")
    if not isinstance(claimed_manifest_digest, str) or claimed_manifest_digest != manifest_digest(manifest):
        raise CandidateValidationError("cannot package a candidate with an invalid manifest digest")
    site_digest, _, _ = compute_tree_digest(site_dir)
    if manifest.get("artifacts", {}).get("pages_assembly", {}).get("digest") != site_digest:
        raise CandidateValidationError("cannot package candidate whose site tree digest differs from its manifest")
    checksums = validate_route_checksums(manifest)
    if assembly.get("candidate_mode") not in {"candidate-only", "no-op-rehearsal"}:
        raise CandidateValidationError("cannot package a candidate produced by a writing workflow")
    if str(assembly.get("artifact_run_id")) != str(producer_run_id):
        raise CandidateValidationError("candidate receipt is not bound to its producer run")
    data = {
        "schema_version": 1,
        "artifact_id": artifact_id,
        "producer_run_id": str(producer_run_id),
        "producer_workflow": producer_workflow,
        "producer_workflow_path": producer_workflow_path,
        "manifest_digest": claimed_manifest_digest,
        "site_tree_sha256": site_digest,
        "develop_sha": manifest.get("develop_sha"),
        "published_results_sha": manifest.get("published_results_sha"),
        "route_checksums": checksums,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return CandidateSummary(
        artifact_id=int(artifact_id or 0),
        producer_run_id=str(producer_run_id),
        producer_workflow=producer_workflow,
        producer_workflow_path=producer_workflow_path,
        producer_head_sha="",
        target=str(manifest.get("target")),
        develop_sha=str(manifest.get("develop_sha")),
        published_results_sha=str(manifest.get("published_results_sha")),
        manifest_digest=claimed_manifest_digest,
        site_tree_sha256=site_digest,
        route_checksums=checksums,
        expected_parent_sha=manifest.get("parent_sha"),
        expected_parent_generation=manifest.get("parent_generation"),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--manifest", type=Path, required=True)
    create.add_argument("--assembly", type=Path, required=True)
    create.add_argument("--site", type=Path, required=True)
    create.add_argument("--artifact-id", type=int, default=None)
    create.add_argument("--producer-run-id", required=True)
    create.add_argument("--producer-workflow", default=EXPECTED_WORKFLOW_NAME)
    create.add_argument("--producer-workflow-path", default=EXPECTED_WORKFLOW_PATH)
    create.add_argument("--output", type=Path, required=True)

    validate = sub.add_parser("validate")
    validate.add_argument("--archive", type=Path, required=True)
    validate.add_argument("--output-dir", type=Path, required=True)
    validate.add_argument("--artifact-id", type=int, required=True)
    validate.add_argument("--artifact-metadata", type=Path, required=True)
    validate.add_argument("--run-metadata", type=Path, required=True)
    validate.add_argument("--expected-develop-sha")
    validate.add_argument("--expected-published-results-sha")
    validate.add_argument("--expected-generation", type=int)
    validate.add_argument("--expected-parent-sha")
    validate.add_argument("--expected-parent-generation", type=int)
    validate.add_argument("--output-summary", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            summary = create_candidate_metadata(
                args.manifest,
                args.assembly,
                args.site,
                artifact_id=args.artifact_id,
                producer_run_id=args.producer_run_id,
                producer_workflow=args.producer_workflow,
                producer_workflow_path=args.producer_workflow_path,
                output=args.output,
            )
        else:
            root = extract_candidate_archive(args.archive, args.output_dir)
            summary = validate_candidate_directory(
                root,
                artifact_id=args.artifact_id,
                run_metadata=_load_object(args.run_metadata),
                artifact_metadata=_load_object(args.artifact_metadata),
                expected_develop_sha=args.expected_develop_sha,
                expected_published_results_sha=args.expected_published_results_sha,
                expected_generation=args.expected_generation,
                expected_parent_sha=args.expected_parent_sha,
                expected_parent_generation=args.expected_parent_generation,
            )
            summary = replace(summary, archive_sha256=archive_sha256(args.archive))
        args.output_summary.write_text(json.dumps(summary.to_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(summary.to_dict(), sort_keys=True))
        return 0
    except CandidateValidationError as exc:
        print(f"ERROR: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
