"""Behavioral-equivalence corpus tests for strip_foreign_keys().

Each adapter's OLD FK-strip regex is preserved as a private constant here so this
suite remains self-contained after w4 migrates the adapters. For every (adapter,
corpus_input) pair the shared helper must produce the same output as the old regex.

Doris is a special case: its regex strips both PRIMARY KEY and FOREIGN KEY in a
single pass. The equivalence test uses a Doris-specific helper that strips only the
FK portion (matching what the migrated adapter will do after w4).

QuestDB's old adapter helper also stripped inline column-level REFERENCES.
The equivalence matrix keeps comparing table-level FK behavior; inline
REFERENCES is now shared-helper behavior with direct correctness tests.
"""

from __future__ import annotations

import re

import pytest

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Old adapter regexes — preserved as private constants for regression testing.
# These must NOT be modified; they are the reference implementations.
# ---------------------------------------------------------------------------


def _old_singlestore(stmt: str) -> str:
    pattern = (
        r",?\s*(?:CONSTRAINT\s+`?\w+`?\s+)?"
        r"FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+`?\w+`?\s*\([^)]*\)"
        r"(?:\s+ON\s+(?:DELETE|UPDATE)\s+\w+(?:\s+\w+)?)?"
    )
    cleaned = re.sub(pattern, "", stmt, flags=re.IGNORECASE)
    cleaned = re.sub(r",(\s*\))", r"\1", cleaned)
    return cleaned


def _old_postgresql(stmt: str) -> str:
    return re.sub(
        r",\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[\w\"]+(?:\.[\w\"]+)?\s*\([^)]*\)[^,)]*",
        "",
        stmt,
        flags=re.IGNORECASE,
    )


def _old_starrocks(stmt: str) -> str:
    return re.sub(r",?\s*FOREIGN\s+KEY\s*\([^)]+\)\s*REFERENCES\s+\w+\s*\([^)]+\)", "", stmt, flags=re.IGNORECASE)


def _old_databend(stmt: str) -> str:
    stmt = re.sub(
        r",?\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[^\s,)]+\s*\([^)]*\)",
        "",
        stmt,
        flags=re.IGNORECASE,
    )
    stmt = re.sub(r",\s*,", ",", stmt)
    stmt = re.sub(r",\s*\)", ")", stmt)
    return stmt


def _old_questdb_fk_only(stmt: str) -> str:
    """QuestDB's old FK stripping — table-level FOREIGN KEY part only.

    Excludes the inline column-level REFERENCES strip, now covered directly as
    shared-helper behavior.
    """
    stmt = re.sub(
        r",?\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[^\s(]+\s*(?:\([^)]*\))?\s*(?:ON\s+(?:DELETE|UPDATE)\s+\w+\s*)*",
        "",
        stmt,
        flags=re.IGNORECASE,
    )
    stmt = re.sub(r",\s*\)", ")", stmt)
    return stmt


def _old_doris_fk_only(stmt: str) -> str:
    """Doris's FK-only portion of _inject_doris_ddl_clauses.

    Doris strips both PRIMARY KEY and FOREIGN KEY in one regex; only the
    FOREIGN KEY path is relevant for the shared helper comparison.
    We isolate it by applying only the FOREIGN KEY branch.
    """
    stripped = re.sub(
        r",\s*FOREIGN\s+KEY\s*\([^)]*\)(?:\s+REFERENCES\s+[`\"\w]+\s*\([^)]*\))?",
        "",
        stmt,
        flags=re.IGNORECASE,
    )
    # Also strip dangling REFERENCES clauses
    stripped = re.sub(
        r",\s*REFERENCES\s+[`\"\w]+\s*\([^)]*\)",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return stripped


# ---------------------------------------------------------------------------
# Corpus of CREATE TABLE statements
# ---------------------------------------------------------------------------

# No foreign keys — should be returned unchanged by all implementations.
_NO_FK = """\
CREATE TABLE region (
    r_regionkey INTEGER NOT NULL,
    r_name      CHAR(25) NOT NULL,
    r_comment   VARCHAR(152)
)"""

# Single FK as the last clause with no preceding comma — exercises the `,?` optional
# comma branch of the regex.
_SINGLE_FK_BARE = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    o_comment    VARCHAR(79)
    FOREIGN KEY (o_custkey) REFERENCES customer(c_custkey)
)"""

# Single FK preceded by a comma on the prior column line — most common form in DuckDB output.
_SINGLE_FK_LEADING_COMMA = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    o_comment    VARCHAR(79),
    FOREIGN KEY (o_custkey) REFERENCES customer(c_custkey)
)"""

