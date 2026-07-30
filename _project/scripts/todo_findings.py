#!/usr/bin/env python3
"""todo_findings.py - findings-domain sibling module for the DB-backed tracker.

Phase 3 of ``_project/specs/findings-domain.md``. This module owns everything
the findings domain adds so the 2,800-line ``todo_db.py`` monolith does not
absorb the blast radius (its hosted write paths are only manually
acceptance-tested). ``todo_db.py`` wires the ``finding`` subparser and dispatch;
all findings logic lives here.

Responsibilities:
- the v3 findings schema (``FINDINGS_SCHEMA_SQL``), composed into
  ``todo_db.SCHEMA_SQL`` (fresh DBs) and ``todo_db.MIGRATIONS[3]`` (existing v2
  DBs) from ONE source so the two can never drift;
- row helpers, disposition transitions, and append-only ``finding_events``
  logging (a separate table, never the item ``events`` table, so finding review
  prose can never reach the version-controlled export snapshot);
- the ``todo finding {create,list,show,candidates,dismiss,triage,link,promote,
  sync}`` subcommands.

Capture stays credential-free: ``create`` and ``candidates`` touch only the
local drafts directory (``~/.benchbox/finding-drafts/``); ``sync`` is the sole
credentialed landing step (review-protocol §4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import validate_blind_spot as vbs  # sibling; no todo_db dependency, so cycle-free

# ---------------------------------------------------------------------------
# Schema (composed into todo_db.SCHEMA_SQL and MIGRATIONS[3])
#
# Defined BEFORE ``import todo_db`` so the todo_db <-> todo_findings import
# cycle resolves in EITHER entry order. todo_db imports this module at load
# time for FINDINGS_SCHEMA_SQL, so that constant must exist before this module
# first touches todo_db -- which it does only at call time, below. All four
# findings tables are deliberately ABSENT from todo_db's EXPORT_TABLE_ALLOWLIST
# / TRANSFER_TABLES: their review prose is not version-controlled (findings
# domain "Export boundary"), and the phase-2 pinning test fails closed on any
# ``finding%`` table by construction.

# ---------------------------------------------------------------------------
# Frozen v3 findings DDL -- HISTORY, never edit.
#
# This is the exact delta MIGRATIONS[3] applied. A v2 database still reaches v3
# through it before MIGRATIONS[4] brings it to the current shape, so changing it
# would rewrite history and make the two paths disagree. Current-shape DDL is
# FINDINGS_SCHEMA_SQL below; that "a migrated DB equals a fresh DB" is pinned by
# a test, which is a stronger guarantee than sharing one string could be.

FINDINGS_SCHEMA_V3_SQL = """
CREATE TABLE findings (
  id                 TEXT PRIMARY KEY CHECK (length(id) BETWEEN 3 AND 200),
  date               TEXT NOT NULL,
  finding_kind       TEXT NOT NULL,
  review_context     TEXT NOT NULL,
  observed_sha       TEXT,
  title              TEXT NOT NULL,
  finding_text       TEXT NOT NULL,
  why_matters        TEXT NOT NULL,
  next_steps         TEXT NOT NULL,
  disposition        TEXT NOT NULL DEFAULT 'open' CHECK (disposition IN
                       ('open','actionable','actioned','dismissed','promoted')),
  disposition_reason TEXT,
  urgency            TEXT,
  breadth            TEXT,
  confidence         TEXT,
  reconsider_after   TEXT,
  created_at         TEXT NOT NULL,
  imported_from      TEXT,
  CHECK (disposition NOT IN ('actionable','dismissed')
         OR (disposition_reason IS NOT NULL AND length(disposition_reason) > 0))
);

CREATE TABLE finding_evidence (
  id         INTEGER PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  path       TEXT NOT NULL,
  pattern    TEXT,
  line_start INTEGER,
  line_end   INTEGER,
  note       TEXT
);

CREATE TABLE finding_links (
  id             INTEGER PRIMARY KEY,
  finding_id     TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN
                   ('promoted-to','informs','resolved-by','related-finding','duplicate-of')),
  target_item    TEXT REFERENCES items(id),
  target_finding TEXT REFERENCES findings(id),
  note           TEXT
);

CREATE TABLE finding_events (
  seq        INTEGER PRIMARY KEY,
  at         TEXT NOT NULL,
  actor      TEXT NOT NULL,
  finding_id TEXT REFERENCES findings(id),
  action     TEXT NOT NULL,
  detail     TEXT
);

CREATE INDEX idx_findings_disposition ON findings(disposition);
CREATE INDEX idx_finding_events_finding ON finding_events(finding_id, seq);
"""

# ---------------------------------------------------------------------------
# Current (v4) findings DDL, used for fresh databases via todo_db.SCHEMA_SQL.
#
# v4 adds the lossless homes for legacy capture fields (see "Legacy field
# mapping (schema v4)" in _project/specs/findings-domain.md) and makes
# finding_links.target_item DEFERRABLE.
#
# Why DEFERRABLE INITIALLY DEFERRED: a hosted `--replace` reload DELETEs every
# items-domain table and reinserts it inside ONE transaction. findings tables are
# deliberately absent from TRANSFER_TABLES, so with an immediate FK the DELETE
# aborts ("FOREIGN KEY constraint failed") even though the very same transaction
# restores the item -- a false failure that made the reload unusable. Deferring
# the check to COMMIT lets the legitimate delete-then-reinsert succeed with the
# promote link intact, while a genuine dangler is still refused at COMMIT.
# ON DELETE SET NULL was rejected: it nulls target_item even when the item IS
# restored, destroying promote provenance on every reload.

FINDINGS_SCHEMA_SQL = """
CREATE TABLE findings (
  id                 TEXT PRIMARY KEY CHECK (length(id) BETWEEN 3 AND 200),
  date               TEXT NOT NULL,
  finding_kind       TEXT NOT NULL,
  review_context     TEXT NOT NULL,
  observed_sha       TEXT,
  title              TEXT NOT NULL,
  finding_text       TEXT NOT NULL,
  why_matters        TEXT NOT NULL,
  next_steps         TEXT NOT NULL,
  disposition        TEXT NOT NULL DEFAULT 'open' CHECK (disposition IN
                       ('open','actionable','actioned','dismissed','promoted')),
  disposition_reason TEXT,
  urgency            TEXT,
  breadth            TEXT,
  confidence         TEXT,
  reconsider_after   TEXT,
  created_at         TEXT NOT NULL,
  imported_from      TEXT,
  related_paths      TEXT,
  suggested_sweep    TEXT,
  CHECK (disposition NOT IN ('actionable','dismissed')
         OR (disposition_reason IS NOT NULL AND length(disposition_reason) > 0))
);

CREATE TABLE finding_evidence (
  id         INTEGER PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  path       TEXT NOT NULL,
  pattern    TEXT,
  line_start INTEGER,
  line_end   INTEGER,
  note       TEXT
);

CREATE TABLE finding_links (
  id             INTEGER PRIMARY KEY,
  finding_id     TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN
                   ('promoted-to','informs','resolved-by','related-finding','duplicate-of')),
  target_item    TEXT REFERENCES items(id) DEFERRABLE INITIALLY DEFERRED,
  target_finding TEXT REFERENCES findings(id),
  note           TEXT
);

CREATE TABLE finding_events (
  seq        INTEGER PRIMARY KEY,
  at         TEXT NOT NULL,
  actor      TEXT NOT NULL,
  finding_id TEXT REFERENCES findings(id),
  action     TEXT NOT NULL,
  detail     TEXT
);

CREATE TABLE finding_sections (
  id         INTEGER PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,
  heading    TEXT NOT NULL,
  text       TEXT NOT NULL,
  UNIQUE (finding_id, position)
);

CREATE INDEX idx_findings_disposition ON findings(disposition);
CREATE INDEX idx_finding_events_finding ON finding_events(finding_id, seq);
CREATE INDEX idx_finding_sections_finding ON finding_sections(finding_id, position);
"""


# The v3 -> v4 delta applied by todo_db.MIGRATIONS[4] to an existing v3 database.
# SQLite cannot ALTER a foreign key, so finding_links is rebuilt: create, copy,
# drop, rename. Nothing references finding_links, so the drop is safe. No SQL
# comments here -- _split_ddl splits on ";" and a comment-only fragment would
# become a bogus statement.
FINDINGS_MIGRATION_V4_SQL = """
ALTER TABLE findings ADD COLUMN related_paths TEXT;
ALTER TABLE findings ADD COLUMN suggested_sweep TEXT;

