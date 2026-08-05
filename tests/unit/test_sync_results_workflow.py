"""Static + behavioral pins for the develop → published-results corpus mirror.

The Build mirror step must apply a **union overlay** for ``results-data/bundles``:
checkout develop's tree without ``git rm -rf`` of the directory, so published-only
community submissions survive when develop is also ahead.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "sync-results-data-to-published.yml"
BUNDLES_DIR = "results-data/bundles"


def _run(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], cwd=root)
    _run(["git", "config", "user.email", "mirror@example.com"], cwd=root)
    _run(["git", "config", "user.name", "Mirror Test"], cwd=root)


def _commit_files(root: Path, files: dict[str, str], message: str) -> str:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _run(["git", "add", rel], cwd=root)
    _run(["git", "commit", "--allow-empty", "-m", message], cwd=root)
    return _run(["git", "rev-parse", "HEAD"], cwd=root)


def _tracked_under(root: Path, prefix: str, ref: str = "HEAD") -> set[str]:
    raw = _run(["git", "ls-tree", "-r", "--name-only", ref, prefix], cwd=root)
    return {line for line in raw.splitlines() if line}


def _build_step_run() -> str:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["mirror"]["steps"]:
        if step.get("name") == "Build mirror branch":
            run = step.get("run", "")
            assert run, "Build mirror branch step has empty run body"
            return run
    raise AssertionError("sync workflow has no Build mirror branch step")

FIXED_POINT_GATE_STEP = "Gate corpus publication fixed point"
BUILD_MIRROR_STEP = "Build mirror branch"
FIXED_POINT_TEST_FRAGMENT = "rederived_corpus_publishes_byte_identically"


def test_sync_results_workflow_sources_triggering_commit() -> None:
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    assert "ref: ${{ github.sha }}" in workflow
    assert 'git diff --name-only origin/published-results "${GITHUB_SHA}"' in workflow
    assert 'SOURCE_REF="${GITHUB_SHA}"' in workflow
    assert 'git checkout "${SOURCE_REF}" -- "${path}"' in workflow
    assert "origin/develop" not in workflow


def test_sync_workflow_references_publication_fixed_point_gate() -> None:
    """The mirror must refuse a corpus that re-anonymization would rewrite.

    Pins the workflow to the same fixed-point invariant as
    ``test_rederived_corpus_publishes_byte_identically_to_what_is_stored`` so a
    future edit cannot drop the gate while leaving the unit suite green.
    """
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert FIXED_POINT_TEST_FRAGMENT in workflow, (
        "sync workflow does not reference the publication fixed-point gate "
        f"({FIXED_POINT_TEST_FRAGMENT}); a non-fixed-point corpus could still be mirrored"
    )
    assert "AnonymizationManager" in workflow
    assert "canonical_json_bytes" in workflow
    assert "publication fixed point" in workflow.lower() or "not at the publication fixed point" in workflow


def test_sync_workflow_fixed_point_gate_runs_before_mirror_build() -> None:
    """Gate must run on develop content before any mirror branch is built.

    Building first would push rewriteable bytes; the gate is a precondition for
    opening a public mirror, not a post-hoc status on an already-opened PR.
    """
    steps = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))["jobs"]["mirror"]["steps"]
    names = [step.get("name") for step in steps]
    assert FIXED_POINT_GATE_STEP in names, f"missing step {FIXED_POINT_GATE_STEP!r}"
    assert BUILD_MIRROR_STEP in names, f"missing step {BUILD_MIRROR_STEP!r}"
    assert names.index(FIXED_POINT_GATE_STEP) < names.index(BUILD_MIRROR_STEP), (
        "publication fixed-point gate runs after Build mirror branch; "
        "the mirror could be built from a corpus that publishing would rewrite"
    )

    gate = next(step for step in steps if step.get("name") == FIXED_POINT_GATE_STEP)
    run = gate.get("run", "")
    assert "Refusing to open a mirror" in run or "not at the publication fixed point" in run
    assert "SystemExit(1)" in run or "raise SystemExit" in run
def test_sync_workflow_does_not_wipe_bundles_directory() -> None:
    """The apply path must not ``git rm -rf`` results-data/bundles (union overlay)."""
    run = _build_step_run()
    assert "union overlay" in run.lower() or "Union overlay" in run
    # Executable lines only: comments may still *describe* the old wipe defect.
    executable = "\n".join(line for line in run.splitlines() if line.strip() and not line.lstrip().startswith("#"))
    assert "git rm -rf" not in executable
    assert 'git checkout "${SOURCE_REF}" -- "${BUNDLES_DIR}"' in executable
    assert "BUNDLES_DIR=" in executable or "BUNDLES_DIR='" in executable or 'BUNDLES_DIR="' in executable
    # Explicit non-wipe guard language for published-only.
    assert "published-only" in run


def test_wipe_then_checkout_deletes_published_only_when_develop_ahead(tmp_path: Path) -> None:
    """w0 evidence: the old wipe strategy deletes community-only paths under mixed drift.

    published has shared + community_only; develop has shared (updated) + develop_only.
    ``git rm -rf bundles`` then checkout develop removes community_only.
    """
    repo = tmp_path / "wipe-proof"
    _init_repo(repo)

    published = {
        f"{BUNDLES_DIR}/shared.json": '{"id": "shared-v1"}\n',
        f"{BUNDLES_DIR}/community_only.json": '{"id": "community"}\n',
        "results-data/corpus-inventory.json": '{"version": 1}\n',
    }
    pub_sha = _commit_files(repo, published, "published tip")
    _run(["git", "branch", "published-results", pub_sha], cwd=repo)

    # Orphan-style develop tip on same repo: replace bundles with develop tree.
    _run(["git", "rm", "-rf", "--quiet", BUNDLES_DIR], cwd=repo)
    develop = {
        f"{BUNDLES_DIR}/shared.json": '{"id": "shared-v2-sanitized"}\n',
        f"{BUNDLES_DIR}/develop_only.json": '{"id": "new-on-develop"}\n',
        "results-data/corpus-inventory.json": '{"version": 1}\n',
    }
    dev_sha = _commit_files(repo, develop, "develop tip")

    # Reproduce the old wipe-based mirror apply starting from published.
    _run(["git", "switch", "--force-create", "mirror-wipe", "published-results"], cwd=repo)
    _run(["git", "rm", "-rf", "--quiet", BUNDLES_DIR], cwd=repo)
    _run(["git", "checkout", dev_sha, "--", BUNDLES_DIR], cwd=repo)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-m", "wipe mirror"], cwd=repo)

    tracked = _tracked_under(repo, BUNDLES_DIR)
    assert f"{BUNDLES_DIR}/shared.json" in tracked
    assert f"{BUNDLES_DIR}/develop_only.json" in tracked
    assert f"{BUNDLES_DIR}/community_only.json" not in tracked, (
        "wipe-then-checkout deleted published-only community_only.json — the defect this TODO fixes"
    )


def test_union_overlay_preserves_published_only_when_develop_ahead(tmp_path: Path) -> None:
    """Union overlay: checkout develop's bundles without wipe; published-only survives."""
    repo = tmp_path / "overlay"
    _init_repo(repo)

    published = {
        f"{BUNDLES_DIR}/shared.json": '{"id": "shared-v1"}\n',
        f"{BUNDLES_DIR}/community_only.json": '{"id": "community"}\n',
        "results-data/corpus-inventory.json": '{"version": 1}\n',
    }
    pub_sha = _commit_files(repo, published, "published tip")
    _run(["git", "branch", "published-results", pub_sha], cwd=repo)

    _run(["git", "rm", "-rf", "--quiet", BUNDLES_DIR], cwd=repo)
    develop = {
        f"{BUNDLES_DIR}/shared.json": '{"id": "shared-v2-sanitized"}\n',
        f"{BUNDLES_DIR}/develop_only.json": '{"id": "new-on-develop"}\n',
        "results-data/corpus-inventory.json": '{"version": 1}\n',
    }
    dev_sha = _commit_files(repo, develop, "develop tip")

    # New union-overlay apply (matches sync workflow Build mirror step).
    _run(["git", "switch", "--force-create", "mirror-overlay", "published-results"], cwd=repo)
    _run(["git", "checkout", dev_sha, "--", BUNDLES_DIR], cwd=repo)
    _run(["git", "add", "-A"], cwd=repo)
    _run(["git", "commit", "-m", "overlay mirror"], cwd=repo)

    tracked = _tracked_under(repo, BUNDLES_DIR)
    assert f"{BUNDLES_DIR}/community_only.json" in tracked
    assert f"{BUNDLES_DIR}/develop_only.json" in tracked
    assert f"{BUNDLES_DIR}/shared.json" in tracked
    shared_body = (repo / f"{BUNDLES_DIR}/shared.json").read_text(encoding="utf-8")
    assert "shared-v2-sanitized" in shared_body
    community_body = (repo / f"{BUNDLES_DIR}/community_only.json").read_text(encoding="utf-8")
    assert "community" in community_body

def test_build_mirror_regenerates_inventory_after_union_overlay() -> None:
    """Inventory must be derived from the unioned tree, not blind-overlaid from develop."""
    workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "generate_corpus_inventory.py --write" in workflow
    build = workflow.split("name: Build mirror branch", 1)[1].split("name: ", 1)[0]
    assert "generate_corpus_inventory.py --write" in build

