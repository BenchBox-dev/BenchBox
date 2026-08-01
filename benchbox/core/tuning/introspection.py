"""Post-load introspection receipts: corroborate the applied ledger.

Per TODO ``tuning-introspection-receipts-20260716`` and the design note
``docs/development/tuning-introspection-receipts.md``. Builds on the
applied-tuning ledger (ADR-001) -- the ledger records *what executed* and
derives ``applied_unverified``; this module corroborates those statements
against the real database catalog and lets the adapter upgrade to
``applied_verified`` **only when corroborated**.

Two must-preserve invariants:

* **``applied_verified`` is earned, never asserted.** :func:`corroborate`
  upgrades only when every catalog-backed (``verifiable``) executed
  ddl/post_load statement is ``corroborated`` and at least one such
  statement exists. Anything absent / mismatched / unverifiable, or any
  introspection error, keeps the run at ``applied_unverified``. The ledger
  alone can never mint verification.
* **Introspection never breaks or slows a run.** The :class:`Introspector`
  contract is bounded, structured catalog reads wrapped non-fatal; a
  degraded state carries ``error`` and corroboration refuses the upgrade.

Platform-agnostic by construction: :func:`corroborate` classifies ledger
statements by generic SQL shape (``CREATE INDEX``, ``CREATE TABLE ... ORDER
BY``, ``SET``/``PRAGMA``, ``OPTIMIZE``); the per-platform catalog *reads*
that produce :class:`IntrospectedState` live in the platform introspectors.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from benchbox.core.tuning.applied_ledger import (
    PHASE_DDL,
    PHASE_POST_LOAD,
    PHASE_SESSION,
    AppliedStatement,
    AppliedTuningLedger,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Per-statement verdicts. The first three are catalog-backed outcomes; the
# last three are classification notes (transient / maintenance are
# non-blocking; unverifiable blocks the upgrade -- see the class table in the
# design note).
CORROBORATED = "corroborated"
ABSENT = "absent"
MISMATCH = "mismatch"
TRANSIENT = "transient"  # session SET/PRAGMA -- noted, non-blocking
MAINTENANCE = "maintenance"  # OPTIMIZE/merge -- noted, non-blocking
UNVERIFIABLE = "unverifiable"  # no rule / introspection error -- BLOCKS

#: Verdicts that count as catalog-backed (participate in the upgrade gate).
#: ``transient`` and ``maintenance`` are deliberately excluded: they are
#: noted but neither earn nor block verification.
_VERIFIABLE_VERDICTS = frozenset({CORROBORATED, ABSENT, MISMATCH, UNVERIFIABLE})

# Intent kinds (catalog-backed statement classes).
KIND_INDEX = "index"
KIND_SORT_KEY = "sort_key"
KIND_PARTITION_KEY = "partition_key"
#: Snowflake/BigQuery-style clustering key, applied by ``CLUSTER BY`` either on
#: ``CREATE TABLE`` or by a post-load ``ALTER TABLE``.
KIND_CLUSTER_KEY = "cluster_key"

_DDL_PHASES = frozenset({PHASE_DDL, PHASE_POST_LOAD})


# ---------------------------------------------------------------------------
# Structured catalog facts (produced by platform introspectors).
# ---------------------------------------------------------------------------
@dataclass
class IntrospectedObject:
    """One structured catalog fact.

    ``columns`` are normalized (case-folded, stripped) so corroboration is a
    plain tuple comparison. ``evidence`` carries the raw catalog row facts for
    the receipt (index name, engine key expression, etc.).
    """

    kind: str
    table: str | None
    columns: tuple[str, ...] = ()
    name: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntrospectedState:
    """Bounded catalog snapshot returned by an :class:`Introspector`.

    ``error`` is set when introspection degraded (query failed / timed out);
    ``truncated`` signals a bound was hit. Either way corroboration refuses the
    upgrade rather than guessing.
    """

    platform: str
    objects: list[IntrospectedObject] = field(default_factory=list)
    error: str | None = None
    truncated: bool = False


@runtime_checkable
class Introspector(Protocol):
    """Platform contract for post-load schema introspection.

    ``introspect`` performs BOUNDED, structured catalog reads (never raises --
    it returns an :class:`IntrospectedState` with ``error`` set on failure) and
    is scoped to the tables the *ledger* touched, so it cannot materially slow a
    run. Implementations MUST NOT screen-scrape engine DDL text where a
    structured catalog (``duckdb_indexes()``, ``system.tables``) exists.
    """

    platform: str

    def introspect(self, connection: Any, ledger: AppliedTuningLedger) -> IntrospectedState: ...


# ---------------------------------------------------------------------------
# Receipt model.
# ---------------------------------------------------------------------------
@dataclass
class ReceiptEntry:
    """Corroboration outcome for one executed ledger statement."""

    statement: str
    phase: str
    verdict: str
    kind: str | None = None
    table: str | None = None
    name: str | None = None
    expected_columns: tuple[str, ...] = ()
    observed_columns: tuple[str, ...] = ()
    diff: str | None = None
    reason: str | None = None
    evidence: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "statement": self.statement,
            "phase": self.phase,
            "verdict": self.verdict,
        }
        if self.kind:
            payload["kind"] = self.kind
        if self.table:
            payload["table"] = self.table
        if self.name:
            payload["name"] = self.name
        if self.expected_columns:
            payload["expected_columns"] = list(self.expected_columns)
        if self.observed_columns:
            payload["observed_columns"] = list(self.observed_columns)
        if self.diff:
            payload["diff"] = self.diff
        if self.reason:
            payload["reason"] = self.reason
        if self.evidence:
            payload["evidence"] = self.evidence
        return payload


@dataclass
class IntrospectionReceipt:
    """The corroboration receipt attached to the ``.applied.json`` companion.

    ``corroborated`` is the upgrade decision: ``True`` only when the trust rule
    (design note) holds. ``entries`` records every executed statement's verdict.
    """

    platform: str
    corroborated: bool
    entries: list[ReceiptEntry] = field(default_factory=list)
    observed: list[IntrospectedObject] = field(default_factory=list)
    error: str | None = None

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            counts[entry.verdict] = counts.get(entry.verdict, 0) + 1
        counts["verifiable_total"] = sum(1 for e in self.entries if e.verdict in _VERIFIABLE_VERDICTS)
        return counts

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "platform": self.platform,
            "corroborated": self.corroborated,
            "summary": self.summary,
            "entries": [e.to_dict() for e in self.entries],
        }
        if self.observed:
            payload["observed"] = [
                {
                    "kind": obj.kind,
                    "table": obj.table,
                    "columns": list(obj.columns),
                    **({"name": obj.name} if obj.name else {}),
                    **({"evidence": obj.evidence} if obj.evidence else {}),
                }
                for obj in self.observed
            ]
        if self.error:
            payload["error"] = self.error
        return payload


# ---------------------------------------------------------------------------
# Statement classification (generic SQL shape -> intent).
# ---------------------------------------------------------------------------
@dataclass
class _Intent:
    """A classified, catalog-backed intent extracted from a ledger statement."""

    kind: str
    table: str | None
    columns: tuple[str, ...]
    name: str | None = None


_CREATE_INDEX_RE = re.compile(
    r"^\s*create\s+(?:unique\s+)?index\s+(?:if\s+not\s+exists\s+)?"
    r"(?P<name>[^\s(]+)\s+on\s+(?P<table>[^\s(]+)\s*\((?P<cols>[^)]*)\)",
    re.IGNORECASE | re.DOTALL,
)
# Key clauses may hold function expressions -- ClickHouse renders a date
# partition as ``PARTITION BY (toYYYYMM(l_shipdate))``. Allow one level of
# nested parens so the captured list is not truncated at the inner ``)``,
# which would make every expression key mismatch its own catalog fact.
_KEY_CLAUSE_COLUMNS = r"(?P<cols>(?:[^()]|\([^()]*\))*)"
_ORDER_BY_RE = re.compile(rf"\border\s+by\s*\({_KEY_CLAUSE_COLUMNS}\)", re.IGNORECASE | re.DOTALL)
_PARTITION_BY_RE = re.compile(rf"\bpartition\s+by\s*\({_KEY_CLAUSE_COLUMNS}\)", re.IGNORECASE | re.DOTALL)
# Bare keyword probes: used to fail closed when a key clause is visibly present
# but its column list did not parse (see _classify).
_ORDER_BY_KEYWORD_RE = re.compile(r"\border\s+by\b", re.IGNORECASE)
_PARTITION_BY_KEYWORD_RE = re.compile(r"\bpartition\s+by\b", re.IGNORECASE)
# ``ORDER BY tuple()`` is MergeTree's explicit "no sort key" form, not an
# unparsed clause -- it carries no columns to corroborate.
_ORDER_BY_NOOP_RE = re.compile(r"\border\s+by\s+tuple\s*\(\s*\)", re.IGNORECASE)
_CREATE_TABLE_RE = re.compile(
    r"^\s*create\s+(?:or\s+replace\s+)?table\s+(?:if\s+not\s+exists\s+)?(?P<table>[^\s(]+)",
    re.IGNORECASE,
)
_OPTIMIZE_RE = re.compile(r"^\s*optimize\s+table\s+(?P<table>[^\s;]+)", re.IGNORECASE)
_CLUSTER_BY_RE = re.compile(rf"\bcluster\s+by\s*\({_KEY_CLAUSE_COLUMNS}\)", re.IGNORECASE | re.DOTALL)
_CLUSTER_BY_KEYWORD_RE = re.compile(r"\bcluster\s+by\b", re.IGNORECASE)
# Snowflake applies a clustering key post-load: ``ALTER TABLE T CLUSTER BY (a, b)``.
_ALTER_TABLE_RE = re.compile(r"^\s*alter\s+table\s+(?P<table>[^\s(]+)", re.IGNORECASE)
# ``ALTER TABLE T RECLUSTER`` (and the RESUME/SUSPEND forms that toggle
# Snowflake's automatic reclustering service) reorganize existing data. They
# have no distinct catalog footprint of their own -- the clustering KEY is what
# CLUSTERING_KEY reports -- so they are maintenance, exactly like OPTIMIZE:
# recorded and noted, but they neither earn nor block verification.
_RECLUSTER_RE = re.compile(r"^\s*alter\s+table\s+\S+\s+(?:(?:resume|suspend)\s+)?recluster\b", re.IGNORECASE)
# Recognized transient (session/config) and maintenance prefixes.
_TRANSIENT_PREFIXES = ("set ", "pragma ", "set\t", "pragma\t", "reset ", "use ")
_MAINTENANCE_PREFIXES = ("optimize ", "vacuum", "analyze", "compact ")


def normalize_identifier(value: Any) -> str:
    """Case-fold and strip quoting from a single SQL identifier."""
    text = str(value).strip()
    # Drop one layer of common quoting (", `, [], ').
    if (
        len(text) >= 2
        and text[0] in "\"`'"
        and text[-1] == text[0]
        or len(text) >= 2
        and text[0] == "["
        and text[-1] == "]"
    ):
        text = text[1:-1]
    return text.strip().casefold()


def _has_balanced_outer_parentheses(text: str) -> bool:
    """Return whether one plain parenthesis pair encloses all of *text*."""
    if not text.startswith("(") or not text.endswith(")"):
        return False
    depth = 0
    for index, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
            if depth == 0 and index != len(text) - 1:
                return False
    return depth == 0


def normalize_columns(raw: Any) -> tuple[str, ...]:
    """Normalize a comma-separated column list (or a bracketed catalog list).

    Accepts ``"a, b"``, ``"[a, b]"`` (DuckDB ``expressions``), or an already
    split iterable. ClickHouse may represent a multi-column partition key as
    ``tuple(a, b)`` or ``(a, b)``; one balanced outer catalog wrapper is
    removed before splitting. Inner expression parentheses remain untouched.
    Returns a case-folded, order-preserving tuple with empty entries dropped.
    """
    if raw is None:
        return ()
    if isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        text = str(raw).strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        elif text[:6].casefold() == "tuple(" and text.endswith(")"):
            text = text[6:-1].strip()
        elif _has_balanced_outer_parentheses(text):
            text = text[1:-1].strip()
        items = text.split(",") if text else []
    normalized = [normalize_identifier(item) for item in items]
    return tuple(col for col in normalized if col)


def _statement_table(statement: AppliedStatement) -> str | None:
    """Best-effort normalized table name a ledger statement references."""
    text = str(statement.statement or "")
    m = _CREATE_INDEX_RE.match(text)
    if m:
        return normalize_identifier(m.group("table"))
    om = _OPTIMIZE_RE.match(text)
    if om:
        return normalize_identifier(om.group("table"))
    ct = _CREATE_TABLE_RE.match(text)
    if ct:
        return normalize_identifier(ct.group("table"))
    if statement.table:
        return normalize_identifier(statement.table)
    return None


def ledger_tables(ledger: AppliedTuningLedger) -> set[str]:
    """Normalized table names the executed ledger statements reference.

    Introspectors use this to BOUND their catalog reads to the tables actually
    touched (CREATE INDEX / CREATE TABLE / OPTIMIZE targets), so introspection
    cannot scan an unbounded catalog.
    """
    tables: set[str] = set()
    for stmt in ledger.executed_statements:
        table = _statement_table(stmt)
        if table:
            tables.add(table)
    return tables


def _classify(statement: AppliedStatement) -> tuple[str, list[_Intent]]:
    """Classify one executed statement into a verdict-class and its intents.

    Returns ``(class, intents)`` where ``class`` is one of ``"verifiable"``,
    ``TRANSIENT``, ``MAINTENANCE`` or ``UNVERIFIABLE``. Session-phase statements
    and SET/PRAGMA are transient; OPTIMIZE/VACUUM are maintenance; a recognized
    ddl-shape (CREATE INDEX / CREATE TABLE ORDER BY|PARTITION BY) yields a
    verifiable intent; anything else in a ddl/post_load phase is unverifiable
    (blocks the upgrade -- we do not guess an unknown statement into verified).

    A ``CREATE TABLE`` carrying BOTH an ``ORDER BY`` and a ``PARTITION BY``
    yields one intent per clause, so each must corroborate independently. One
    statement can physically apply two distinct key layouts (ClickHouse
    MergeTree does exactly this), and corroborating only the first would let a
    run reach ``applied_verified`` while the other key silently never applied.
    """
    text = str(statement.statement or "").strip()
    lowered = text.lower()

    if statement.phase == PHASE_SESSION or lowered.startswith(_TRANSIENT_PREFIXES):
        return TRANSIENT, []
    if lowered.startswith(_MAINTENANCE_PREFIXES):
        return MAINTENANCE, []

    m = _CREATE_INDEX_RE.match(text)
    if m:
        return "verifiable", [
            _Intent(
                kind=KIND_INDEX,
                table=normalize_identifier(m.group("table")),
                columns=normalize_columns(m.group("cols")),
                name=normalize_identifier(m.group("name")),
            )
        ]

    ct = _CREATE_TABLE_RE.match(text)
    if ct:
        table = normalize_identifier(ct.group("table"))
        intents: list[_Intent] = []
        order = _ORDER_BY_RE.search(text)
        if order:
            intents.append(_Intent(kind=KIND_SORT_KEY, table=table, columns=normalize_columns(order.group("cols"))))
        part = _PARTITION_BY_RE.search(text)
        if part:
            intents.append(_Intent(kind=KIND_PARTITION_KEY, table=table, columns=normalize_columns(part.group("cols"))))
        cluster = _CLUSTER_BY_RE.search(text)
        if cluster:
            intents.append(
                _Intent(kind=KIND_CLUSTER_KEY, table=table, columns=normalize_columns(cluster.group("cols")))
            )
        # Fail closed: a key clause we can SEE but could not parse must block the
        # upgrade rather than silently vanish while a sibling clause corroborates.
        # Dropping it would recreate exactly the hole this classifier closes.
        if order is None and _ORDER_BY_KEYWORD_RE.search(text) and not _ORDER_BY_NOOP_RE.search(text):
            return UNVERIFIABLE, []
        if cluster is None and _CLUSTER_BY_KEYWORD_RE.search(text):
            return UNVERIFIABLE, []
        if part is None and _PARTITION_BY_KEYWORD_RE.search(text):
            return UNVERIFIABLE, []
        if intents:
            return "verifiable", intents
        # A plain CREATE TABLE with no recognized key clause is not a tuning
        # footprint we can corroborate -> unverifiable (conservative).
        return UNVERIFIABLE, []

    # Snowflake applies its clustering key after load, so the tuning footprint
    # arrives as ALTER TABLE rather than CREATE TABLE.
    at = _ALTER_TABLE_RE.match(text)
    if at:
        if _RECLUSTER_RE.match(text):
            return MAINTENANCE, []
        table = normalize_identifier(at.group("table"))
        cluster = _CLUSTER_BY_RE.search(text)
        if cluster:
            return "verifiable", [
                _Intent(kind=KIND_CLUSTER_KEY, table=table, columns=normalize_columns(cluster.group("cols")))
            ]
        # Any other ALTER TABLE (including a CLUSTER BY we could not parse) has
        # no corroboration rule and must keep blocking the upgrade.
        return UNVERIFIABLE, []

    return UNVERIFIABLE, []


# ---------------------------------------------------------------------------
# Corroboration.
# ---------------------------------------------------------------------------
def _short_diff(expected: tuple[str, ...], observed: tuple[str, ...]) -> str:
    return f"expected {list(expected)} != observed {list(observed)}"


def _match_object(intent: _Intent, state: IntrospectedState) -> tuple[str, IntrospectedObject | None]:
    """Match an intent against catalog facts, returning ``(verdict, fact)``."""
    same_table = [
        obj
        for obj in state.objects
        if obj.kind == intent.kind and normalize_identifier(obj.table or "") == (intent.table or "")
    ]
    if not same_table:
        return ABSENT, None
    # Exact column match (order-sensitive) is corroboration. Prefer a
    # name-matched fact when the intent carries an index name.
    for obj in same_table:
        if obj.columns == intent.columns:
            return CORROBORATED, obj
    # Present-but-different columns -> mismatch. Prefer a name-matched fact for
    # the observed-columns diff, else the first fact on the table.
    named = next(
        (o for o in same_table if intent.name and normalize_identifier(o.name or "") == intent.name),
        None,
    )
    return MISMATCH, named or same_table[0]


def corroborate(ledger: AppliedTuningLedger, introspected_state: IntrospectedState | None) -> IntrospectionReceipt:
    """Corroborate the ledger against catalog facts and decide the upgrade.

    Platform-agnostic: consumes the executed ledger statements and a structured
    :class:`IntrospectedState`, classifies each statement (design-note table),
    and produces per-statement verdicts. The returned receipt's
    ``corroborated`` flag is ``True`` iff the trust rule holds -- at least one
    verifiable statement, and every verifiable statement ``corroborated``. A
    ``None`` / errored state marks every verifiable statement ``unverifiable``
    and refuses the upgrade. Never raises.
    """
    platform = introspected_state.platform if introspected_state else "unknown"
    state_error = None
    if introspected_state is None:
        state_error = "introspection unavailable (no state)"
    elif introspected_state.error:
        state_error = introspected_state.error
    elif introspected_state.truncated:
        # A bound hit means the catalog snapshot is incomplete: a match would
        # only prove the object appeared among the rows we happened to fetch,
        # and an ABSENT verdict cannot be trusted at all. Per this module's
        # contract (see IntrospectedState) a truncated snapshot is treated
        # exactly like a degraded one -- refuse the upgrade rather than certify
        # partial evidence as applied_verified.
        state_error = "introspection truncated (catalog row bound hit)"

    entries: list[ReceiptEntry] = []
    for stmt in ledger.executed_statements:
        klass, intents = _classify(stmt)

        if klass == TRANSIENT:
            entries.append(
                ReceiptEntry(
                    statement=stmt.statement,
                    phase=stmt.phase,
                    verdict=TRANSIENT,
                    reason="session/config statement -- transient, not corroboration-eligible",
                )
            )
            continue
        if klass == MAINTENANCE:
            entries.append(
                ReceiptEntry(
                    statement=stmt.statement,
                    phase=stmt.phase,
                    verdict=MAINTENANCE,
                    table=stmt.table,
                    reason="maintenance op -- no distinct catalog footprint",
                )
            )
            continue
        if klass == UNVERIFIABLE or not intents:
            entries.append(
                ReceiptEntry(
                    statement=stmt.statement,
                    phase=stmt.phase,
                    verdict=UNVERIFIABLE,
                    table=stmt.table,
                    reason="no corroboration rule for this statement",
                )
            )
            continue

        # One entry per verifiable intent: a statement that applies two key
        # layouts must have BOTH corroborated to count toward the upgrade.
        for intent in intents:
            # If introspection degraded we cannot confirm the intent.
            if state_error is not None or introspected_state is None:
                entries.append(
                    ReceiptEntry(
                        statement=stmt.statement,
                        phase=stmt.phase,
                        verdict=UNVERIFIABLE,
                        kind=intent.kind,
                        table=intent.table,
                        name=intent.name,
                        expected_columns=intent.columns,
                        reason=f"introspection degraded: {state_error}",
                    )
                )
                continue

            verdict, fact = _match_object(intent, introspected_state)
            entry = ReceiptEntry(
                statement=stmt.statement,
                phase=stmt.phase,
                verdict=verdict,
                kind=intent.kind,
                table=intent.table,
                name=intent.name,
                expected_columns=intent.columns,
            )
            if fact is not None:
                entry.observed_columns = fact.columns
                entry.evidence = dict(fact.evidence) if fact.evidence else None
            if verdict == MISMATCH:
                observed = fact.columns if fact is not None else ()
                entry.diff = _short_diff(intent.columns, observed)
            elif verdict == ABSENT:
                entry.reason = f"no {intent.kind} on {intent.table} found in catalog"
            entries.append(entry)

    verifiable = [e for e in entries if e.verdict in _VERIFIABLE_VERDICTS]
    corroborated = bool(verifiable) and all(e.verdict == CORROBORATED for e in verifiable)
    # Belt-and-suspenders: a degraded state can never yield the upgrade even if
    # the ledger happened to contain no verifiable statements.
    if state_error is not None:
        corroborated = False

    return IntrospectionReceipt(
        platform=platform,
        corroborated=corroborated,
        entries=entries,
        observed=list(introspected_state.objects) if introspected_state else [],
        error=state_error,
    )


__all__ = [
    "ABSENT",
    "CORROBORATED",
    "Introspector",
    "IntrospectedObject",
    "IntrospectedState",
    "IntrospectionReceipt",
    "KIND_INDEX",
    "KIND_CLUSTER_KEY",
    "KIND_PARTITION_KEY",
    "KIND_SORT_KEY",
    "MAINTENANCE",
    "MISMATCH",
    "ReceiptEntry",
    "TRANSIENT",
    "UNVERIFIABLE",
    "corroborate",
    "ledger_tables",
    "normalize_columns",
    "normalize_identifier",
]
