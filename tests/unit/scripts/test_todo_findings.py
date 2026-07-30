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
import json
import sqlite3
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
    def test_findings_tables_and_current_version(self, conn):
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {
            "findings",
            "finding_evidence",
            "finding_links",
            "finding_events",
            "finding_sections",
        } <= tables
        assert conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"] == str(
            todo_db.SCHEMA_VERSION
        )

    def test_v4_columns_present(self, conn):
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(findings)")}
        assert {"related_paths", "suggested_sweep"} <= cols

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
        # Adding findings must not move ANY items-domain count. Compare every key
        # except the additive findings one (rather than a hardcoded allowlist), so
        # a future stats key that wrongly reflects findings is still caught.

        def items_domain(snapshot):
            return {k: v for k, v in snapshot.items() if k != "findings_by_disposition"}

        assert items_domain(after) == items_domain(before)
        assert after["findings_by_disposition"] == {"open": 2}

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


# ---------------------------------------------------------------------------
# Phase 4: surfacing -- the ready/stats banner + additive stats key.
#
# The banner must never perturb the machine-readable STDOUT of ready/stats
# (automation parses it): it renders to stderr, is suppressed at zero-state, and
# piggybacks a single cheap aggregate on the existing connection (no extra hosted
# round-trip). ``findings_by_disposition`` is an additive stats key.


class _CountingConn:
    """Proxy that records every SQL string executed, delegating to a real conn.

    sqlite3.Connection is a C type whose ``execute`` cannot be monkeypatched, so
    the banner's statement count is asserted through this thin proxy instead."""

    def __init__(self, real):
        self._real = real
        self.executed: list[str] = []

    def execute(self, sql, *args, **kwargs):
        self.executed.append(sql)
        return self._real.execute(sql, *args, **kwargs)


