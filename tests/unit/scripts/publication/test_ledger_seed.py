"""Tests for the set-preserving corpus seed and disposition ledger (A9 w1 + review follow-ups)."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "publication" / "create_ledger_seed.py"
SEED_PATH = REPO_ROOT / "publication" / "ledger-seed.json"
CORPUS_PREFIX = "results-data/bundles/"
IGNORED_SUFFIXES = (".manifest.json", ".applied.json", ".plans.json", ".tuning.json", ".gitkeep")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")

# The seed pins an immutable snapshot of the accepted corpus (M8). Bumping this
# constant is the deliberate, reviewable act that regenerates the committed seed.
PINNED_SOURCE_REF = "origin/published-results"

# How many ref-dependent tests MUST run. If the accepted ref is unreachable and
# this is not explicitly allowed, the suite fails loudly instead of silently
# skipping ~half its coverage (M8).
_ALLOW_MISSING_REF = os.environ.get("BENCHBOX_ALLOW_MISSING_PUBLISHED_REF") == "1"


def _accepted_ref_exists() -> bool:
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", f"{PINNED_SOURCE_REF}^{{commit}}"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        try:
            subprocess.run(
                ["git", "fetch", "--no-tags", "origin", "published-results:refs/remotes/origin/published-results"],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False


REF_AVAILABLE = _accepted_ref_exists()
skip_no_ref = pytest.mark.skipif(
    not REF_AVAILABLE,
    reason="origin/published-results not reachable",
)


def _seed() -> dict:
    return json.loads(SEED_PATH.read_text(encoding="utf-8"))


def _primary(path: str) -> bool:
    return path.endswith(".json") and not any(path.endswith(sfx) for sfx in IGNORED_SUFFIXES)


def _bundles_at_ref(ref: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", ref, "--", CORPUS_PREFIX],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    return sorted(p.strip() for p in out.splitlines() if p.strip().startswith(CORPUS_PREFIX) and _primary(p.strip()))


def _worktree_bundles() -> list[str]:
    base = REPO_ROOT / CORPUS_PREFIX
    return sorted(
        p.relative_to(REPO_ROOT).as_posix()
        for p in base.rglob("*.json")
        if _primary(p.relative_to(REPO_ROOT).as_posix())
    )


def _blob_sha256(ref: str, path: str) -> str:
    proc = subprocess.run(
        ["git", "cat-file", "blob", f"{ref}:{path}"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )
    return hashlib.sha256(proc.stdout).hexdigest()


# ---------------------------------------------------------------------------
# Loud-failure guard (M8)
# ---------------------------------------------------------------------------


def test_ref_dependent_suite_is_not_silently_skipped() -> None:
    """If the accepted ref is unreachable and not explicitly allowed, fail — don't skip."""
    assert REF_AVAILABLE or _ALLOW_MISSING_REF, (
        f"{PINNED_SOURCE_REF} is unreachable; set BENCHBOX_ALLOW_MISSING_PUBLISHED_REF=1 to allow "
        "an offline run, otherwise fetch the ref so the ledger-seed contract is actually tested"
    )


# ---------------------------------------------------------------------------
# Seed schema
# ---------------------------------------------------------------------------


def test_seed_file_exists_and_is_valid_json() -> None:
    assert SEED_PATH.is_file()
    assert isinstance(_seed(), dict)


def test_seed_schema_version() -> None:
    assert _seed()["schema_version"] == 2


def test_seed_has_required_keys() -> None:
    data = _seed()
    for key in (
        "schema_version",
        "generated_at",
        "source",
        "source_ref",
        "main_source",
        "bidirectional",
        "union",
        "dispositions",
        "digests",
        "published_only",
        "legacy_overlay",
        "count",
    ):
        assert key in data, f"missing key: {key}"


def test_seed_source_is_pinned_commit_sha() -> None:
    """M8: `source` is an immutable commit SHA, not a moving branch name."""
    data = _seed()
    assert COMMIT_SHA_RE.match(data["source"]), f"source must be a 40-hex commit SHA, got {data['source']!r}"
    assert data["source_ref"] == PINNED_SOURCE_REF


def test_seed_count_matches_union_length() -> None:
    data = _seed()
    assert data["count"] == len(data["union"]) == len(data["dispositions"]) == len(data["digests"])


def test_seed_bidirectional_is_derived() -> None:
    """N12: bidirectional reflects real two-sided membership, not a hardcoded literal."""
    data = _seed()
    assert isinstance(data["bidirectional"], bool)
    expected = not data["published_only"] and not data["legacy_overlay"]
    assert data["bidirectional"] is expected