# CONSTRAINT name prefix (MySQL-family, common in TPC-H migration scripts).
_CONSTRAINT_NAME = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_partkey    INTEGER NOT NULL,
    l_comment    VARCHAR(44),
    CONSTRAINT lineitem_fk1 FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey)
)"""

# ON DELETE CASCADE action.
_ON_DELETE_CASCADE = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_comment    VARCHAR(44),
    FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey) ON DELETE CASCADE
)"""

# ON DELETE + ON UPDATE compound.
_ON_DELETE_ON_UPDATE = """\
CREATE TABLE part_supplier (
    ps_partkey   INTEGER NOT NULL,
    ps_suppkey   INTEGER NOT NULL,
    FOREIGN KEY (ps_partkey) REFERENCES part(p_partkey) ON DELETE SET NULL ON UPDATE CASCADE
)"""

# Double-quoted identifier (PostgreSQL style).
_DOUBLE_QUOTED = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    FOREIGN KEY (o_custkey) REFERENCES "customer"(c_custkey)
)"""

# Backtick-quoted identifier (MySQL / SingleStore style).
_BACKTICK_QUOTED = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    FOREIGN KEY (o_custkey) REFERENCES `customer`(`c_custkey`)
)"""

# Schema-qualified reference (PostgreSQL schema.table).
_SCHEMA_QUALIFIED = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    FOREIGN KEY (o_custkey) REFERENCES public.customer(c_custkey)
)"""

# FK is NOT the last column — trailing comma must be cleaned.
_FK_NOT_LAST = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey),
    l_comment    VARCHAR(44)
)"""

# Multiple FK constraints.
_MULTI_FK = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_partkey    INTEGER NOT NULL,
    l_suppkey    INTEGER NOT NULL,
    FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey),
    FOREIGN KEY (l_partkey) REFERENCES part(p_partkey),
    FOREIGN KEY (l_suppkey) REFERENCES supplier(s_suppkey)
)"""

# FK with CONSTRAINT name AND ON DELETE.
_CONSTRAINT_WITH_ON_DELETE = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_comment    VARCHAR(44),
    CONSTRAINT lineitem_orders_fk FOREIGN KEY (l_orderkey)
        REFERENCES orders(o_orderkey) ON DELETE RESTRICT
)"""

# ---------------------------------------------------------------------------
# Adapters × corpus matrix
# ---------------------------------------------------------------------------

