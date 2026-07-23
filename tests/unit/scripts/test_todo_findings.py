"""Tests for the findings domain (phase 3): schema v3, the ``todo finding`` CLI,
sync, promote, and -- critically -- the non-claimability guarantee.

Findings live in separate tables (``findings``, ``finding_evidence``,
``finding_links``, ``finding_events``) and must be STRUCTURALLY invisible to the
items-domain surfaces: ``ready``, ``claim``, ``lint --all``, ``stats`` open
counts, and ``deps``. That invisibility is by construction (those queries read
only ``items`` and its children), pinned here so a future refactor cannot
silently make a finding claimable or inflate the open-item count.

Marked ``medium`` (not ``fast``): materialises scratch databases and matches the
sibling ``test_todo_db*`` suites, so it stays out of the fast-lane budget.
"""

from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = REPO_ROOT / "_project" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

todo_findings = importlib.import_module("todo_findings")
# Bind the EXACT todo_db instance todo_findings raises TodoError from. Sibling
# test files load todo_db under synthetic names (spec_from_file_location), so a
# plain import_module("todo_db") can resolve to a different instance under broad
# collection -- then `pytest.raises(todo_db.TodoError)` would miss the class the
# findings code actually raises. At runtime there is only one instance.
todo_db = todo_findings.todo_db


@pytest.fixture()
def conn(tmp_path):
    connection = todo_db.connect(tmp_path / "todo.sqlite")
    yield connection
    connection.close()


def _mk_finding(conn, finding_id="2026-01-02-030405-a-sample-class", **overrides):
    fields = {
        "id": finding_id,
        "date": "2026-01-02",
        "finding_kind": "framework-gap",
        "review_context": "ultrareview X / feat/thing",
        "observed_sha": None,
        "title": "A sample blind-spot class",
        "finding_text": "the review never checks axis Y",
        "why_matters": "axis Y is a whole dimension of correctness",
        "next_steps": "- [ ] add a gate for axis Y",
        "disposition": "open",
        "disposition_reason": None,
        "evidence": [],
    }
    fields.update(overrides)
    with todo_db._write_txn(conn):
        todo_findings.insert_finding(conn, "tester", fields)
    return finding_id


def _mk_item(conn, item_id="a-real-item", **overrides):
    kwargs = {
        "item_id": item_id,
        "title": "A real tracked item",
        "worktree": "spike",
        "priority": "medium",
        "description": "A description longer than ten characters.",
    }
    kwargs.update(overrides)
    todo_db.create_item(conn, "tester", **kwargs)
    return item_id


def _draft(path: Path, stem: str, *, status="open", finding="the review never checks axis Y", title="A sample class"):
    path.parent.mkdir(parents=True, exist_ok=True)
    (path.parent / f"{stem}.md").write_text(
        "---\n"
        f"id: {stem}\n"
        "date: 2026-01-02\n"
        f"status: {status}\n"
        "finding_kind: framework-gap\n"
        'review_context: "ultrareview X"\n'
        "---\n\n"
        f"# {title}\n\n"
        f"## Finding\n{finding}\n\n"
        "## Why this matters\naxis Y is a whole dimension\n\n"
        "## Suggested next steps\n- [ ] add a gate for axis Y\n",
        encoding="utf-8",
    )
    return path.parent / f"{stem}.md"


# ---------------------------------------------------------------------------
# Schema + CHECK constraints (w1)