CREATE TABLE finding_sections (
  id         INTEGER PRIMARY KEY,
  finding_id TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  position   INTEGER NOT NULL,
  heading    TEXT NOT NULL,
  text       TEXT NOT NULL,
  UNIQUE (finding_id, position)
);

CREATE INDEX idx_finding_sections_finding ON finding_sections(finding_id, position);

CREATE TABLE finding_links_v4 (
  id             INTEGER PRIMARY KEY,
  finding_id     TEXT NOT NULL REFERENCES findings(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL CHECK (kind IN
                   ('promoted-to','informs','resolved-by','related-finding','duplicate-of')),
  target_item    TEXT REFERENCES items(id) DEFERRABLE INITIALLY DEFERRED,
  target_finding TEXT REFERENCES findings(id),
  note           TEXT
);

INSERT INTO finding_links_v4 (id, finding_id, kind, target_item, target_finding, note)
  SELECT id, finding_id, kind, target_item, target_finding, note FROM finding_links;

DROP TABLE finding_links;

ALTER TABLE finding_links_v4 RENAME TO finding_links;
"""


def _split_ddl(sql: str) -> list[str]:
    """Semicolon-split our own controlled DDL. No string literal contains a ";"."""
    return [statement.strip() for statement in sql.split(";") if statement.strip()]


def finding_schema_statements() -> list[str]:
    """The v3 migration delta (``todo_db.MIGRATIONS[3]``): frozen history.

    Derived from FINDINGS_SCHEMA_V3_SQL, NOT from the current-shape
    FINDINGS_SCHEMA_SQL: a v2 database must reach exactly v3 here and then be
    carried to the current shape by MIGRATIONS[4]. Deriving this from the current
    DDL would create v4 tables at v3 and then collide with the v4 ALTERs.
    """
    return _split_ddl(FINDINGS_SCHEMA_V3_SQL)


def finding_migration_v4_statements() -> list[str]:
    """The v3 -> v4 delta (``todo_db.MIGRATIONS[4]``)."""
    return _split_ddl(FINDINGS_MIGRATION_V4_SQL)


import todo_db  # noqa: E402  (cycle-break: import must follow FINDINGS_SCHEMA_SQL; see note above)

# ---------------------------------------------------------------------------
# Constants

DISPOSITIONS = ("open", "actionable", "actioned", "dismissed", "promoted")
# Disposition values that the CHECK (and this module) require a reason for.
DISPOSITION_REASON_REQUIRED = frozenset({"actionable", "dismissed"})
# Terminal dispositions: no transition leaves them.
TERMINAL_DISPOSITIONS = frozenset({"actioned", "dismissed", "promoted"})
# Legal disposition transitions (everything else is rejected). `promoted` is
# reached only through `finding promote`, never a plain triage flip.
DISPOSITION_TRANSITIONS = frozenset(
    {
        ("open", "actionable"),
        ("open", "actioned"),
        ("open", "dismissed"),
        ("open", "promoted"),
        ("actionable", "actioned"),
        ("actionable", "dismissed"),
        ("actionable", "promoted"),
    }
)
LINK_KINDS = ("promoted-to", "informs", "resolved-by", "related-finding", "duplicate-of")

# Draft `status` frontmatter -> DB `disposition` (findings-domain phase-5 status
# map; sync applies it too). `merged-to-todo` is the legacy YAML-era label.
STATUS_TO_DISPOSITION = {
    "open": "open",
    "actionable": "actionable",
    "actioned": "actioned",
    "dismissed": "dismissed",
    "merged-to-todo": "promoted",
}

DEFAULT_DRAFTS_DIR = vbs.DEFAULT_DRAFTS_DIR
SYNCED_SUFFIX = ".synced"
SYNCED_PRUNE_DAYS = 30

# Bridge to the standalone todo-db drafts convention. BenchBox binds drafts to
# ~/.benchbox/finding-drafts/ while the standalone CLI defaults to
# ~/.todo-db/finding-drafts/<project-id>/. Those diverge silently, not loudly:
# at cutover `sync` reports "synced 0" and the banner counts zero unsynced
# drafts while a real draft sits stranded in the BenchBox directory. Honouring
# one env var in BOTH tools means the bound directory can be pinned once and
# every surface -- create, candidates, sync, and the planning banner -- agrees.
# The frontmatter schemas are already compatible; only the location diverged.
DRAFTS_DIR_ENV = "TODO_DB_FINDING_DRAFTS_DIR"


def resolve_drafts_dir() -> str:
    """The drafts directory every findings surface should use.

    ``TODO_DB_FINDING_DRAFTS_DIR`` wins when set and non-empty, so the same pin
    works before and after the standalone cutover; otherwise the BenchBox default.
    Reads the module global as its fallback (not a bound copy) so tests that
    override ``DEFAULT_DRAFTS_DIR`` keep working.
    """
    return os.environ.get(DRAFTS_DIR_ENV) or DEFAULT_DRAFTS_DIR


# ---------------------------------------------------------------------------
# Parser-completeness contract
#
# `validate_blind_spot.py` decides what a draft may CONTAIN; `parse_draft` below
# decides what actually reaches the DB. Those two sets drifted silently: the
# validator accepts 13 frontmatter keys and `_split_body` parses EVERY `## `
# section, but parse_draft read 5 keys plus `evidence` and only 4 sections --
# and `sync` still printed "synced 1". Measured over the live 65-record corpus
# (2026-07-29): 65 of 65 records lost content this way.
#
# These maps make the contract explicit and TOTAL, so a NEW validator field
# fails the guard test immediately instead of vanishing at sync time. The guard
# in tests/unit/scripts/test_todo_findings.py derives its expectation from
# `vbs.ALLOWED_FIELDS` itself -- never a hand-copied list, which would drift the
# same way parse_draft already drifted.

# Frontmatter keys parse_draft lands today, and where each one goes.
FRONTMATTER_HOMES = {
    "id": "findings.id",
    "date": "findings.date",
    "status": "findings.disposition",
    "finding_kind": "findings.finding_kind",
    "review_context": "findings.review_context",
    "observed_sha": "findings.observed_sha",
    "urgency": "findings.urgency",
    "breadth": "findings.breadth",
    "confidence": "findings.confidence",
    "evidence": "finding_evidence rows",
    "related_paths": "findings.related_paths (JSON array)",
    "suggested_sweep": "findings.suggested_sweep",
    "todo_id": "finding_links row, kind by status",
}

# Validator-accepted keys with no column yet. EMPTY as of schema v4, which landed
# a home for every key the validator accepts. It stays here deliberately: the
# guard test requires every accepted key to appear in one map or the other, so a
# newly added field must be given a home or named here, never silently dropped.
FRONTMATTER_HOMES_PENDING_V4: dict[str, str] = {}

# Body sections parse_draft lands today. Any OTHER `## ` heading is preserved
# verbatim in the v4 `finding_sections` table, in document order.
SECTION_HOMES = {
    "Finding": "findings.finding_text",
    "Why this matters": "findings.why_matters",
    "Suggested next steps": "findings.next_steps",
    "Triage log": "finding_events rows",
}
EXTRA_SECTION_HOME = "finding_sections rows"

# YYYY-MM-DD-HHMMSS-<kebab-slug> (matches the phase-1 validator's FILENAME_RE).
FINDING_ID_RE = vbs.FILENAME_RE

# `finding` subcommands that NEVER touch the DB (zero-credential capture path).
FINDING_OFFLINE_SUBCOMMANDS = frozenset({"create", "candidates"})
# `finding` subcommands that only READ the tracker (no mutation). Like item
# `list`/`show`, these use the normal connection -- they are NOT bulk readers,
# so they stay out of todo_db.READ_ONLY_COMMANDS (the remote-only RO-token path).
FINDING_READ_SUBCOMMANDS = frozenset({"list", "show"})
# Everything else (sync, dismiss, triage, link, promote) mutates the tracker.


# ---------------------------------------------------------------------------
# Classifier hook (called from todo_db._command_mutates_tracker)


def finding_command_mutates(args: argparse.Namespace) -> bool:
    """Whether a parsed ``finding`` subcommand can modify tracker state.

    Fail closed: an unrecognized subcommand is treated as mutating.
    """
    sub = getattr(args, "finding_command", None)
    if sub in FINDING_OFFLINE_SUBCOMMANDS or sub in FINDING_READ_SUBCOMMANDS:
        return False
    return True


# ---------------------------------------------------------------------------
# Draft parsing (reuses the phase-1 validator)


def _slugify(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", raw.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _split_body(body: str) -> tuple[str, dict[str, str]]:
    """Split a draft body into (title, {section_heading: text}).

    Title is the first top-level ``# `` heading; sections are keyed by the
    ``## `` heading text (e.g. ``Finding``, ``Why this matters``).
    """
    title = ""
    sections: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    def _flush() -> None:
        if current is not None:
            sections[current] = "\n".join(buf).strip()

    for line in vbs.normalize_newlines(body).splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            _flush()
            current = stripped[3:].strip()
            buf = []
        elif stripped.startswith("# ") and not title:
            title = stripped[2:].strip()
        else:
            buf.append(line)
    _flush()
    return title, sections


def parse_draft(path: Path) -> dict[str, Any]:
    """Parse a draft markdown file into finding-row fields.

    Validates via the phase-1 validator first; a malformed draft is a loud
    ``TodoError`` (never a partial insert).
    """
    errors = vbs.validate_file(path)
    if errors:
        raise todo_db.TodoError(f"draft {path.name} failed validation: " + "; ".join(errors))
    text = vbs.normalize_newlines(path.read_text(encoding="utf-8"))
    data, body, _ = vbs.parse_frontmatter(text)
    if data is None:  # pragma: no cover - validate_file already rejected this
        raise todo_db.TodoError(f"draft {path.name}: unparseable frontmatter")
    title, sections = _split_body(body)
    status = str(data.get("status", "open"))
    disposition = STATUS_TO_DISPOSITION.get(status, "open")
    triage_log = sections.get("Triage log", "").strip()
    reason: str | None = None
    if disposition in DISPOSITION_REASON_REQUIRED:
        # A fresh draft is `open`; a non-open draft carries its rationale in the
        # triage log. Never fabricate a judgement -- carry the prose verbatim,
        # or name the source when the log is absent.
        reason = triage_log or f"synced from draft {path.stem} (status {status})"
    return {
        "id": path.stem,
        "date": str(data["date"]),
        "finding_kind": str(data["finding_kind"]),
        "review_context": str(data["review_context"]),
        "observed_sha": _str_or_none(data.get("observed_sha")),
        "title": title,
        "finding_text": sections.get("Finding", "").strip(),
        "why_matters": sections.get("Why this matters", "").strip(),
        "next_steps": sections.get("Suggested next steps", "").strip(),
        "disposition": disposition,
        "disposition_reason": reason,
        "urgency": _str_or_none(data.get("urgency")),
        "breadth": _str_or_none(data.get("breadth")),
        "confidence": _str_or_none(data.get("confidence")),
        "evidence": list(data.get("evidence") or []),
        # Whether the draft ASSERTS an evidence list at all. An absent key means
        # "no assertion", which is not the same as "no evidence": stored rows may
        # have been curated at triage (or hand-mapped during an import) and must
        # not be deleted just because the capture file never mentioned them.
        "evidence_declared": "evidence" in data,
        "triage_log": triage_log,
        # v4 homes. related_paths is a JSON array so list ORDER (part of the
        # record) survives, and an absent key stays NULL rather than becoming
        # "[]" -- a record that never had the key stays distinguishable from one
        # that had an empty list.
        "related_paths": _json_list_or_none(data.get("related_paths")),
        "suggested_sweep": _str_or_none(data.get("suggested_sweep")),
        "todo_id": _str_or_none(data.get("todo_id")),
        # Legacy todo_id -> link kind, by status. A `promoted-to` edge asserts the
        # finding is `promoted`, so an `actioned` record must not use it.
        "todo_link_kind": ("promoted-to" if disposition == "promoted" else "resolved-by"),
        "sections": _extra_sections(sections),
        # Validator-accepted content with no column. Empty as of v4; kept so a
        # future field with no home is reported rather than dropped silently --
        # silent loss is what made `sync` print "synced 1" over 65 lossy records.
        "unmapped": unmapped_content(data, sections),
    }


def _json_list_or_none(value: Any) -> str | None:
    """A frontmatter list as a JSON array string, preserving order; None if absent."""
    if value is None:
        return None
    if not isinstance(value, list):
        return json.dumps([str(value)])
    return json.dumps([str(item) for item in value])


def _extra_sections(sections: dict[str, str]) -> list[dict[str, Any]]:
    """Body sections with no dedicated column, in DOCUMENT order.

    ``_split_body`` returns an insertion-ordered dict, so enumerating it preserves
    the order the headings appeared in. Blank sections are dropped: there is no
    content to preserve, and a row would imply there was.
    """
    extra: list[dict[str, Any]] = []
    for heading, text in sections.items():
        if heading in SECTION_HOMES or not text.strip():
            continue
        extra.append({"position": len(extra), "heading": heading, "text": text})
    return extra


def unmapped_content(data: dict[str, Any], sections: dict[str, str]) -> dict[str, list[str]]:
    """Validator-accepted content with no home in the current schema.

    Returns ``{"frontmatter": [...], "sections": [...]}`` naming keys and `## `
    headings that carry a value but that ``parse_draft`` cannot land. Empty lists
    mean the draft round-trips completely. Keys present but null/empty are NOT
    reported -- there is nothing to lose.
    """
    frontmatter = [
        key for key in sorted(FRONTMATTER_HOMES_PENDING_V4) if key in data and data[key] not in (None, "", [], {})
    ]
    # Sections outside SECTION_HOMES now land in finding_sections, so they are no
    # longer unmapped. Kept as an explicit empty list rather than removed: the
    # shape is part of sync's report, and a future heading class with no home
    # would repopulate it.
    return {"frontmatter": frontmatter, "sections": []}


# ---------------------------------------------------------------------------
# Row helpers

_FINDING_COLUMNS = (
    "id",
    "date",
    "finding_kind",
    "review_context",
    "observed_sha",
    "title",
    "finding_text",
    "why_matters",
    "next_steps",
    "disposition",
    "disposition_reason",
    "urgency",
    "breadth",
    "confidence",
    "reconsider_after",
    "created_at",
    "imported_from",
    "related_paths",
    "suggested_sweep",
)

# Fields compared to decide same-id-different-content on sync. Excludes
# created_at (assigned at first insert) and imported_from (provenance).
_CONTENT_FIELDS = (
    "date",
    "finding_kind",
    "review_context",
    "observed_sha",
    "title",
    "finding_text",
    "why_matters",
    "next_steps",
    "disposition",
)


def log_finding_event(
    conn: Any,
    actor: str,
    finding_id: str | None,
    action: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """Append a provenance row to ``finding_events`` (never the item ``events``
    table -- finding prose must not reach the committed export snapshot)."""
    conn.execute(
        "INSERT INTO finding_events (at, actor, finding_id, action, detail) VALUES (?, ?, ?, ?, ?)",
        (todo_db.utc_now(), actor, finding_id, action, json.dumps(detail or {}, sort_keys=True)),
    )


def get_finding(conn: Any, finding_id: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM findings WHERE id = ?", (finding_id,)).fetchone()
    if row is None:
        return None
    finding = dict(row)
    finding["evidence"] = [
        dict(r)
        for r in conn.execute(
            "SELECT path, pattern, line_start, line_end, note FROM finding_evidence WHERE finding_id = ? ORDER BY id",
            (finding_id,),
        )
    ]
    finding["links"] = [
        dict(r)
        for r in conn.execute(
            "SELECT kind, target_item, target_finding, note FROM finding_links WHERE finding_id = ? ORDER BY id",
            (finding_id,),
        )
    ]
    finding["sections"] = [
        dict(r)
        for r in conn.execute(
            "SELECT position, heading, text FROM finding_sections WHERE finding_id = ? ORDER BY position",
            (finding_id,),
        )
    ]
    finding["events"] = [
        dict(r)
        for r in conn.execute(
            "SELECT seq, at, actor, action, detail FROM finding_events WHERE finding_id = ? ORDER BY seq",
            (finding_id,),
        )
    ]
    return finding


def _require_finding(conn: Any, finding_id: str) -> dict[str, Any]:
    finding = get_finding(conn, finding_id)
    if finding is None:
        raise todo_db.TodoError(f"no finding {finding_id!r}")
    return finding


def insert_finding(conn: Any, actor: str, fields: dict[str, Any], *, imported_from: str | None = None) -> None:
    """Insert one finding row plus its evidence, INSIDE a caller-held write
    transaction. Raises ``TodoError`` on an invalid id or a reason-less
    terminal disposition (the CHECK enforces the latter too; this phrases it)."""
    finding_id = str(fields["id"])
    if not FINDING_ID_RE.match(finding_id):
        raise todo_db.TodoError(f"invalid finding id {finding_id!r} (expect YYYY-MM-DD-HHMMSS-<kebab-slug>)")
    disposition = fields.get("disposition", "open")
    if disposition not in DISPOSITIONS:
        raise todo_db.TodoError(f"invalid disposition {disposition!r}; one of {', '.join(DISPOSITIONS)}")
    reason = fields.get("disposition_reason")
    if disposition in DISPOSITION_REASON_REQUIRED and not (reason and str(reason).strip()):
        raise todo_db.TodoError(f"disposition {disposition!r} requires a reason (finding {finding_id!r})")
    for section in ("title", "finding_text", "why_matters", "next_steps"):
        if not str(fields.get(section) or "").strip():
            raise todo_db.TodoError(f"finding {finding_id!r} is missing body section {section!r}")
    row = {name: fields.get(name) for name in _FINDING_COLUMNS}
    row["id"] = finding_id
    row["disposition"] = disposition
    row["created_at"] = fields.get("created_at") or todo_db.utc_now()
    row["imported_from"] = fields.get("imported_from") or imported_from
    placeholders = ", ".join("?" for _ in _FINDING_COLUMNS)
    try:
        conn.execute(
            f"INSERT INTO findings ({', '.join(_FINDING_COLUMNS)}) VALUES ({placeholders})",
            tuple(row[name] for name in _FINDING_COLUMNS),
        )
    except todo_db.sqlite3.IntegrityError as exc:
        raise todo_db.TodoError(f"cannot insert finding {finding_id!r}: {exc}") from exc
    for entry in fields.get("evidence") or []:
        if not isinstance(entry, dict):
            raise todo_db.TodoError(f"finding {finding_id!r} evidence entry must be a mapping, got {entry!r}")
        path = entry.get("path")
        if not (isinstance(path, str) and path.strip()):
            raise todo_db.TodoError(f"finding {finding_id!r} evidence entry needs a non-empty path")
        conn.execute(
            "INSERT INTO finding_evidence (finding_id, path, pattern, line_start, line_end, note)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                finding_id,
                path,
                entry.get("pattern"),
                entry.get("line_start"),
                entry.get("line_end"),
                entry.get("note"),
            ),
        )
    for section in fields.get("sections") or []:
        conn.execute(
            "INSERT INTO finding_sections (finding_id, position, heading, text) VALUES (?, ?, ?, ?)",
            (finding_id, section["position"], section["heading"], section["text"]),
        )
    _insert_legacy_todo_link(conn, finding_id, fields)
    log_finding_event(
        conn, actor, finding_id, "sync" if imported_from is None else "import", {"disposition": disposition}
    )


def _insert_legacy_todo_link(conn: Any, finding_id: str, fields: dict[str, Any]) -> None:
    """Land a legacy ``todo_id`` as a ``finding_links`` row.

    Kind follows the record's status (see the v4 mapping in
    _project/specs/findings-domain.md): 'promoted-to' for a promoted finding,
    'resolved-by' for one that was merely actioned -- a 'promoted-to' edge asserts
    disposition 'promoted', so using it for an actioned record would misstate the
    history and break the promote invariant.

    A target that does not resolve is recorded with ``target_item = NULL`` and the
    original id preserved in the note, then surfaced by the caller. Reported, never
    silently skipped: the FK is DEFERRABLE, so a bare insert would otherwise fail
    the whole transaction at COMMIT with no indication of which record was at fault.
    """
    todo_id = fields.get("todo_id")
    if not todo_id:
        return
    kind = fields.get("todo_link_kind") or "resolved-by"
    resolved = conn.execute("SELECT 1 FROM items WHERE id = ?", (todo_id,)).fetchone() is not None
    conn.execute(
        "INSERT INTO finding_links (finding_id, kind, target_item, note) VALUES (?, ?, ?, ?)",
        (
            finding_id,
            kind,
            todo_id if resolved else None,
            f"imported from todo_id: {todo_id}" + ("" if resolved else " (no such item at import time)"),
        ),
    )


def _finding_matches(existing: dict[str, Any], fields: dict[str, Any]) -> bool:
    """True when a stored finding equals a re-parsed draft on content fields
    (sync idempotency). Different content is a conflict, never a merge."""
    for name in _CONTENT_FIELDS:
        if (existing.get(name) or None) != (fields.get(name) or None):
            return False
    return True


# Evidence-row fields compared to decide whether a re-parsed draft's evidence
# differs from what is stored. Order is significant: the draft's list order is
# the record, and `get_finding` reads evidence back `ORDER BY id`.
_EVIDENCE_FIELDS = ("path", "pattern", "line_start", "line_end", "note")

# Judgement fields are deliberately ABSENT from every comparison below. They are
# DB-owned once `todo finding triage` sets them, and a draft file captured before
# triage carries them as null -- reconciling them "from the draft" would silently
# wipe the triage judgement on every re-sync.
_DB_OWNED_FIELDS = ("urgency", "breadth", "confidence", "reconsider_after", "disposition_reason")


def _normalize_evidence(entries: Any) -> list[tuple[Any, ...]]:
    """Evidence entries as an ordered list of comparable tuples.

    Normalizes the two shapes that must compare equal: parsed-draft mappings
    (which omit absent keys) and stored rows (which carry explicit NULLs).
    """
    normalized: list[tuple[Any, ...]] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        normalized.append(tuple(entry.get(name) if entry.get(name) != "" else None for name in _EVIDENCE_FIELDS))
    return normalized


def _evidence_differs(existing: dict[str, Any], fields: dict[str, Any]) -> bool:
    """Whether a re-parsed draft's evidence disagrees with what is stored.

    A draft that declares no ``evidence:`` key makes no assertion, so it never
    counts as a difference. Treating an absent key as an empty list would let a
    re-sync DELETE evidence rows the draft never knew about -- exactly the case of
    a legacy record whose rows were hand-mapped at import time.
    """
    if not fields.get("evidence_declared"):
        return False
    return _normalize_evidence(existing.get("evidence")) != _normalize_evidence(fields.get("evidence"))


def _reconcile_evidence(conn: Any, actor: str, existing: dict[str, Any], fields: dict[str, Any]) -> None:
    """Replace a finding's evidence rows with the draft's, in ONE write txn.

    The draft file is authoritative for capture-owned payload, so an evidence-only
    edit is persisted rather than silently marked synced (which lost the edit) or
    reported as a content conflict (which the prose did not justify). The
    before/after is recorded in ``finding_events``, so the audit trail carries the
    change instead of the row quietly differing from its draft. ``existing`` is the
    row the caller already fetched -- re-reading it here would cost an extra hosted
    round-trip for no new information.
    """
    finding_id = str(existing["id"])
    before = _normalize_evidence(existing.get("evidence"))
    after = _normalize_evidence(fields.get("evidence"))
    with todo_db._write_txn(conn):
        conn.execute("DELETE FROM finding_evidence WHERE finding_id = ?", (finding_id,))
        for entry in fields.get("evidence") or []:
            if not isinstance(entry, dict):
                raise todo_db.TodoError(f"finding {finding_id!r} evidence entry must be a mapping, got {entry!r}")
            path = entry.get("path")
            if not (isinstance(path, str) and path.strip()):
                raise todo_db.TodoError(f"finding {finding_id!r} evidence entry needs a non-empty path")
            conn.execute(
                "INSERT INTO finding_evidence (finding_id, path, pattern, line_start, line_end, note)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (
                    finding_id,
                    path,
                    entry.get("pattern"),
                    entry.get("line_start"),
                    entry.get("line_end"),
                    entry.get("note"),
                ),
            )
        log_finding_event(
            conn,
            actor,
            finding_id,
            "resync_evidence",
            {"rows_before": len(before), "rows_after": len(after)},
        )


def _set_disposition(conn: Any, actor: str, finding_id: str, new: str, reason: str | None) -> None:
    """Apply a legal disposition transition with a conditional UPDATE (the same
    defense-in-depth as claim_item), INSIDE a caller-held write transaction."""
    finding = _require_finding(conn, finding_id)
    current = finding["disposition"]
    if current == new:
        raise todo_db.TodoError(f"finding {finding_id!r} is already {new}")
    if current in TERMINAL_DISPOSITIONS:
        raise todo_db.TodoError(f"finding {finding_id!r} is {current} (terminal); no further transition")
    if (current, new) not in DISPOSITION_TRANSITIONS:
        raise todo_db.TodoError(f"illegal disposition transition {current} -> {new} for {finding_id!r}")
    if new in DISPOSITION_REASON_REQUIRED and not (reason and reason.strip()):
        raise todo_db.TodoError(f"disposition {new!r} requires a --reason")
    updated = conn.execute(
        "UPDATE findings SET disposition = ?, disposition_reason = ? WHERE id = ? AND disposition = ?",
        (new, reason, finding_id, current),
    )
    if updated.rowcount != 1:
        raise todo_db.TodoError(f"finding {finding_id!r} disposition changed concurrently")
    log_finding_event(conn, actor, finding_id, "disposition", {"from": current, "to": new, "reason": reason})


# ---------------------------------------------------------------------------
# Sync (the authorized landing step)


def _mark_synced(path: Path) -> None:
    """Rename ``foo.md`` -> ``foo.md.synced`` so it drops out of the unsynced
    glob. Best-effort: idempotency is guaranteed by the id-absence check, not
    this rename, so a failure here just re-syncs (and no-ops) next time."""
    try:
        path.replace(path.with_name(path.name + SYNCED_SUFFIX))
    except OSError:  # pragma: no cover - best-effort; next sync is idempotent
        pass


def _prune_synced(drafts_dir: Path) -> int:
    """Delete ``*.md.synced`` files older than SYNCED_PRUNE_DAYS. Returns count."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=SYNCED_PRUNE_DAYS)
    pruned = 0
    for path in sorted(drafts_dir.glob("*" + SYNCED_SUFFIX)):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:  # pragma: no cover
            continue
        if mtime < cutoff:
            try:
                path.unlink()
                pruned += 1
            except OSError:  # pragma: no cover
                pass
    return pruned


