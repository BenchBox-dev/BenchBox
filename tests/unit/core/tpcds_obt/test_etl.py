import json
from pathlib import Path

import pytest

from benchbox.core.tpcds_obt import schema
from benchbox.core.tpcds_obt.etl.transformer import SUPPORTED_CHANNELS, TPCDSOBTTransformer

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class FakeConnection:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.statements: list[str] = []
        self.last_sql: str = ""

    def execute(self, sql: str) -> "FakeConnection":
        self.last_sql = " ".join(sql.split())
        self.statements.append(self.last_sql)

        if "COPY" in sql:
            start = sql.find("TO '") + 4
            end = sql.find("'", start)
            out_path = Path(sql[start:end])
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text("data\n", encoding="utf-8")

        return self

    def fetchone(self) -> tuple[int]:
        if "has_return" in self.last_sql:
            return (5,)
        return (15,)

    def fetchall(self) -> list[tuple[str, int]]:
        return [("store", 10), ("web", 5)]

    def close(self) -> None:
        return None


class FakeDuckDB:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.last_connection: FakeConnection | None = None

    def connect(self, _: str) -> FakeConnection:
        self.last_connection = FakeConnection(self.tmp_path)
        return self.last_connection


def test_union_query_contains_channel_literal() -> None:
    transformer = TPCDSOBTTransformer()
    columns = schema.get_obt_columns("minimal")

    sql = transformer._build_union_query(columns, ["store"])

    assert "CREATE OR REPLACE TABLE tpcds_sales_returns_obt AS" in sql
    assert "CAST('store' AS VARCHAR(10)) AS channel" in sql
    assert "FROM store_sales ss" in sql


def _make_fake_transform(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TPCDSOBTTransformer:
    """Return a TPCDSOBTTransformer wired to FakeDuckDB with source files stubbed out."""
    fake_duckdb = FakeDuckDB(tmp_path)
    transformer = TPCDSOBTTransformer(duckdb_module=fake_duckdb)

    def fake_resolve(base_dir: Path, table_name: str) -> Path:
        path = base_dir / f"{table_name}.dat"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        return path

    monkeypatch.setattr(transformer, "_resolve_source_path", fake_resolve)
    return transformer


def test_transform_with_fake_duckdb_writes_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Explicit dat format: transformer writes manifest with correct fields."""
    transformer = _make_fake_transform(tmp_path, monkeypatch)

    result = transformer.transform(
        tpcds_dir=tmp_path,
        output_dir=tmp_path / "out",
        mode="minimal",
        channels=SUPPORTED_CHANNELS,
        output_format="dat",
        scale_factor=1.0,
    )

    manifest_path = result["manifest"]
    output_path = result["table"]

    assert output_path.exists()
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    assert manifest["table"] == "tpcds_sales_returns_obt"
    assert manifest["rows_total"] == 15
    assert manifest["rows_with_returns"] == 5
    assert manifest["channels"] == list(SUPPORTED_CHANNELS)
    assert manifest["column_count"] == len(schema.get_obt_columns("minimal"))


def test_transform_default_format_is_parquet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """transform() with no output_format argument should produce a .parquet artifact."""
    transformer = _make_fake_transform(tmp_path, monkeypatch)

    result = transformer.transform(
        tpcds_dir=tmp_path,
        output_dir=tmp_path / "out",
        mode="minimal",
        channels=SUPPORTED_CHANNELS,
        scale_factor=1.0,
    )

    output_path = result["table"]
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))

    assert output_path.suffix == ".parquet", f"Expected .parquet, got {output_path.suffix}"
    assert output_path.exists()
    assert manifest["output_format"] == "parquet"


def test_parquet_output_materially_smaller_than_dat(tmp_path: Path) -> None:
    """Parquet output must be materially smaller than the equivalent .dat for a nullable OBT schema.

    Uses a real (tiny) DuckDB run with a synthetic in-memory table so we measure actual
    columnar encoding vs pipe-delimited text.  The assertion is intentionally lenient
    (parquet < 80 % of dat) to avoid flakiness while still catching an accidental
    fallback to row-oriented encoding.
    """
    import os

    import duckdb

    dat_path = tmp_path / "obt_test.dat"
    parquet_path = tmp_path / "obt_test.parquet"

    # Build a tiny synthetic table with many NULLable columns (mirrors OBT null density).
    # 500 rows × 20 columns where ~60 % of cells are NULL to exercise null suppression.
    cols_ddl = ", ".join(f"c{i} VARCHAR" for i in range(20))
    col_exprs = ", ".join(
        f"CASE WHEN (row_number() OVER () + {i}) % 5 < 3 THEN NULL ELSE 'value_{i}' END AS c{i}" for i in range(20)
    )
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE TABLE t ({cols_ddl})")
    conn.execute(f"INSERT INTO t SELECT {col_exprs} FROM range(500)")

    conn.execute(f"COPY t TO '{dat_path}' (DELIMITER '|', HEADER FALSE, NULL '')")
    conn.execute(f"COPY t TO '{parquet_path}' (FORMAT PARQUET)")
    conn.close()

    dat_size = os.path.getsize(dat_path)
    parquet_size = os.path.getsize(parquet_path)

    assert parquet_size < dat_size * 0.8, (
        f"Expected parquet ({parquet_size} bytes) to be < 80% of dat ({dat_size} bytes), "
        f"but ratio was {parquet_size / dat_size:.2%}"
    )
