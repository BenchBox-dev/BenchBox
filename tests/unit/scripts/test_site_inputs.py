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
    dirs = {"docs", "explorer/fixtures", "explorer/parity"}
    for name, body in members.items():
        if name == "attestations.json":
            continue
        target = out / name
        if name in dirs:
            _write(target / "member.txt", body)
        else:
            _write(target, body)
    snapshot = site_inputs.member_digest(out / "explorer/results.duckdb")
    att = [
        {
            "name": "privacy",
            "result": attestations,
            "inputs": {"bundle": "fixture-bundle"},
            "compared": {"core_sha": "abc"},
        },
        {"name": "explorer_compat", "result": "pass", "inputs": {"snapshot": snapshot}},
        {"name": "snapshot_invariants", "result": "pass", "inputs": {"snapshot": snapshot}},
        {
            "name": "corpus_bijection",
            "result": "pass",
            "inputs": {"snapshot": snapshot},
            "compared": {"accepted_ref": "abc"},
        },
        {"name": "validator_parity", "result": "skip", "compared": {"base": "def", "head": "abc"}},
    ]
    _write(out / "attestations.json", json.dumps(att) + "\n")
    digests = {name: site_inputs.member_digest(out / name) for name in members}
    manifest = {
        "schema": schema,
        "core_sha": "abc",
        "parent_core_sha": "def",
        "members": digests,
    }
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