def sync_drafts(conn: Any, actor: str, drafts_dir: str | Path) -> dict[str, Any]:
    """Insert-if-absent every draft under ``drafts_dir`` by filename-stem id.

    Idempotent: an identical already-landed finding is skipped (and its draft
    marked synced). Same-id/different *prose* is a loud error naming the id --
    never a merge (silent data loss in an audit-trail domain).

    Capture-owned payload the prose comparison does not cover -- today the
    evidence rows -- is reconciled IN PLACE from the draft and recorded in
    ``finding_events``. Comparing only the prose fields meant an evidence-only
    edit was marked ``.synced`` and lost with `sync` reporting success. Judgement
    fields (urgency/breadth/confidence/reconsider_after) are excluded from every
    comparison: they are DB-owned once triage sets them, so reconciling them from
    a pre-triage draft would wipe the judgement.

    A draft carrying validator-accepted content with no column in the current
    schema is still inserted, but is deliberately NOT marked ``.synced``: it stays
    in the unsynced glob so the planning banner keeps surfacing it and the file
    survives until v4 gives that content a home. Marking it synced would hide the
    one copy of the un-landed prose behind a rename.
    """
    drafts_dir = Path(drafts_dir).expanduser()
    result: dict[str, Any] = {
        "synced": [],
        "updated": [],
        "skipped": [],
        "conflicts": [],
        "pruned": 0,
        "unmapped": {},
    }
    if not drafts_dir.is_dir():
        return result
    for path in sorted(drafts_dir.glob("*.md")):
        if path.name == "README.md":
            continue
        fields = parse_draft(path)
        unmapped = fields.get("unmapped") or {}
        lossy = bool(unmapped.get("frontmatter") or unmapped.get("sections"))
        if lossy:
            # Surfaced, never swallowed: the caller warns. Until v4 lands there is
            # nowhere to put this content, so the only honest option is to say so.
            result["unmapped"][fields["id"]] = unmapped
        existing = get_finding(conn, fields["id"])
        if existing is not None:
            if not _finding_matches(existing, fields):
                # Prose disagreement is still a loud conflict, never a merge.
                result["conflicts"].append(fields["id"])
                continue
            if _evidence_differs(existing, fields):
                # Capture-owned payload the old comparison ignored entirely: the
                # draft used to be marked .synced and the edit lost silently.
                _reconcile_evidence(conn, actor, existing, fields)
                result["updated"].append(fields["id"])
            else:
                result["skipped"].append(fields["id"])
            if not lossy:
                _mark_synced(path)
            continue
        with todo_db._write_txn(conn):
            insert_finding(conn, actor, fields)
        if not lossy:
            _mark_synced(path)
        result["synced"].append(fields["id"])
    result["pruned"] = _prune_synced(drafts_dir)
    if result["conflicts"]:
        raise todo_db.TodoError(
            "sync conflict -- same filename-stem id, different content: "
            + ", ".join(result["conflicts"])
            + ". The DB copy and the draft disagree; resolve by hand (findings are an audit trail, never merged)."
        )
    return result


