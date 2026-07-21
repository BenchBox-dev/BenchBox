"""Contract tests for the opt-in BenchBox to standalone CLI adapter."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from subprocess import CompletedProcess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "_project" / "scripts"))
import todo_db_standalone_compat as compat  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def _envelope() -> dict:
    return {
        "format_version": 2,
        "metadata": {"lint.require_scope_rules": "on"},
        "events": [{"seq": 1, "action": "create", "detail": {"item_id": "sample-item"}}],
        "tables": {
            "items": [
                {
                    "id": "sample-item",
                    "title": "A sample tracked item",
                    "worktree": "benchbox",
                    "priority": "high",
                    "state": "planning",
                    "blocked_reason": None,
                    "category": "Core",
                    "description": "A description longer than ten characters.",
                    "approach": "Keep the adapter thin.",
                    "claimed_by": None,
                    "claimed_at": None,
                    "created_at": "2026-07-20T00:00:00Z",
                    "completed_at": None,
                    "completed_pr": None,
                }
            ],
            "work_units": [
                {
                    "item_id": "sample-item",
                    "wid": "w0",
                    "summary": "Run the compatibility tests",
                    "status": "pending",
                    "evidence": None,
                    "notes": None,
                    "started_at": None,
                    "started_worktree": None,
                    "started_branch": None,
                }
            ],
            "work_needs": [],
            "item_deps": [],
            "scope_rules": [{"item_id": "sample-item", "kind": "only_modify", "path_glob": "benchbox/**"}],
            "verifications": [],
            "preserves": [{"item_id": "sample-item", "behavior": "legacy output"}],
            "anti_patterns": [],
            "prior_art": [],
            "deferrals": [],
        },
    }


def test_lifecycle_commands_receive_identity_and_actor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append((argv, command))
        return CompletedProcess(argv, 0, stdout=f"delegated {command}\n", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "--actor", "alice", "claim", "item"]) == 0

    argv, command = calls[0]
    command_position = argv.index(command)
    assert command == "claim"
    assert argv[:command_position] == [
        "--db",
        str(tmp_path / "todo.sqlite"),
        "--actor",
        "alice",
        "--project-id",
        "benchbox",
        "--repository",
        "https://github.com/joeharris76/BenchBox",
    ]
    assert argv[command_position:] == ["claim", "item"]


@pytest.mark.parametrize(
    "command",
    [
        "init",
        "migrate",
        "create",
        "show",
        "claim",
        "release",
        "deps",
        "unblock",
        "start",
        "done",
        "defer",
        "promote",
        "dismiss",
        "complete",
        "drop",
        "block",
        "list",
        "ready",
        "stats",
        "check-scope",
        "verify",
        "lint",
        "config",
    ],
)
def test_required_legacy_commands_are_routable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str) -> None:
    calls: list[str] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), command]) == 0
    assert calls == [command]


def test_policy_failures_keep_legacy_status_code(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        return CompletedProcess(argv, 2, stdout="policy output\n", stderr="policy failure\n")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "check-scope", "item"]) == 2
    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "verify", "item", "--run", "1"]) == 2
    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "lint", "item"]) == 2


def test_option_values_that_match_commands_are_not_parsed_as_commands() -> None:
    assert compat._command_index(["--actor", "audit", "show", "item"]) == (2, "show")


def test_destructive_standalone_only_commands_are_not_routable() -> None:
    assert compat._command_index(["restore", "--input", "backup.json"]) is None
    assert compat._command_index(["audit", "verify"]) == (1, "verify")


def test_missing_db_is_pinned_to_benchbox_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    assert compat.main(["show", "item"]) == 0
    assert calls[0][:2] == ["--db", str(tmp_path / ".todo-db" / "todo.sqlite")]


def test_missing_binary_fails_cleanly(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_COMMAND", "definitely-not-a-real-todo-db-command")
    assert compat.main(["show", "item"]) == 2
    assert "standalone todo-db command not found" in capsys.readouterr().err


def test_delegate_rejects_unversioned_or_mismatched_binary(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BENCHBOX_TODO_DB_COMMAND", "todo-db")
    monkeypatch.setenv("BENCHBOX_TODO_DB_EXPECTED_VERSION", "1.2.3")
    monkeypatch.setattr(
        compat.subprocess,
        "run",
        lambda *args, **kwargs: CompletedProcess(args[0], 0, stdout="todo-db 9.9.9\n", stderr=""),
    )
    with pytest.raises(RuntimeError, match="version mismatch"):
        compat._delegate(["show", "item"], command="show", cwd=tmp_path)


def test_broken_pipe_is_a_clean_exit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setattr(compat, "_delegate", lambda *args, **kwargs: CompletedProcess([], 0, stdout="ok", stderr=""))
    monkeypatch.setattr(compat.sys.stdout, "write", lambda value: (_ for _ in ()).throw(BrokenPipeError()))
    assert compat.main(["show", "item"]) == 0


def test_no_command_output_redacts_both_token_names(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setenv("TODO_DB_AUTH_TOKEN", "rw-secret")
    monkeypatch.setenv("TODO_DB_RO_AUTH_TOKEN", "ro-secret")
    monkeypatch.setattr(compat, "_repo_root", lambda: tmp_path)

    def fake_run(command, *, cwd, env, capture_output, text, check):
        if command[-1] == "--version":
            return CompletedProcess(command, 0, stdout="todo-db 1.0.0\n", stderr="")
        return CompletedProcess(command, 2, stdout="rw-secret ro-secret\n", stderr="rw-secret ro-secret\n")

    monkeypatch.setattr(compat.subprocess, "run", fake_run)
    assert compat.main(["--help"]) == 2
    captured = capsys.readouterr()
    assert "rw-secret" not in captured.out + captured.err
    assert "ro-secret" not in captured.out + captured.err


def test_export_writes_lossless_envelope_and_legacy_views(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    envelope = _envelope()

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        output = Path(argv[argv.index("--output") + 1])
        output.write_text(json.dumps(envelope), encoding="utf-8")
        return CompletedProcess(argv, 0, stdout="export complete\n", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    output_dir = tmp_path / "snapshot"

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "export", "--out", str(output_dir)]) == 0

    lossless = json.loads((output_dir / "todo-db.json").read_text(encoding="utf-8"))
    assert lossless["metadata"] == envelope["metadata"]
    assert lossless["events"] == envelope["events"]
    item = json.loads((output_dir / "items.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert item["work"][0]["wid"] == "w0"
    assert "sample-item" in (output_dir / "index.md").read_text(encoding="utf-8")


def test_export_views_are_byte_identical_to_legacy_format(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope["tables"]["items"][0]["title"] = "Café | table"
    compat._write_legacy_export(tmp_path, envelope)
    item = compat._item_rows(envelope)[0]
    assert (tmp_path / "items.jsonl").read_text(encoding="utf-8") == json.dumps(item, sort_keys=True) + "\n"
    assert "| sample-item | planning | high | benchbox | Café | table |" in (tmp_path / "index.md").read_text(
        encoding="utf-8"
    )


def test_yaml_import_defaults_are_explicit_benchbox_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout="imported\n", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "import-yaml"]) == 0
    argv = calls[0]
    assert argv[argv.index("--todo-dir") + 1] == str(tmp_path / "_project" / "TODO")
    assert argv[argv.index("--done-dir") + 1] == str(tmp_path / "_project" / "DONE")


def test_legacy_entrypoint_only_routes_when_explicitly_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    path = Path(__file__).resolve().parents[3] / "_project" / "scripts" / "todo_db.py"
    spec = importlib.util.spec_from_file_location("benchbox_todo_db_entrypoint_test", path)
    assert spec is not None and spec.loader is not None
    entrypoint = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entrypoint)
    calls: list[list[str] | None] = []

    monkeypatch.setattr(compat, "main", lambda argv=None: calls.append(argv) or 17)
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")

    assert entrypoint.main(["--db", str(tmp_path / "todo.sqlite"), "stats"]) == 17
    assert calls == [["--db", str(tmp_path / "todo.sqlite"), "stats"]]
