"""Execute canonical JoinOrder queries against the tiny fixture."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from benchbox.core.joinorder.queries import JoinOrderQueryManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

KNOWN_ZERO_UNDERLYING = {"2c", "5a", "5b", "10b", "32a"}
REPO_ROOT = Path(__file__).resolve().parents[4]
TINY_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "joinorder_canonical_tiny"
TINY_REFERENCE = REPO_ROOT / "_project" / "joinorder" / "tiny_reference_cardinalities.json"


@pytest.fixture(scope="module")
def tiny_reference() -> dict[str, Any]:
    return json.loads(TINY_REFERENCE.read_text(encoding="utf-8"))["queries"]


@pytest.fixture(scope="module")
def duckdb_conn() -> Any:
    duckdb = pytest.importorskip("duckdb")

    conn = duckdb.connect(database=":memory:")
    for parquet_path in sorted(TINY_FIXTURE.glob("*.parquet")):
        table_name = parquet_path.stem
        conn.execute(f"CREATE TABLE {table_name} AS SELECT * FROM read_parquet(?)", [str(parquet_path)])
    try:
        yield conn
    finally:
        conn.close()


def _underlying_count_query(query: str) -> str:
    from_match = re.search(r"\bFROM\b", query, flags=re.IGNORECASE)
    if from_match is None:
        raise AssertionError(f"query has no FROM clause: {query}")
    return "SELECT COUNT(*) AS underlying_row_count\n" + query[from_match.start() :].rstrip(";\n ")


@pytest.mark.parametrize("query_id", JoinOrderQueryManager().get_query_ids())
def test_canonical_query_matches_tiny_fixture_oracle(
    query_id: str,
    duckdb_conn: Any,
    tiny_reference: dict[str, Any],
) -> None:
    query = JoinOrderQueryManager().get_query(query_id)

    rows = duckdb_conn.execute(query).fetchall()
    underlying_rows = duckdb_conn.execute(_underlying_count_query(query)).fetchone()[0]
    expected = tiny_reference[query_id]

    assert len(rows) == expected["row_count"] == 1
    assert underlying_rows == expected["underlying_row_count"]
    if query_id in KNOWN_ZERO_UNDERLYING:
        assert underlying_rows == 0
    else:
        assert underlying_rows >= 1
