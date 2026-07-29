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
import json
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


def finding_schema_statements() -> list[str]:
    """The v3 migration delta: each CREATE statement, semicolon-split.

    Shared verbatim by ``todo_db.SCHEMA_SQL`` (fresh DBs) and
    ``todo_db.MIGRATIONS[3]`` (existing v2 DBs) so the two representations of the
    findings schema can never drift. FINDINGS_SCHEMA_SQL is our own controlled
    DDL: no string literal contains a ``;``.
    """
    return [statement.strip() for statement in FINDINGS_SCHEMA_SQL.split(";") if statement.strip()]


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
}

# Validator-accepted keys with NO home in schema v3. Every entry is a named,
# measured loss -- never a licensed omission -- and names the v4 home that will
# take it (see "Legacy field mapping (schema v4)" in
# _project/specs/findings-domain.md). The v4 migration empties this map; it must
# never be used to silence a newly added field.
FRONTMATTER_HOMES_PENDING_V4 = {
    "related_paths": "findings.related_paths (v4 column)",
    "suggested_sweep": "findings.suggested_sweep (v4 column)",
    "todo_id": "finding_links row, kind by status (v4 mapping)",
}

# Body sections parse_draft lands today. Any OTHER `## ` heading has no v3 home
# and is reported as unmapped until the v4 `finding_sections` table exists.
SECTION_HOMES = {
    "Finding": "findings.finding_text",
    "Why this matters": "findings.why_matters",
    "Suggested next steps": "findings.next_steps",
    "Triage log": "finding_events rows",
}
PENDING_SECTION_HOME_V4 = "finding_sections table (v4)"

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
        "triage_log": triage_log,
        # Content the validator accepted but that has no v3 column. Reported, not
        # dropped: silent loss here is what made `sync` print "synced 1" over 65
        # records that each lost content. v4 empties both lists.
        "unmapped": unmapped_content(data, sections),
    }


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
    unmapped_sections = [
        heading for heading in sorted(sections) if heading not in SECTION_HOMES and sections[heading].strip()
    ]
    return {"frontmatter": frontmatter, "sections": unmapped_sections}


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
    log_finding_event(
        conn, actor, finding_id, "sync" if imported_from is None else "import", {"disposition": disposition}
    )


def _finding_matches(existing: dict[str, Any], fields: dict[str, Any]) -> bool:
    """True when a stored finding equals a re-parsed draft on content fields
    (sync idempotency). Different content is a conflict, never a merge."""
    for name in _CONTENT_FIELDS:
        if (existing.get(name) or None) != (fields.get(name) or None):
            return False
    return True


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
    marked synced). Same-id/different-content is a loud error naming the id --
    never a merge (silent data loss in an audit-trail domain).

    A draft carrying validator-accepted content with no column in the current
    schema is still inserted, but is deliberately NOT marked ``.synced``: it stays
    in the unsynced glob so the planning banner keeps surfacing it and the file
    survives until v4 gives that content a home. Marking it synced would hide the
    one copy of the un-landed prose behind a rename.
    """
    drafts_dir = Path(drafts_dir).expanduser()
    result: dict[str, Any] = {"synced": [], "skipped": [], "conflicts": [], "pruned": 0, "unmapped": {}}
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
            if _finding_matches(existing, fields):
                result["skipped"].append(fields["id"])
                if not lossy:
                    _mark_synced(path)
            else:
                result["conflicts"].append(fields["id"])
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


def count_unsynced_drafts(drafts_dir: str | Path = DEFAULT_DRAFTS_DIR) -> int:
    """Local directory glob of unsynced drafts -- no credentials, no network.

    A draft is 'unsynced' until ``sync`` renames it to ``*.md.synced``; this is
    the count the phase-4 ``todo ready`` / ``todo stats`` banner shows.
    """
    directory = Path(drafts_dir).expanduser()
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
        drafts_dir = DEFAULT_DRAFTS_DIR
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
    p.add_argument("--drafts-dir", default=DEFAULT_DRAFTS_DIR)

    p = sub.add_parser("candidates", help="list unsynced drafts (local glob, zero-credential)")
    p.add_argument("--drafts-dir", default=DEFAULT_DRAFTS_DIR)

    p = sub.add_parser("list", help="list findings")
    p.add_argument("--disposition", choices=DISPOSITIONS)
    p.add_argument("--rank", choices=("urgency", "breadth", "confidence"), help="opt-in post-triage ranking")

    p = sub.add_parser("show", help="show one finding")
    p.add_argument("id")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("sync", help="land drafts into the tracker (authorized landing step)")
    p.add_argument("--drafts-dir", default=DEFAULT_DRAFTS_DIR)

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
            f"synced {len(result['synced'])}, skipped {len(result['skipped'])} (already landed),"
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
    for evidence in finding.get("evidence", []):
        loc = ""
        if evidence.get("line_start"):
            loc = f":{evidence['line_start']}"
            if evidence.get("line_end"):
                loc += f"-{evidence['line_end']}"
        print(f"evidence: {evidence['path']}{loc} {evidence.get('pattern') or ''}".rstrip())
    for link in finding.get("links", []):
        target = link.get("target_item") or link.get("target_finding") or "(dangling)"
        print(f"link: {link['kind']} -> {target}")
