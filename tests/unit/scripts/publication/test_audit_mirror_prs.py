"""Tests for the corpus-mirror PR set-equivalence auditor."""

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

BASE_CORPUS = ["results-data/bundles/existing.json", "results-data/corpus-inventory.json"]


def _completed(stdout: str = "", stderr: str = "", code: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=code, stdout=stdout, stderr=stderr)


def _tree_payload(paths: list[str]) -> str:
    return json.dumps({"tree": [{"path": p} for p in paths]})


def _pr_payload(prs: list[dict]) -> str:
    return json.dumps(prs)


def _pr_file(path: str) -> dict:
    return {"path": path, "additions": 1, "deletions": 0, "status": "added", "additions/2": 0}


class _FakeRunner:
    def __init__(self, pr_payload: str, tree_payload: str, tree_code: int = 0, pr_code: int = 0):
        self.pr_payload = pr_payload
        self.tree_payload = tree_payload
        self.tree_code = tree_code
        self.pr_code = pr_code

    def __call__(self, args: list[str], **kwargs):
        if args[:2] == ["gh", "pr"]:
            return _completed(stdout=self.pr_payload, code=self.pr_code)
        if args[:2] == ["gh", "api"]:
            return _completed(stdout=self.tree_payload, code=self.tree_code)
        raise AssertionError(f"unexpected args: {args}")


def _run_main(argv: list[str], fake: _FakeRunner) -> int:
    with mock.patch("subprocess.run", side_effect=fake):
        return audit_mirror_prs.main(argv)


def test_no_open_prs_json_count_zero(capsys):
    fake = _FakeRunner(pr_payload=_pr_payload([]), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--json"], fake)
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "set-equivalence"
    assert payload["count"] == 0
    assert payload["prs"] == []


def test_no_open_prs_text_output(capsys):
    fake = _FakeRunner(pr_payload=_pr_payload([]), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE], fake)
    assert exit_code == 0
    assert "[audit ok] 0 mirror PRs open" in capsys.readouterr().out


def test_additive_pr_is_additive(capsys):
    prs = [
        {
            "number": 12,
            "title": "mirror new bundle",
            "headRefName": "auto/results-mirror-abcdef12",
            "files": [_pr_file("results-data/bundles/new.json")],
        }
    ]
    fake = _FakeRunner(pr_payload=_pr_payload(prs), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--json"], fake)
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    (pr,) = payload["prs"]
    assert pr["number"] == 12
    assert pr["verdict"] == "ADDITIVE"
    assert pr["new_to_union"] is True
    assert pr["added_path_count"] == 1
    assert pr["duplicate_count"] == 0


def test_noop_pr_is_noop(capsys):
    prs = [
        {
            "number": 13,
            "title": "re-mirror existing",
            "headRefName": "auto/results-mirror-00000013",
            "files": [_pr_file("results-data/bundles/existing.json")],
        }
    ]
    fake = _FakeRunner(pr_payload=_pr_payload(prs), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--json"], fake)
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    (pr,) = payload["prs"]
    assert pr["verdict"] == "NOOP"
    assert pr["new_to_union"] is False
    assert pr["duplicate_count"] == 1


def test_empty_pr_is_empty(capsys):
    prs = [
        {
            "number": 14,
            "title": "docs-only mirror",
            "headRefName": "auto/results-mirror-00000014",
            "files": [_pr_file("scripts/validate_submission.py")],
        }
    ]
    fake = _FakeRunner(pr_payload=_pr_payload(prs), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--json"], fake)
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    (pr,) = payload["prs"]
    assert pr["verdict"] == "EMPTY"
    assert pr["added_path_count"] == 0


def test_strict_union_with_noop_exits_three():
    prs = [
        {
            "number": 15,
            "title": "noop",
            "headRefName": "auto/results-mirror-00000015",
            "files": [_pr_file("results-data/bundles/existing.json")],
        }
    ]
    fake = _FakeRunner(pr_payload=_pr_payload(prs), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--strict-union"], fake)
    assert exit_code == 3


def test_strict_union_all_additive_exits_zero(capsys):
    prs = [
        {
            "number": 16,
            "title": "additive",
            "headRefName": "auto/results-mirror-00000016",
            "files": [_pr_file("results-data/bundles/new16.json")],
        }
    ]
    fake = _FakeRunner(pr_payload=_pr_payload(prs), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--strict-union"], fake)
    assert exit_code == 0


def test_json_schema_shape(capsys):
    prs = [
        {
            "number": 17,
            "title": "mixed",
            "headRefName": "auto/results-mirror-00000017",
            "files": [
                _pr_file("results-data/bundles/existing.json"),
                _pr_file("results-data/bundles/nouveau.json"),
            ],
        }
    ]
    fake = _FakeRunner(pr_payload=_pr_payload(prs), tree_payload=_tree_payload(BASE_CORPUS))
    exit_code = _run_main(["--repo", CID, "--base", BASE, "--json"], fake)
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"mode", "base", "count", "prs"}
    (pr,) = payload["prs"]
    assert set(pr.keys()) == {
        "number",
        "title",
        "head_ref",
        "added_path_count",
        "new_to_union",
        "duplicate_count",
        "verdict",
        "added_paths",
        "new_paths",
    }
    assert pr["verdict"] == "ADDITIVE"
    assert pr["duplicate_count"] == 1


def test_gh_failure_is_operational_error(capsys):
    fake = _FakeRunner(pr_payload="[]", tree_payload="", tree_code=1)
    exit_code = _run_main(["--repo", CID, "--base", BASE], fake)
    assert exit_code != 0
    assert "error" in capsys.readouterr().err.lower()


def test_pr_list_failure_is_operational_error(capsys):
    fake = _FakeRunner(pr_payload="", tree_payload=_tree_payload(BASE_CORPUS), pr_code=1)
    exit_code = _run_main(["--repo", CID, "--base", BASE], fake)
    assert exit_code != 0
    assert "error" in capsys.readouterr().err.lower()
