#!/usr/bin/env python3
"""Generate a set-preserving corpus seed and disposition ledger (A9 w1, review follow-ups).

The seed captures the *union* of the accepted ``published-results`` corpus and the
main-line working corpus, pins the accepted snapshot to an immutable commit SHA,
records a per-object ``sha256`` digest for every path (G1: "exact accepted-path
union exported with per-object digest"), and derives each path's disposition from
real set membership rather than manual CLI flags:

  * ``accepted``        -- present in both the accepted ref and the main corpus
  * ``published_only``  -- present only in the accepted ref (preservation obligation)
  * ``legacy_overlay``  -- present only in the main corpus (main-only / not yet accepted)

Usage:
  uv run python scripts/publication/create_ledger_seed.py \
    --accepted-ref origin/published-results --output publication/ledger-seed.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CORPUS_PREFIX = "results-data/bundles/"
IGNORED_SUFFIXES = (".manifest.json", ".applied.json", ".plans.json", ".tuning.json", ".gitkeep")
SCHEMA_VERSION = 2


class LedgerSeedError(RuntimeError):
    """Raised when the seed cannot be produced from real corpus state."""


def _git(args: list[str], repo_root: Path) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo_root,
        check=True,
        text=True,
        capture_output=True,
    )
    return proc.stdout


def _is_primary_bundle(path: str) -> bool:
    return (
        path.startswith(CORPUS_PREFIX)
        and path.endswith(".json")
        and not any(path.endswith(sfx) for sfx in IGNORED_SUFFIXES)
    )


def resolve_ref(ref: str, repo_root: Path = ROOT) -> str:
    """Resolve *ref* to an immutable commit SHA (M8: stable snapshot, not a branch)."""
    try:
        return _git(["rev-parse", "--verify", f"{ref}^{{commit}}"], repo_root).strip()
    except subprocess.CalledProcessError as exc:  # M9: distinct, actionable message
        raise LedgerSeedError(f"git rev-parse failed on ref {ref!r}: {exc.stderr.strip() or exc}") from exc


def list_bundles_at_ref(ref: str, repo_root: Path = ROOT) -> list[str]:
    """List every primary JSON bundle path in the git tree at *ref*."""
    try:
        out = _git(["ls-tree", "-r", "--name-only", ref, "--", CORPUS_PREFIX], repo_root).strip()
    except subprocess.CalledProcessError as exc:  # M9: never silently return []
        raise LedgerSeedError(f"git ls-tree failed on ref {ref!r}: {exc.stderr.strip() or exc}") from exc
    return sorted(p.strip() for p in out.splitlines() if _is_primary_bundle(p.strip()))


def list_bundles_on_worktree(repo_root: Path = ROOT) -> list[str]:
    """List every primary JSON bundle path on the working tree (recursively)."""
    base = repo_root / CORPUS_PREFIX
    if not base.is_dir():
        return []
    found: list[str] = []
    for p in base.rglob("*.json"):
        rel = p.relative_to(repo_root).as_posix()
        if _is_primary_bundle(rel):
            found.append(rel)
    return sorted(found)


def blob_sha256_at_ref(ref: str, path: str, repo_root: Path = ROOT) -> str:
    """SHA-256 of the exact blob bytes for *path* at *ref*."""
    return hashlib.sha256(blob_bytes_at_ref(ref, path, repo_root)).hexdigest()


def blob_bytes_at_ref(ref: str, path: str, repo_root: Path = ROOT) -> bytes:
    """Exact blob bytes for *path* at *ref*."""
    try:
        proc = subprocess.run(
            ["git", "cat-file", "blob", f"{ref}:{path}"],
            cwd=repo_root,
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace").strip()
        raise LedgerSeedError(f"git cat-file failed for {ref}:{path}: {stderr or exc}") from exc
    return proc.stdout


def worktree_sha256(path: str, repo_root: Path = ROOT) -> str:
    return hashlib.sha256((repo_root / path).read_bytes()).hexdigest()


def materialize_union(
    accepted_ref: str,
    ledger_seed: Path,
    dest: Path,
    repo_root: Path = ROOT,
) -> int:
    """Write every seed-union path's bytes into *dest*, verifying digests.

    Paths whose worktree bytes match the seed digest are copied from the
    worktree. ``published_only`` paths and digest mismatches are taken from
    ``git show`` of *accepted_ref*. Returns the number of primary bundles written.
    """
    if not ledger_seed.is_file():
        raise LedgerSeedError(f"ledger seed not found: {ledger_seed}")
    seed = json.loads(ledger_seed.read_text(encoding="utf-8"))
    union = seed.get("union") or []
    digests = seed.get("digests") or {}
    if not union:
        raise LedgerSeedError(f"ledger seed {ledger_seed} has an empty union (no vacuous pass)")

    accepted_sha = resolve_ref(accepted_ref, repo_root)
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    for path in union:
        expected = digests.get(path)
        if not expected:
            raise LedgerSeedError(f"ledger seed missing digest for {path}")

        worktree_path = repo_root / path
        if worktree_path.is_file() and hashlib.sha256(worktree_path.read_bytes()).hexdigest() == expected:
            data = worktree_path.read_bytes()
        else:
            data = blob_bytes_at_ref(accepted_sha, path, repo_root)

        actual = hashlib.sha256(data).hexdigest()
        if actual != expected:
            raise LedgerSeedError(f"materialized digest mismatch for {path}: expected {expected}, got {actual}")

        rel = path[len(CORPUS_PREFIX) :] if path.startswith(CORPUS_PREFIX) else Path(path).name
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        written += 1
    return written


def build_seed(
    accepted_ref: str,
    repo_root: Path = ROOT,
    main_ref: str | None = None,
    published_only_override: list[str] | None = None,
    legacy_overlay_override: list[str] | None = None,
) -> dict:
    """Build the full seed JSON structure from real two-sided set membership.

    ``main_ref`` selects the main-line corpus source. When omitted the working
    tree is used (so a fresh checkout still produces a correct union).
    """
    accepted_sha = resolve_ref(accepted_ref, repo_root)
    accepted_paths = set(list_bundles_at_ref(accepted_sha, repo_root))

    if main_ref:
        main_sha = resolve_ref(main_ref, repo_root)
        main_paths = set(list_bundles_at_ref(main_sha, repo_root))
        main_source = main_sha
    else:
        main_sha = None
        main_paths = set(list_bundles_on_worktree(repo_root))
        main_source = "working-tree"

    union = sorted(accepted_paths | main_paths)
    if not union:
        raise LedgerSeedError(
            "accepted corpus is empty: neither the accepted ref nor the main corpus "
            "contains a primary bundle (no vacuous pass)"
        )

    published_only = accepted_paths - main_paths
    legacy_overlay = main_paths - accepted_paths

    po_override = set(published_only_override or [])
    lo_override = set(legacy_overlay_override or [])
    for supplied in po_override | lo_override:  # M10: validate every supplied path
        if supplied not in union:
            raise LedgerSeedError(f"disposition override path is not in the corpus union: {supplied}")

    dispositions: dict[str, str] = {}
    digests: dict[str, str] = {}
    for p in union:
        if p in legacy_overlay or p in lo_override:
            dispositions[p] = "legacy_overlay"
        elif p in published_only or p in po_override:
            dispositions[p] = "published_only"
        else:
            dispositions[p] = "accepted"

        if p in accepted_paths:
            digests[p] = blob_sha256_at_ref(accepted_sha, p, repo_root)
        elif main_sha is not None:
            digests[p] = blob_sha256_at_ref(main_sha, p, repo_root)
        else:
            digests[p] = worktree_sha256(p, repo_root)

    # N12: derived, not hardcoded -- true only when both sides hold the same set.
    bidirectional = not published_only and not legacy_overlay and not po_override and not lo_override

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": accepted_sha,
        "source_ref": accepted_ref,
        "main_source": main_source,
        "bidirectional": bidirectional,
        "union": union,
        "dispositions": dispositions,
        "digests": digests,
        "published_only": sorted(published_only | po_override),
        "legacy_overlay": sorted(legacy_overlay | lo_override),
        "count": len(union),
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate set-preserving corpus seed and disposition ledger.")
    parser.add_argument(
        "--accepted-ref",
        default="origin/published-results",
        help="Git ref for accepted published-results (default: origin/published-results)",
    )
    parser.add_argument(
        "--main-ref",
        default=None,
        help="Git ref for the main-line corpus (default: working tree)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "publication" / "ledger-seed.json",
        help="Output path for the seed JSON (default: publication/ledger-seed.json)",
    )
    parser.add_argument(
        "--ledger-seed",
        type=Path,
        default=ROOT / "publication" / "ledger-seed.json",
        help="Existing seed JSON to materialize from (default: publication/ledger-seed.json)",
    )
    parser.add_argument(
        "--materialize-dest",
        type=Path,
        default=None,
        help="When set, materialize the seed union into this directory and exit",
    )
    parser.add_argument(
        "--published-only",
        nargs="*",
        default=[],
        help="Additional paths to force to the published_only disposition",
    )
    parser.add_argument(
        "--legacy-overlay",
        nargs="*",
        default=[],
        help="Additional paths to force to the legacy_overlay disposition",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help="Repository root directory",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = args.repo_root.resolve()

    if args.materialize_dest is not None:
        try:
            count = materialize_union(
                accepted_ref=args.accepted_ref,
                ledger_seed=args.ledger_seed,
                dest=args.materialize_dest,
                repo_root=repo_root,
            )
        except LedgerSeedError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"Materialized {count} bundle(s) into {args.materialize_dest}")
        return 0

    try:
        seed = build_seed(
            accepted_ref=args.accepted_ref,
            repo_root=repo_root,
            main_ref=args.main_ref,
            published_only_override=args.published_only or None,
            legacy_overlay_override=args.legacy_overlay or None,
        )
    except LedgerSeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(seed, indent=2) + "\n", encoding="utf-8")
    print(
        f"Seed written to {args.output} ({seed['count']} paths, "
        f"{len(seed['published_only'])} published_only, {len(seed['legacy_overlay'])} legacy_overlay)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