def test_seed_every_path_has_a_sha256_digest() -> None:
    """M6 / G1: exact accepted-path union exported with a per-object digest."""
    data = _seed()
    for path in data["union"]:
        digest = data["digests"].get(path)
        assert digest and SHA256_RE.match(digest), f"missing/invalid digest for {path}: {digest!r}"


# ---------------------------------------------------------------------------
# Set preservation (M7)
# ---------------------------------------------------------------------------


@skip_no_ref
def test_seed_union_is_the_two_sided_union() -> None:
    """M7: the union covers BOTH the accepted ref and the main working corpus."""
    accepted = set(_bundles_at_ref(_seed()["source"]))
    main = set(_worktree_bundles())
    data = _seed()
    assert sorted(accepted | main) == sorted(data["union"])
    assert accepted, "accepted set is empty (broken ref?)"


@skip_no_ref
def test_seed_dispositions_match_set_membership() -> None:
    """M7: published_only / legacy_overlay are derived from set difference, not CLI flags."""
    accepted = set(_bundles_at_ref(_seed()["source"]))
    main = set(_worktree_bundles())
    data = _seed()
    assert sorted(accepted - main) == sorted(data["published_only"])
    assert sorted(main - accepted) == sorted(data["legacy_overlay"])
    for path, disp in data["dispositions"].items():
        if path in data["legacy_overlay"]:
            assert disp == "legacy_overlay"
        elif path in data["published_only"]:
            assert disp == "published_only"
        else:
            assert disp == "accepted"


@skip_no_ref
def test_seed_dispositions_cover_all_union_paths() -> None:
    data = _seed()
    assert set(data["union"]) == set(data["dispositions"]) == set(data["digests"])


@skip_no_ref
def test_seed_digests_match_git_blob_bytes() -> None:
    """M6: every recorded digest is the real sha256 of the blob at the pinned ref/worktree."""
    data = _seed()
    accepted = set(_bundles_at_ref(data["source"]))
    sample = list(data["union"])[:: max(1, len(data["union"]) // 15)]  # ~15 spot checks
    for path in sample:
        if path in accepted:
            expected = _blob_sha256(data["source"], path)
        else:
            expected = hashlib.sha256((REPO_ROOT / path).read_bytes()).hexdigest()
        assert data["digests"][path] == expected, f"digest mismatch for {path}"


@skip_no_ref
def test_seed_count_is_nonzero() -> None:
    assert _seed()["count"] > 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_cli(*args: str, cwd: Path = REPO_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


@skip_no_ref
def test_cli_regenerates_committed_seed_content(tmp_path: Path) -> None:
    """The committed seed must be reproducible from the pinned ref (no manual drift)."""
    out = tmp_path / "seed.json"
    result = _run_cli("--accepted-ref", PINNED_SOURCE_REF, "--output", str(out))
    assert result.returncode == 0, result.stderr
    regen = json.loads(out.read_text(encoding="utf-8"))
    committed = _seed()
    for key in ("union", "dispositions", "digests", "published_only", "legacy_overlay", "count"):
        assert regen[key] == committed[key], f"regenerated seed drifted at {key}"


@skip_no_ref
def test_cli_classifies_forced_legacy_overlay(tmp_path: Path) -> None:
    out = tmp_path / "seed.json"
    first = _bundles_at_ref(PINNED_SOURCE_REF)[0]
    result = _run_cli("--accepted-ref", PINNED_SOURCE_REF, "--output", str(out), "--legacy-overlay", first)
    assert result.returncode == 0, result.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["dispositions"][first] == "legacy_overlay"
    assert data["bidirectional"] is False


def test_cli_rejects_disposition_path_outside_union(tmp_path: Path) -> None:
    """M10: an unvalidated disposition path is an error, not a silent drop."""
    out = tmp_path / "seed.json"
    result = _run_cli(
        "--accepted-ref",
        PINNED_SOURCE_REF if REF_AVAILABLE else "HEAD",
        "--output",
        str(out),
        "--published-only",
        "results-data/bundles/does-not-exist.json",
    )
    assert result.returncode != 0
    assert not out.exists()


def test_cli_empty_corpus_fails(tmp_path: Path) -> None:
    """M9 / no vacuous pass: an unusable ref must exit non-zero and write nothing."""
    out = tmp_path / "seed.json"
    result = _run_cli("--accepted-ref", "4b825dc642cb6eb9a060e54bf899d150063038c2", "--output", str(out))
    assert result.returncode != 0
    assert not out.exists()


def test_cli_reports_bad_ref_distinctly(tmp_path: Path) -> None:
    """M9: a git failure is reported as such, not misreported as an empty corpus."""
    out = tmp_path / "seed.json"
    result = _run_cli("--accepted-ref", "totally/not/a/ref", "--output", str(out))
    assert result.returncode != 0
    assert "rev-parse" in result.stderr or "ls-tree" in result.stderr