class TestSurfacingBanner:
    def test_banner_none_at_zero_state(self, conn, tmp_path):
        # No findings and an empty drafts dir -> nothing to surface.
        assert todo_findings.surfacing_banner(conn, drafts_dir=tmp_path / "nope") is None

    def test_banner_counts_open_findings_and_unsynced_drafts(self, conn, tmp_path):
        _mk_finding(conn)  # open
        _mk_finding(conn, finding_id="2026-01-02-030406-b-class", disposition="dismissed", disposition_reason="no")
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "2026-01-02-030407-draft-class.md").write_text("draft", encoding="utf-8")
        (drafts / "README.md").write_text("skip me", encoding="utf-8")  # README excluded
        banner = todo_findings.surfacing_banner(conn, drafts_dir=drafts)
        assert banner is not None
        assert "1 open finding(s)" in banner  # 'dismissed' is not 'open'
        assert "1 unsynced draft(s)" in banner  # README.md not counted
        assert "todo finding list --disposition open" in banner
        assert "todo finding candidates" in banner

    def test_banner_open_findings_only(self, conn, tmp_path):
        _mk_finding(conn)
        banner = todo_findings.surfacing_banner(conn, drafts_dir=tmp_path / "empty")
        assert "1 open finding(s)" in banner
        assert "draft" not in banner
        assert "todo finding list --disposition open" in banner
        assert "todo finding candidates" not in banner

    def test_banner_unsynced_drafts_only(self, conn, tmp_path):
        drafts = tmp_path / "drafts"
        drafts.mkdir()
        (drafts / "2026-01-02-030407-draft-class.md").write_text("draft", encoding="utf-8")
        banner = todo_findings.surfacing_banner(conn, drafts_dir=drafts)
        assert "1 unsynced draft(s)" in banner
        assert "open finding" not in banner

    @pytest.mark.parametrize("command", ["ready", "stats"])
    def test_command_issues_at_most_one_findings_query(self, conn, capsys, monkeypatch, command):
        # "No extra hosted round-trip", pinned at the COMMAND level -- spying on
        # the helper alone is true by construction (one function, one statement)
        # and so can never regress. `stats` must reuse the disposition breakdown
        # it already computed instead of a second open-count aggregate.
        _mk_finding(conn)
        _mk_finding(conn, finding_id="2026-01-02-030406-b-class")
        monkeypatch.setattr(todo_findings, "DEFAULT_DRAFTS_DIR", "/nonexistent-drafts")
        spy = _CountingConn(conn)
        handler = {"ready": todo_db._cmd_ready, "stats": todo_db._cmd_stats}[command]
        assert handler(spy, "tester", SimpleNamespace()) == 0
        findings_queries = [s for s in spy.executed if "FROM findings" in s]
        assert len(findings_queries) == 1, f"{command} issued {len(findings_queries)}: {findings_queries}"
        assert "2 open finding(s)" in capsys.readouterr().err

    def test_banner_opens_no_new_connection(self, conn, monkeypatch):
        # "No extra hosted round-trip": the banner reuses the caller's connection.
        # Block EVERY connect entry point -- a regression would realistically open
        # a hosted connection, not the local one.
        _mk_finding(conn)
        for entry in ("connect", "connect_backend", "connect_hosted", "_hosted_read_connect", "_hosted_raw_connect"):
            if hasattr(todo_db, entry):
                monkeypatch.setattr(todo_db, entry, lambda *a, _e=entry, **k: pytest.fail(f"banner must not call {_e}"))
        assert todo_findings.surfacing_banner(conn, drafts_dir=Path("/nonexistent-drafts")) is not None

    def test_banner_ready_on_stderr_not_stdout(self, conn, capsys, monkeypatch):
        _mk_item(conn, item_id="ready-item")  # a ready planning item -> stdout content
        monkeypatch.setattr(todo_findings, "surfacing_banner", lambda c, **kw: "→ SENTINEL-banner")
        todo_db._cmd_ready(conn, "tester", SimpleNamespace())
        captured = capsys.readouterr()
        assert "ready-item" in captured.out  # items on stdout
        assert "SENTINEL-banner" not in captured.out  # banner NEVER on stdout
        assert "SENTINEL-banner" in captured.err  # banner on stderr

    def test_banner_stats_on_stderr_not_stdout(self, conn, capsys, monkeypatch):
        monkeypatch.setattr(todo_findings, "surfacing_banner", lambda c, **kw: "→ SENTINEL-banner")
        todo_db._cmd_stats(conn, "tester", SimpleNamespace())
        captured = capsys.readouterr()
        json.loads(captured.out)  # stdout stays valid JSON, banner absent
        assert "SENTINEL-banner" not in captured.out
        assert "SENTINEL-banner" in captured.err

    def test_banner_survives_ascii_only_stderr(self, conn, monkeypatch, capfd):
        # The banner carries non-ASCII (→ / —). On a byte-oriented stderr (C
        # locale, or a POSIX pipe under LC_ALL=C) the *write* raises
        # UnicodeEncodeError -- which must not escape and break `ready`.
        import io

        _mk_item(conn, item_id="ready-item")
        _mk_finding(conn)
        monkeypatch.setattr(todo_findings, "DEFAULT_DRAFTS_DIR", "/nonexistent-drafts")
        buffer = io.BytesIO()
        ascii_stderr = io.TextIOWrapper(buffer, encoding="ascii", errors="strict")
        monkeypatch.setattr(todo_db.sys, "stderr", ascii_stderr)
        assert todo_db._cmd_ready(conn, "tester", SimpleNamespace()) == 0
        ascii_stderr.flush()
        # The hint degrades to readable ASCII rather than vanishing or crashing.
        emitted = buffer.getvalue().decode("ascii")
        assert "open finding(s)" in emitted
        assert "todo finding list --disposition open" in emitted
        assert "-> " in emitted  # transliterated, not "?"-replaced
        # ...and the degraded path still never touches stdout.
        assert "finding" not in capfd.readouterr().out

    def test_banner_bails_out_when_stderr_is_closed(self, conn, capsys, monkeypatch):
        # With fd 2 closed CPython sets sys.stderr to None, and print(file=None)
        # falls back to STDOUT -- which would put the hint in the machine-readable
        # stream (and break `stats` JSON). Bail out instead.
        _mk_item(conn, item_id="ready-item")
        _mk_finding(conn)
        monkeypatch.setattr(todo_db.sys, "stderr", None)
        assert todo_db._cmd_ready(conn, "tester", SimpleNamespace()) == 0
        out = capsys.readouterr().out
        assert "ready-item" in out
        assert "finding" not in out

    def test_banner_never_breaks_ready_when_hint_fails(self, conn, capsys, monkeypatch):
        # A hint must never break the core command: a failing banner is swallowed
        # AFTER the stdout contract is met, ready still returns 0.
        _mk_item(conn, item_id="ready-item")
        monkeypatch.setattr(
            todo_findings, "surfacing_banner", lambda c, **kw: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        assert todo_db._cmd_ready(conn, "tester", SimpleNamespace()) == 0
        assert "ready-item" in capsys.readouterr().out


class TestFindingsStats:
    def test_findings_stats_shape(self, conn):
        _mk_finding(conn)  # open
        _mk_finding(conn, finding_id="2026-01-02-030406-b-class", disposition="dismissed", disposition_reason="x")
        s = todo_db.stats(conn)
        assert s["findings_by_disposition"] == {"open": 1, "dismissed": 1}
        # Existing items-domain keys are untouched (additive-only change).
        for key in ("items_by_state", "open_by_priority", "open_by_worktree", "deferrals_by_resolution", "claimed"):
            assert key in s

    def test_findings_stats_empty_when_no_findings(self, conn):
        assert todo_db.stats(conn)["findings_by_disposition"] == {}


class TestSurfacingFlow:
    def test_surfacing_flow_ready_shows_findings_when_present(self, conn, capsys, tmp_path, monkeypatch):
        # Documented-flow encounter: an agent following the planning flow runs
        # `ready`; when an untriaged finding exists it is surfaced (on stderr).
        monkeypatch.setattr(todo_findings, "DEFAULT_DRAFTS_DIR", str(tmp_path / "no-drafts"))
        _mk_item(conn, item_id="ready-item")
        _mk_finding(conn)  # one open finding
        todo_db._cmd_ready(conn, "tester", SimpleNamespace())
        captured = capsys.readouterr()
        assert "ready-item" in captured.out
        assert "1 open finding(s)" in captured.err
        assert "todo finding list --disposition open" in captured.err

    def test_surfacing_flow_silent_when_nothing_untriaged(self, conn, capsys, tmp_path, monkeypatch):
        monkeypatch.setattr(todo_findings, "DEFAULT_DRAFTS_DIR", str(tmp_path / "no-drafts"))
        _mk_item(conn, item_id="ready-item")
        todo_db._cmd_ready(conn, "tester", SimpleNamespace())
        captured = capsys.readouterr()
        assert "ready-item" in captured.out
        assert "finding" not in captured.err  # zero-state: no banner


# ---------------------------------------------------------------------------
# Parser-completeness guard (findings-parser-completeness-guard)
#
# The root cause of the silent-loss class: `validate_blind_spot.py` decides what a
# draft may contain, `parse_draft` decides what reaches the DB, and nothing
# compared the two. Measured over the live 65-record corpus (2026-07-29), 65 of 65
# records lost content while `sync` printed "synced 1".
#
# Every expectation below is derived from the validator's OWN constants. A
# hand-copied field list would drift exactly the way parse_draft drifted, which is
# the defect under test.

vbs = importlib.import_module("validate_blind_spot")


class TestParserCompletenessGuard:
    def test_every_accepted_frontmatter_key_has_a_declared_home(self):
        declared = set(todo_findings.FRONTMATTER_HOMES) | set(todo_findings.FRONTMATTER_HOMES_PENDING_V4)
        undeclared = vbs.ALLOWED_FIELDS - declared
        assert not undeclared, (
            f"validator accepts {sorted(undeclared)} with no entry in FRONTMATTER_HOMES or "
            "FRONTMATTER_HOMES_PENDING_V4 -- add a home, or name it pending with its v4 target. "
            "An undeclared field is silently dropped at sync time."
        )

    def test_no_declared_home_for_a_field_the_validator_rejects(self):
        # The other direction: a home for a field the validator will never accept is
        # dead weight that misleads the next reader about what can arrive.
        declared = set(todo_findings.FRONTMATTER_HOMES) | set(todo_findings.FRONTMATTER_HOMES_PENDING_V4)
        assert not (declared - vbs.ALLOWED_FIELDS)

    def test_pending_set_is_empty_at_v4(self):
        # v4 landed a real home for every accepted key. The map stays in the code so
        # a future field must be given a home or named here; it must not silently
        # refill, which would reopen the loss this domain was built to close.
        assert todo_findings.FRONTMATTER_HOMES_PENDING_V4 == {}

    def test_every_accepted_key_has_a_real_home_not_a_pending_one(self):
        assert set(todo_findings.FRONTMATTER_HOMES) == set(vbs.ALLOWED_FIELDS)

    def test_declared_section_homes_cover_the_required_headings(self):
        required = {heading.removeprefix("## ") for heading in vbs.REQUIRED_BODY_HEADINGS}
        assert required <= set(todo_findings.SECTION_HOMES)

    def test_guard_fails_closed_on_a_new_validator_field(self, monkeypatch):
        # Proves the guard actually fails rather than merely passing today: add a
        # field to the validator's accepted set and the completeness check must break.
        monkeypatch.setattr(vbs, "ALLOWED_FIELDS", vbs.ALLOWED_FIELDS | {"newly_added_field"})
        declared = set(todo_findings.FRONTMATTER_HOMES) | set(todo_findings.FRONTMATTER_HOMES_PENDING_V4)
        assert vbs.ALLOWED_FIELDS - declared == {"newly_added_field"}


class TestUnmappedContentIsReported:
    def test_legacy_shaped_record_lands_completely_at_v4(self, tmp_path):
        stem = "2026-01-02-030405-legacy-shaped-record"
        (tmp_path / f"{stem}.md").write_text(
            "---\n"
            f"id: {stem}\n"
            "date: 2026-01-02\n"
            "status: open\n"
            "finding_kind: framework-gap\n"
            'review_context: "ultrareview X"\n'
            "related_paths:\n  - benchbox/core/thing.py\n"
            "suggested_sweep: rg -n 'thing' benchbox/\n"
            "---\n\n"
            "# A legacy-shaped record\n\n"
            "## Finding\nthe review never checks axis Y\n\n"
            "## Why this matters\naxis Y is a whole dimension\n\n"
            "## Suggested next steps\n- [ ] add a gate\n\n"
            "## Why the five-axis review missed it\nthe rubric had no axis for it\n",
            encoding="utf-8",
        )
        fields = todo_findings.parse_draft(tmp_path / f"{stem}.md")
        # Nothing is unmapped any more; every field has a column or a row.
        assert fields["unmapped"] == {"frontmatter": [], "sections": []}
        assert json.loads(fields["related_paths"]) == ["benchbox/core/thing.py"]
        assert fields["suggested_sweep"] == "rg -n 'thing' benchbox/"
        assert fields["sections"] == [
            {
                "position": 0,
                "heading": "Why the five-axis review missed it",
                "text": "the rubric had no axis for it",
            }
        ]

    def test_clean_draft_reports_nothing_unmapped(self, tmp_path):
        path = _draft(tmp_path / "d", "2026-01-02-030405-a-clean-record")
        fields = todo_findings.parse_draft(path)
        assert fields["unmapped"] == {"frontmatter": [], "sections": []}

    def test_empty_optional_keys_are_not_reported_as_loss(self, tmp_path):
        # A key present but null carries nothing, so reporting it would be noise.
        stem = "2026-01-02-030405-null-optionals"
        (tmp_path / f"{stem}.md").write_text(
            "---\n"
            f"id: {stem}\n"
            "date: 2026-01-02\n"
            "status: open\n"
            "finding_kind: framework-gap\n"
            'review_context: "ultrareview X"\n'
            "related_paths:\n"
            "suggested_sweep:\n"
            "todo_id:\n"
            "---\n\n"
            "# Null optionals\n\n"
            "## Finding\nf\n\n## Why this matters\nw\n\n## Suggested next steps\n- [ ] s\n",
            encoding="utf-8",
        )
        fields = todo_findings.parse_draft(tmp_path / f"{stem}.md")
        assert fields["unmapped"] == {"frontmatter": [], "sections": []}

    def test_sync_lands_a_legacy_record_and_marks_it_synced_at_v4(self, conn, tmp_path, capsys):
        stem = "2026-01-02-030405-lossy-record"
        (tmp_path / f"{stem}.md").write_text(
            "---\n"
            f"id: {stem}\n"
            "date: 2026-01-02\n"
            "status: open\n"
            "finding_kind: framework-gap\n"
            'review_context: "ultrareview X"\n'
            "suggested_sweep: rg -n 'thing' benchbox/\n"
            "---\n\n"
            "# Lossy record\n\n"
            "## Finding\nf\n\n## Why this matters\nw\n\n## Suggested next steps\n- [ ] s\n",
            encoding="utf-8",
        )
        result = todo_findings.sync_drafts(conn, "tester", tmp_path)
        assert result["synced"] == [stem]
        # Nothing lossy at v4, so the draft is marked synced as normal.
        assert result["unmapped"] == {}
        assert not (tmp_path / f"{stem}.md").exists()
        assert (tmp_path / f"{stem}.md.synced").exists()
        assert todo_findings.count_unsynced_drafts(tmp_path) == 0
        stored = todo_findings.get_finding(conn, stem)
        assert stored["suggested_sweep"] == "rg -n 'thing' benchbox/"

    def test_warn_unmapped_still_reports_when_something_has_no_home(self, capsys):
        # The reporting path must keep working for a FUTURE field with no column;
        # v4 emptied the pending set but did not remove the safety net.
        todo_findings._warn_unmapped({"2026-01-02-030405-x": {"frontmatter": ["future_field"], "sections": []}})
        err = capsys.readouterr().err
        assert "did NOT land" in err
        assert "future_field" in err

    def test_sync_marks_a_clean_draft_synced_as_before(self, conn, tmp_path):
        path = _draft(tmp_path / "d", "2026-01-02-030405-a-clean-record")
        result = todo_findings.sync_drafts(conn, "tester", tmp_path)
        assert result["synced"] == ["2026-01-02-030405-a-clean-record"]
        assert result["unmapped"] == {}
        assert not path.exists()
        assert path.with_name(path.name + ".synced").exists()


class TestShowRendersEvidenceNote:
    """`show --json` always carried evidence `note`; the human rendering dropped it,
    so the default `todo finding show` hid the reviewer's reason for each row."""

    def _finding_with_evidence(self, conn, evidence):
        fid = _mk_finding(conn, evidence=evidence)
        return todo_findings.get_finding(conn, fid)

    def test_note_reaches_human_output(self, conn, capsys):
        finding = self._finding_with_evidence(
            conn, [{"path": "benchbox/core/thing.py", "pattern": "def thing", "note": "only the SQL path is guarded"}]
        )
        todo_findings._print_finding(finding)
        out = capsys.readouterr().out
        assert "evidence: benchbox/core/thing.py def thing" in out
        assert "note: only the SQL path is guarded" in out

    def test_note_less_evidence_row_renders_as_before(self, conn, capsys):
        finding = self._finding_with_evidence(conn, [{"path": "benchbox/core/thing.py", "pattern": "def thing"}])
        todo_findings._print_finding(finding)
        lines = [line for line in capsys.readouterr().out.splitlines() if "thing.py" in line or "note:" in line]
        assert lines == ["evidence: benchbox/core/thing.py def thing"]

    def test_json_payload_is_unchanged_and_already_included_the_note(self, conn):
        finding = self._finding_with_evidence(conn, [{"path": "p.py", "pattern": None, "note": "why p matters"}])
        assert finding["evidence"][0]["note"] == "why p matters"


class TestSyncFullPayloadComparison:
    """`_finding_matches` compared only `_CONTENT_FIELDS`, so an evidence-only draft
    edit was marked `.synced` and lost while `sync` printed success."""

    def _write(self, directory: Path, stem: str, *, evidence_block: str = "", extra_front: str = ""):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{stem}.md").write_text(
            "---\n"
            f"id: {stem}\n"
            "date: 2026-01-02\n"
            "status: open\n"
            "finding_kind: framework-gap\n"
            'review_context: "ultrareview X"\n'
            f"{extra_front}{evidence_block}"
            "---\n\n"
            "# A sample class\n\n"
            "## Finding\nthe review never checks axis Y\n\n"
            "## Why this matters\naxis Y is a whole dimension\n\n"
            "## Suggested next steps\n- [ ] add a gate for axis Y\n",
            encoding="utf-8",
        )
        return directory / f"{stem}.md"

    def test_evidence_only_edit_is_persisted_not_silently_synced(self, conn, tmp_path):
        stem = "2026-01-02-030405-evidence-edited"
        path = self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n    note: first\n")
        assert todo_findings.sync_drafts(conn, "tester", tmp_path)["synced"] == [stem]

        # Edit only the evidence, then re-sync from the same drafts directory.
        path.with_name(path.name + ".synced").rename(path)
        self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n    note: SECOND\n  - path: b.py\n")
        result = todo_findings.sync_drafts(conn, "tester", tmp_path)

        assert result["updated"] == [stem]
        assert result["conflicts"] == []
        stored = todo_findings.get_finding(conn, stem)["evidence"]
        assert [(row["path"], row["note"]) for row in stored] == [("a.py", "SECOND"), ("b.py", None)]

    def test_evidence_reconcile_is_recorded_in_finding_events(self, conn, tmp_path):
        stem = "2026-01-02-030405-evidence-audited"
        path = self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n")
        todo_findings.sync_drafts(conn, "tester", tmp_path)
        path.with_name(path.name + ".synced").rename(path)
        self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n  - path: b.py\n")
        todo_findings.sync_drafts(conn, "tester", tmp_path)

        actions = [event["action"] for event in todo_findings.get_finding(conn, stem)["events"]]
        assert "resync_evidence" in actions
        detail = json.loads(
            next(
                e["detail"] for e in todo_findings.get_finding(conn, stem)["events"] if e["action"] == "resync_evidence"
            )
        )
        assert detail == {"rows_before": 1, "rows_after": 2}

    def test_unchanged_draft_is_still_skipped_and_marked_synced(self, conn, tmp_path):
        stem = "2026-01-02-030405-unchanged-record"
        path = self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n    note: same\n")
        todo_findings.sync_drafts(conn, "tester", tmp_path)
        path.with_name(path.name + ".synced").rename(path)

        result = todo_findings.sync_drafts(conn, "tester", tmp_path)
        assert result["skipped"] == [stem]
        assert result["updated"] == []
        assert path.with_name(path.name + ".synced").exists()

    def test_prose_difference_is_still_a_loud_conflict(self, conn, tmp_path):
        stem = "2026-01-02-030405-prose-changed"
        path = self._write(tmp_path, stem)
        todo_findings.sync_drafts(conn, "tester", tmp_path)
        path.with_name(path.name + ".synced").rename(path)
        path.write_text(path.read_text(encoding="utf-8").replace("axis Y", "axis Z"), encoding="utf-8")

        with pytest.raises(todo_db.TodoError, match="sync conflict"):
            todo_findings.sync_drafts(conn, "tester", tmp_path)

    def test_triage_judgement_survives_a_resync(self, conn, tmp_path):
        # The draft predates triage and carries no urgency; reconciling judgement
        # fields "from the draft" would wipe what triage recorded.
        stem = "2026-01-02-030405-triaged-record"
        path = self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n")
        todo_findings.sync_drafts(conn, "tester", tmp_path)
        with todo_db._write_txn(conn):
            conn.execute("UPDATE findings SET urgency = 'high', breadth = 'wide' WHERE id = ?", (stem,))

        path.with_name(path.name + ".synced").rename(path)
        self._write(tmp_path, stem, evidence_block="evidence:\n  - path: a.py\n  - path: b.py\n")
        todo_findings.sync_drafts(conn, "tester", tmp_path)

        stored = todo_findings.get_finding(conn, stem)
        assert (stored["urgency"], stored["breadth"]) == ("high", "wide")
        assert len(stored["evidence"]) == 2


