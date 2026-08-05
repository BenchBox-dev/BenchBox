"""Tests for the project wrapper's audited ``update`` verb.

Ported from the standalone todo-db update contract: one chained audit event
with from/to diffs; id/state/claim identity immutable; terminal edits and
verification drops require ``--reason``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "todo_db_update_under_test"
    path = REPO_ROOT / "_project" / "scripts" / "todo_db.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


todo_db = _load_script()


@pytest.fixture()
def conn(tmp_path):
    connection = todo_db.connect(tmp_path / "todo.sqlite")
    yield connection
    connection.close()


def _mk(conn, item_id="update-item", **overrides):
    kwargs = {
        "item_id": item_id,
        "title": "Original title",
        "worktree": "todo-db",
        "priority": "medium",
        "description": "The original description before any update.",
        "work": [{"id": "w0", "summary": "Original pending unit"}],
        "verifications": [{"description": "Tests", "command": "printf PASS", "expected": "PASS"}],
    }
    kwargs.update(overrides)
    todo_db.create_item(conn, "tester", **kwargs)
    return item_id


def _last_update_event(conn, item_id: str) -> dict:
    row = conn.execute(
        "SELECT action, detail FROM events WHERE item_id = ? AND action = 'update' ORDER BY seq DESC LIMIT 1",
        (item_id,),
    ).fetchone()
    assert row is not None
    return {"action": row["action"], "detail": json.loads(row["detail"])}


class TestMetadataUpdate:
    def test_metadata_updates_carry_exact_from_to_diffs(self, conn):
        _mk(conn)
        detail = todo_db.update_item(
            conn,
            "tester",
            "update-item",
            title="Corrected title",
            description="The corrected description after review.",
            priority="high",
            worktree="other-tree",
        )
        item = todo_db.get_item(conn, "update-item")
        assert item["title"] == "Corrected title"
        assert item["description"] == "The corrected description after review."
        assert item["priority"] == "high"
        assert item["worktree"] == "other-tree"
        assert item["state"] == "planning"
        event = _last_update_event(conn, "update-item")
        assert event["action"] == "update"
        assert (
            event["detail"]["changes"]
            == detail["changes"]
            == {
                "title": {"from": "Original title", "to": "Corrected title"},
                "description": {
                    "from": "The original description before any update.",
                    "to": "The corrected description after review.",
                },
                "priority": {"from": "medium", "to": "high"},
                "worktree": {"from": "todo-db", "to": "other-tree"},
            }
        )
        assert "reason" not in event["detail"]

    def test_update_validates_fields(self, conn):
        _mk(conn)
        with pytest.raises(todo_db.TodoError, match="title must be between"):
            todo_db.update_item(conn, "tester", "update-item", title="tiny")
        with pytest.raises(todo_db.TodoError, match="invalid priority"):
            todo_db.update_item(conn, "tester", "update-item", priority="urgent")
        with pytest.raises(todo_db.TodoError, match="worktree must not be empty"):
            todo_db.update_item(conn, "tester", "update-item", worktree="   ")
        with pytest.raises(todo_db.TodoError, match="description must be at least"):
            todo_db.update_item(conn, "tester", "update-item", description="short")
        assert todo_db.get_item(conn, "update-item")["title"] == "Original title"

    def test_terminal_item_edits_require_reason(self, conn):
        _mk(conn)
        todo_db.claim_item(conn, "tester", "update-item")
        todo_db.done_unit(conn, "tester", "update-item", "w0", "completion evidence")
        todo_db.complete_item(conn, "tester", "update-item", None)
        with pytest.raises(todo_db.TodoError, match="requires --reason"):
            todo_db.update_item(conn, "tester", "update-item", title="Post-completion title")
        todo_db.update_item(
            conn,
            "tester",
            "update-item",
            title="Post-completion title",
            reason="typo found in review",
        )
        event = _last_update_event(conn, "update-item")
        assert event["detail"]["reason"] == "typo found in review"
        item = todo_db.get_item(conn, "update-item")
        assert item["title"] == "Post-completion title"
        assert item["state"] == "done"


class TestWorkAndVerifyAmendments:
    def test_edit_work_only_pending(self, conn):
        _mk(
            conn,
            work=[
                {"id": "w0", "summary": "Original pending unit"},
                {"id": "w1", "summary": "Unit to finish"},
            ],
        )
        detail = todo_db.update_item(conn, "tester", "update-item", edit_work={"w0": "Corrected pending unit"})
        assert detail["work_edited"] == {"w0": {"from": "Original pending unit", "to": "Corrected pending unit"}}
        assert todo_db.get_item(conn, "update-item")["work"][0]["summary"] == "Corrected pending unit"
        todo_db.claim_item(conn, "tester", "update-item")
        todo_db.done_unit(conn, "tester", "update-item", "w1", "unit evidence")
        with pytest.raises(todo_db.TodoError, match="only pending units"):
            todo_db.update_item(conn, "tester", "update-item", edit_work={"w1": "Rewriting a done unit"})
        assert todo_db.get_item(conn, "update-item")["work"][1]["summary"] == "Unit to finish"

    def test_add_work_extends_breakdown(self, conn):
        _mk(conn)
        detail = todo_db.update_item(
            conn,
            "tester",
            "update-item",
            add_work=[{"id": "w1", "summary": "Mid-batch discovered unit", "needs": ["w0"]}],
        )
        assert detail["work_added"] == [{"id": "w1", "summary": "Mid-batch discovered unit", "needs": ["w0"]}]
        unit = todo_db.get_item(conn, "update-item")["work"][1]
        assert (unit["wid"], unit["status"], unit["needs"]) == ("w1", "pending", ["w0"])
        with pytest.raises(todo_db.TodoError, match="duplicate work-unit id"):
            todo_db.update_item(conn, "tester", "update-item", add_work=[{"id": "w0", "summary": "Colliding unit"}])

    def test_verification_amendments(self, conn):
        _mk(conn)
        detail = todo_db.update_item(
            conn,
            "tester",
            "update-item",
            add_verify=[{"description": "Lint", "command": "uv run ruff check ."}],
        )
        assert detail["verify_added"] == [{"seq": 2, "name": "Lint", "command": "uv run ruff check ."}]
        with pytest.raises(todo_db.TodoError, match="--reason is required"):
            todo_db.update_item(conn, "tester", "update-item", drop_verify=[1])
        detail = todo_db.update_item(
            conn,
            "tester",
            "update-item",
            drop_verify=[1],
            reason="superseded by the lint step",
        )
        assert detail["verify_dropped"] == [{"seq": 1, "name": "Tests", "command": "printf PASS"}]
        assert detail["reason"] == "superseded by the lint step"
        assert [row["seq"] for row in todo_db.get_item(conn, "update-item")["verifications"]] == [2]
        with pytest.raises(todo_db.TodoError, match="no verification seq=9"):
            todo_db.update_item(conn, "tester", "update-item", drop_verify=[9], reason="no such row")

    def test_no_change_flags_and_no_op_edits_rejected(self, conn):
        _mk(conn)
        before = conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"]
        with pytest.raises(todo_db.TodoError, match="at least one change flag"):
            todo_db.update_item(conn, "tester", "update-item")
        with pytest.raises(todo_db.TodoError, match="at least one change flag"):
            todo_db.update_item(conn, "tester", "update-item", reason="a reason is not a change")
        with pytest.raises(todo_db.TodoError, match="nothing to update"):
            todo_db.update_item(conn, "tester", "update-item", title="Original title")
        with pytest.raises(todo_db.TodoError, match="nothing to update"):
            todo_db.update_item(conn, "tester", "update-item", edit_work={"w0": "Original pending unit"})
        assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == before


class TestCliSurface:
    def test_update_help_and_main_path(self, conn, tmp_path, capsys, monkeypatch):
        db = tmp_path / "cli.sqlite"
        assert todo_db.main(["--db", str(db), "init"]) == 0
        assert (
            todo_db.main(
                [
                    "--db",
                    str(db),
                    "create",
                    "cli-item",
                    "--title",
                    "CLI item",
                    "--worktree",
                    "todo-db",
                    "--priority",
                    "medium",
                    "--description",
                    "A CLI item exercising the update verb.",
                    "--work",
                    "w0:Do the work",
                ]
            )
            == 0
        )
        capsys.readouterr()
        assert todo_db.main(["--db", str(db), "update", "cli-item"]) == 2
        assert "at least one change flag" in capsys.readouterr().err
        assert todo_db.main(["--db", str(db), "update", "cli-item", "--title", "CLI item"]) == 2
        assert "nothing to update" in capsys.readouterr().err
        assert (
            todo_db.main(
                [
                    "--db",
                    str(db),
                    "update",
                    "cli-item",
                    "--title",
                    "CLI item corrected",
                    "--add-verify",
                    "Smoke::printf PASS",
                ]
            )
            == 0
        )
        assert "updated cli-item (changes, verify_added)" in capsys.readouterr().out
        with pytest.raises(SystemExit) as help_exit:
            todo_db.main(["--db", str(db), "update", "--help"])
        assert help_exit.value.code == 0
        help_out = capsys.readouterr().out
        assert "never mutates lifecycle" in help_out
        assert "--title" in help_out
        assert "--add-work" in help_out
