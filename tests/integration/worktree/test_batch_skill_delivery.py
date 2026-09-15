"""Integration contracts for the installed todo-db batch delivery capability."""

from __future__ import annotations

import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
CATALOG_REV = "c8473708b5c7809700e8449ecde0dabcdc8e9892"
SOURCE_REV = "74631c83f74b7f184abbd49001f032943b720774"
SCRIPTS_PROJECT = ROOT / "_project/scripts"
WHEEL = SCRIPTS_PROJECT / "vendor/todo_db-0.7.3-py3-none-any.whl"
WHEEL_SHA256 = "d5d411703d571559df60b88445da194c59423c6d6d91f12f2d3177e41ab05ce4"
REQUIRED_BATCH_TOOLS = {"register_batch", "prepare", "bind_batch_pr", "abort_batch"}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence() -> dict:
    path = ROOT / "_project/analysis/batch-rollout-evidence.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _local_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["uv", "run", "--project", str(SCRIPTS_PROJECT), "--locked", "--", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )


def _rpc(proc: subprocess.Popen[str], method: str, params: dict | None = None, request_id: int = 1) -> dict:
    assert proc.stdin is not None and proc.stdout is not None
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()
    line = proc.stdout.readline()
    if not line:
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        raise AssertionError(f"no response for {method}: {stderr}")
    return json.loads(line)


def test_pin_receipt_and_tracked_mirror_bind_catalog_tip() -> None:
    config = (ROOT / "skill-sync.conf").read_text(encoding="utf-8")
    receipt = (ROOT / ".claude/skills/skill-sync.receipt").read_text(encoding="utf-8")
    evidence = _evidence()
    assert f"rev    = {CATALOG_REV}" in config
    assert f"rev = {CATALOG_REV}" in receipt
    assert evidence["catalog"]["merge_revision"] == CATALOG_REV
    assert evidence["source"]["merge_revision"] == SOURCE_REV
    assert evidence["benchbox_pin"]["after"] == CATALOG_REV
    for relative, expected in evidence["mirrors"]["tracked_target"]["files"].items():
        assert _sha256(ROOT / ".claude/skills/todo" / relative) == expected


def test_active_agent_materialization_matches_tracked_snapshot() -> None:
    evidence = _evidence()
    active_root = ROOT / ".agents/skills/todo"
    if not active_root.is_dir():
        return
    assert evidence["mirrors"]["agents_target"]["materialized"] is True
    for relative in evidence["mirrors"]["tracked_target"]["files"]:
        tracked = ROOT / ".claude/skills/todo" / relative
        active = ROOT / ".agents/skills/todo" / relative
        assert active.is_file()
        assert active.read_bytes() == tracked.read_bytes()


def test_feature_mode_is_capability_gated_and_serial_remains_default() -> None:
    docs = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "AGENTS.md",
            "docs/agent/batch-feature-delivery.md",
            "docs/agent/review-protocol.md",
            "docs/operations/dev-loop-worktrees.md",
        )
    )
    normalized = docs.lower()
    assert "serial mode is the default" in normalized
    assert "active todo-db mcp server" in normalized
    assert "one shared integration branch" in normalized
    assert "one integrator" in normalized
    assert "no feature-base prs" in normalized
    assert "no new ci skips" in normalized


def test_project_local_wheel_and_lock_are_exact_and_sibling_free() -> None:
    assert WHEEL.is_file()
    assert _sha256(WHEEL) == WHEEL_SHA256
    pyproject = (SCRIPTS_PROJECT / "pyproject.toml").read_text(encoding="utf-8")
    lock = (SCRIPTS_PROJECT / "uv.lock").read_text(encoding="utf-8")
    expected_path = "vendor/todo_db-0.7.3-py3-none-any.whl"
    assert f'path = "{expected_path}"' in pyproject
    assert f'path = "{expected_path}"' in lock
    assert 'name = "todo-db"\nversion = "0.7.3"' in lock
    assert "/Users/joe/Developer/todo-db" not in pyproject
    assert "/Users/joe/Developer/todo-db" not in lock
    with zipfile.ZipFile(WHEEL) as archive:
        names = set(archive.namelist())
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = archive.read(metadata_name).decode("utf-8")
    assert "Name: todo-db\n" in metadata
    assert "Version: 0.7.3\n" in metadata
    assert "todo_db/mcp/server.py" in names
    assert "todo_db/mcp/tools.py" in names
    assert "todo_db/database.py" not in names


def test_installed_runtime_handshake_exposes_registered_batch_tools(tmp_path: Path) -> None:
    remote = tmp_path / "state.git"
    subprocess.run(["git", "init", "--bare", "--quiet", str(remote)], check=True, capture_output=True)
    _local_tool("todo-db", "bootstrap", "--state-remote", str(remote), "--state-branch", "todo-state")
    proc = subprocess.Popen(
        [
            "uv",
            "run",
            "--project",
            str(SCRIPTS_PROJECT),
            "--locked",
            "--",
            "todo-db-mcp",
            "--state-remote",
            str(remote),
            "--state-branch",
            "todo-state",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--actor",
            "batch-runtime-test",
        ],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        initialized = _rpc(
            proc,
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "batch-runtime-test", "version": "1"},
            },
        )
        assert initialized["result"]["serverInfo"] == {"name": "todo-db", "version": "0.7.3"}
        assert proc.stdin is not None
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        proc.stdin.flush()
        listed = _rpc(proc, "tools/list", {}, request_id=2)
        tools = listed["result"]["tools"]
        names = {tool["name"] for tool in tools}
        assert len(tools) == 14
        assert names >= REQUIRED_BATCH_TOOLS
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def test_rollout_evidence_records_active_runtime_capability() -> None:
    evidence = _evidence()
    runtime = evidence["runtime"]
    assert runtime["dependency_metadata_version"] == "0.7.3"
    assert runtime["schema_version"] == 3
    assert runtime["tool_count"] == 14
    assert set(runtime["registered_batch_tools"]) == REQUIRED_BATCH_TOOLS
    assert evidence["verification"]["active_runtime_blocker"] is None