# Each entry: (adapter_name, old_func, list_of_corpus_inputs)
# Corpus inputs are chosen to match what each adapter actually encounters.
# Doris is FK-only (its full regex also strips PK; we compare FK-only path).
# QuestDB is table-level FK only in this equivalence matrix; inline REFERENCES
# stripping is intentionally tested as shared-helper behavior below.
_EQUIVALENCE_CASES: list[tuple[str, object, list[str]]] = [
    (
        "singlestore",
        _old_singlestore,
        [
            _NO_FK,
            _SINGLE_FK_BARE,
            _SINGLE_FK_LEADING_COMMA,
            _CONSTRAINT_NAME,
            _ON_DELETE_CASCADE,
            _BACKTICK_QUOTED,
            _FK_NOT_LAST,
            _MULTI_FK,
            _CONSTRAINT_WITH_ON_DELETE,
        ],
    ),
    (
        "postgresql",
        _old_postgresql,
        [
            _NO_FK,
            _SINGLE_FK_LEADING_COMMA,
            _ON_DELETE_CASCADE,
            _DOUBLE_QUOTED,
            _SCHEMA_QUALIFIED,
            _MULTI_FK,
        ],
    ),
    (
        "starrocks",
        _old_starrocks,
        [
            _NO_FK,
            _SINGLE_FK_BARE,
            _SINGLE_FK_LEADING_COMMA,
            _MULTI_FK,
        ],
    ),
    (
        "databend",
        _old_databend,
        [
            _NO_FK,
            _SINGLE_FK_BARE,
            _SINGLE_FK_LEADING_COMMA,
            _MULTI_FK,
            _FK_NOT_LAST,
        ],
    ),
    (
        "questdb",
        _old_questdb_fk_only,
        [
            _NO_FK,
            _SINGLE_FK_BARE,
            _SINGLE_FK_LEADING_COMMA,
            _ON_DELETE_CASCADE,
            # _ON_DELETE_ON_UPDATE excluded: old QuestDB regex only matches one word
            # after DELETE/UPDATE, so "ON DELETE SET NULL" leaves " NULL ON UPDATE CASCADE"
            # in the output. The new helper correctly handles multi-word actions and
            # intentionally diverges from the buggy old behavior.
            _MULTI_FK,
            _FK_NOT_LAST,
        ],
    ),
    (
        "doris",
        _old_doris_fk_only,
        [
            _NO_FK,
            # _SINGLE_FK_BARE excluded: old Doris regex starts with r",\s*FOREIGN" (comma
            # required), so it silently skips FK clauses with no preceding comma. The new
            # helper strips them correctly and intentionally diverges from the buggy old behavior.
            _SINGLE_FK_LEADING_COMMA,
            _BACKTICK_QUOTED,
            _MULTI_FK,
        ],
    ),
]


def _sql_norm(s: str) -> str:
    """Normalize whitespace for semantic DDL comparison.

    Old adapter regexes differed from the new helper only in trailing whitespace
    around the closing ``)``: PostgreSQL and QuestDB ate the newline via ``[^,)]*``
    / trailing ``\\s*``; the new helper preserves the newline. Both produce valid
    DDL — we compare semantics rather than exact whitespace formatting.
    """
    s = re.sub(r"\s+", " ", s).strip()
    # Remove whitespace immediately before ) — old regexes left "token)" while the
    # new helper may leave "token )" when preserving a newline before the closing paren.
    s = re.sub(r"\s+\)", ")", s)
    return s


@pytest.mark.parametrize(
    "adapter,old_func,stmt",
    [
        pytest.param(adapter, old_func, stmt, id=f"{adapter}-corpus{i}")
        for adapter, old_func, stmts in _EQUIVALENCE_CASES
        for i, stmt in enumerate(stmts)
    ],
)
def test_strip_foreign_keys_matches_old_adapter(adapter: str, old_func, stmt: str) -> None:
    """shared strip_foreign_keys() must be semantically equivalent to each adapter's old regex.

    Whitespace is normalized before comparison: old regexes differ from the new helper
    only in whether the closing ``)`` gets a preceding newline stripped. That cosmetic
    difference is irrelevant for DDL execution correctness.
    """
    expected = _sql_norm(old_func(stmt))
    actual = _sql_norm(strip_foreign_keys(stmt))
    assert actual == expected, (
        f"Adapter '{adapter}': strip_foreign_keys() output differs from old regex.\n"
        f"Input:\n{stmt}\n\n"
        f"Old regex output (normalized):\n{expected}\n\n"
        f"New helper output (normalized):\n{actual}"
    )


# ---------------------------------------------------------------------------
# Standalone helper correctness tests
# ---------------------------------------------------------------------------


def test_no_fk_passthrough() -> None:
    assert strip_foreign_keys(_NO_FK) == _NO_FK


def test_single_fk_removed() -> None:
    result = strip_foreign_keys(_SINGLE_FK_LEADING_COMMA)
    assert "FOREIGN KEY" not in result.upper()
    assert "REFERENCES" not in result.upper()
    assert "o_comment" in result


def test_inline_references_removed() -> None:
    stmt = "CREATE TABLE t (id INT, cust_id INT REFERENCES customer(id))"
    result = strip_foreign_keys(stmt)
    assert "REFERENCES" not in result.upper()
    assert "cust_id INT" in result


