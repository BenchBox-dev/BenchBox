"""Unit and CLI tests for publication lane isolation verification."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.publication.verify_lane_isolation import (
    REPO_ROOT,
    classify_path,
    compute_all_lane_digests,
    compute_lane_digest,
    is_ignored,
    main,
    scan_lane_files,
    verify_lane_isolation,
    verify_workflow_isolation,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_classify_path_identifies_correct_lanes() -> None:
    # Site lane
    assert classify_path("docs/index.rst") == {"site"}
    assert classify_path("landing/index.html") == {"site"}
    assert classify_path("_blog/post.md") == {"site"}
    assert classify_path("scripts/assemble_public_site.py") == {"site"}
    assert classify_path(".github/workflows/publication-lane-docs.yml") == {"site"}

    # Explorer lane
    assert classify_path("results-explorer/src/App.tsx") == {"explorer"}
    assert classify_path("_project/scripts/explorer_pipeline/pipeline.py") == {"explorer"}
    assert classify_path("_project/scripts/explorer_publish.py") == {"explorer"}
    assert classify_path(".github/workflows/publication-lane-explorer.yml") == {"explorer"}

    # Corpus lane
    assert classify_path("results-data/bundles/bundle_123.json") == {"corpus"}
    assert classify_path("scripts/validate_submission.py") == {"corpus"}
    assert classify_path(".github/workflows/validate-submission.yml") == {"corpus"}

    # Unclassified / root paths
    assert classify_path("README.md") == set()
    assert classify_path("pyproject.toml") == set()
    assert classify_path("") == set()


def test_is_ignored() -> None:
    assert is_ignored(".venv/lib/python3.11/site-packages/foo.py") is True
    assert is_ignored("docs/_build/html/index.html") is True
    assert is_ignored("benchbox/__pycache__/foo.cpython-311.pyc") is True
    assert is_ignored(".DS_Store") is True
    assert is_ignored("docs/index.rst") is False
    assert is_ignored("landing/style.css") is False


def test_scan_lane_files_finds_tracked_files() -> None:
    site_files = scan_lane_files("site", repo_root=REPO_ROOT)
    assert len(site_files) > 0
    assert "docs/conf.py" in site_files
    assert "scripts/assemble_public_site.py" in site_files


def test_compute_lane_digest_is_deterministic() -> None:
    digest1 = compute_lane_digest("site", repo_root=REPO_ROOT)
    digest2 = compute_lane_digest("site", repo_root=REPO_ROOT)
    assert digest1 == digest2
    assert len(digest1) == 64


def test_compute_all_lane_digests_returns_all_lanes() -> None:
    digests = compute_all_lane_digests(repo_root=REPO_ROOT)
    assert set(digests.keys()) == {"site", "explorer", "corpus"}
    for lane, d in digests.items():
        assert len(d) == 64


def test_lane_mutation_isolation_invariants() -> None:
    baseline = compute_all_lane_digests(repo_root=REPO_ROOT)

    # 1. Modifying corpus does not mutate site or explorer
    corpus_mod = {"results-data/bundles/synthetic_test.json": b'{"synthetic": true}'}
    corpus_mutated = compute_all_lane_digests(repo_root=REPO_ROOT, extra_files=corpus_mod)
    assert corpus_mutated["corpus"] != baseline["corpus"]
    assert corpus_mutated["site"] == baseline["site"]
    assert corpus_mutated["explorer"] == baseline["explorer"]

    # 2. Modifying explorer does not mutate site or corpus
    explorer_mod = {"results-explorer/synthetic_component.tsx": b"export const Foo = () => null;"}
    explorer_mutated = compute_all_lane_digests(repo_root=REPO_ROOT, extra_files=explorer_mod)
    assert explorer_mutated["explorer"] != baseline["explorer"]
    assert explorer_mutated["site"] == baseline["site"]
    assert explorer_mutated["corpus"] == baseline["corpus"]

    # 3. Modifying site does not mutate explorer or corpus
    site_mod = {"docs/synthetic_page.md": b"# Synthetic"}
    site_mutated = compute_all_lane_digests(repo_root=REPO_ROOT, extra_files=site_mod)
    assert site_mutated["site"] != baseline["site"]
    assert site_mutated["explorer"] == baseline["explorer"]
    assert site_mutated["corpus"] == baseline["corpus"]


def test_verify_lane_isolation_current_repo() -> None:
    report = verify_lane_isolation("site", repo_root=REPO_ROOT)
    assert report.success is True
    assert report.lane == "site"
    assert report.mutation_isolation_verified is True
    assert "prose_site" in report.artifacts
    assert "api_docs" in report.artifacts
    assert not report.errors


def test_verify_lane_isolation_detects_contaminating_changed_paths() -> None:
    # Clean paths for site
    clean_paths = ["docs/index.rst", "landing/index.html"]
    clean_report = verify_lane_isolation("site", repo_root=REPO_ROOT, changed_paths=clean_paths)
    assert clean_report.success is True

    # Contaminated paths with explorer and corpus changes
    dirty_paths = [
        "docs/index.rst",
        "results-explorer/package.json",
        "results-data/bundles/test.json",
    ]
    dirty_report = verify_lane_isolation("site", repo_root=REPO_ROOT, changed_paths=dirty_paths)
    assert dirty_report.success is False
    assert any("changed paths violate lane 'site' isolation" in err for err in dirty_report.errors)


def test_non_lane_inputs_skipped_in_changed_paths() -> None:
    # Tracked inputs owned by no lane and never read by lane builds must not
    # trip the boundary check (broad PRs such as tracker cutovers mix these
    # with lane files).
    mixed_paths = [
        "docs/index.rst",
        "tests/unit/test_example.py",
        ".claude/skills/todo-db/SKILL.md",
        ".github/workflows/pr.yml",
        "Makefile",
        "make/inventory.json",
        "_project/specs/example.md",
        "_project/scripts/agent_instruction_audit.py",
        "AGENTS.md",
        "skill-sync.yaml",
        "scripts/skill_sync_ci_policy.py",
        ".mcp.json",
        ".todo-db/config.json",
    ]
    report = verify_lane_isolation("site", repo_root=REPO_ROOT, changed_paths=mixed_paths)
    assert report.success is True
    assert not report.errors


def test_unclassified_changed_paths_still_fail() -> None:
    # Genuinely new areas outside every lane and allowlist must still fail
    # closed, with remediation guidance.
    report = verify_lane_isolation("site", repo_root=REPO_ROOT, changed_paths=["brand-new-area/file.txt"])
    assert report.success is False
    assert any("unclassified inputs" in err for err in report.errors)


def test_lane_owned_paths_still_contaminate_despite_non_lane_allowlist() -> None:
    # Classification runs before the non-lane allowlist: an explorer-owned
    # file under a non-lane parent (_project/) must still report
    # contamination when the site lane builds.
    report = verify_lane_isolation(
        "site",
        repo_root=REPO_ROOT,
        changed_paths=["docs/index.rst", "_project/scripts/explorer_pipeline/contract.py"],
    )
    assert report.success is False
    assert any("changed paths violate lane 'site' isolation" in err for err in report.errors)


def test_non_lane_inputs_excluded_from_digests() -> None:
    # Unlike shared inputs, non-lane inputs must never fold into lane
    # digests: lane fingerprints stay scoped to real build inputs.
    baseline = compute_lane_digest("site", repo_root=REPO_ROOT)
    with_non_lane_extra = compute_lane_digest(
        "site", repo_root=REPO_ROOT, extra_files={"tests/synthetic_probe.py": b"# probe\n"}
    )
    assert with_non_lane_extra == baseline
    with_lane_extra = compute_lane_digest(
        "site", repo_root=REPO_ROOT, extra_files={"docs/synthetic_probe.md": b"# probe\n"}
    )
    assert with_lane_extra != baseline


def test_verify_workflow_isolation_least_privilege(tmp_path: Path) -> None:
    # Create valid mock repo with compliant workflow
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    wf_path = wf_dir / "publication-lane-docs.yml"

    wf_content = """name: Test Lane
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: prose_site
      - uses: actions/upload-artifact@v4
        with:
          name: api_docs