class TestDraftsDirBridge:
    """BenchBox binds drafts to ~/.benchbox/finding-drafts/ while the standalone
    todo-db defaults to ~/.todo-db/finding-drafts/<project-id>/. The divergence is
    silent — `sync` reports "synced 0" and the banner counts zero while a real draft
    sits stranded — so one env var has to bind every surface."""

    def test_env_var_wins_over_the_benchbox_default(self, monkeypatch, tmp_path):
        monkeypatch.setenv(todo_findings.DRAFTS_DIR_ENV, str(tmp_path / "pinned"))
        assert todo_findings.resolve_drafts_dir() == str(tmp_path / "pinned")

    def test_falls_back_to_the_benchbox_default_when_unset(self, monkeypatch):
        monkeypatch.delenv(todo_findings.DRAFTS_DIR_ENV, raising=False)
        assert todo_findings.resolve_drafts_dir() == todo_findings.DEFAULT_DRAFTS_DIR

    def test_empty_env_var_is_ignored(self, monkeypatch):
        # An exported-but-empty var must not resolve drafts to the process cwd.
        monkeypatch.setenv(todo_findings.DRAFTS_DIR_ENV, "")
        assert todo_findings.resolve_drafts_dir() == todo_findings.DEFAULT_DRAFTS_DIR

    def test_a_stranded_draft_becomes_visible_to_the_pinned_dir(self, monkeypatch, tmp_path):
        # The item's own scenario: a real draft in the bound directory must be
        # counted, not silently missed.
        drafts = tmp_path / "benchbox-drafts"
        _draft(drafts / "d", "2026-07-24-150447-guards-only-cover-configured-root")
        monkeypatch.setenv(todo_findings.DRAFTS_DIR_ENV, str(drafts))
        assert todo_findings.count_unsynced_drafts() == 1

    def test_banner_follows_the_pinned_dir(self, conn, monkeypatch, tmp_path):
        drafts = tmp_path / "pinned-drafts"
        _draft(drafts / "d", "2026-07-24-150447-guards-only-cover-configured-root")
        monkeypatch.setenv(todo_findings.DRAFTS_DIR_ENV, str(drafts))
        banner = todo_findings.surfacing_banner(conn)
        assert banner is not None
        assert "1 unsynced draft(s)" in banner


