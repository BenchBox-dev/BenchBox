"""Unit tests for scripts/publication/compare_db_digest.py.

The G2 root-neutrality gate compares a rebuilt root results.duckdb against
the live production database. Exact bytes can never match (wall-clock
generated_at stamp, 1-ULP float drift across runners), so the gate hashes
canonical logical content. These tests pin that contract: build-stamp and
float noise compare equal, real content changes do not.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

duckdb = pytest.importorskip("duckdb")

ROOT = Path(__file__).parents[4]
SCRIPT = ROOT / "scripts/publication/compare_db_digest.py"
SPEC = importlib.util.spec_from_file_location("compare_db_digest", SCRIPT)
assert SPEC and SPEC.loader
compare_db_digest = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(compare_db_digest)


def _write_db(path: Path, rows: list[tuple], extra_table: bool = False) -> None:
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE results (result_id VARCHAR, geomean_ms DOUBLE, rank INTEGER, generated_at VARCHAR)")
        for row in rows:
            con.execute("INSERT INTO results VALUES (?, ?, ?, ?)", row)
        if extra_table:
            con.execute("CREATE TABLE extra (id INTEGER)")
            con.execute("INSERT INTO extra VALUES (1)")
    finally:
        con.close()


BASE_ROWS = [
    ("r1", 50.52781415620743, 1, "2026-09-03T00:00:00+00:00"),
    ("r2", 23.624040633774726, 2, "2026-09-03T00:00:00+00:00"),
]


def test_same_content_different_build_stamp_is_equivalent(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    _write_db(
        second,
        [(rid, geo, rank, "2026-09-04T12:34:56+00:00") for rid, geo, rank, _ in BASE_ROWS],
    )
    assert compare_db_digest.canonical_digest(first) == compare_db_digest.canonical_digest(second)
    assert compare_db_digest.compare_databases(first, second) == []


def test_one_ulp_float_drift_is_equivalent(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    drifted = [(rid, float(f"{geo:.15g}") + 1e-15 * abs(geo), rank, ts) for rid, geo, rank, ts in BASE_ROWS]
    _write_db(second, drifted)
    assert compare_db_digest.compare_databases(first, second) == []


def test_changed_rank_fails(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    _write_db(second, [(rid, geo, rank + 1, ts) for rid, geo, rank, ts in BASE_ROWS])
    findings = compare_db_digest.compare_databases(first, second)
    assert len(findings) == 1 and "refusing deploy" in findings[0]


def test_added_row_fails(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    _write_db(second, [*BASE_ROWS, ("r3", 1.0, 3, "2026-09-03T00:00:00+00:00")])
    assert compare_db_digest.compare_databases(first, second) != []


def test_added_table_fails(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    _write_db(second, BASE_ROWS, extra_table=True)
    assert compare_db_digest.compare_databases(first, second) != []


def test_material_float_change_fails(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    doubled = [(rid, geo * 2.0, rank, ts) for rid, geo, rank, ts in BASE_ROWS]
    _write_db(second, doubled)
    assert compare_db_digest.compare_databases(first, second) != []


def test_missing_file_is_fail_closed(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    _write_db(first, BASE_ROWS)
    findings = compare_db_digest.compare_databases(first, tmp_path / "absent.duckdb")
    assert findings and "missing" in findings[0]
    assert compare_db_digest.main(["compare", str(first), str(tmp_path / "absent.duckdb")]) == 1
    assert compare_db_digest.main(["digest", str(tmp_path / "absent.duckdb")]) == 2


def test_cli_compare_exit_codes(tmp_path: Path) -> None:
    first = tmp_path / "a.duckdb"
    second = tmp_path / "b.duckdb"
    _write_db(first, BASE_ROWS)
    _write_db(second, BASE_ROWS)
    assert compare_db_digest.main(["compare", str(first), str(second)]) == 0
    assert compare_db_digest.main(["digest", str(first)]) == 0
