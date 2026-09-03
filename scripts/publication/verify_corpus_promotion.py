#!/usr/bin/env python3
"""Verify corpus promotion gate and shadow promotion (A8).

Verifies the published-results corpus invariants: exact accepted-path
inventory, zero skips, and Explorer compatibility.

Usage:
  uv run python scripts/publication/verify_corpus_promotion.py            # live mode
  uv run python scripts/publication/verify_corpus_promotion.py --shadow   # shadow mode
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.publication.check_artifact_privacy import scan_directory_for_privacy
from scripts.publication.check_corpus_bijection import BijectionError, check as check_corpus_bijection
from scripts.publication.verify_shadow_site import verify_site_directory

CORPUS_PREFIX = "results-data/bundles/"
IGNORED_SUFFIXES = (".manifest.json", ".applied.json", ".plans.json", ".tuning.json", ".gitkeep")
INVENTORY_FILE = REPO_ROOT / "results-data" / "corpus-inventory.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(list(args), cwd=REPO_ROOT, check=False, text=True, capture_output=True)


def get_accepted_bundles(ref: str) -> list[str]:
    """List all primary JSON bundle paths in the git tree at *ref*."""
    result = run("git", "ls-tree", "-r", "--name-only", ref, "--", CORPUS_PREFIX)
    if result.returncode != 0:
        return []
    paths = []
    for line in result.stdout.strip().splitlines():
        p = line.strip()
        if not p or not p.endswith(".json"):
            continue
        if any(p.endswith(sfx) for sfx in IGNORED_SUFFIXES):
            continue
        paths.append(p)
    return sorted(paths)


def get_local_bundles(bundles_dir: Path) -> list[str]:
    """List all primary JSON bundle paths from a local directory (recursive)."""
    if not bundles_dir.exists():
        return []
    paths = []
    for p in bundles_dir.rglob("*.json"):
        if any(p.name.endswith(sfx) for sfx in IGNORED_SUFFIXES):
            continue
        rel = p.relative_to(REPO_ROOT).as_posix()
        paths.append(rel)
    return sorted(paths)


def get_inventory_paths() -> list[str]:
    """List accepted bundle paths recorded in corpus-inventory.json."""
    if not INVENTORY_FILE.exists():
        return []
    data = json.loads(INVENTORY_FILE.read_text(encoding="utf-8"))
    paths = []
    for bundle in data.get("bundles", []):
        fname = bundle.get("file", "")
        if fname:
            paths.append(f"{CORPUS_PREFIX}{fname}")
    return sorted(paths)


def verify_exact_inventory(
    accepted: list[str],
    inventory_expected: list[str],
) -> list[str]:
    """Verify the accepted-path inventory exactly matches expected."""
    if accepted == inventory_expected:
        return []
    missing = sorted(set(inventory_expected) - set(accepted))
    extra = sorted(set(accepted) - set(inventory_expected))
    errors = []
    if missing:
        errors.append(f"Missing accepted path(s) not in inventory ({len(missing)}): {missing[:5]}...")
    if extra:
        errors.append(f"Extra path(s) accepted not in inventory ({len(extra)}): {extra[:5]}...")
    return errors


def _resolve_artifact() -> Path | None:
    candidates = (
        REPO_ROOT / "results-explorer" / "public" / "data" / "results.duckdb",
        REPO_ROOT / "publication" / "out" / "site" / "results" / "data" / "results.duckdb",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _verify_inventory(shadow: bool, accepted_ref: str) -> list[str]:
    errors: list[str] = []
    if shadow:
        local = get_local_bundles(REPO_ROOT / "results-data" / "bundles")
        inventory = get_inventory_paths()
        print(f"Shadow mode: verified {len(local)} local bundle(s) against {len(inventory)} inventory entries")
        if not INVENTORY_FILE.is_file():
            errors.append(f"Corpus inventory missing: {INVENTORY_FILE}")
        elif not inventory:
            errors.append("Corpus inventory is empty — cannot verify exact accepted-path inventory")
        else:
            errors.extend(verify_exact_inventory(local, inventory))
        missing_files = [p for p in inventory if not (REPO_ROOT / p).is_file()]
        if missing_files:
            errors.append(
                f"Zero-skip violation: {len(missing_files)} accepted bundle(s) missing on disk: {missing_files[:5]}..."
            )
        if not local:
            errors.append("No local accepted bundles found — corpus inventory is empty")
        return errors

    accepted = get_accepted_bundles(accepted_ref)
    print(f"Live mode: found {len(accepted)} accepted bundle(s) at {accepted_ref}")
    if not accepted:
        errors.append("No accepted bundles found at accepted ref — corpus inventory is empty")
    return errors


def _verify_bijection_and_privacy(accepted_ref: str, ledger_seed: Path) -> list[str]:
    errors: list[str] = []
    try:
        artifact = _resolve_artifact()
        bijection_errors = check_corpus_bijection(
            accepted_ref=accepted_ref,
            bundles_dir=REPO_ROOT / "results-data" / "bundles",
            artifact=artifact,
            ledger_seed=ledger_seed,
        )
        if artifact is None:
            print("Corpus bijection: path/ref stage only (no DuckDB artifact present)")
        if bijection_errors:
            errors.extend(f"Corpus bijection: {e}" for e in bijection_errors)
    except BijectionError as exc:
        errors.append(f"Corpus bijection failed: {exc}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"Corpus bijection check failed: {e}")

    try:
        privacy_findings = scan_directory_for_privacy(REPO_ROOT / "publication" / "out" / "site")
        if privacy_findings:
            errors.extend(f"Privacy: {f}" for f in privacy_findings[:5])
    except Exception as e:  # noqa: BLE001
        errors.append(f"Privacy scan failed: {e}")
    return errors


def _verify_compat_and_site() -> list[str]:
    errors: list[str] = []
    try:
        from scripts.publication.check_explorer_compat import check_schema_compatibility

        results = check_schema_compatibility()
        for version, compat_errors in results.items():
            if compat_errors:
                errors.append(f"Explorer compatibility failed for v{version}: {compat_errors}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"Explorer compatibility check failed: {e}")

    try:
        site_errors = verify_site_directory(REPO_ROOT / "publication" / "out" / "site")
        if site_errors:
            errors.append(f"Shadow site verification: {site_errors[:3]}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"Shadow site verification failed: {e}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify corpus promotion gate")
    parser.add_argument(
        "--shadow",
        action="store_true",
        help="Shadow mode: verify local shadow state (no live deployment)",
    )
    parser.add_argument(
        "--accepted-ref",
        default="origin/published-results",
        help="Git ref for accepted corpus (live mode only)",
    )
    parser.add_argument(
        "--ledger-seed",
        type=Path,
        default=None,
        help="Disposition ledger seed (default: publication/ledger-seed.json)",
    )
    args = parser.parse_args(argv)
    ledger_seed = args.ledger_seed if args.ledger_seed is not None else (REPO_ROOT / "publication" / "ledger-seed.json")

    errors: list[str] = []
    errors.extend(_verify_inventory(args.shadow, args.accepted_ref))
    errors.extend(_verify_bijection_and_privacy(args.accepted_ref, ledger_seed))
    errors.extend(_verify_compat_and_site())

    if errors:
        print("❌ Corpus promotion verification FAILED:")
        for err in errors[:10]:
            print(f"  - {err}")
        if len(errors) > 10:
            print(f"  ... and {len(errors) - 10} more errors")
        return 1

    mode = "SHADOW" if args.shadow else "LIVE"
    print(f"✅ Corpus promotion verification PASSED ({mode} mode): exact inventory, zero skips, Explorer compat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
