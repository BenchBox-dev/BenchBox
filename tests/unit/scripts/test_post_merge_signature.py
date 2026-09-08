"""Tests for post-merge failure-signature attribution."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("post_merge_signature", SCRIPTS / "post_merge_signature.py")
assert spec is not None and spec.loader is not None
sig = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sig
spec.loader.exec_module(sig)


def test_dotted_bigquery_style_classname_normalizes() -> None:
    """#2071/#2068 replay: dotted JUnit classnames resolve to the owning test file."""
    assert sig.failure_id_test_paths(["tests.unit.foo.TestFoo::test_bar"]) == ["tests/unit/foo.py"]
    assert sig.failure_id_test_paths(["tests.unit.foo::test_bar"]) == ["tests/unit/foo.py"]


def test_job_level_ids_stay_fail_closed_revert() -> None:
    action, basis = sig.attribution_detail(["lint:Run CI lint mirror"], ["docs/x.md"])
    assert (action, basis) == ("revert", "no-extractable-path")


def test_cleared_sha_is_advisory() -> None:
    action, basis = sig.attribution_detail(["tests/unit/foo.py::test_bar"], ["benchbox/other.py"])
    assert (action, basis) == ("advisory", "cleared")


def test_owning_test_path_reverts() -> None:
    action, basis = sig.attribution_detail(["tests/unit/foo.py::test_bar"], ["tests/unit/foo.py"])
    assert (action, basis) == ("revert", "test-path")


def test_unrecognized_class_escalates(tmp_path: Path) -> None:
    action, basis = sig.attribution_detail(["weird-id-without-shape"], ["anything.py"])
    assert (action, basis) == ("escalate", "unrecognized-class")
    assert sig.unrecognized_failure_ids(["weird-id-without-shape", 42]) == [
        "weird-id-without-shape",
        "42",
    ]
    assert sig.unrecognized_failure_ids(["tests/unit/foo.py::t", "lint:step"]) == []


def test_import_signal_reverts_on_unrelated_basename(tmp_path: Path) -> None:
    (tmp_path / "helper_dep.py").write_text("VALUE = 1\n")
    (tmp_path / "test_owner.py").write_text("from helper_dep import VALUE\n\n\ndef test_v():\n    assert VALUE\n")
    action, basis = sig.attribution_detail(["test_owner.py::test_v"], ["helper_dep.py"], repo_root=tmp_path)
    assert (action, basis) == ("revert", "import")


def _git_repo(path: Path) -> tuple[str, str]:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "T"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "helper_dep.py").write_text("VALUE = 1\n")
    (path / "test_owner.py").write_text("from helper_dep import VALUE\n\n\ndef test_v():\n    assert VALUE\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True, capture_output=True)
    (path / "helper_dep.py").write_text("VALUE = 2\n")
    subprocess.run(["git", "commit", "-qam", "bad"], cwd=path, check=True, capture_output=True)
    bad = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    (path / "unrelated.txt").write_text("x\n")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "unrelated"], cwd=path, check=True, capture_output=True)
    other = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()
    return bad, other


def test_isolated_bad_fix_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """w3: only the blamed commit's own diff drives the verdict."""
    bad, other = _git_repo(tmp_path / "repo")
    monkeypatch.chdir(tmp_path / "repo")
    failing = ["test_owner.py::test_v"]
    bad_paths = sig.changed_paths_for_sha(bad)
    assert bad_paths == ["helper_dep.py"]
    assert sig.attribution_detail(failing, bad_paths, repo_root=tmp_path / "repo")[0] == "revert"
    other_paths = sig.changed_paths_for_sha(other)
    assert other_paths == ["unrelated.txt"]
    assert sig.attribution_detail(failing, other_paths, repo_root=tmp_path / "repo")[0] == "advisory"


def test_attribute_cli_binds_sha_and_basis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    bad, _ = _git_repo(tmp_path / "repo")
    monkeypatch.chdir(tmp_path / "repo")
    ids = tmp_path / "ids.json"
    ids.write_text(json.dumps(["test_owner.py::test_v"]), encoding="utf-8")
    out = tmp_path / "attribution.json"
    assert sig.main(["attribute", "--sha", bad, "--failure-ids", str(ids), "--out", str(out)]) == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["sha"] == bad
    assert data["action"] == "revert"
    assert data["attribution_basis"] == "import"


def test_diff_reports_only_new_ids(tmp_path: Path) -> None:
    prev = tmp_path / "prev.json"
    curr = tmp_path / "curr.json"
    prev.write_text(json.dumps({"failure_ids": ["a", "b"]}), encoding="utf-8")
    curr.write_text(json.dumps({"failure_ids": ["b", "c"]}), encoding="utf-8")
    assert sig.diff_signatures(
        json.loads(prev.read_text(encoding="utf-8")), json.loads(curr.read_text(encoding="utf-8"))
    ) == ["c"]
