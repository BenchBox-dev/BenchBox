"""Runtime parity checks for risky read_primitives platform variants."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import pytest

from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark
from benchbox.core.read_primitives.catalog import ResultContract, load_primitives_catalog

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]

duckdb = pytest.importorskip("duckdb", reason="duckdb not installed")

_TPCH_TABLES = (
    "customer",
    "lineitem",
    "nation",
    "orders",
    "part",
    "partsupp",
    "region",
    "supplier",
)

_DUCKDB_CONTRACT_SHAPE_QUERIES = (
    "json_aggregates",
    "array_agg_distinct",
    "array_slice",
    "array_distinct",
    "struct_construction",
    "array_of_struct",
    "map_construction",
    "list_filter",
    "list_reduce",
    "window_rank",
)

_EXTREME_BY_VARIANT_QUERIES = (
    "max_by_simple",
    "min_by_simple",
    "max_by_complex",
    "min_by_complex",
    "max_by_with_ties",
    "min_by_with_ties",
)

_DATAFUSION_VARIANT_QUERIES = (
    *_EXTREME_BY_VARIANT_QUERIES,
    "map_construction",
    "map_access",
    "map_keys_values",
    "window_rank",
)

_CLICKHOUSE_VARIANT_QUERIES = (
    "array_contains",
    "array_length",
    "array_min_max",
    "array_agg_distinct",
    "array_slice",
    "array_sort",
    "array_distinct",
    "struct_access",
    "array_of_struct",
    "map_keys_values",
    "list_filter",
    "list_reduce",
)


@pytest.fixture(scope="session")
def read_primitives_tpch_parquet_dir(tmp_path_factory):
    """Generate TPC-H SF=0.01 Parquet data for local parity engines."""
    data_dir = tmp_path_factory.mktemp("read_primitives_variant_tpch_sf001")
    conn = duckdb.connect(":memory:")
    try:
        conn.execute("INSTALL tpch; LOAD tpch; CALL dbgen(sf=0.01)")
        for table in _TPCH_TABLES:
            conn.execute(f"COPY {table} TO '{data_dir / f'{table}.parquet'}' (FORMAT PARQUET)")
    finally:
        conn.close()
    return data_dir


@pytest.fixture(scope="session")
def read_primitives_duckdb_conn(read_primitives_tpch_parquet_dir):
    """DuckDB reference connection loaded from the shared SF=0.01 Parquet data."""
    conn = duckdb.connect(":memory:")
    for table in _TPCH_TABLES:
        parquet_path = read_primitives_tpch_parquet_dir / f"{table}.parquet"
        conn.execute(f"CREATE TABLE {table} AS SELECT * FROM read_parquet('{parquet_path}')")
    yield conn
    conn.close()


@pytest.fixture(scope="session")
def read_primitives_queries_by_dialect():
    benchmark = ReadPrimitivesBenchmark()
    return {
        "duckdb": benchmark.get_queries(dialect="duckdb"),
        "datafusion": benchmark.get_queries(dialect="datafusion"),
        "clickhouse": benchmark.get_queries(dialect="clickhouse"),
    }


@pytest.fixture(scope="session")
def read_primitives_contracts():
    return {
        query_id: query.result_contract
        for query_id, query in load_primitives_catalog().queries.items()
        if query.result_contract is not None
    }


@pytest.fixture(scope="session")
def datafusion_ctx(read_primitives_tpch_parquet_dir):
    """DataFusion context registered with the same SF=0.01 Parquet tables."""
    datafusion = pytest.importorskip("datafusion", reason="datafusion not installed")
    ctx = datafusion.SessionContext()
    for table in _TPCH_TABLES:
        ctx.register_parquet(table, str(read_primitives_tpch_parquet_dir / f"{table}.parquet"))
    return ctx


@pytest.fixture(scope="session")
def clickhouse_session(read_primitives_tpch_parquet_dir):
    """ClickHouse-local session backed by the same SF=0.01 Parquet tables."""
    pytest.importorskip("chdb", reason="chdb not installed")
    from chdb import session as chdb_session

    sess = chdb_session.Session()
    sess.query("CREATE DATABASE IF NOT EXISTS tpch", "CSV")
    sess.query("USE tpch", "CSV")

    for table in _TPCH_TABLES:
        parquet_path = read_primitives_tpch_parquet_dir / f"{table}.parquet"
        sess.query(f"CREATE TABLE IF NOT EXISTS {table} ENGINE=File(Parquet, '{parquet_path}')", "CSV")

    return sess


def _duckdb_rows(conn: object, sql: str) -> list[tuple[Any, ...]]:
    return [tuple(row) for row in conn.execute(sql).fetchall()]  # type: ignore[union-attr]


def _datafusion_rows(ctx: object, sql: str) -> list[tuple[Any, ...]]:
    batches = ctx.sql(sql).collect()  # type: ignore[attr-defined]
    rows: list[tuple[Any, ...]] = []
    for batch in batches:
        for row_index in range(batch.num_rows):
            rows.append(
                tuple(batch.column(column_index)[row_index].as_py() for column_index in range(batch.num_columns))
            )
    return rows


def _clickhouse_rows(sess: object, sql: str) -> list[tuple[Any, ...]]:
    pyarrow = pytest.importorskip("pyarrow", reason="pyarrow not installed")
    ipc = pytest.importorskip("pyarrow.ipc", reason="pyarrow.ipc not installed")

    result = sess.query(sql, "Arrow")  # type: ignore[attr-defined]
    if result.has_error():
        raise RuntimeError(result.error_message())
    table = ipc.open_file(pyarrow.BufferReader(result.bytes())).read_all()
    return [tuple(row[name] for name in table.column_names) for row in table.to_pylist()]


def _canonical_value(value: Any, *, order_sensitive: bool, type_class: str = "scalar") -> Any:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value.normalize())
    if isinstance(value, float):
        return round(value, 10)
    if isinstance(value, str):
        stripped = value.rstrip()
        if stripped.startswith(("[", "{")):
            try:
                return _canonical_value(json.loads(stripped), order_sensitive=order_sensitive, type_class="json")
            except json.JSONDecodeError:
                return stripped
        return stripped
    if type_class == "map":
        if isinstance(value, dict):
            items = value.items()
        elif isinstance(value, (list, tuple)) and all(
            isinstance(item, (list, tuple)) and len(item) == 2 for item in value
        ):
            items = value
        else:
            return value
        return tuple(
            sorted(
                (
                    str(_canonical_value(key, order_sensitive=True)),
                    _canonical_value(cell, order_sensitive=True),
                )
                for key, cell in items
            )
        )
    if isinstance(value, dict):
        return tuple(
            (str(key), _canonical_value(cell, order_sensitive=order_sensitive))
            for key, cell in sorted(value.items(), key=lambda item: str(item[0]))
        )
    if isinstance(value, (list, tuple)):
        items = [_canonical_value(cell, order_sensitive=True) for cell in value]
        if not order_sensitive:
            return tuple(sorted(items, key=repr))
        return tuple(items)
    return value


def _canonical_rows(rows: list[tuple[Any, ...]], contract: ResultContract) -> list[tuple[Any, ...]]:
    column_contracts = list(contract.columns)
    canonical = [
        tuple(
            _canonical_value(
                cell,
                order_sensitive=column_contracts[index].order_sensitive,
                type_class=column_contracts[index].type_class,
            )
            for index, cell in enumerate(row)
        )
        for row in rows
    ]
    if not contract.row_identity:
        return canonical
    identity_indexes = [index for index, column in enumerate(column_contracts) if column.name in contract.row_identity]
    return sorted(canonical, key=lambda row: tuple(row[index] for index in identity_indexes))


def _canonical_rows_in_order(rows: list[tuple[Any, ...]], contract: ResultContract) -> list[tuple[Any, ...]]:
    column_contracts = list(contract.columns)
    return [
        tuple(
            _canonical_value(
                cell,
                order_sensitive=column_contracts[index].order_sensitive,
                type_class=column_contracts[index].type_class,
            )
            for index, cell in enumerate(row)
        )
        for row in rows
    ]


def _assert_shape_contract(rows: list[tuple[Any, ...]], contract: ResultContract) -> None:
    assert rows, "Runtime parity queries should return at least one row at SF=0.01"
    for row in rows:
        assert len(row) == len(contract.columns)
        for cell, column in zip(row, contract.columns):
            if cell is None:
                continue
            if column.type_class == "json":
                assert isinstance(
                    _canonical_value(cell, order_sensitive=column.order_sensitive, type_class=column.type_class),
                    (tuple, list),
                )
            elif column.type_class == "array":
                assert isinstance(cell, (list, tuple))
            elif column.type_class in {"struct", "map"}:
                assert isinstance(cell, (dict, tuple))


@pytest.mark.parametrize("query_id", _DUCKDB_CONTRACT_SHAPE_QUERIES)
def test_duckdb_reference_outputs_satisfy_declared_contracts(
    query_id,
    read_primitives_duckdb_conn,
    read_primitives_queries_by_dialect,
    read_primitives_contracts,
):
    """DuckDB reference rows should expose parseable nested values for risky families."""
    rows = _duckdb_rows(read_primitives_duckdb_conn, read_primitives_queries_by_dialect["duckdb"][query_id])

    _assert_shape_contract(rows, read_primitives_contracts[query_id])


@pytest.mark.parametrize("query_id", _DATAFUSION_VARIANT_QUERIES)
def test_datafusion_variants_match_duckdb_reference(
    query_id,
    read_primitives_duckdb_conn,
    datafusion_ctx,
    read_primitives_queries_by_dialect,
    read_primitives_contracts,
):
    """DataFusion variants retained in the catalog should match DuckDB reference rows."""
    reference_rows = _duckdb_rows(read_primitives_duckdb_conn, read_primitives_queries_by_dialect["duckdb"][query_id])
    comparison_rows = _datafusion_rows(datafusion_ctx, read_primitives_queries_by_dialect["datafusion"][query_id])
    contract = read_primitives_contracts[query_id]

    assert _canonical_rows(comparison_rows, contract) == _canonical_rows(reference_rows, contract)


@pytest.mark.parametrize("query_id", _EXTREME_BY_VARIANT_QUERIES)
def test_datafusion_extreme_by_variants_preserve_duckdb_reference_order(
    query_id,
    read_primitives_duckdb_conn,
    datafusion_ctx,
    read_primitives_queries_by_dialect,
    read_primitives_contracts,
):
    """MAX_BY/MIN_BY fallbacks must not rely on accidental row ordering."""
    reference_rows = _duckdb_rows(read_primitives_duckdb_conn, read_primitives_queries_by_dialect["duckdb"][query_id])
    comparison_rows = _datafusion_rows(datafusion_ctx, read_primitives_queries_by_dialect["datafusion"][query_id])
    contract = read_primitives_contracts[query_id]

    assert _canonical_rows_in_order(comparison_rows, contract) == _canonical_rows_in_order(reference_rows, contract)


@pytest.mark.parametrize("query_id", _EXTREME_BY_VARIANT_QUERIES)
def test_redshift_extreme_by_variants_preserve_duckdb_reference_order(
    query_id,
    read_primitives_duckdb_conn,
    read_primitives_queries_by_dialect,
    read_primitives_contracts,
):
    """Redshift MAX_BY/MIN_BY fallbacks are local-SQL-compatible and must stay ordered."""
    benchmark = ReadPrimitivesBenchmark()
    reference_rows = _duckdb_rows(read_primitives_duckdb_conn, read_primitives_queries_by_dialect["duckdb"][query_id])
    comparison_rows = _duckdb_rows(
        read_primitives_duckdb_conn, benchmark.query_manager.get_query(query_id, dialect="redshift")
    )
    contract = read_primitives_contracts[query_id]

    assert _canonical_rows_in_order(comparison_rows, contract) == _canonical_rows_in_order(reference_rows, contract)


@pytest.mark.parametrize("query_id", _CLICKHOUSE_VARIANT_QUERIES)
def test_clickhouse_variants_match_duckdb_reference(
    query_id,
    read_primitives_duckdb_conn,
    clickhouse_session,
    read_primitives_queries_by_dialect,
    read_primitives_contracts,
):
    """ClickHouse-local variants retained in the catalog should match DuckDB reference rows."""
    reference_rows = _duckdb_rows(read_primitives_duckdb_conn, read_primitives_queries_by_dialect["duckdb"][query_id])
    comparison_rows = _clickhouse_rows(clickhouse_session, read_primitives_queries_by_dialect["clickhouse"][query_id])
    contract = read_primitives_contracts[query_id]

    assert _canonical_rows(comparison_rows, contract) == _canonical_rows(reference_rows, contract)