def test_inline_references_with_action_removed() -> None:
    stmt = "CREATE TABLE t (id INT, cust_id INT REFERENCES customer(id) ON DELETE SET NULL, note TEXT)"
    result = strip_foreign_keys(stmt)
    assert "REFERENCES" not in result.upper()
    assert "ON DELETE" not in result.upper()
    assert "cust_id INT" in result
    assert "note TEXT" in result


def test_constraint_name_fk_removed() -> None:
    result = strip_foreign_keys(_CONSTRAINT_NAME)
    assert "FOREIGN KEY" not in result.upper()
    assert "lineitem_fk1" not in result


def test_on_delete_cascade_removed() -> None:
    result = strip_foreign_keys(_ON_DELETE_CASCADE)
    assert "FOREIGN KEY" not in result.upper()
    assert "ON DELETE" not in result.upper()


def test_on_delete_on_update_removed() -> None:
    result = strip_foreign_keys(_ON_DELETE_ON_UPDATE)
    assert "FOREIGN KEY" not in result.upper()
    assert "ON DELETE" not in result.upper()
    assert "ON UPDATE" not in result.upper()


def test_multi_fk_all_removed() -> None:
    result = strip_foreign_keys(_MULTI_FK)
    assert "FOREIGN KEY" not in result.upper()
    assert "REFERENCES" not in result.upper()


def test_no_trailing_comma_after_removal() -> None:
    result = strip_foreign_keys(_SINGLE_FK_LEADING_COMMA)
    # Should not end the column list with a trailing comma before )
    assert ",\n)" not in result and ", )" not in result and ",)" not in result


def test_schema_qualified_reference_removed() -> None:
    result = strip_foreign_keys(_SCHEMA_QUALIFIED)
    assert "REFERENCES" not in result.upper()
    assert "public.customer" not in result


def test_backtick_quoted_reference_removed() -> None:
    result = strip_foreign_keys(_BACKTICK_QUOTED)
    assert "FOREIGN KEY" not in result.upper()
    assert "customer" not in result


def test_double_quoted_reference_removed() -> None:
    result = strip_foreign_keys(_DOUBLE_QUOTED)
    assert "FOREIGN KEY" not in result.upper()


def test_multi_word_on_action_removed() -> None:
    """ON DELETE SET NULL (two words after DELETE) must be fully stripped.

    Old QuestDB regex had a bug: ``\\w+`` only matched one word after DELETE/UPDATE,
    so ``SET NULL`` left `` NULL`` dangling in output. The new helper uses
    ``\\w+(?:\\s+\\w+)*`` to consume multi-word actions.
    """
    result = strip_foreign_keys(_ON_DELETE_ON_UPDATE)
    assert "FOREIGN KEY" not in result.upper()
    assert "SET NULL" not in result.upper()
    assert "ON UPDATE" not in result.upper()
    assert "CASCADE" not in result.upper()


def test_primary_key_preserved() -> None:
    """strip_foreign_keys must NOT touch PRIMARY KEY constraints."""
    stmt = """\
CREATE TABLE orders (
    o_orderkey INTEGER NOT NULL,
    PRIMARY KEY (o_orderkey),
    FOREIGN KEY (o_custkey) REFERENCES customer(c_custkey)
)"""
    result = strip_foreign_keys(stmt)
    assert "PRIMARY KEY" in result.upper()
    assert "FOREIGN KEY" not in result.upper()


def test_trailing_non_action_content_preserved() -> None:
    """A non-action token after a CASCADE must NOT be swallowed by the action match.

    Earlier versions used ``\\w+(?:\\s+\\w+)*`` which would greedily consume any
    trailing identifier ("CASCADE foo_bar" → both gone). The action keyword set is
    now bounded so the FK clause ends at CASCADE and downstream content survives.
    """
    stmt = "CREATE TABLE t (a INT, FOREIGN KEY (a) REFERENCES x(b) ON DELETE CASCADE, next_column VARCHAR(32))"
    result = strip_foreign_keys(stmt)
    assert "FOREIGN KEY" not in result.upper()
    assert "ON DELETE" not in result.upper()
    assert "next_column" in result, f"Trailing column was swallowed: {result!r}"