class TestEvidenceReconcileIsNotDestructive:
    """A draft with no `evidence:` key makes no assertion about evidence. Treating
    that as an empty list would delete rows curated at triage or hand-mapped during
    an import — the live record 2026-07-18-190500-evidence-tree-sha-provenance-mismatch
    has exactly that shape: no key in the file, three rows in the DB."""

    def test_absent_evidence_key_never_deletes_stored_rows(self, conn, tmp_path):
        stem = "2026-01-02-030405-hand-mapped-record"
        fid = _mk_finding(
            conn,
            finding_id=stem,
            title="A sample class",
            review_context="ultrareview X",
            why_matters="axis Y is a whole dimension",
            evidence=[{"path": "a.py", "note": "hand-mapped from related_paths"}],
        )
        # A draft file that carries no `evidence:` key at all.
        _draft(tmp_path / "d", stem)

        result = todo_findings.sync_drafts(conn, "tester", tmp_path)
        assert result["updated"] == []
        assert result["skipped"] == [fid]
        stored = todo_findings.get_finding(conn, fid)["evidence"]
        assert [(row["path"], row["note"]) for row in stored] == [("a.py", "hand-mapped from related_paths")]

    def test_explicitly_empty_evidence_list_does_clear_stored_rows(self, conn, tmp_path):
        # An explicit `evidence: []` IS an assertion, so it is honoured.
        stem = "2026-01-02-030405-explicitly-cleared"
        _mk_finding(
            conn,
            finding_id=stem,
            review_context="ultrareview X",
            why_matters="axis Y is a whole dimension",
            evidence=[{"path": "a.py"}],
        )
        (tmp_path / f"{stem}.md").write_text(
            "---\n"
            f"id: {stem}\n"
            "date: 2026-01-02\n"
            "status: open\n"
            "finding_kind: framework-gap\n"
            'review_context: "ultrareview X"\n'
            "evidence: []\n"
            "---\n\n"
            "# A sample blind-spot class\n\n"
            "## Finding\nthe review never checks axis Y\n\n"
            "## Why this matters\naxis Y is a whole dimension\n\n"
            "## Suggested next steps\n- [ ] add a gate for axis Y\n",
            encoding="utf-8",
        )
        result = todo_findings.sync_drafts(conn, "tester", tmp_path)
        assert result["updated"] == [stem]
        assert todo_findings.get_finding(conn, stem)["evidence"] == []