# ---------------------------------------------------------------------------
# Corpus import (phase 5)
#
# Deliberately NOT sync_drafts: that path renames each landed file to `*.synced`,
# and phase 5 must leave the tracked `_project/blind-spots/*.md` records untouched
# (the freeze window is both the requirement-2 proof and the rollback path -- phase
# 6 deletes, after its own gates). This importer only READS the corpus.
#
# Triage-log prose imports as ONE finding_events row per line, verbatim. Parsing it
# into structured disposition events was rejected as unfalsifiable: either trivial
# (a blob) or unachievable (prose parsing), and structured guesses corrupt an audit
# trail.

IMPORTED_TRIAGE_ACTION = "imported_triage_log"


def _triage_log_lines(triage_log: str) -> list[str]:
    """Non-empty triage-log lines, verbatim and in order."""
    return [line.rstrip() for line in triage_log.splitlines() if line.strip()]


def import_corpus(
    conn: Any,
    actor: str,
    corpus_dir: str | Path,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Import legacy records into the findings tables. Reads only; never writes files.

    Idempotent by filename-stem id: an already-imported record is reported as
    ``skipped``, so a re-run after a partial import is safe. ``dry_run`` parses and
    reports without touching the database at all.
    """
    corpus = Path(corpus_dir).expanduser()
    result: dict[str, Any] = {
        "imported": [],
        "skipped": [],
        "failed": [],
        "triage_events": 0,
        "danglers": [],
        "records": {},
    }
    for path in sorted(corpus.glob("*.md")):
        if path.name == "README.md":
            continue
        try:
            fields = parse_draft(path)
        except todo_db.TodoError as exc:
            result["failed"].append({"file": path.name, "error": str(exc)})
            continue
        finding_id = fields["id"]
        result["records"][finding_id] = fields
        lines = _triage_log_lines(fields.get("triage_log") or "")
        if fields.get("todo_id"):
            resolved = conn.execute("SELECT 1 FROM items WHERE id = ?", (fields["todo_id"],)).fetchone() is not None
            if not resolved:
                result["danglers"].append({"finding": finding_id, "todo_id": fields["todo_id"]})
        if get_finding(conn, finding_id) is not None:
            result["skipped"].append(finding_id)
            continue
        if dry_run:
            result["imported"].append(finding_id)
            result["triage_events"] += len(lines)
            continue
        with todo_db._write_txn(conn):
            insert_finding(conn, actor, fields, imported_from=str(path))
            for line in lines:
                log_finding_event(conn, actor, finding_id, IMPORTED_TRIAGE_ACTION, {"line": line})
        result["imported"].append(finding_id)
        result["triage_events"] += len(lines)
    return result


def parity_report(conn: Any, corpus_dir: str | Path, imported: dict[str, Any]) -> dict[str, Any]:
    """Machine-checkable parity of the corpus against what is stored.

    Falsifiable by construction: every check names the record and field it failed
    on, and ``ok`` is true only when every list below is empty.
    """
    corpus = Path(corpus_dir).expanduser()
    files = [p for p in sorted(corpus.glob("*.md")) if p.name != "README.md"]
    report: dict[str, Any] = {
        "corpus_records": len(files),
        "stored_records": 0,
        "body_diffs": [],
        "frontmatter_diffs": [],
        "section_diffs": [],
        "triage_log_diffs": [],
        "danglers": imported.get("danglers", []),
        "failed_parses": imported.get("failed", []),
    }
    for path in files:
        fields = imported["records"].get(path.stem)
        if fields is None:
            report["frontmatter_diffs"].append({"record": path.stem, "field": "<unparsed>"})
            continue
        stored = get_finding(conn, path.stem)
        if stored is None:
            report["frontmatter_diffs"].append({"record": path.stem, "field": "<absent from DB>"})
            continue
        report["stored_records"] += 1
        # Verbatim body columns, hash-compared.
        for column in ("title", "finding_text", "why_matters", "next_steps"):
            want, got = fields.get(column) or "", stored.get(column) or ""
            if hashlib.sha256(want.encode()).hexdigest() != hashlib.sha256(got.encode()).hexdigest():
                report["body_diffs"].append({"record": path.stem, "field": column})
        # Every frontmatter-derived column.
        for column in (
            "date",
            "finding_kind",
            "review_context",
            "observed_sha",
            "disposition",
            "related_paths",
            "suggested_sweep",
            "urgency",
            "breadth",
            "confidence",
        ):
            if (fields.get(column) or None) != (stored.get(column) or None):
                report["frontmatter_diffs"].append({"record": path.stem, "field": column})
        # Extra sections, verbatim and in order.
        want_sections = [(s["position"], s["heading"], s["text"]) for s in fields.get("sections") or []]
        got_sections = [(s["position"], s["heading"], s["text"]) for s in stored.get("sections") or []]
        if want_sections != got_sections:
            report["section_diffs"].append(
                {"record": path.stem, "expected": len(want_sections), "stored": len(got_sections)}
            )
        # One imported_triage_log event per non-empty line.
        want_lines = _triage_log_lines(fields.get("triage_log") or "")
        got_lines = [e for e in stored.get("events") or [] if e.get("action") == IMPORTED_TRIAGE_ACTION]
        if len(want_lines) != len(got_lines):
            report["triage_log_diffs"].append(
                {"record": path.stem, "expected_lines": len(want_lines), "stored_events": len(got_lines)}
            )
    report["ok"] = (
        report["corpus_records"] == report["stored_records"]
        and not report["body_diffs"]
        and not report["frontmatter_diffs"]
        and not report["section_diffs"]
        and not report["triage_log_diffs"]
        and not report["failed_parses"]
    )
    return report


def count_unsynced_drafts(drafts_dir: str | Path | None = None) -> int:
    """Local directory glob of unsynced drafts -- no credentials, no network.

    A draft is 'unsynced' until ``sync`` renames it to ``*.md.synced``; this is
    the count the phase-4 ``todo ready`` / ``todo stats`` banner shows.
    """
    directory = Path(drafts_dir if drafts_dir is not None else resolve_drafts_dir()).expanduser()
    if not directory.is_dir():
        return 0
    return sum(1 for p in directory.glob("*.md") if p.name != "README.md")


def open_findings_count(conn) -> int:
    """Count findings still awaiting triage (``disposition='open'``).

    A single cheap ``count(*)`` on the connection ``ready``/``stats`` already
    holds -- on the hosted backend it is served from the local embedded replica,
    so it adds no primary (network) round-trip to those commands.
    """
    row = conn.execute("SELECT count(*) FROM findings WHERE disposition = 'open'").fetchone()
    return int(row[0])


def findings_by_disposition(conn) -> dict[str, int]:
    """Findings grouped by disposition, for the additive ``todo stats`` key."""
    return {row[0]: row[1] for row in conn.execute("SELECT disposition, count(*) FROM findings GROUP BY disposition")}


def surfacing_banner(conn, drafts_dir: str | Path | None = None, open_count: int | None = None) -> str | None:
    """A one-line hint for ``ready``/``stats`` pointing at untriaged findings.

    Returns ``None`` when there is nothing to surface (no open findings and no
    unsynced drafts), so callers emit nothing at zero-state and never perturb the
    machine-readable *stdout* of those commands. Callers must print the returned
    string to *stderr* (the stdout contract is items-domain only).

    ``drafts_dir`` defaults to ``DEFAULT_DRAFTS_DIR`` resolved at call time (not
    bound at definition), so the default remains overridable for tests.
    ``open_count`` lets a caller that already has the number (``stats``) skip the
    aggregate entirely.
    """
    if drafts_dir is None:
        drafts_dir = resolve_drafts_dir()
    if open_count is None:
        open_count = open_findings_count(conn)
    draft_count = count_unsynced_drafts(drafts_dir)
    if not open_count and not draft_count:
        return None
    parts = []
    if open_count:
        parts.append(f"{open_count} open finding(s)")
    if draft_count:
        parts.append(f"{draft_count} unsynced draft(s)")
    destinations = []
    if open_count:
        destinations.append("todo finding list --disposition open")
    if draft_count:
        destinations.append("todo finding candidates")
    return f"→ {', '.join(parts)} awaiting triage — see: {'; '.join(destinations)}"


# ---------------------------------------------------------------------------
# Capture (zero-credential draft write)

_GATE_TEXT = (
    "review-protocol §2 defect gate: a finding is a *class* blind spot (a gap in "
    "what the review looks for), never a single defect. A concrete bug goes to the "
    "severity table / a TODO, not here. Attest with --gate class-not-instance."
)


def create_draft(args: argparse.Namespace) -> Path:
    """Write a draft finding file (never the DB). Prints the §2 gate; requires
    the ``--gate class-not-instance`` attestation; a ``bug-class`` finding
    requires ``--fixed-by`` (a bug-class blind spot needs an already-landed
    fix)."""
    print(_GATE_TEXT, file=todo_db.sys.stderr)
    if args.gate != "class-not-instance":
        raise todo_db.TodoError("create requires --gate class-not-instance (the review-protocol §2 attestation)")
    kind = args.finding_kind
    if kind not in vbs.ALLOWED_KIND:
        raise todo_db.TodoError(f"finding_kind {kind!r} not in {sorted(vbs.ALLOWED_KIND)}")
    if kind == "bug-class" and not (args.fixed_by and args.fixed_by.strip()):
        raise todo_db.TodoError(
            "finding_kind 'bug-class' requires --fixed-by <ref> (a bug-class finding needs a landed fix)"
        )
    slug = _slugify(args.slug or args.title)
    if not slug:
        raise todo_db.TodoError("could not derive a slug; pass --slug <kebab-slug>")
    drafts_dir = Path(args.drafts_dir).expanduser()
    drafts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d-%H%M%S")
    stem = f"{timestamp}-{slug}"
    path = drafts_dir / f"{stem}.md"
    suffix = 2
    while path.exists():
        path = drafts_dir / f"{stem}-{suffix}.md"
        suffix += 1
    stem = path.stem
    front = {
        "id": stem,
        "date": timestamp[:10],
        "status": "open",
        "finding_kind": kind,
        "review_context": args.review_context,
    }
    if args.observed_sha:
        front["observed_sha"] = args.observed_sha
    lines = ["---"]
    for key, value in front.items():
        lines.append(f"{key}: {json.dumps(value) if key == 'review_context' else value}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {args.title}")
    lines.append("")
    lines.append("## Finding")
    lines.append(args.finding or "<verbatim audit text>")
    if kind == "bug-class":
        lines.append("")
        lines.append(f"Fixed by: {args.fixed_by}")
    lines.append("")
    lines.append("## Why this matters")
    lines.append(args.why or "<one short paragraph on the lesson, not the instance>")
    lines.append("")
    lines.append("## Suggested next steps")
    lines.append(args.next_steps or "- [ ] <concrete action>")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    errors = vbs.validate_file(path)
    if errors:
        path.unlink()
        raise todo_db.TodoError("generated draft failed validation (not written): " + "; ".join(errors))
    return path


# ---------------------------------------------------------------------------
# Promote (finding -> tracker item, atomic)


def promote_finding(
    conn: Any,
    actor: str,
    finding_id: str,
    *,
    new_item_id: str,
    title: str | None = None,
    priority: str = "medium",
    worktree: str | None = None,
    description: str | None = None,
) -> None:
    """Create a planning item from a finding, link it, and flip the finding to
    ``promoted`` -- all in ONE write transaction, so a payload failure (e.g. a
    duplicate item id) rolls back with NO orphan link and NO disposition flip.
    Mirrors ``todo_db.promote_deferral``."""
    with todo_db._write_txn(conn):
        finding = _require_finding(conn, finding_id)
        if finding["disposition"] in TERMINAL_DISPOSITIONS:
            raise todo_db.TodoError(f"finding {finding_id!r} is {finding['disposition']} (terminal); cannot promote")
        # Defaults must NOT inline the finding's verbatim review prose (title,
        # finding_text, why_matters): the new item lands in the version-
        # controlled export snapshot (items.jsonl) and its create event lands in
        # events.jsonl -- both exported. Copying prose here would smuggle exactly
        # the review text the export boundary keeps out of Git. Default to a
        # reference instead; a caller who wants prose in the item passes explicit
        # --title/--description and owns that choice. The finding id (a
        # kebab-slug) is a tolerable identifier.
        todo_db.create_item(
            conn,
            actor,
            item_id=new_item_id,
            title=title or f"Promoted finding {finding_id}"[:200],
            worktree=worktree or "main",
            priority=priority,
            description=description
            or (
                f"Promoted from finding {finding_id}. "
                f"Run `todo finding show {finding_id}` for the review prose "
                f"(deliberately kept out of version control)."
            ),
            _in_txn=True,
        )
        conn.execute(
            "INSERT INTO finding_links (finding_id, kind, target_item, note) VALUES (?, 'promoted-to', ?, ?)",
            (finding_id, new_item_id, f"promoted by {actor}"),
        )
        updated = conn.execute(
            "UPDATE findings SET disposition = 'promoted' WHERE id = ? AND disposition IN ('open','actionable')",
            (finding_id,),
        )
        if updated.rowcount != 1:
            raise todo_db.TodoError(f"finding {finding_id!r} disposition changed concurrently")
        log_finding_event(conn, actor, finding_id, "promote", {"new_item": new_item_id})


def add_link(
    conn: Any,
    actor: str,
    finding_id: str,
    *,
    kind: str,
    target_item: str | None,
    target_finding: str | None,
    note: str | None,
) -> None:
    if kind not in LINK_KINDS:
        raise todo_db.TodoError(f"invalid link kind {kind!r}; one of {', '.join(LINK_KINDS)}")
    if kind == "promoted-to":
        # A 'promoted-to' link is created only by `todo finding promote`, which
        # atomically flips the disposition alongside the link. Allowing it via
        # `link` would leave a promoted-to edge with no disposition change.
        raise todo_db.TodoError("'promoted-to' links are created by `todo finding promote`, not `link`")
    if bool(target_item) == bool(target_finding):
        raise todo_db.TodoError("link needs exactly one of --to-item / --to-finding")
    with todo_db._write_txn(conn):
        _require_finding(conn, finding_id)
        if target_item and conn.execute("SELECT 1 FROM items WHERE id = ?", (target_item,)).fetchone() is None:
            raise todo_db.TodoError(f"link target item {target_item!r} does not exist")
        if target_finding:
            _require_finding(conn, target_finding)
        try:
            conn.execute(
                "INSERT INTO finding_links (finding_id, kind, target_item, target_finding, note)"
                " VALUES (?, ?, ?, ?, ?)",
                (finding_id, kind, target_item, target_finding, note),
            )
        except todo_db.sqlite3.IntegrityError as exc:
            raise todo_db.TodoError(f"cannot link finding {finding_id!r}: {exc}") from exc
        log_finding_event(
            conn,
            actor,
            finding_id,
            "link",
            {"kind": kind, "target_item": target_item, "target_finding": target_finding},
        )


# ---------------------------------------------------------------------------
# Query helpers


def list_findings(conn: Any, *, disposition: str | None = None, rank: str | None = None) -> list[dict[str, Any]]:
    """List findings. Default order is disposition then age (created_at); the
    capture-time judgement fields (urgency/breadth/confidence) are often absent,
    so ranking by them is opt-in (``--rank``) and never the default, or missing
    values would launder guesses into a deterministic-looking order."""
    query = "SELECT id, disposition, finding_kind, urgency, breadth, confidence, created_at, title FROM findings"
    params: list[Any] = []
    if disposition:
        query += " WHERE disposition = ?"
        params.append(disposition)
    if rank in ("urgency", "breadth", "confidence"):
        # NULLs last, then the rank field descending, then age; still deterministic.
        query += f" ORDER BY ({rank} IS NULL), {rank} DESC, created_at, id"
    else:
        query += " ORDER BY disposition, created_at, id"
    return [dict(row) for row in conn.execute(query, params)]


# ---------------------------------------------------------------------------
# Parser + dispatch


def add_finding_subparsers(parser: argparse.ArgumentParser) -> None:
    """Attach the ``finding`` sub-subcommands to todo_db's top-level parser."""
    sub = parser.add_subparsers(dest="finding_command", required=True)

    p = sub.add_parser("create", help="write a draft finding (draft file only, never the DB)")
    p.add_argument("--title", required=True)
    p.add_argument("--finding-kind", required=True, choices=sorted(vbs.ALLOWED_KIND))
    p.add_argument("--review-context", required=True)
    p.add_argument("--gate", help="review-protocol §2 attestation; must be 'class-not-instance'")
    p.add_argument("--fixed-by", help="landed fix ref (required when --finding-kind bug-class)")
    p.add_argument("--slug", help="kebab-slug override (default: derived from --title)")
    p.add_argument("--finding", help="## Finding body text")
    p.add_argument("--why", help="## Why this matters body text")
    p.add_argument("--next-steps", dest="next_steps", help="## Suggested next steps body text")
    p.add_argument("--observed-sha", help="provenance SHA (not a lookup key)")
    p.add_argument("--drafts-dir", default=resolve_drafts_dir())

    p = sub.add_parser("candidates", help="list unsynced drafts (local glob, zero-credential)")
    p.add_argument("--drafts-dir", default=resolve_drafts_dir())

    p = sub.add_parser("list", help="list findings")
    p.add_argument("--disposition", choices=DISPOSITIONS)
    p.add_argument("--rank", choices=("urgency", "breadth", "confidence"), help="opt-in post-triage ranking")

    p = sub.add_parser("show", help="show one finding")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("sync", help="land drafts into the tracker (authorized landing step)")
    p.add_argument("--drafts-dir", default=resolve_drafts_dir())

    p = sub.add_parser("dismiss", help="dismiss a finding with a reason")
    p.add_argument("id")
    p.add_argument("--reason", required=True)

    p = sub.add_parser("triage", help="set judgement fields and/or move disposition")
    p.add_argument("id")
    p.add_argument("--urgency")
    p.add_argument("--breadth")
    p.add_argument("--confidence")
    p.add_argument("--reconsider-after", dest="reconsider_after")
    p.add_argument("--disposition", choices=("actionable", "actioned"))
    p.add_argument("--reason")

    p = sub.add_parser("link", help="link a finding to an item or another finding")
    p.add_argument("id")
    # 'promoted-to' is reserved for `todo finding promote` (it flips disposition
    # atomically), so it is not offered here.
    p.add_argument("--kind", required=True, choices=[k for k in LINK_KINDS if k != "promoted-to"])
    p.add_argument("--to-item", dest="to_item")
    p.add_argument("--to-finding", dest="to_finding")
    p.add_argument("--note")

    p = sub.add_parser("import", help="import the legacy corpus into the findings tables (phase 5)")
    p.add_argument("--corpus", default="_project/blind-spots", help="corpus directory (read-only)")
    p.add_argument("--dry-run", action="store_true", dest="dry_run", help="parse and report; touch no rows")
    p.add_argument("--report", action="store_true", help="print the machine-checkable parity report as JSON")

    p = sub.add_parser("promote", help="promote a finding to a planning item (atomic)")
    p.add_argument("id")
    p.add_argument("--to-item", dest="to_item", required=True)
    p.add_argument("--title")
    p.add_argument("--priority", default="medium", choices=todo_db.PRIORITIES)
    p.add_argument("--worktree")
    p.add_argument("--description")


def run_offline(actor: str, args: argparse.Namespace) -> int:
    """Handle the zero-credential subcommands (``create``, ``candidates``) with
    NO database connection -- capture must work with no creds and no network."""
    if args.finding_command == "create":
        path = create_draft(args)
        print(f"Recorded: {path}")
        print("Draft only -- run `todo finding sync` (a separate, authorized step) to land it.")
        return 0
    if args.finding_command == "candidates":
        directory = Path(args.drafts_dir).expanduser()
        drafts = sorted(p for p in directory.glob("*.md") if p.name != "README.md") if directory.is_dir() else []
        for path in drafts:
            print(path.name)
        print(f"{len(drafts)} unsynced draft(s) in {directory}")
        return 0
    raise todo_db.TodoError(f"unknown offline finding subcommand {args.finding_command!r}")  # pragma: no cover


def dispatch_finding(conn: Any, actor: str, args: argparse.Namespace) -> int:
    """Handle the DB-backed ``finding`` subcommands (list/show/sync/dismiss/
    triage/link/promote). ``create``/``candidates`` are handled offline in
    ``todo_db.main`` before any connection is opened."""
    command = args.finding_command
    if command == "list":
        for finding in list_findings(conn, disposition=args.disposition, rank=args.rank):
            print(f"{finding['id']:45s} {finding['disposition']:11s} {finding['finding_kind']:14s} {finding['title']}")
        return 0
    if command == "show":
        finding = _require_finding(conn, args.id)
        if args.json:
            print(json.dumps(finding, indent=2, sort_keys=True))
        else:
            _print_finding(finding)
        return 0
    if command == "sync":
        result = sync_drafts(conn, actor, args.drafts_dir)
        print(
            f"synced {len(result['synced'])}, updated {len(result['updated'])} (evidence reconciled),"
            f" skipped {len(result['skipped'])} (already landed),"
            f" pruned {result['pruned']} old .synced draft(s)"
        )
        _warn_unmapped(result.get("unmapped") or {})
        return 0
    if command == "dismiss":
        with todo_db._write_txn(conn):
            _set_disposition(conn, actor, args.id, "dismissed", args.reason)
        print(f"{args.id} dismissed")
        return 0
    if command == "triage":
        return _cmd_triage(conn, actor, args)
    if command == "link":
        add_link(
            conn,
            actor,
            args.id,
            kind=args.kind,
            target_item=args.to_item,
            target_finding=args.to_finding,
            note=args.note,
        )
        print(f"linked {args.id} [{args.kind}]")
        return 0
    if command == "import":
        return _cmd_import(conn, actor, args)
    if command == "promote":
        promote_finding(
            conn,
            actor,
            args.id,
            new_item_id=args.to_item,
            title=args.title,
            priority=args.priority,
            worktree=args.worktree,
            description=args.description,
        )
        print(f"finding {args.id} promoted to {args.to_item}")
        return 0
    raise todo_db.TodoError(f"unknown finding subcommand {command!r}")  # pragma: no cover


def _cmd_import(conn: Any, actor: str, args: argparse.Namespace) -> int:
    """Import (or dry-run) the legacy corpus and optionally print the parity report.

    Exit 1 when parity fails, so the rung is self-asserting: a report with any diff
    must not read as success.
    """
    result = import_corpus(conn, actor, args.corpus, dry_run=args.dry_run)
    mode = "dry-run" if args.dry_run else "imported"
    print(
        f"{mode}: {len(result['imported'])} record(s), skipped {len(result['skipped'])} (already present),"
        f" failed {len(result['failed'])}, triage-log events {result['triage_events']},"
        f" dangling todo_id {len(result['danglers'])}"
    )
    if args.dry_run:
        # Nothing was written, so a stored-vs-file comparison would be vacuous.
        # Report coverage and parse health only; w3 runs the real check in a scratch DB.
        for failure in result["failed"]:
            print(f"  FAILED {failure['file']}: {failure['error']}", file=todo_db.sys.stderr)
        for dangler in result["danglers"]:
            print(f"  dangling todo_id {dangler['todo_id']} on {dangler['finding']}", file=todo_db.sys.stderr)
        return 1 if result["failed"] else 0
    report = parity_report(conn, args.corpus, result)
    if args.report:
        print(json.dumps(report, indent=2, sort_keys=True))
    if not report["ok"]:
        print("PARITY FAILED", file=todo_db.sys.stderr)
        return 1
    print(f"parity OK: {report['stored_records']}/{report['corpus_records']} records, zero diffs")
    return 0


def _cmd_triage(conn: Any, actor: str, args: argparse.Namespace) -> int:
    updates: list[tuple[str, Any]] = []
    for field in ("urgency", "breadth", "confidence", "reconsider_after"):
        value = getattr(args, field)
        if value is not None:
            updates.append((field, value))
    if not updates and not args.disposition:
        raise todo_db.TodoError(
            "triage needs at least one of --urgency/--breadth/--confidence/--reconsider-after/--disposition"
        )
    with todo_db._write_txn(conn):
        _require_finding(conn, args.id)
        if updates:
            assignments = ", ".join(f"{field} = ?" for field, _ in updates)
            conn.execute(
                f"UPDATE findings SET {assignments} WHERE id = ?",
                (*[value for _, value in updates], args.id),
            )
            log_finding_event(conn, actor, args.id, "triage", dict(updates))
        if args.disposition:
            _set_disposition(conn, actor, args.id, args.disposition, args.reason)
    print(f"{args.id} triaged")
    return 0


def _warn_unmapped(unmapped: dict[str, dict[str, list[str]]]) -> None:
    """Warn on stderr about validator-accepted content with no column yet.

    Stderr, so the stdout summary line stays machine-readable. Naming the ids and
    the exact keys/headings turns what used to be a silent "synced 1" into a
    reviewable statement of what did NOT land.
    """
    if not unmapped:
        return
    print(
        f"warning: {len(unmapped)} draft(s) carry content with no column in schema "
        f"{todo_db.SCHEMA_VERSION} -- it did NOT land:",
        file=todo_db.sys.stderr,
    )
    for finding_id, detail in sorted(unmapped.items()):
        lost = [*detail.get("frontmatter", []), *(f"## {h}" for h in detail.get("sections", []))]
        print(f"  {finding_id}: {', '.join(lost)}", file=todo_db.sys.stderr)
    print(
        "  These drafts were left unsynced on purpose so the file survives until "
        "schema v4 lands a home (see _project/specs/findings-domain.md).",
        file=todo_db.sys.stderr,
    )


def _print_finding(finding: dict[str, Any]) -> None:
    print(f"== {finding['id']} [{finding['disposition']}] {finding['title']}")
    print(f"kind={finding['finding_kind']} date={finding['date']} review={finding['review_context']}")
    if finding.get("disposition_reason"):
        print(f"reason: {finding['disposition_reason']}")
    for label in ("urgency", "breadth", "confidence", "reconsider_after", "observed_sha"):
        if finding.get(label):
            print(f"{label}: {finding[label]}")
    print("-- Finding")
    print(finding["finding_text"])
    print("-- Why this matters")
    print(finding["why_matters"])
    print("-- Suggested next steps")
    print(finding["next_steps"])
    for section in finding.get("sections", []):
        # Verbatim, under the original heading: these carry the "why the review
        # missed it" meta-analysis the corpus exists for.
        print(f"-- {section['heading']}")
        print(section["text"])
    if finding.get("related_paths"):
        try:
            paths = json.loads(finding["related_paths"])
        except (TypeError, ValueError):  # pragma: no cover - stored by us as JSON
            paths = [finding["related_paths"]]
        print("related paths: " + ", ".join(str(path) for path in paths))
    if finding.get("suggested_sweep"):
        print(f"suggested sweep: {finding['suggested_sweep']}")
    for evidence in finding.get("evidence", []):
        loc = ""
        if evidence.get("line_start"):
            loc = f":{evidence['line_start']}"
            if evidence.get("line_end"):
                loc += f"-{evidence['line_end']}"
        print(f"evidence: {evidence['path']}{loc} {evidence.get('pattern') or ''}".rstrip())
        if evidence.get("note"):
            # The note is where the reviewer said WHY the path is evidence, so
            # hiding it from the default `show` withheld the reason for the row.
            # Indented continuation, so a long note never crowds the locator.
            print(f"    note: {evidence['note']}")
    for link in finding.get("links", []):
        target = link.get("target_item") or link.get("target_finding") or "(dangling)"
        print(f"link: {link['kind']} -> {target}")
