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