class TestV4MigrationEquivalence:
    """v4's delta is ALTER/CREATE/rebuild statements, so it can never be the same
    text as the fresh CREATEs. The property that actually matters — a migrated
    database is indistinguishable from a fresh one — is therefore pinned here
    rather than by sharing one DDL string."""

    @staticmethod
    def _schema(conn):
        """Normalized sqlite_master rows.

        Whitespace is collapsed, and `CREATE TABLE "x"` is normalized to
        `CREATE TABLE x`: SQLite always quotes the new name in
        `ALTER TABLE ... RENAME TO`, so the rebuilt finding_links carries quotes a
        freshly created one does not. That is a documented SQLite formatting
        artifact of the rebuild, not a schema difference -- every column, type,
        constraint, and FK clause still has to match exactly.
        """
        rows = []
        for row in conn.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"):
            sql = " ".join((row["sql"] or "").split())
            sql = sql.replace(f'CREATE TABLE "{row["name"]}"', f"CREATE TABLE {row['name']}", 1)
            rows.append((row["type"], row["name"], sql))
        return sorted(rows)

    def test_migrated_v3_schema_equals_fresh_v4(self, tmp_path):
        fresh = todo_db.connect(tmp_path / "fresh.sqlite")

        # Build a v3 database the way the released v3 CLI did, then migrate it.
        migrated_path = tmp_path / "migrated.sqlite"
        raw = sqlite3.connect(migrated_path)
        raw.executescript(todo_db._CORE_SCHEMA_SQL)
        for statement in todo_findings.finding_schema_statements():
            raw.execute(statement)
        raw.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")
        raw.commit()
        raw.close()

        assert todo_db.migrate_db(migrated_path) == [4]
        migrated = todo_db.connect(migrated_path)
        assert self._schema(migrated) == self._schema(fresh)

    def test_migration_preserves_existing_findings_rows_and_links(self, tmp_path):
        migrated_path = tmp_path / "withdata.sqlite"
        raw = sqlite3.connect(migrated_path)
        raw.executescript(todo_db._CORE_SCHEMA_SQL)
        for statement in todo_findings.finding_schema_statements():
            raw.execute(statement)
        raw.execute("INSERT INTO meta (key, value) VALUES ('schema_version', '3')")
        raw.commit()
        raw.close()

        conn = sqlite3.connect(migrated_path)
        conn.execute(
            "INSERT INTO items (id, title, worktree, priority, state, description, created_at) VALUES (?,?,?,?,?,?,?)",
            (
                "kept-item",
                "A kept item",
                "main",
                "medium",
                "planning",
                "a description long enough",
                "2026-01-02T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO findings (id, date, finding_kind, review_context, title, finding_text,"
            " why_matters, next_steps, disposition, created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "2026-01-02-030405-kept",
                "2026-01-02",
                "framework-gap",
                "rc",
                "T",
                "f",
                "w",
                "n",
                "promoted",
                "2026-01-02T00:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO finding_links (finding_id, kind, target_item, note) VALUES (?,?,?,?)",
            ("2026-01-02-030405-kept", "promoted-to", "kept-item", "promoted by tester"),
        )
        conn.execute(
            "INSERT INTO finding_evidence (finding_id, path, note) VALUES (?,?,?)",
            ("2026-01-02-030405-kept", "a.py", "kept note"),
        )
        conn.commit()
        conn.close()

        assert todo_db.migrate_db(migrated_path) == [4]
        conn = todo_db.connect(migrated_path)
        finding = todo_findings.get_finding(conn, "2026-01-02-030405-kept")
        assert finding["disposition"] == "promoted"
        assert finding["links"] == [
            {"kind": "promoted-to", "target_item": "kept-item", "target_finding": None, "note": "promoted by tester"}
        ]
        assert [(row["path"], row["note"]) for row in finding["evidence"]] == [("a.py", "kept note")]
        # New columns exist and default to NULL for pre-v4 rows.
        assert (finding["related_paths"], finding["suggested_sweep"]) == (None, None)

    def test_replace_style_reload_no_longer_aborts_and_keeps_the_link(self, tmp_path):
        # The w1 defect, as a regression test: DELETE every items-domain table and
        # reinsert inside one transaction, with foreign_keys ON.
        conn = todo_db.connect(tmp_path / "reload.sqlite")
        todo_db.create_item(
            conn,
            "t",
            item_id="target-item",
            title="A real item",
            worktree="main",
            priority="medium",
            description="a description long enough for the CHECK",
        )
        fid = _mk_finding(conn)
        todo_findings.promote_finding(conn, "t", fid, new_item_id="promoted-item")
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1

        rows = {t: [tuple(r) for r in conn.execute(f"SELECT * FROM {t}")] for t in todo_db.TRANSFER_TABLES}
        with todo_db._write_txn(conn):
            for table in reversed(todo_db.TRANSFER_TABLES):
                conn.execute(f"DELETE FROM {table}")
            for table in todo_db.TRANSFER_TABLES:
                if not rows[table]:
                    continue
                width = len(rows[table][0])
                placeholders = ", ".join("?" for _ in range(width))
                for row in rows[table]:
                    conn.execute(f"INSERT INTO {table} VALUES ({placeholders})", row)

        link = todo_findings.get_finding(conn, fid)["links"][0]
        assert link["target_item"] == "promoted-item"

    def test_a_genuine_dangler_is_still_refused_at_commit(self, tmp_path):
        conn = todo_db.connect(tmp_path / "dangle.sqlite")
        fid = _mk_finding(conn)
        todo_findings.promote_finding(conn, "t", fid, new_item_id="promoted-item")
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            with todo_db._write_txn(conn):
                for table in reversed(todo_db.TRANSFER_TABLES):
                    conn.execute(f"DELETE FROM {table}")


class TestLegacyTodoIdLinkMapping:
    """`todo_id` maps to a finding_links row whose KIND follows the record's status.
    A `promoted-to` edge asserts disposition 'promoted', so the 4 corpus records that
    are `actioned` with a todo_id must use `resolved-by` instead."""

    def _draft_with_todo_id(self, directory: Path, stem: str, *, status: str, todo_id: str):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{stem}.md").write_text(
            "---\n"
            f"id: {stem}\n"
            "date: 2026-01-02\n"
            f"status: {status}\n"
            "finding_kind: framework-gap\n"
            'review_context: "ultrareview X"\n'
            f"todo_id: {todo_id}\n"
            "---\n\n"
            "# A sample class\n\n"
            "## Finding\nf\n\n## Why this matters\nw\n\n## Suggested next steps\n- [ ] s\n\n"
            "## Triage log\n- merged\n",
            encoding="utf-8",
        )

    def test_merged_to_todo_becomes_promoted_to(self, conn, tmp_path):
        todo_db.create_item(
            conn,
            "t",
            item_id="the-target",
            title="A real item",
            worktree="main",
            priority="medium",
            description="a description long enough for the CHECK",
        )
        stem = "2026-01-02-030405-merged-record"
        self._draft_with_todo_id(tmp_path, stem, status="merged-to-todo", todo_id="the-target")
        todo_findings.sync_drafts(conn, "tester", tmp_path)

        finding = todo_findings.get_finding(conn, stem)
        assert finding["disposition"] == "promoted"
        assert finding["links"] == [
            {
                "kind": "promoted-to",
                "target_item": "the-target",
                "target_finding": None,
                "note": "imported from todo_id: the-target",
            }
        ]

    def test_actioned_becomes_resolved_by_not_promoted_to(self, conn, tmp_path):
        todo_db.create_item(
            conn,
            "t",
            item_id="the-target",
            title="A real item",
            worktree="main",
            priority="medium",
            description="a description long enough for the CHECK",
        )
        stem = "2026-01-02-030405-actioned-record"
        self._draft_with_todo_id(tmp_path, stem, status="actioned", todo_id="the-target")
        todo_findings.sync_drafts(conn, "tester", tmp_path)

        finding = todo_findings.get_finding(conn, stem)
        assert finding["disposition"] == "actioned"
        assert [link["kind"] for link in finding["links"]] == ["resolved-by"]

    def test_unresolvable_todo_id_keeps_the_id_in_the_note_and_does_not_abort(self, conn, tmp_path):
        stem = "2026-01-02-030405-dangling-record"
        self._draft_with_todo_id(tmp_path, stem, status="merged-to-todo", todo_id="never-existed")
        # Must not raise: a bare insert against the DEFERRABLE FK would fail the whole
        # transaction at COMMIT without naming the offending record.
        todo_findings.sync_drafts(conn, "tester", tmp_path)

        link = todo_findings.get_finding(conn, stem)["links"][0]
        assert link["target_item"] is None
        assert "never-existed" in link["note"]
        assert "no such item" in link["note"]

    def test_no_todo_id_creates_no_link(self, conn, tmp_path):
        path = _draft(tmp_path / "d", "2026-01-02-030405-no-todo-id")
        todo_findings.sync_drafts(conn, "tester", tmp_path)
        assert todo_findings.get_finding(conn, path.stem)["links"] == []


