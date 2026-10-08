from __future__ import annotations

import re

import pytest

from benchbox.platforms.base.ddl_helpers import strip_foreign_keys

pytestmark = [pytest.mark.unit, pytest.mark.fast]


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
    stmt = re.sub(
        r",?\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+[^\s(]+\s*(?:\([^)]*\))?\s*(?:ON\s+(?:DELETE|UPDATE)\s+\w+\s*)*",
        "",
        stmt,
        flags=re.IGNORECASE,
    )
    stmt = re.sub(r",\s*\)", ")", stmt)
    return stmt


def _old_doris_fk_only(stmt: str) -> str:
    stripped = re.sub(
        r",\s*FOREIGN\s+KEY\s*\([^)]*\)(?:\s+REFERENCES\s+[`\"\w]+\s*\([^)]*\))?",
        "",
        stmt,
        flags=re.IGNORECASE,
    )
    stripped = re.sub(
        r",\s*REFERENCES\s+[`\"\w]+\s*\([^)]*\)",
        "",
        stripped,
        flags=re.IGNORECASE,
    )
    return stripped


_NO_FK = """\
CREATE TABLE region (
    r_regionkey INTEGER NOT NULL,
    r_name      CHAR(25) NOT NULL,
    r_comment   VARCHAR(152)
)"""

_SINGLE_FK_BARE = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    o_comment    VARCHAR(79)
    FOREIGN KEY (o_custkey) REFERENCES customer(c_custkey)
)"""

_SINGLE_FK_LEADING_COMMA = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    o_comment    VARCHAR(79),
    FOREIGN KEY (o_custkey) REFERENCES customer(c_custkey)
)"""

_CONSTRAINT_NAME = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_partkey    INTEGER NOT NULL,
    l_comment    VARCHAR(44),
    CONSTRAINT lineitem_fk1 FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey)
)"""

_ON_DELETE_CASCADE = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_comment    VARCHAR(44),
    FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey) ON DELETE CASCADE
)"""

_ON_DELETE_ON_UPDATE = """\
CREATE TABLE part_supplier (
    ps_partkey   INTEGER NOT NULL,
    ps_suppkey   INTEGER NOT NULL,
    FOREIGN KEY (ps_partkey) REFERENCES part(p_partkey) ON DELETE SET NULL ON UPDATE CASCADE
)"""

_DOUBLE_QUOTED = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    FOREIGN KEY (o_custkey) REFERENCES "customer"(c_custkey)
)"""

_BACKTICK_QUOTED = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    FOREIGN KEY (o_custkey) REFERENCES `customer`(`c_custkey`)
)"""

_SCHEMA_QUALIFIED = """\
CREATE TABLE orders (
    o_orderkey   INTEGER NOT NULL,
    o_custkey    INTEGER NOT NULL,
    FOREIGN KEY (o_custkey) REFERENCES public.customer(c_custkey)
)"""

_FK_NOT_LAST = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey),
    l_comment    VARCHAR(44)
)"""

_MULTI_FK = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_partkey    INTEGER NOT NULL,
    l_suppkey    INTEGER NOT NULL,
    FOREIGN KEY (l_orderkey) REFERENCES orders(o_orderkey),
    FOREIGN KEY (l_partkey) REFERENCES part(p_partkey),
    FOREIGN KEY (l_suppkey) REFERENCES supplier(s_suppkey)
)"""

_CONSTRAINT_WITH_ON_DELETE = """\
CREATE TABLE lineitem (
    l_orderkey   INTEGER NOT NULL,
    l_comment    VARCHAR(44),
    CONSTRAINT lineitem_orders_fk FOREIGN KEY (l_orderkey)
        REFERENCES orders(o_orderkey) ON DELETE RESTRICT
)"""


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
            _MULTI_FK,
            _FK_NOT_LAST,
        ],
    ),
    (
        "doris",
        _old_doris_fk_only,
        [
            _NO_FK,
            _SINGLE_FK_LEADING_COMMA,
            _BACKTICK_QUOTED,
            _MULTI_FK,
        ],
    ),
]


def _sql_norm(s: str) -> str:
    s = re.sub(r"\s+", " ", s).strip()
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
    expected = _sql_norm(old_func(stmt))
    actual = _sql_norm(strip_foreign_keys(stmt))
    assert actual == expected, (
        f"Adapter '{adapter}': strip_foreign_keys() output differs from old regex.\n"
        f"Input:\n{stmt}\n\n"
        f"Old regex output (normalized):\n{expected}\n\n"
        f"New helper output (normalized):\n{actual}"
    )


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
    result = strip_foreign_keys(_ON_DELETE_ON_UPDATE)
    assert "FOREIGN KEY" not in result.upper()
    assert "SET NULL" not in result.upper()
    assert "ON UPDATE" not in result.upper()
    assert "CASCADE" not in result.upper()


def test_primary_key_preserved() -> None:
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
    stmt = "CREATE TABLE t (a INT, FOREIGN KEY (a) REFERENCES x(b) ON DELETE CASCADE, next_column VARCHAR(32))"
    result = strip_foreign_keys(stmt)
    assert "FOREIGN KEY" not in result.upper()
    assert "ON DELETE" not in result.upper()
    assert "next_column" in result, f"Trailing column was swallowed: {result!r}"