def test_verify_rejects_missing_member(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["members"].pop("docs")
    (out / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_missing_attestation(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    kept = [e for e in json.loads((out / "attestations.json").read_text(encoding="utf-8")) if e["name"] != "privacy"]
    (out / "attestations.json").write_text(json.dumps(kept) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_skipped_required_attestation(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, result="skip") if e["name"] == "privacy" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_empty_attestations(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    (out / "attestations.json").write_text("[]\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_pass_entry_without_inputs(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        {k: v for k, v in e.items() if k != "inputs"} if e["name"] == "explorer_compat" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_snapshot_digest_mismatch(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, inputs={"snapshot": "0" * 64}) if e["name"] == "snapshot_invariants" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_empty_member_digest(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    manifest["members"]["docs"] = ""
    (out / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_compared_head_mismatch(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, compared={"base": "def", "head": "0" * 40}) if e["name"] == "validator_parity" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_compared_core_sha_mismatch(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, compared={"core_sha": "0" * 40}) if e["name"] == "privacy" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_compared_accepted_ref_mismatch(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, compared={"accepted_ref": "0" * 40}) if e["name"] == "corpus_bijection" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_compared_base_mismatch(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, compared={"base": "0" * 40, "head": "abc"}) if e["name"] == "validator_parity" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_verify_rejects_compared_base_without_parent(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    del manifest["parent_core_sha"]
    (out / "manifest.json").write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_member_digest_raises_on_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        site_inputs.member_digest(tmp_path / "absent")


def test_build_refuses_foreign_core_sha(tmp_path: Path) -> None:
    for sha in ("d076a974d", "0" * 40):
        args = argparse.Namespace(
            out=str(tmp_path / "out"), core_sha=sha, parent_core_sha=None, certified_by=None, cmd="build"
        )
        with pytest.raises(RuntimeError, match="not the bundle core_sha"):
            site_inputs.cmd_build(args)


def _gen_data(tmp_path: Path, payload: dict | None = None) -> Path:
    data = tmp_path / "gen" / "data"
    _write(data / "results.duckdb", "duckdb-bytes")
    _write(data / "bundles" / "r1.json", '{"run": {"id": "x"}}\n')
    if payload is not None:
        _write(data / "fixture-ids.json", json.dumps(payload) + "\n")
    return data


def test_stage_fixtures_copies_db_bundles_and_role_keyed_ids(tmp_path: Path) -> None:
    out = tmp_path / "out"
    site_inputs._stage_fixtures(_gen_data(tmp_path, {"ids": {"duckdb": "r1"}, "shortIds": {"duckdb": "s1"}}), out)

    assert (out / "results.duckdb").is_file()
    assert (out / "r1.json").is_file()
    assert json.loads((out / "fixture-ids.json").read_text(encoding="utf-8"))["ids"]["duckdb"] == "r1"


def test_stage_fixtures_rejects_missing_ids_file(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="no fixture-ids.json"):
        site_inputs._stage_fixtures(_gen_data(tmp_path), tmp_path / "out")


def test_stage_fixtures_rejects_flat_id_map(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="role-keyed contract"):
        site_inputs._stage_fixtures(_gen_data(tmp_path, {"r1": "s1"}), tmp_path / "out")


def test_repo_files_lists_every_tracked_path_with_kinds(tmp_path: Path) -> None:
    out = tmp_path / "repo-files.json"
    site_inputs.build_repo_files(out, "abc123")
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["core_sha"] == "abc123"
    by_path = {entry["path"]: entry["kind"] for entry in payload["files"]}
    assert by_path["scripts/check_decision_records.py"] == "file"
    assert by_path["scripts"] == "tree"
    assert by_path["docs/development/adr/adr-site-repo-split.md"] == "file"


def _captured_attestations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, corpus_changed: bool
) -> tuple[list[dict], list[list[str]]]:
    commands: list[list[str]] = []

    def fake_run(*cmd: str, cwd: Path = site_inputs.ROOT) -> argparse.Namespace:
        commands.append([str(c) for c in cmd])
        return argparse.Namespace(returncode=0, stdout="ok", stderr="")

    def fake_tree_sha(ref: str, subdir: str) -> str:
        if subdir == "results-data" and corpus_changed:
            return f"tree-{ref}"
        return "tree"

    monkeypatch.setattr(site_inputs, "run", fake_run)
    monkeypatch.setattr(site_inputs, "tree_sha", fake_tree_sha)
    bundle = tmp_path / "bundle"
    _write(bundle / "explorer/results.duckdb", "duckdb-bytes")
    out = tmp_path / "attestations.json"
    site_inputs.build_attestations(out, bundle, "core", "parent")
    return json.loads(out.read_text(encoding="utf-8")), commands


def _command(commands: list[list[str]], script: str) -> list[str]:
    matches = [c for c in commands if script in c]
    assert len(matches) == 1, commands
    return matches[0]


def test_corpus_bijection_matches_the_deploy_gate_form(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries, commands = _captured_attestations(tmp_path, monkeypatch, corpus_changed=False)
    command = _command(commands, "scripts/publication/check_corpus_bijection.py")
    assert command[command.index("--accepted-ref") + 1] == "core"
    assert command[command.index("--expect-source") + 1] == "core"
    assert command[command.index("--bundles-dir") + 1] == str(site_inputs.ROOT / "results-data" / "bundles")
    assert command[command.index("--ledger-seed") + 1] == str(site_inputs.ROOT / "publication/ledger-seed.json")
    assert "--require-artifact" in command
    bijection = next(e for e in entries if e["name"] == "corpus_bijection")
    assert bijection["compared"] == {"accepted_ref": "core"}


def test_build_refuses_missing_ledger_seed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(site_inputs, "ROOT", tmp_path)
    with pytest.raises(RuntimeError, match="ledger seed missing"):
        _captured_attestations(tmp_path, monkeypatch, corpus_changed=False)


def test_verify_rejects_accepted_ref_other_than_core_sha(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    changed = [
        dict(e, compared={"accepted_ref": "def"}) if e["name"] == "corpus_bijection" else e
        for e in json.loads((out / "attestations.json").read_text(encoding="utf-8"))
    ]
    (out / "attestations.json").write_text(json.dumps(changed) + "\n", encoding="utf-8")
    assert site_inputs.cmd_verify(out) == 1


def test_validator_parity_skips_when_corpus_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    entries, commands = _captured_attestations(tmp_path, monkeypatch, corpus_changed=False)
    parity = next(e for e in entries if e["name"] == "validator_parity")
    assert parity["result"] == "skip"
    assert parity["reason"] == "corpus unchanged"
    assert parity["compared"] == {"base": "parent", "head": "core"}
    assert not [c for c in commands if "scripts/publication/validator_parity.py" in c]


def test_validator_parity_uses_the_mirror_form_when_corpus_changed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries, commands = _captured_attestations(tmp_path, monkeypatch, corpus_changed=True)
    command = _command(commands, "scripts/publication/validator_parity.py")
    assert command[command.index("--base-sha") + 1] == "parent"
    assert command[command.index("--merge-sha") + 1] == "core"
    assert command[command.index("--head-sha") + 1] == "core"
    assert "--allow-partial-validation" in command
    assert "--require-manifest" not in command
    parity = next(e for e in entries if e["name"] == "validator_parity")
    assert parity["result"] == "pass"
    assert parity["compared"] == {"base": "parent", "merge": "core", "head": "core"}