class TestFindingImportParity:
    """Phase-5 importer. Named so the work order's rung
    (`pytest -k 'finding_import or parity'`) selects it."""

    def _record(self, directory: Path, stem: str, *, triage_lines=(), todo_id=None, extra_section=None):
        directory.mkdir(parents=True, exist_ok=True)
        front = [
            "---",
            f"id: {stem}",
            "date: 2026-01-02",
            f"status: {'merged-to-todo' if todo_id else 'open'}",
            "finding_kind: framework-gap",
            'review_context: "ultrareview X"',
            "related_paths:",
            "  - benchbox/core/a.py",
            "suggested_sweep: rg -n 'a' benchbox/",
        ]
        if todo_id:
            front.append(f"todo_id: {todo_id}")
        front.append("---")
        body = [
            "",
            "# A sample class",
            "",
            "## Finding",
            "the review never checks axis Y",
            "",
            "## Why this matters",
            "axis Y is a whole dimension",
            "",
            "## Suggested next steps",
            "- [ ] add a gate",
        ]
        if extra_section:
            body += ["", f"## {extra_section[0]}", extra_section[1]]
        if triage_lines:
            body += ["", "## Triage log"] + list(triage_lines)
        (directory / f"{stem}.md").write_text("\n".join(front + body) + "\n", encoding="utf-8")
        return directory / f"{stem}.md"

    def test_import_never_renames_or_deletes_corpus_files(self, conn, tmp_path):
        # The freeze window is the rollback path: phase 5 must not touch the files.
        # sync_drafts renames to *.synced, which is exactly why import is separate.
        path = self._record(tmp_path, "2026-01-02-030405-frozen-record")
        before = sorted(p.name for p in tmp_path.iterdir())
        todo_findings.import_corpus(conn, "importer", tmp_path)
        assert sorted(p.name for p in tmp_path.iterdir()) == before
        assert path.exists()
        assert not list(tmp_path.glob("*.synced"))

    def test_triage_log_imports_one_verbatim_event_per_line(self, conn, tmp_path):
        lines = ["- 2026-01-02 raised in review", "- 2026-01-03 merged to some-item"]
        self._record(tmp_path, "2026-01-02-030405-triaged-record", triage_lines=lines)
        result = todo_findings.import_corpus(conn, "importer", tmp_path)
        assert result["triage_events"] == 2

        events = [
            e
            for e in todo_findings.get_finding(conn, "2026-01-02-030405-triaged-record")["events"]
            if e["action"] == todo_findings.IMPORTED_TRIAGE_ACTION
        ]
        assert [json.loads(e["detail"])["line"] for e in events] == lines

    def test_import_is_idempotent_by_record_id(self, conn, tmp_path):
        self._record(tmp_path, "2026-01-02-030405-twice-record", triage_lines=["- once"])
        first = todo_findings.import_corpus(conn, "importer", tmp_path)
        second = todo_findings.import_corpus(conn, "importer", tmp_path)
        assert first["imported"] == ["2026-01-02-030405-twice-record"]
        assert second["imported"] == []
        assert second["skipped"] == ["2026-01-02-030405-twice-record"]
        # No duplicated triage events on the re-run.
        events = [
            e
            for e in todo_findings.get_finding(conn, "2026-01-02-030405-twice-record")["events"]
            if e["action"] == todo_findings.IMPORTED_TRIAGE_ACTION
        ]
        assert len(events) == 1

    def test_import_records_provenance(self, conn, tmp_path):
        path = self._record(tmp_path, "2026-01-02-030405-provenance-record")
        todo_findings.import_corpus(conn, "importer", tmp_path)
        stored = todo_findings.get_finding(conn, "2026-01-02-030405-provenance-record")
        assert stored["imported_from"] == str(path)

    def test_dry_run_writes_nothing(self, conn, tmp_path):
        self._record(tmp_path, "2026-01-02-030405-dryrun-record", triage_lines=["- x"])
        result = todo_findings.import_corpus(conn, "importer", tmp_path, dry_run=True)
        assert result["imported"] == ["2026-01-02-030405-dryrun-record"]
        assert todo_findings.get_finding(conn, "2026-01-02-030405-dryrun-record") is None
        assert conn.execute("SELECT count(*) FROM findings").fetchone()[0] == 0

    def test_parity_report_is_clean_on_a_faithful_import(self, conn, tmp_path):
        self._record(
            tmp_path,
            "2026-01-02-030405-parity-record",
            triage_lines=["- a", "- b"],
            extra_section=("Why the five-axis review missed it", "no axis for it"),
        )
        result = todo_findings.import_corpus(conn, "importer", tmp_path)
        report = todo_findings.parity_report(conn, tmp_path, result)
        assert report["ok"] is True
        assert (report["corpus_records"], report["stored_records"]) == (1, 1)

    def test_parity_report_fails_closed_when_a_section_is_lost(self, conn, tmp_path):
        self._record(
            tmp_path,
            "2026-01-02-030405-lossy-parity",
            extra_section=("Why it didn't get caught earlier", "the rubric had no axis"),
        )
        result = todo_findings.import_corpus(conn, "importer", tmp_path)
        # Simulate a lossy importer by removing the stored section behind its back.
        with todo_db._write_txn(conn):
            conn.execute("DELETE FROM finding_sections WHERE finding_id = ?", ("2026-01-02-030405-lossy-parity",))
        report = todo_findings.parity_report(conn, tmp_path, result)
        assert report["ok"] is False
        assert report["section_diffs"]

    def test_parity_report_fails_closed_when_a_triage_line_is_lost(self, conn, tmp_path):
        self._record(tmp_path, "2026-01-02-030405-lossy-triage", triage_lines=["- a", "- b", "- c"])
        result = todo_findings.import_corpus(conn, "importer", tmp_path)
        with todo_db._write_txn(conn):
            conn.execute(
                "DELETE FROM finding_events WHERE finding_id = ? AND action = ?",
                ("2026-01-02-030405-lossy-triage", todo_findings.IMPORTED_TRIAGE_ACTION),
            )
        report = todo_findings.parity_report(conn, tmp_path, result)
        assert report["ok"] is False
        assert report["triage_log_diffs"][0]["expected_lines"] == 3

    def test_dangling_todo_id_is_reported_not_silently_skipped(self, conn, tmp_path):
        self._record(tmp_path, "2026-01-02-030405-dangling-import", todo_id="no-such-item")
        result = todo_findings.import_corpus(conn, "importer", tmp_path)
        assert result["danglers"] == [{"finding": "2026-01-02-030405-dangling-import", "todo_id": "no-such-item"}]


