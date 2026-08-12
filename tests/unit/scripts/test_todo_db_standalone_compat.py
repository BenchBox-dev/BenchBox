"""Contract tests for the opt-in BenchBox to standalone CLI adapter."""

from __future__ import annotations

import importlib.util
import json
import os
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
    target = tmp_path / "todo.sqlite"
    target.touch()
    assert compat.main(["--db", str(target), command]) == 0
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
    assert compat._command_index(["audit", "verify"]) == (0, "audit")


def test_missing_db_is_pinned_to_benchbox_database(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    assert compat.main(["show", "item"]) == 0
    assert calls[0][:2] == ["--db", str(tmp_path / ".todo-db" / "todo.sqlite")]


@pytest.mark.parametrize(
    ("variable", "value"),
    [("TODO_DB_PATH", "/tmp/pinned.sqlite"), ("TODO_DB_URL", "libsql://tracker.example")],
)
def test_database_environment_is_left_for_standalone_cli(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, variable: str, value: str
) -> None:
    calls: list[list[str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv(variable, value)

    assert compat.main(["show", "item"]) == 0
    assert "--db" not in calls[0]


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

    lossless_dir = tmp_path / "lossless"

    assert (
        compat.main(
            [
                "--db",
                str(tmp_path / "todo.sqlite"),
                "export",
                "--out",
                str(output_dir),
                "--lossless-out",
                str(lossless_dir),
            ]
        )
        == 0
    )

    # The lossless envelope is the recovery artifact -- complete, and OUTSIDE the
    # committed snapshot directory.
    lossless = json.loads((lossless_dir / "todo-db.json").read_text(encoding="utf-8"))
    assert lossless == envelope
    assert not (output_dir / "todo-db.json").exists()
    item = json.loads((output_dir / "items.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert item["work"][0]["wid"] == "w0"
    assert "sample-item" in (output_dir / "index.md").read_text(encoding="utf-8")
    # events.jsonl comes from THIS envelope (one read snapshot), not a stale
    # leftover from a separate main-path export.
    events = [json.loads(line) for line in (output_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert events == envelope["events"]


def test_export_lossless_envelope_defaults_outside_the_committed_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Without --lossless-out the envelope must STILL not land in --out: the
    # workflow's `git add "${EXPORT_DIR}"` would otherwise commit it.
    envelope = _envelope()

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps(envelope), encoding="utf-8")
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    output_dir = tmp_path / "snapshot"

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "export", "--out", str(output_dir)]) == 0

    assert not (output_dir / "todo-db.json").exists()
    assert (output_dir.parent / f"{output_dir.name}-lossless" / "todo-db.json").exists()


def test_export_rerun_removes_legacy_in_tree_envelope(tmp_path: Path) -> None:
    output_dir = tmp_path / "snapshot"
    lossless_dir = tmp_path / "lossless"
    envelope = _envelope()
    compat._write_legacy_export(output_dir, envelope, lossless_dir)

    legacy_envelope = output_dir / "todo-db.json"
    legacy_envelope.write_text('{"legacy": true}\n', encoding="utf-8")
    updated = {**envelope, "metadata": {"rerun": True}}

    compat._write_legacy_export(output_dir, updated, lossless_dir)

    assert not legacy_envelope.exists()
    assert json.loads((lossless_dir / "todo-db.json").read_text(encoding="utf-8")) == updated


def test_export_never_commits_findings_domain_prose(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The guard: findings review prose must never reach the committed snapshot.

    Mirrors the phase-2 allowlist pin for the standalone path -- a findings table
    in the envelope may travel in the lossless recovery artifact, never in --out.
    """
    envelope = _envelope()
    prose = "SENTINEL-findings-review-prose"
    envelope["tables"]["findings"] = [
        {
            "id": "2026-01-02-030405-a-class",
            "title": f"{prose}-title",
            "finding_text": f"{prose}-finding",
            "why_matters": f"{prose}-why",
            "disposition": "open",
        }
    ]
    envelope["tables"]["finding_evidence"] = [{"finding_id": "2026-01-02-030405-a-class", "path": "x.py"}]

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        Path(argv[argv.index("--output") + 1]).write_text(json.dumps(envelope), encoding="utf-8")
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    output_dir = tmp_path / "snapshot"
    lossless_dir = tmp_path / "lossless"

    assert (
        compat.main(
            [
                "--db",
                str(tmp_path / "todo.sqlite"),
                "export",
                "--out",
                str(output_dir),
                "--lossless-out",
                str(lossless_dir),
            ]
        )
        == 0
    )

    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            assert prose not in path.read_text(encoding="utf-8"), f"findings prose leaked into {path.name}"
            assert "finding_evidence" not in path.read_text(encoding="utf-8")
    # ...but the recovery artifact is still lossless.
    assert prose in (lossless_dir / "todo-db.json").read_text(encoding="utf-8")


def test_export_views_are_byte_identical_to_legacy_format(tmp_path: Path) -> None:
    envelope = _envelope()
    envelope["tables"]["items"][0]["title"] = "Café | table"
    compat._write_legacy_export(tmp_path / "out", envelope, tmp_path / "lossless")
    tmp_path = tmp_path / "out"
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


@pytest.mark.parametrize(
    "command",
    [
        "update",
        "finding",
        "sweep-stale",
        "migrate",
        "doctor",
    ],
)
def test_standalone_030_verbs_are_routable_through_shim(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    """w3: every 0.3.0 verb routes through shim without forking DB."""
    calls: list[str] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    # Provide explicit DB so shim does not refuse fork-DB path
    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), command]) == 0
    # finding/doctor are not in COMMANDS — they route via command="" delegation path
    if command in compat.COMMANDS:
        assert calls == [command]
    else:
        assert calls == [""]


def test_scope_update_translates_to_package_update(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[tuple[list[str], str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append((argv, command))
        return CompletedProcess(argv, 0, stdout="updated\n", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "scope-update", "item", "--reason", "boundary"]) == 0
    assert calls[-1][1] == "update"
    assert "scope-update" not in calls[-1][0]
    assert "update" in calls[-1][0]


@pytest.mark.parametrize("command", sorted(compat.EXTENSION_COMMANDS))
def test_missing_package_commands_use_extension_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, command: str
) -> None:
    calls: list[list[str]] = []

    def fake_extension(argv: list[str], *, cwd: Path) -> CompletedProcess[str]:
        calls.append(argv)
        return CompletedProcess(argv, 0, stdout=f"{command} ok\n", stderr="")

    monkeypatch.setattr(compat, "_delegate_extension", fake_extension)
    monkeypatch.setattr(
        compat,
        "_delegate",
        lambda *args, **kwargs: pytest.fail("package CLI must not receive a command it does not expose"),
    )
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), command]) == 0
    assert len(calls) == 1
    assert calls[0][:2] == ["--db", str(tmp_path / "todo.sqlite")]
    assert command in calls[0]


def test_explicit_missing_local_read_target_is_initialized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(argv, 0, stdout="{}\n" if command == "stats" else "", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setattr(
        compat,
        "_delegate_extension",
        lambda argv, *, cwd: CompletedProcess(argv, 0, stdout='{"events": {}, "stale": false}\n', stderr=""),
    )
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    target = tmp_path / "missing.sqlite"

    assert compat.main(["--db", str(target), "stats"]) == 0
    assert calls == ["init", "stats"]


@pytest.mark.parametrize(
    ("argv", "stdout"), [(["stats", "--help"], "stats help\n"), (["--version", "stats"], "todo-db 0.3.1\n")]
)
def test_stats_metadata_skips_activity_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    stdout: str,
) -> None:
    monkeypatch.setattr(
        compat,
        "_delegate",
        lambda argv, *, command, cwd, capture=True: CompletedProcess(argv, 0, stdout=stdout, stderr=""),
    )
    monkeypatch.setattr(
        compat,
        "_delegate_extension",
        lambda *args, **kwargs: pytest.fail("metadata-only stats must not open the database"),
    )
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")

    assert compat.main(argv) == 0
    assert capsys.readouterr().out == stdout


def test_existing_local_init_checks_freeze_before_package_command(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[str] = []
    target = tmp_path / "todo.sqlite"
    target.touch()

    def fake_extension(argv: list[str], *, cwd: Path) -> CompletedProcess[str]:
        calls.append("freeze-guard")
        return CompletedProcess(argv, 0, stdout="", stderr="")

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate_extension", fake_extension)
    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")

    assert compat.main(["--db", str(target), "init"]) == 0
    assert calls == ["freeze-guard", "init"]


def test_renew_stops_when_freeze_guard_rejects(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[str] = []
    target = tmp_path / "todo.sqlite"
    target.touch()

    def fake_extension(argv: list[str], *, cwd: Path) -> CompletedProcess[str]:
        calls.append(argv[-1])
        return CompletedProcess(argv, 2, stdout="", stderr="frozen\n")

    monkeypatch.setattr(compat, "_delegate_extension", fake_extension)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")

    assert compat.main(["--db", str(target), "renew", "item"]) == 2
    assert calls == ["freeze-guard"]


def test_audit_verify_is_read_only_during_freeze() -> None:
    assert not compat._command_mutates_tracker(["audit", "verify"], "audit")


@pytest.mark.parametrize(
    ("command", "stdout", "expected_stdout", "expected_banner"),
    [
        (
            "ready",
            "item high worktree\n2 open finding(s), 3 unsynced draft(s) -- todo-db finding candidates\n",
            "item high worktree\n",
            "→ 2 open finding(s), 3 unsynced draft(s) awaiting triage — see: "
            "todo finding list --disposition open; todo finding candidates\n",
        ),
        (
            "stats",
            '{"findings_by_disposition": {"open": 2}, "unsynced_drafts": 3}\n',
            '{"findings_by_disposition": {"open": 2}, "unsynced_drafts": 3}\n',
            "→ 2 open finding(s), 3 unsynced draft(s) awaiting triage — see: "
            "todo finding list --disposition open; todo finding candidates\n",
        ),
    ],
)
def test_ready_and_stats_findings_banners_are_stderr_only(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    command: str,
    stdout: str,
    expected_stdout: str,
    expected_banner: str,
) -> None:
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    monkeypatch.setattr(
        compat,
        "_delegate",
        lambda argv, *, command, cwd, capture=True: CompletedProcess(argv, 0, stdout=stdout, stderr=""),
    )
    monkeypatch.setattr(
        compat,
        "_delegate_extension",
        lambda argv, *, cwd: CompletedProcess(
            argv,
            0,
            stdout=(
                '{"events": {"count": 1, "last_seq": 1, "latest": "2026-08-11T00:00:00Z", '
                '"findings": {"count": 2, "last_seq": 2, "latest": "2026-08-11T00:00:01Z"}}, '
                '"stale": false}\n'
            ),
            stderr="",
        ),
    )

    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), command]) == 0
    captured = capsys.readouterr()
    if command == "stats":
        stats = json.loads(captured.out)
        assert stats["events"] == {
            "count": 1,
            "last_seq": 1,
            "latest": "2026-08-11T00:00:00Z",
            "findings": {"count": 2, "last_seq": 2, "latest": "2026-08-11T00:00:01Z"},
        }
        assert stats["stale"] is False
    else:
        assert captured.out == expected_stdout
    assert captured.err == expected_banner


@pytest.mark.parametrize("subcommand", ["create", "candidates"])
def test_standalone_offline_finding_commands_do_not_require_db(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, subcommand: str
) -> None:
    """Offline finding capture/listing must delegate without inventing a DB."""
    calls: list[tuple[list[str], str]] = []

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        calls.append((argv, command))
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)

    assert compat.main(["finding", subcommand]) == 0
    assert calls[0][1] == "finding"
    assert "--db" not in calls[0][0]
    assert not (tmp_path / ".todo-db" / "todo.sqlite").exists()


def test_standalone_finding_sync_still_requires_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Database-backed finding sync must remain fail-closed without a backend."""
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    assert compat.main(["finding", "sync"]) == 2
    assert not (tmp_path / ".todo-db" / "todo.sqlite").exists()

    # honors config.json — with config present, refusal must not trigger
    (tmp_path / ".todo-db").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".todo-db" / "config.json").write_text('{"url": "libsql://example.turso.io"}', encoding="utf-8")

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        return CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    monkeypatch.setattr(
        compat,
        "_delegate_extension",
        lambda argv, *, cwd: CompletedProcess(argv, 0, stdout="", stderr=""),
    )
    assert compat.main(["finding", "sync"]) == 0


def test_env_passthrough_includes_finding_drafts_and_ro_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """w4: TODO_DB_FINDING_DRAFTS_DIR and TODO_DB_RO_AUTH_TOKEN are forwarded via _delegate env."""
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    monkeypatch.setenv("TODO_DB_FINDING_DRAFTS_DIR", "/tmp/drafts")
    monkeypatch.setenv("TODO_DB_RO_AUTH_TOKEN", "ro-secret-xyz")

    captured: dict[str, str] = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, check):
        captured.update(
            {
                k: v
                for k, v in env.items()
                if k in ("TODO_DB_FINDING_DRAFTS_DIR", "TODO_DB_RO_AUTH_TOKEN", "TODO_DB_AUTH_TOKEN")
            }
        )
        if "--version" in cmd:
            return CompletedProcess(cmd, 0, stdout="todo-db 1.0.0\n", stderr="")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(compat.subprocess, "run", fake_run)
    # Use explicit DB so refusal path not taken; command will delegate with env passthrough
    assert compat.main(["--db", str(tmp_path / "todo.sqlite"), "finding", "sync"]) == 0
    assert captured.get("TODO_DB_FINDING_DRAFTS_DIR") == "/tmp/drafts"
    assert captured.get("TODO_DB_RO_AUTH_TOKEN") == "ro-secret-xyz"


def test_finding_sync_defaults_to_benchbox_drafts_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Standalone finding sync must read the same drafts directory as BenchBox."""
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    monkeypatch.setenv("TODO_DB_COMMAND", "todo-db")
    monkeypatch.setenv("TODO_DB_PATH", str(tmp_path / "todo.sqlite"))
    monkeypatch.delenv("TODO_DB_FINDING_DRAFTS_DIR", raising=False)

    captured: dict[str, str] = {}

    def fake_run(cmd, *, cwd, env, capture_output, text, check):
        captured.update({"TODO_DB_FINDING_DRAFTS_DIR": env["TODO_DB_FINDING_DRAFTS_DIR"]})
        if "--version" in cmd:
            return CompletedProcess(cmd, 0, stdout="todo-db 1.0.0\n", stderr="")
        return CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(compat.subprocess, "run", fake_run)

    assert compat.main(["finding", "sync"]) == 0
    assert captured["TODO_DB_FINDING_DRAFTS_DIR"] == str(Path.home() / ".benchbox" / "finding-drafts")
    assert "TODO_DB_FINDING_DRAFTS_DIR" not in os.environ


def test_standalone_doctor_without_db_diagnoses_not_refuse(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """w5: standalone doctor without DB diagnoses, not exit-2 refusal; legacy doctor works."""
    monkeypatch.setenv("BENCHBOX_REPO_ROOT", str(tmp_path))
    monkeypatch.setenv("BENCHBOX_TODO_DB_STANDALONE", "1")
    monkeypatch.delenv("TODO_DB_PATH", raising=False)
    monkeypatch.delenv("TODO_DB_URL", raising=False)
    # Remove config.json if present
    config = tmp_path / ".todo-db" / "config.json"
    if config.exists():
        config.unlink()

    def fake_delegate(argv: list[str], *, command: str, cwd: Path, capture: bool = True) -> CompletedProcess[str]:
        assert command == "doctor"
        return CompletedProcess(argv, 0, stdout="doctor OK no-backend-configured\n", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate)
    assert compat.main(["doctor"]) == 0

    # legacy (no standalone) should still route doctor via --db pin, not refuse
    monkeypatch.delenv("BENCHBOX_TODO_DB_STANDALONE", raising=False)

    def fake_delegate_legacy(
        argv: list[str], *, command: str, cwd: Path, capture: bool = True
    ) -> CompletedProcess[str]:
        assert "--db" in argv
        return CompletedProcess(argv, 0, stdout="legacy doctor\n", stderr="")

    monkeypatch.setattr(compat, "_delegate", fake_delegate_legacy)
    assert compat.main(["doctor"]) == 0
