from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = ROOT / "scripts/site_inputs.py"

spec = importlib.util.spec_from_file_location("site_inputs_test", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
site_inputs = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = site_inputs
spec.loader.exec_module(site_inputs)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_member_digest_is_stable_and_path_sensitive(tmp_path: Path) -> None:
    root = tmp_path / "member"
    _write(root / "a.json", '{"a": 1}\n')
    _write(root / "sub/b.json", '{"b": 2}\n')
    first = site_inputs.member_digest(root)
    assert site_inputs.member_digest(root) == first
    _write(root / "sub/b.json", '{"b": 3}\n')
    assert site_inputs.member_digest(root) != first


def test_member_digest_covers_single_file(tmp_path: Path) -> None:
    target = _write(tmp_path / "symbols.json", '{"symbols": []}\n')
    assert site_inputs.member_digest(target) == site_inputs.file_sha(target)


def _bundle(tmp_path: Path, schema: int = 1, attestations: str = "pass") -> Path:
    out = tmp_path / "bundle"
    members = {
        "docs": "docs tree",
        "repo-files.json": '{"files": []}\n',
        "explorer/results.duckdb": "duckdb-bytes",
        "explorer/contract.json": '{"version": "6"}\n',
        "explorer/fixtures": "fixture tree",
        "explorer/parity": "parity tree",
        "landing/prompt-catalog.json": '{"prompts": []}\n',
        "api-public-symbols.json": '{"symbols": []}\n',
        "attestations.json": "attestation tree",
    }
    att = [{"name": "privacy", "result": attestations}, {"name": "validator_parity", "result": "skip"}]
    members["attestations.json"] = json.dumps(att) + "\n"
    digests = {}
    dirs = {"docs", "explorer/fixtures", "explorer/parity"}
    for name, body in members.items():
        target = out / name
        if name in dirs:
            _write(target / "member.txt", body)
        else:
            _write(target, body)
        digests[name] = site_inputs.member_digest(target)
    manifest = {"schema": schema, "core_sha": "abc", "members": digests}
    _write(out / "manifest.json", json.dumps(manifest) + "\n")
    return out


def test_verify_accepts_consistent_bundle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert site_inputs.cmd_verify(_bundle(tmp_path)) == 0
    assert "verify OK" in capsys.readouterr().out


def test_verify_rejects_tampered_member(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    (out / "api-public-symbols.json").write_text('{"symbols": ["x"]}\n', encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_schema_mismatch(tmp_path: Path) -> None:
    assert site_inputs.cmd_verify(_bundle(tmp_path, schema=2)) == 1


def test_verify_rejects_failed_attestation(tmp_path: Path) -> None:
    assert site_inputs.cmd_verify(_bundle(tmp_path, attestations="fail")) == 1


def test_build_refuses_foreign_core_sha(tmp_path: Path) -> None:
    args = argparse.Namespace(
        out=str(tmp_path / "out"), core_sha="d076a974d", parent_core_sha=None, certified_by=None, cmd="build"
    )
    with pytest.raises(RuntimeError, match="not the bundle core_sha"):
        site_inputs.cmd_build(args)


def test_repo_files_lists_every_tracked_path_with_kinds(tmp_path: Path) -> None:
    out = tmp_path / "repo-files.json"
    site_inputs.build_repo_files(out, "abc123")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["core_sha"] == "abc123"
    by_path = {entry["path"]: entry["kind"] for entry in payload["files"]}
    assert by_path["scripts/check_decision_records.py"] == "file"
    assert by_path["scripts"] == "tree"
    assert by_path["docs/development/adr/adr-site-repo-split.md"] == "file"