class TestBulkImportKeepsTheExportBoundaryClosed:
    """The phase-5 import moves findings over the same Hrana pipeline as import-yaml,
    via an explicit table list. That must NOT widen what gets committed to Git."""

    def test_findings_transfer_set_is_disjoint_from_the_export_allowlist(self):
        assert not (set(todo_findings.FINDINGS_TRANSFER_TABLES) & todo_db.EXPORT_TABLE_ALLOWLIST)

    def test_findings_tables_are_still_absent_from_transfer_tables(self):
        # TRANSFER_TABLES drives backup/restore AND the --replace delete loop; adding
        # findings there would put review prose in the committed snapshot's scope.
        assert not [t for t in todo_db.TRANSFER_TABLES if t.startswith("finding")]

    def test_bulk_transfer_defaults_to_the_items_domain(self):
        import inspect

        signature = inspect.signature(todo_db.bulk_transfer)
        assert signature.parameters["tables"].default is None

    def test_findings_transfer_order_puts_parents_first(self):
        order = todo_findings.FINDINGS_TRANSFER_TABLES
        assert order[0] == "findings"
        for child in ("finding_evidence", "finding_links", "finding_sections", "finding_events"):
            assert order.index("findings") < order.index(child)


class TestBulkImportPkOffset:
    """bulk_transfer copies primary keys verbatim, so staged rows numbered from 1
    collide with whatever the target already holds. Production really did have
    finding_events.seq=1 from an earlier sync, which would have aborted the transfer."""

    def _staged(self, tmp_path, n=3):
        path = tmp_path / "staging.sqlite"
        conn = todo_db.connect(path)
        fid = _mk_finding(conn, evidence=[{"path": "a.py"}])
        with todo_db._write_txn(conn):
            for i in range(n):
                todo_findings.log_finding_event(conn, "t", fid, "imported_triage_log", {"line": f"- {i}"})
        conn.close()
        return path

    def test_offset_shifts_ids_above_the_target_maximum(self, tmp_path):
        path = self._staged(tmp_path)
        before = todo_db.sqlite3.connect(path).execute("SELECT min(seq), max(seq) FROM finding_events").fetchone()
        applied = todo_findings.offset_staging_pks(path, {"finding_events": 100, "finding_evidence": 5})
        after = todo_db.sqlite3.connect(path).execute("SELECT min(seq), max(seq) FROM finding_events").fetchone()
        assert applied["finding_events"] == 100
        assert after == (before[0] + 100, before[1] + 100)

    def test_offset_preserves_row_order(self, tmp_path):
        # finding_events is an append-only audit trail: order is the meaning.
        path = self._staged(tmp_path, n=5)
        conn = todo_db.sqlite3.connect(path)
        before = [r[0] for r in conn.execute("SELECT detail FROM finding_events ORDER BY seq")]
        conn.close()
        todo_findings.offset_staging_pks(path, {"finding_events": 50})
        conn = todo_db.sqlite3.connect(path)
        after = [r[0] for r in conn.execute("SELECT detail FROM finding_events ORDER BY seq")]
        conn.close()
        assert after == before

    def test_zero_offset_is_a_no_op(self, tmp_path):
        path = self._staged(tmp_path)
        assert todo_findings.offset_staging_pks(path, {"finding_events": 0}) == {}

    def test_target_maxima_reads_every_findings_table(self, conn):
        maxima = todo_findings.target_findings_maxima(conn)
        assert set(maxima) == {"finding_evidence", "finding_links", "finding_sections", "finding_events"}
        assert all(v == 0 for v in maxima.values())
