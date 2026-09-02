"""Tests for the set-preserving corpus seed and disposition ledger (A9 w1)."""

from __future__ import annotations

import json
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


def _accepted_ref_exists() -> bool:
    """Check whether origin/published-results is reachable."""
    try:
        subprocess.run(
            ["git", "rev-parse", "--verify", "origin/published-results"],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except subprocess.CalledProcessError:
        return False


def _get_expected_accepted_bundles() -> list[str]:
    """Mirror the script's accepted-bundle logic against origin/published-results."""
    out = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "origin/published-results", "--", CORPUS_PREFIX],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    bundles: list[str] = []
    for line in out.splitlines():
        p = line.strip()
        if not p or not p.endswith(".json"):
            continue
        if any(p.endswith(sfx) for sfx in IGNORED_SUFFIXES):
            continue
        bundles.append(p)
    return sorted(bundles)


skip_no_ref = pytest.mark.skipif(
    not _accepted_ref_exists(),
    reason="origin/published-results not reachable",
)


# ---------------------------------------------------------------------------
# Seed file schema tests
# ---------------------------------------------------------------------------


def test_seed_file_exists_and_is_valid_json() -> None:
    assert SEED_PATH.is_file(), f"Ledger seed not found at {SEED_PATH}"
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert isinstance(data, dict)


def test_seed_schema_version() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert data["schema_version"] == 1


def test_seed_has_required_keys() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for key in ("schema_version", "generated_at", "source", "bidirectional", "union", "dispositions", "count"):
        assert key in data, f"missing key: {key}"


def test_seed_bidirectional_is_false() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert data["bidirectional"] is False


def test_seed_count_matches_union_length() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert data["count"] == len(data["union"])


# ---------------------------------------------------------------------------
# Set preservation tests
# ---------------------------------------------------------------------------


@skip_no_ref
def test_seed_union_matches_accepted_bundles_exactly() -> None:
    """The seed union must contain every accepted published-results path with no extras."""
    expected = _get_expected_accepted_bundles()
    assert len(expected) > 0, "upstream accepted set is empty (broken ref?)"
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    actual = sorted(data["union"])
    assert actual == expected


@skip_no_ref
def test_seed_count_is_nonzero() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert data["count"] > 0, "empty corpus seed is a vacuous pass (forbidden)"


@skip_no_ref
def test_seed_dispositions_cover_all_union_paths() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    union_set = set(data["union"])
    disp_keys = set(data["dispositions"].keys())
    assert union_set == disp_keys, (
        f"dispositions do not cover union: missing={union_set - disp_keys}, extra={disp_keys - union_set}"
    )


@skip_no_ref
def test_seed_all_default_dispositions_are_accepted() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    for path, disp in data["dispositions"].items():
        assert disp in ("accepted", "published_only", "legacy_overlay"), f"unexpected disposition for {path}: {disp}"


@skip_no_ref
def test_seed_source_is_origin_published_results() -> None:
    data = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert data["source"] == "origin/published-results"


# ---------------------------------------------------------------------------
# CLI tests (subprocess against real origin/published-results)
# ---------------------------------------------------------------------------


@skip_no_ref
def test_cli_generates_seed(tmp_path: Path) -> None:
    out_path = tmp_path / "out" / "seed.json"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--accepted-ref",
            "origin/published-results",
            "--output",
            str(out_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    assert out_path.is_file()
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["count"] > 0


@skip_no_ref
def test_cli_classifies_legacy_overlay(tmp_path: Path) -> None:
    out_path = tmp_path / "seed.json"
    # Grab first path from accepted set as legacy overlay
    accepted = _get_expected_accepted_bundles()
    first_path = accepted[0]
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--accepted-ref",
            "origin/published-results",
            "--output",
            str(out_path),
            "--legacy-overlay",
            first_path,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["dispositions"][first_path] == "legacy_overlay"
    # All others remain accepted
    for p in accepted[1:]:
        assert data["dispositions"][p] == "accepted"


@skip_no_ref
def test_cli_classifies_published_only(tmp_path: Path) -> None:
    out_path = tmp_path / "seed.json"
    accepted = _get_expected_accepted_bundles()
    last_path = accepted[-1]
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--accepted-ref",
            "origin/published-results",
            "--output",
            str(out_path),
            "--published-only",
            last_path,
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"CLI failed: {result.stderr}"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["dispositions"][last_path] == "published_only"


def test_cli_empty_corpus_fails(tmp_path: Path) -> None:
    """When no bundles exist at the ref, the script must fail (no vacuous pass)."""
    out_path = tmp_path / "seed.json"
    # Use a ref that has no results-data/bundles (HEAD might have none in the tree)
    # We pass an explicit empty tree-ish to force the issue
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--accepted-ref",
            "4b825dc642cb6eb9a060e54bf899d150063038c2",
            "--output",
            str(out_path),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0, "expected failure on empty corpus"
    assert not out_path.exists() or json.loads(out_path.read_text(encoding="utf-8")).get("count", 0) == 0