"""
    wf_path.write_text(wf_content, encoding="utf-8")

    errors = verify_workflow_isolation("site", repo_root=tmp_path)
    assert not errors

    # Non-compliant with pages write permission
    bad_wf_content = wf_content.replace("contents: read", "contents: read\n  pages: write")
    wf_path.write_text(bad_wf_content, encoding="utf-8")
    errors = verify_workflow_isolation("site", repo_root=tmp_path)
    assert any("permissions" in err or "deployment" in err for err in errors)

    # Missing artifact declaration
    no_artifact_content = """name: Test Lane
permissions:
  contents: read
jobs:
  build:
    runs-on: ubuntu-latest
"""
    wf_path.write_text(no_artifact_content, encoding="utf-8")
    errors = verify_workflow_isolation("site", repo_root=tmp_path)
    assert any("does not declare required lane artifact" in err for err in errors)


def test_verify_workflow_isolation_missing_file(tmp_path: Path) -> None:
    errors = verify_workflow_isolation("site", repo_root=tmp_path)
    assert any("required workflow file missing" in err for err in errors)


def test_cli_lane_site() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/publication/verify_lane_isolation.py"), "--lane", "site"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "[PASS] Publication lane 'site' isolation verified:" in result.stdout
    assert "prose_site, api_docs" in result.stdout


def test_cli_lane_all_json() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts/publication/verify_lane_isolation.py"),
            "--lane",
            "all",
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    assert isinstance(data, list)
    assert len(data) == 3
    lanes = {item["lane"] for item in data}
    assert lanes == {"site", "explorer", "corpus"}
    for item in data:
        assert item["success"] is True


def test_cli_changed_paths_file(tmp_path: Path) -> None:
    paths_file = tmp_path / "changed.txt"
    paths_file.write_text("docs/overview.md\nlanding/index.html\n", encoding="utf-8")

    exit_code = main(["--lane", "site", "--changed-paths-file", str(paths_file)])
    assert exit_code == 0

    # Test failure on cross-lane path in file
    paths_file.write_text("results-data/bundles/bundle_evil.json\n", encoding="utf-8")
    exit_code = main(["--lane", "site", "--changed-paths-file", str(paths_file)])
    assert exit_code == 1


def test_classify_path_shared_inputs_are_exempt() -> None:
    """benchbox/** is a SHARED_BUILD_INPUTS exempt path, not a lane-owned path.

    Finding #3: classify_path must return empty for shared inputs; ownership
    is signalled via _is_shared_input and digest folding, not lane prefixes.
    """
    from scripts.publication.verify_lane_isolation import _is_shared_input

    assert classify_path("benchbox/foo.py") == set()
    assert classify_path("benchbox/core/results/anonymization.py") == set()
    assert classify_path("pyproject.toml") == set()
    assert classify_path("uv.lock") == set()
    assert _is_shared_input("benchbox/foo.py") is True
    assert _is_shared_input("pyproject.toml") is True
    assert _is_shared_input("uv.lock") is True
    # Shared inputs must not be flagged as unclassified contamination
    report = verify_lane_isolation("site", repo_root=REPO_ROOT, changed_paths=["benchbox/foo.py"])
    assert report.success is True
    # Shared input mutation must affect every lane digest (closure)
    baseline = compute_all_lane_digests(repo_root=REPO_ROOT)
    mutated = compute_all_lane_digests(
        repo_root=REPO_ROOT, extra_files={"benchbox/synthetic_shared_probe2.py": b"# probe\n"}
    )
    for lane in ("site", "explorer", "corpus"):
        assert mutated[lane] != baseline[lane]


def test_verify_workflow_isolation_rejects_job_level_write(tmp_path: Path) -> None:
    """Finding #2: job-level permissions: contents: write must be rejected."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    wf_path = wf_dir / "publication-lane-docs.yml"
    # Top-level is least-privilege but job escalates
    wf_content = """name: Test Lane
permissions:
  contents: read
jobs:
  build-docs-lane:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/upload-artifact@v4
        with:
          name: prose_site
      - uses: actions/upload-artifact@v4
        with:
          name: api_docs
"""
    wf_path.write_text(wf_content, encoding="utf-8")
    errors = verify_workflow_isolation("site", repo_root=tmp_path)
    assert any(
        "job 'build-docs-lane'" in e and "contents: write" in e.lower() or "non-least-privilege" in e for e in errors
    ), errors
    # Also test scalar job permissions
    wf_content_scalar = wf_content.replace("contents: write", '"write-all"')
    wf_path.write_text(wf_content_scalar, encoding="utf-8")
    errors = verify_workflow_isolation("site", repo_root=tmp_path)
    assert any("job 'build-docs-lane'" in e for e in errors), errors


def test_cli_changed_paths_fails_closed_on_empty() -> None:
    """Finding #5: --changed-paths with no values must fail closed, not silently pass."""
    # Bare flag with no paths
    exit_code = main(["--lane", "site", "--changed-paths"])
    assert exit_code == 1
    # Empty string arg also fails closed
    exit_code = main(["--lane", "site", "--changed-paths", ""])
    assert exit_code == 1
    # Whitespace-only fails closed
    exit_code = main(["--lane", "site", "--changed-paths", "   "])
    assert exit_code == 1


def test_cli_changed_paths_file_fails_closed_on_empty(tmp_path: Path) -> None:
    """Empty --changed-paths-file that exists must fail closed, same as empty --changed-paths."""
    empty_file = tmp_path / "empty-changed.txt"
    empty_file.write_text("", encoding="utf-8")
    assert main(["--lane", "site", "--changed-paths-file", str(empty_file)]) == 1

    whitespace_file = tmp_path / "whitespace-changed.txt"
    whitespace_file.write_text("\n  \n\n", encoding="utf-8")
    assert main(["--lane", "site", "--changed-paths-file", str(whitespace_file)]) == 1


def test_verify_workflow_isolation_real_explorer_lane() -> None:
    """Explorer isolation must parse the real publication-lane-explorer.yml (no deploy-pages)."""
    from scripts.publication.verify_lane_isolation import LANE_ARTIFACTS, LANE_WORKFLOWS

    assert LANE_WORKFLOWS["explorer"] == ".github/workflows/publication-lane-explorer.yml"
    assert LANE_ARTIFACTS["explorer"] == ("explorer_app",)
    assert "results.duckdb" not in LANE_ARTIFACTS["explorer"]

    errors = verify_workflow_isolation("explorer", repo_root=REPO_ROOT)
    assert not errors, errors

    report = verify_lane_isolation("explorer", repo_root=REPO_ROOT, check_mutations=False)
    assert report.success is True
    assert report.artifacts == ["explorer_app"]

    raw = (REPO_ROOT / LANE_WORKFLOWS["explorer"]).read_text(encoding="utf-8")
    assert "deploy-pages" not in raw
    assert "pages: write" not in raw


def test_verify_workflow_isolation_missing_explorer_workflow(tmp_path: Path) -> None:
    errors = verify_workflow_isolation("explorer", repo_root=tmp_path)
    assert any("required workflow file missing" in err for err in errors)
    assert any("publication-lane-explorer.yml" in err for err in errors)


def test_cli_lane_all_runs_explorer_and_corpus_workflow_checks() -> None:
    """--lane all must not be a vacuous pass: explorer+corpus workflows are inspected."""
    from scripts.publication.verify_lane_isolation import LANE_WORKFLOWS

    assert set(LANE_WORKFLOWS) == {"site", "explorer", "corpus"}
    exit_code = main(["--lane", "all", "--json"])
    assert exit_code == 0


def test_real_file_mutation_and_disjointness(tmp_path: Path) -> None:
    """Finding #1: real lane files must classify and not be double-counted."""
    from scripts.publication.verify_lane_isolation import _is_shared_input, scan_lane_files

    # All non-shared files must classify to their lane
    for lane in ("site", "explorer", "corpus"):
        files = scan_lane_files(lane, repo_root=REPO_ROOT)
        for rel in files:
            if _is_shared_input(rel):
                continue
            assert lane in classify_path(rel), f"{rel} in lane {lane} does not classify"
    # No non-shared file is in two lanes
    filesets = {lane: set(scan_lane_files(lane, repo_root=REPO_ROOT).keys()) for lane in ("site", "explorer", "corpus")}
    shared = {p for lane in filesets for p in filesets[lane] if _is_shared_input(p)}
    for a in ("site", "explorer", "corpus"):
        for b in ("site", "explorer", "corpus"):
            if a >= b:
                continue
            overlap = (filesets[a] & filesets[b]) - shared
            assert not overlap, f"lanes {a} and {b} share non-shared files: {overlap}"
    # Vacuity guard: site and explorer have owned files
    for lane in ("site", "explorer"):
        owned = [p for p in filesets[lane] if not _is_shared_input(p)]
        assert owned, f"lane {lane} has no owned files; mutation check vacuous"
