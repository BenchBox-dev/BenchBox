"""Full-archive assurance tests for the canonical JoinOrder (IMDb 2013) dataset.

These re-express, at LOAD time on the full ~GB canonical archive a user actually
downloads, the strong JOB-grade guarantees the build pipeline only checks at
BUILD time and the unit suite only checks on the 50-row tiny fixture
(``tests/unit/core/joinorder/test_canonical_queries.py``):

  * cardinality -- every one of the 113 canonical queries reproduces the
    independent PostgreSQL 16.2 oracle in ``reference_cardinalities.json``;
  * FK integrity -- every declared foreign key resolves EXCEPT the reviewed,
    hash-locked legitimate dangling set in ``allowed_dangling_fks.json``
    (the canonical data has opt-in FKs / legitimate dangling references, so
    full closure is NOT asserted);
  * encoding fidelity -- NULLs are preserved (never coerced to '') and multibyte
    UTF-8 round-trips, pinned against values derived from the hash-locked archive.

They need the downloaded archive, so they REUSE the existing opt-in ``slow`` +
``integration`` markers (deselected from the default lane by pytest.ini's
``-m "not slow ..."``) and skip when the archive cannot be materialized. They do
not run in the default unit suite.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
import tomllib

duckdb = pytest.importorskip("duckdb", reason="DuckDB not installed")

from benchbox.core.joinorder.queries import JoinOrderQueryManager
from benchbox.core.joinorder.schema import JoinOrderSchema

pytestmark = [
    pytest.mark.slow,
    pytest.mark.integration,
    pytest.mark.duckdb,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
REFERENCE_CARDINALITIES = REPO_ROOT / "_project" / "joinorder" / "reference_cardinalities.json"
ALLOWED_DANGLING_FKS = REPO_ROOT / "_project" / "joinorder" / "allowed_dangling_fks.json"
RUNTIME_MANIFEST = REPO_ROOT / "benchbox" / "core" / "joinorder" / "data_manifest.toml"

KNOWN_ZERO_UNDERLYING = {"2c", "5a", "5b", "10b", "32a"}
FK_DECLARATION_RE = re.compile(
    r"FOREIGN KEY\s*\(\s*(\w+)\s*\)\s*REFERENCES\s*(\w+)\s*\(\s*(\w+)\s*\)",
    re.IGNORECASE,
)

# NULL-vs-empty fidelity, derived from the hash-locked archive
# (data_archive_hash 0f9061ba...). Each column stores NULLs, never '' -- the
# build pipeline's CANONICAL_NULL_COUNTS oracle, re-expressed at load time.
CANONICAL_NULL_COUNTS: dict[tuple[str, str], int] = {
    ("movie_companies", "note"): 1_271_989,
    ("cast_info", "note"): 22_007_252,
    ("title", "episode_of_id"): 985_048,
}

# Multibyte UTF-8 fidelity, pinned from the hash-locked archive: per column,
# (count of rows containing a non-ASCII byte, sha256 over the ordered
# id\x1fvalue\x1e stream of those rows). A latin1 misread, truncation, or
# re-encode would change the count or the hash.
UTF8_FIDELITY: dict[tuple[str, str], tuple[int, str]] = {
    ("title", "title"): (5, "99cc1eb7d57881fbf7966886718c359570ce85045ab759912e9fa278de582bc9"),
    ("char_name", "name"): (4, "73f997632839dcd98adff8b5fe89785c255cb6a450e63589eb8d5b2e9f0a6389"),
    ("aka_title", "title"): (2, "7f140d945dc9b7e0a759bf9131e628f23467decdcf82750060a616d1b2afe28f"),
}


def _quote_ident(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise AssertionError(f"unsafe identifier: {identifier}")
    return f'"{identifier}"'


def _underlying_count_query(query: str) -> str:
    """Wrap the query's FROM..WHERE in COUNT(*) to get the join cardinality.

    Mirrors tests/unit/core/joinorder/test_canonical_queries.py so the tiny and
    full-archive oracles are checked the same way.
    """
    from_match = re.search(r"\bFROM\b", query, flags=re.IGNORECASE)
    if from_match is None:
        raise AssertionError(f"query has no FROM clause: {query}")
    return "SELECT COUNT(*) AS underlying_row_count\n" + query[from_match.start() :].rstrip(";\n ")


def _declared_foreign_keys() -> set[tuple[str, str, str, str]]:
    schema = JoinOrderSchema()
    keys: set[tuple[str, str, str, str]] = set()
    for table in schema.get_table_names():
        for declaration in schema.get_table_info(table).get("foreign_keys", []) or []:
            match = FK_DECLARATION_RE.search(declaration)
            assert match is not None, f"unparseable FK on {table}: {declaration!r}"
            child_column, parent_table, parent_column = match.groups()
            keys.add((table, child_column, parent_table, parent_column))
    return keys


@pytest.fixture(scope="module")
def archive_dir() -> Path:
    """Fetch + sha256-verify the canonical archive through the runtime loader.

    Reuses a locally present/cached archive (no re-download); skips when the
    archive cannot be materialized (offline, missing optional deps, etc.).
    """
    from benchbox.core.joinorder.benchmark import JoinOrderBenchmark

    try:
        paths = JoinOrderBenchmark().generate_data()
    except Exception as exc:  # noqa: BLE001 - any fetch/verify failure => skip
        pytest.skip(f"canonical joinorder archive unavailable: {exc}")
    return paths[0].parent


@pytest.fixture(scope="module")
def archive_conn(archive_dir: Path) -> Any:
    conn = duckdb.connect(database=":memory:")
    for parquet_path in sorted(archive_dir.glob("*.parquet")):
        # DuckDB cannot bind a prepared parameter inside CREATE VIEW, so the
        # (machine-controlled) path is embedded as an escaped string literal.
        # Lazy views over Parquet avoid materializing the 74M-row archive in RAM.
        path_literal = "'" + str(parquet_path).replace("'", "''") + "'"
        conn.execute(f"CREATE VIEW {_quote_ident(parquet_path.stem)} AS SELECT * FROM read_parquet({path_literal})")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="module")
def reference_cardinalities() -> dict[str, Any]:
    return json.loads(REFERENCE_CARDINALITIES.read_text(encoding="utf-8"))["queries"]


@pytest.mark.parametrize("query_id", JoinOrderQueryManager().get_query_ids())
def test_full_archive_cardinality_matches_postgres_oracle(
    query_id: str,
    archive_conn: Any,
    reference_cardinalities: dict[str, Any],
) -> None:
    """Every canonical query reproduces the PostgreSQL oracle at full scale."""
    query = JoinOrderQueryManager().get_query(query_id)
    rows = archive_conn.execute(query).fetchall()
    underlying_rows = archive_conn.execute(_underlying_count_query(query)).fetchone()[0]
    expected = reference_cardinalities[query_id]

    assert len(rows) == expected["row_count"] == 1
    assert underlying_rows == expected["underlying_row_count"]
    if query_id in KNOWN_ZERO_UNDERLYING:
        assert underlying_rows == 0
    else:
        assert underlying_rows >= 1


def test_full_archive_fk_integrity_matches_allowed_dangling_set(archive_conn: Any) -> None:
    """Each declared FK resolves except the reviewed, hash-locked dangling set."""
    artifact = json.loads(ALLOWED_DANGLING_FKS.read_text(encoding="utf-8"))

    # The census must be hash-locked to the shipped manifest, or it is stale.
    manifest = tomllib.loads(RUNTIME_MANIFEST.read_text(encoding="utf-8"))
    assert artifact["data_archive_hash"] == manifest["data_archive_hash"]

    allowed = {
        (fk["child_table"], fk["child_column"], fk["parent_table"], fk["parent_column"]): fk["dangling_count"]
        for fk in artifact["foreign_keys"]
    }
    # The reviewed set must name exactly the schema's declared FKs (no drift).
    assert set(allowed) == _declared_foreign_keys()

    for (child_table, child_column, parent_table, parent_column), expected_dangling in sorted(allowed.items()):
        child = _quote_ident(child_table)
        parent = _quote_ident(parent_table)
        cc = _quote_ident(child_column)
        pc = _quote_ident(parent_column)
        dangling = archive_conn.execute(
            f"SELECT count(*) FROM {child} AS c WHERE c.{cc} IS NOT NULL "
            f"AND NOT EXISTS (SELECT 1 FROM {parent} AS p WHERE p.{pc} = c.{cc})"
        ).fetchone()[0]
        assert dangling == expected_dangling, (
            f"FK {child_table}.{child_column} -> {parent_table}.{parent_column}: "
            f"live dangling {dangling} != reviewed allowed {expected_dangling}"
        )


def test_full_archive_preserves_nulls_not_empty_strings(archive_conn: Any) -> None:
    """NULLs are preserved as NULL (never coerced to '') at full scale."""
    for (table, column), expected_nulls in CANONICAL_NULL_COUNTS.items():
        null_count, empty_count = archive_conn.execute(
            f"SELECT count(*) FILTER (WHERE {_quote_ident(column)} IS NULL), "
            f"count(*) FILTER (WHERE CAST({_quote_ident(column)} AS VARCHAR) = '') "
            f"FROM {_quote_ident(table)}"
        ).fetchone()
        assert null_count == expected_nulls
        assert empty_count == 0


def test_full_archive_utf8_multibyte_fidelity(archive_conn: Any) -> None:
    """Multibyte UTF-8 strings round-trip exactly (pinned count + content hash)."""
    for (table, column), (expected_count, expected_sha256) in UTF8_FIDELITY.items():
        rows = archive_conn.execute(
            f"SELECT id, {_quote_ident(column)} FROM {_quote_ident(table)} "
            f"WHERE {_quote_ident(column)} ~ '[^\\x00-\\x7F]' ORDER BY id, {_quote_ident(column)}"
        ).fetchall()
        assert len(rows) == expected_count
        digest = hashlib.sha256()
        for row_id, value in rows:
            digest.update(f"{row_id}\x1f{value}\x1e".encode())
        assert digest.hexdigest() == expected_sha256