class TestFindingsSchema:
    def test_v3_tables_and_version(self, conn):
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"findings", "finding_evidence", "finding_links", "finding_events"} <= tables
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"] == "3"

    def test_disposition_check_rejects_unknown(self, conn):
        with pytest.raises(todo_db.sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO findings (id, date, finding_kind, review_context, title, finding_text,"
                " why_matters, next_steps, disposition, created_at)"
                " VALUES ('2026-01-01-000000-x', '2026-01-01', 'other', 'r', 't', 'f', 'w', 'n', 'bogus', 'now')"
            )

    def test_reason_required_check_for_dismissed(self, conn):
        # dismissed/actionable without a reason violates the CHECK.
        with pytest.raises(todo_db.sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO findings (id, date, finding_kind, review_context, title, finding_text,"
                " why_matters, next_steps, disposition, created_at)"
                " VALUES ('2026-01-01-000000-x', '2026-01-01', 'other', 'r', 't', 'f', 'w', 'n', 'dismissed', 'now')"
            )


# ---------------------------------------------------------------------------
# Non-claimability pinning suite (w7): findings invisible to items surfaces


class TestFindingsNonClaimable:
    def test_findings_absent_from_ready(self, conn):
        _mk_item(conn, item_id="ready-item")
        _mk_finding(conn)
        ready_ids = {item["id"] for item in todo_db.ready_items(conn, "tester")}
        assert "ready-item" in ready_ids
        assert not any("class" in rid for rid in ready_ids)
        assert "2026-01-02-030405-a-sample-class" not in ready_ids

    def test_finding_id_is_not_claimable_as_an_item(self, conn):
        fid = _mk_finding(conn)
        # A finding id is not an item id; claim must refuse it as a missing item.
        with pytest.raises(todo_db.TodoError):
            todo_db.claim_item(conn, "tester", fid)

    def test_lint_all_ignores_findings(self, conn, capsys):
        _mk_item(conn, item_id="lint-item")
        fid = _mk_finding(conn)
        # Drive the REAL `lint --all` code path: it iterates planning/active
        # ITEMS only, so the finding is never a lint target (across 1 item, not 2).
        todo_db._cmd_lint(conn, "tester", SimpleNamespace(all=True, id=None))
        out = capsys.readouterr().out
        assert fid not in out
        assert "across 1 item(s)" in out

    def test_findings_absent_from_deps(self, conn):
        # `todo deps <finding-id>` must not resolve a finding as an item (N2).
        fid = _mk_finding(conn)
        with pytest.raises(todo_db.TodoError):
            todo_db._cmd_deps(conn, "tester", SimpleNamespace(id=fid))

    def test_stats_open_counts_exclude_findings(self, conn):
        _mk_item(conn, item_id="stats-item")
        before = todo_db.stats(conn)
        _mk_finding(conn)
        _mk_finding(conn, finding_id="2026-01-02-030406-another-class")
        after = todo_db.stats(conn)
        # Adding findings must not move any items-domain count.
        assert after == before

    def test_findings_do_not_appear_in_items_table(self, conn):
        _mk_finding(conn)
        item_ids = {row["id"] for row in conn.execute("SELECT id FROM items")}
        assert item_ids == set()

    def test_ready_and_claim_sql_reference_only_items(self):
        # Guard the must-preserve "ready+claim SQL unchanged": neither routine's
        # source may start reading a findings table.
        import inspect

        for func in (todo_db.ready_items, todo_db.claim_item):
            src = inspect.getsource(func)
            for table in ("findings", "finding_evidence", "finding_links", "finding_events"):
                assert table not in src, f"{func.__name__} must not reference {table}"


# ---------------------------------------------------------------------------
# Sync: the authorized landing step (w5)


class TestFindingSync:
    def test_finding_sync_inserts_absent(self, conn, tmp_path):
        drafts = tmp_path / "drafts"
        _draft(drafts / "x.md", "2026-01-02-030405-sync-me-class")
        result = todo_findings.sync_drafts(conn, "tester", drafts)
        assert result["synced"] == ["2026-01-02-030405-sync-me-class"]
        assert todo_findings.get_finding(conn, "2026-01-02-030405-sync-me-class") is not None
        # renamed out of the unsynced glob
        assert (drafts / "2026-01-02-030405-sync-me-class.md.synced").exists()
        assert not (drafts / "2026-01-02-030405-sync-me-class.md").exists()

    def test_finding_sync_is_idempotent(self, conn, tmp_path):
        drafts = tmp_path / "drafts"
        _draft(drafts / "x.md", "2026-01-02-030405-idem-class")
        first = todo_findings.sync_drafts(conn, "tester", drafts)
        assert len(first["synced"]) == 1
        # Re-writing the SAME draft (unsynced again) and re-syncing is a no-op skip.
        _draft(drafts / "x.md", "2026-01-02-030405-idem-class")
        second = todo_findings.sync_drafts(conn, "tester", drafts)
        assert second["synced"] == [] and second["skipped"] == ["2026-01-02-030405-idem-class"]

    def test_finding_sync_conflict_is_loud_never_merged(self, conn, tmp_path):
        drafts = tmp_path / "drafts"
        _draft(drafts / "x.md", "2026-01-02-030405-conflict-class", finding="original text")
        todo_findings.sync_drafts(conn, "tester", drafts)
        # Same id, DIFFERENT content -> loud error, never a silent merge.
        _draft(drafts / "x.md", "2026-01-02-030405-conflict-class", finding="TAMPERED text")
        with pytest.raises(todo_db.TodoError, match="sync conflict"):
            todo_findings.sync_drafts(conn, "tester", drafts)
        # The stored copy is untouched (no merge).
        stored = todo_findings.get_finding(conn, "2026-01-02-030405-conflict-class")
        assert stored["finding_text"] == "original text"

    def test_finding_sync_prunes_old_synced_drafts(self, conn, tmp_path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        old = drafts / "2020-01-01-000000-ancient-class.md.synced"
        old.write_text("stale", encoding="utf-8")
        stale_time = (datetime.now(timezone.utc) - timedelta(days=todo_findings.SYNCED_PRUNE_DAYS + 5)).timestamp()
        import os

        os.utime(old, (stale_time, stale_time))
        result = todo_findings.sync_drafts(conn, "tester", drafts)
        assert result["pruned"] == 1
        assert not old.exists()

    def test_finding_sync_zero_credential_candidate_count(self, tmp_path):
        drafts = tmp_path / "drafts"
        _draft(drafts / "x.md", "2026-01-02-030405-pending-class")
        # A pure local glob -- no DB, no credentials.
        assert todo_findings.count_unsynced_drafts(drafts) == 1


# ---------------------------------------------------------------------------
# Promote: finding -> item, atomic (w6)


class TestFindingPromote:
    def test_finding_promote_creates_item_links_and_flips(self, conn):
        fid = _mk_finding(conn)
        todo_findings.promote_finding(conn, "tester", fid, new_item_id="promoted-item")
        assert conn.execute("SELECT 1 FROM items WHERE id='promoted-item'").fetchone() is not None
        finding = todo_findings.get_finding(conn, fid)
        assert finding["disposition"] == "promoted"
        assert finding["links"] == [
            {
                "kind": "promoted-to",
                "target_item": "promoted-item",
                "target_finding": None,
                "note": "promoted by tester",
            }
        ]

    def test_finding_promote_does_not_leak_prose_into_item_or_events(self, conn):
        # C1: the auto-generated item title/description (which land in the
        # exported items.jsonl, and the create event lands in events.jsonl) must
        # NOT inline the finding's verbatim review prose. Promote with no
        # explicit --title/--description so only the defaults are in play.
        prose = "SENTINEL-review-prose-not-versioned"
        fid = _mk_finding(
            conn,
            finding_id="2026-01-02-030405-leaky-class",
            title=f"{prose}-title",
            finding_text=f"{prose}-finding",
            why_matters=f"{prose}-why",
        )
        todo_findings.promote_finding(conn, "tester", fid, new_item_id="promoted-leaky")
        item = todo_db.get_item(conn, "promoted-leaky")
        assert prose not in item["title"]
        assert prose not in (item["description"] or "")
        events_text = " ".join(
            str(row["detail"]) for row in conn.execute("SELECT detail FROM events WHERE item_id='promoted-leaky'")
        )
        assert prose not in events_text

    def test_finding_promote_rolls_back_on_duplicate_item(self, conn):
        _mk_item(conn, item_id="taken-id")
        fid = _mk_finding(conn)
        # Promoting to an existing item id must fail AND leave no partial state:
        # disposition stays open, no link row, no finding_events promote row.
        with pytest.raises(todo_db.TodoError):
            todo_findings.promote_finding(conn, "tester", fid, new_item_id="taken-id")
        finding = todo_findings.get_finding(conn, fid)
        assert finding["disposition"] == "open"
        assert finding["links"] == []
        assert [e["action"] for e in finding["events"]] == ["sync"]  # only the original insert event

    def test_finding_promote_rejects_terminal(self, conn):
        fid = _mk_finding(conn, disposition="dismissed", disposition_reason="not load-bearing")
        with pytest.raises(todo_db.TodoError, match="terminal"):
            todo_findings.promote_finding(conn, "tester", fid, new_item_id="never-item")


# ---------------------------------------------------------------------------
# Capture: create gate + draft-only (w4)


class TestFindingCreate:
    def _args(self, drafts_dir, **overrides):
        base = {
            "finding_command": "create",
            "title": "A sample class",
            "finding_kind": "framework-gap",
            "review_context": "ultrareview X",
            "gate": "class-not-instance",
            "fixed_by": None,
            "slug": None,
            "finding": "the review never checks axis Y",
            "why": "axis Y matters",
            "next_steps": "- [ ] add a gate",
            "observed_sha": None,
            "drafts_dir": str(drafts_dir),
        }
        base.update(overrides)
        return SimpleNamespace(**base)

    def test_finding_create_requires_gate_attestation(self, tmp_path):
        with pytest.raises(todo_db.TodoError, match="class-not-instance"):
            todo_findings.create_draft(self._args(tmp_path / "d", gate=None))

    def test_finding_create_bug_class_requires_fixed_by(self, tmp_path):
        with pytest.raises(todo_db.TodoError, match="fixed-by"):
            todo_findings.create_draft(self._args(tmp_path / "d", finding_kind="bug-class"))

    def test_finding_create_writes_valid_draft_only(self, tmp_path):
        path = todo_findings.create_draft(self._args(tmp_path / "d"))
        assert path.exists()
        # The generated draft passes the phase-1 validator by construction.
        import validate_blind_spot as vbs

        assert vbs.validate_file(path) == []

    def test_finding_create_collision_suffix(self, tmp_path):
        a = todo_findings.create_draft(self._args(tmp_path / "d", slug="dup-class"))
        b = todo_findings.create_draft(self._args(tmp_path / "d", slug="dup-class"))
        assert a != b  # second write gets a -2 suffix, never overwrites


# ---------------------------------------------------------------------------
# Disposition transitions, triage, link (w3)


class TestFindingDisposition:
    def test_dismiss_requires_reason(self, conn):
        fid = _mk_finding(conn)
        with pytest.raises(SystemExit):
            todo_db.main(["--db", "x", "finding", "dismiss", fid])  # argparse: --reason required

    def test_dismiss_sets_disposition(self, conn):
        fid = _mk_finding(conn)
        with todo_db._write_txn(conn):
            todo_findings._set_disposition(conn, "tester", fid, "dismissed", "not load-bearing")
        assert todo_findings.get_finding(conn, fid)["disposition"] == "dismissed"

    def test_illegal_transition_rejected(self, conn):
        fid = _mk_finding(conn, disposition="actioned")
        with pytest.raises(todo_db.TodoError, match="terminal"), todo_db._write_txn(conn):
            todo_findings._set_disposition(conn, "tester", fid, "open", None)

    def test_triage_sets_judgment_fields(self, conn):
        fid = _mk_finding(conn)
        args = SimpleNamespace(
            finding_command="triage",
            id=fid,
            urgency="high",
            breadth="wide",
            confidence="med",
            reconsider_after=None,
            disposition=None,
            reason=None,
        )
        todo_findings._cmd_triage(conn, "tester", args)
        finding = todo_findings.get_finding(conn, fid)
        assert (finding["urgency"], finding["breadth"], finding["confidence"]) == ("high", "wide", "med")

    def test_link_requires_exactly_one_target(self, conn):
        fid = _mk_finding(conn)
        with pytest.raises(todo_db.TodoError, match="exactly one"):
            todo_findings.add_link(
                conn, "tester", fid, kind="informs", target_item=None, target_finding=None, note=None
            )

    def test_link_reserves_promoted_to_for_promote(self, conn):
        # N6: 'promoted-to' edges come only from `finding promote` (atomic flip).
        _mk_item(conn, item_id="an-item")
        fid = _mk_finding(conn)
        with pytest.raises(todo_db.TodoError, match="promote"):
            todo_findings.add_link(
                conn, "tester", fid, kind="promoted-to", target_item="an-item", target_finding=None, note=None
            )


class TestFindingListOrdering:
    def test_list_default_order_is_not_by_urgency(self, conn):
        # Capture-time urgency is often absent; the default order is disposition
        # then age, never a fabricated urgency ranking (anti-pattern).
        _mk_finding(conn, finding_id="2026-01-02-030405-first-class", urgency=None)
        _mk_finding(conn, finding_id="2026-01-02-030406-second-class", urgency="high")
        ids = [f["id"] for f in todo_findings.list_findings(conn)]
        # both open -> ordered by created_at/id, so the earlier id sorts first
        assert ids == ["2026-01-02-030405-first-class", "2026-01-02-030406-second-class"]
