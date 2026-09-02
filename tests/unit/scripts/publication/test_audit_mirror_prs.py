"""Tests for the corpus-mirror PR content-equivalence auditor."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "publication" / "audit_mirror_prs.py"

spec = importlib.util.spec_from_file_location("audit_mirror_prs", SCRIPT_PATH)
audit_mirror_prs = importlib.util.module_from_spec(spec)
sys.modules["audit_mirror_prs"] = audit_mirror_prs
assert spec.loader is not None
spec.loader.exec_module(audit_mirror_prs)

CID = "benchbox-dev/BenchBox"
BASE = "published-results"

# path -> blob sha on the base branch tree
BASE_TREE = {
    "results-data/bundles/existing.json": "aaaa1111",
    "results-data/corpus-inventory.json": "bbbb2222",
    "scripts/validate_submission.py": "cccc3333",
}


def _completed(stdout: str = "", stderr: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


def _tree_payload(tree: dict[str, str], truncated: bool = False) -> str:
    return json.dumps(
        {"truncated": truncated, "tree": [{"path": p, "type": "blob", "sha": s} for p, s in tree.items()]}
    )


def _pr_file(path: str, sha: str, status: str = "modified") -> dict:
    return {"filename": path, "sha": sha, "status": status, "additions": 1, "deletions": 0}


class _FakeRunner:
    """Dispatches gh calls: pr list, git trees, and per-PR pulls/N/files."""

    def __init__(
        self,
        prs: list[dict],
        tree: dict[str, str],
        pr_files: dict[int, list[dict]] | None = None,
        tree_code: int = 0,
        pr_list_code: int = 0,
        files_code: int = 0,
        truncated: bool = False,
    ):
        self.prs = prs
        self.tree = tree
        self.pr_files = pr_files or {}
        self.tree_code = tree_code
        self.pr_list_code = pr_list_code
        self.files_code = files_code
        self.truncated = truncated

    def __call__(self, args: list[str], **kwargs):
        if args[:3] == ["gh", "pr", "list"]:
            return _completed(stdout=json.dumps(self.prs), code=self.pr_list_code)
        if args[:2] == ["gh", "api"]:
            target = args[-1]
            if "git/trees" in target:
                return _completed(stdout=_tree_payload(self.tree, self.truncated), code=self.tree_code)
            if "/pulls/" in target and target.endswith("files?per_page=100"):
                number = int(target.split("/pulls/")[1].split("/")[0])
                return _completed(stdout=json.dumps([self.pr_files.get(number, [])]), code=self.files_code)
        raise AssertionError(f"unexpected args: {args}")


def _run_main(argv: list[str], fake: _FakeRunner) -> int:
    with mock.patch("subprocess.run", side_effect=fake):
        return audit_mirror_prs.main(argv)


def _pr(number: int, title: str = "mirror") -> dict:
    return {"number": number, "title": title, "headRefName": f"auto/results-mirror-{number:08d}"}


def test_no_open_prs(capsys):
    fake = _FakeRunner(prs=[], tree=BASE_TREE)
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["count"] == 0
    assert payload["prs"] == []


def test_additive_pr(capsys):
    fake = _FakeRunner(
        prs=[_pr(12)],
        tree=BASE_TREE,
        pr_files={12: [_pr_file("results-data/bundles/new.json", "deadbeef", status="added")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "ADDITIVE"
    assert p["new_paths"] == ["results-data/bundles/new.json"]
    assert p["retire_able"] is False


def test_noop_pr_identical_blob(capsys):
    fake = _FakeRunner(
        prs=[_pr(13)],
        tree=BASE_TREE,
        pr_files={13: [_pr_file("results-data/bundles/existing.json", "aaaa1111", status="modified")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "NOOP"
    assert p["noop_paths"] == ["results-data/bundles/existing.json"]
    assert p["retire_able"] is True


def test_mutating_pr_rewrites_existing_path_content(capsys):
    """A PR that rewrites an existing path with new bytes must NOT be retire-able."""
    fake = _FakeRunner(
        prs=[_pr(14)],
        tree=BASE_TREE,
        pr_files={14: [_pr_file("results-data/corpus-inventory.json", "9999ffff", status="modified")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "MUTATING"
    assert p["changed_paths"] == ["results-data/corpus-inventory.json"]
    assert p["retire_able"] is False


def test_validator_only_mirror_is_mutating_not_empty(capsys):
    """Regression: a validator-only mirror PR used to classify EMPTY (retire-able)
    because CORPUS_PREFIXES covered only results-data/. The mirror workflow also
    mirrors scripts/validate_submission.py etc., so a content change there is a
    real refresh."""
    fake = _FakeRunner(
        prs=[_pr(15)],
        tree=BASE_TREE,
        pr_files={15: [_pr_file("scripts/validate_submission.py", "newsha00", status="modified")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "MUTATING"
    assert p["retire_able"] is False


def test_bundle_impl_path_is_mirrored(capsys):
    fake = _FakeRunner(
        prs=[_pr(16)],
        tree=BASE_TREE,
        pr_files={16: [_pr_file("benchbox/validation/bundle.py", "implsha1", status="added")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "ADDITIVE"


def test_empty_pr_touches_no_mirrored_path(capsys):
    fake = _FakeRunner(
        prs=[_pr(17)],
        tree=BASE_TREE,
        pr_files={17: [_pr_file("README.md", "xxxx", status="modified")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "EMPTY"
    assert p["retire_able"] is True


def test_removed_mirrored_path_is_mutating(capsys):
    fake = _FakeRunner(
        prs=[_pr(18)],
        tree=BASE_TREE,
        pr_files={18: [_pr_file("results-data/bundles/existing.json", "", status="removed")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["verdict"] == "MUTATING"
    assert p["removed_paths"] == ["results-data/bundles/existing.json"]


def test_large_pr_files_are_fully_paginated(capsys):
    """>100 mirrored files; a new bundle past file 100 must still be seen."""
    files = [_pr_file(f"results-data/bundles/b{i:04d}.json", f"sha{i}", status="added") for i in range(150)]
    fake = _FakeRunner(prs=[_pr(19)], tree=BASE_TREE, pr_files={19: files})
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    (p,) = json.loads(capsys.readouterr().out)["prs"]
    assert p["mirrored_file_count"] == 150
    assert p["verdict"] == "ADDITIVE"
    assert len(p["new_paths"]) == 150


def test_strict_union_with_noop_exits_three():
    fake = _FakeRunner(
        prs=[_pr(20)],
        tree=BASE_TREE,
        pr_files={20: [_pr_file("results-data/bundles/existing.json", "aaaa1111")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--strict-union"], fake) == 3


def test_strict_union_all_mutating_exits_zero():
    fake = _FakeRunner(
        prs=[_pr(21)],
        tree=BASE_TREE,
        pr_files={21: [_pr_file("results-data/bundles/existing.json", "changed99")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--strict-union"], fake) == 0


def test_truncated_base_tree_is_operational_error(capsys):
    fake = _FakeRunner(prs=[], tree=BASE_TREE, truncated=True)
    assert _run_main(["--repo", CID, "--base", BASE], fake) != 0
    assert "truncated" in capsys.readouterr().err.lower()


def test_per_pr_files_failure_is_isolated_error_verdict(capsys):
    fake = _FakeRunner(prs=[_pr(22), _pr(23)], tree=BASE_TREE, files_code=1)
    fake.pr_files = {23: [_pr_file("results-data/bundles/new.json", "s", status="added")]}
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--json"], fake)
    payload = json.loads(capsys.readouterr().out)
    verdicts = {p["number"]: p["verdict"] for p in payload["prs"]}
    assert verdicts[22] == "ERROR"
    # exit nonzero because a PR could not be audited
    assert exit_code == 1
    assert payload["errored"] == [22, 23]


def test_pr_list_failure_is_operational_error(capsys):
    fake = _FakeRunner(prs=[], tree=BASE_TREE, pr_list_code=1)
    assert _run_main(["--repo", CID, "--base", BASE], fake) != 0
    assert "error" in capsys.readouterr().err.lower()


def test_base_tree_failure_is_operational_error(capsys):
    fake = _FakeRunner(prs=[], tree=BASE_TREE, tree_code=1)
    assert _run_main(["--repo", CID, "--base", BASE], fake) != 0
    assert "error" in capsys.readouterr().err.lower()


def test_json_schema_shape(capsys):
    fake = _FakeRunner(
        prs=[_pr(24)],
        tree=BASE_TREE,
        pr_files={24: [_pr_file("results-data/bundles/new.json", "s", status="added")]},
    )
    assert _run_main(["--repo", CID, "--base", BASE, "--json"], fake) == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"mode", "base", "count", "retire_able", "errored", "prs"}
    (p,) = payload["prs"]
    assert set(p.keys()) == {
        "number",
        "title",
        "head_ref",
        "mirrored_file_count",
        "new_paths",
        "changed_paths",
        "removed_paths",
        "noop_paths",
        "verdict",
        "error",
        "retire_able",
    }
