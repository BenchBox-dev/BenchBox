"""Unit tests for TPCHBenchmark using lightweight fakes."""

from pathlib import Path

import pytest

from benchbox.core.tpch.benchmark import TPCHBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def fake_tpch_components(monkeypatch, tmp_path):
    """Patch TPCHBenchmark dependencies with lightweight fakes."""

    class FakeTPCHDataGenerator:
        def __init__(self, scale_factor, parallel, output_dir, **_):
            self.scale_factor = scale_factor
            self.parallel = parallel
            self.output_dir = Path(output_dir)
            self.verbose = False

        def generate(self):
            tables = {
                "customer": self.output_dir / "customer.tbl",
                "orders": self.output_dir / "orders.tbl",
            }
            for path in tables.values():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("row\n")
            return tables

    class FakeTPCHQueryManager:
        def get_all_queries(self, **_):
            return {1: "SELECT 1", 2: "SELECT 2"}

        def get_query(self, query_id, **_):
            return f"SELECT {query_id}"

    monkeypatch.setattr("benchbox.core.tpch.benchmark.TPCHDataGenerator", FakeTPCHDataGenerator)
    monkeypatch.setattr("benchbox.core.tpch.benchmark.TPCHQueries", lambda: FakeTPCHQueryManager())

    # Ensure stream permutations are predictable for stream-based queries
    monkeypatch.setattr(
        "benchbox.core.tpch.streams.TPCHStreams.PERMUTATION_MATRIX",
        [[1, 2], [2, 1]],
        raising=False,
    )

    return tmp_path


def test_tpch_benchmark_generates_data_with_fakes(fake_tpch_components):
    bench = TPCHBenchmark(scale_factor=0.1, output_dir=fake_tpch_components)

    generated = bench.generate_data()

    assert len(generated) == 2
    assert all(path.exists() for path in generated)

    queries = bench.get_queries(dialect="duckdb")
    assert queries["1"].lower().startswith("select")

    query = bench.get_query(1, seed=5, scale_factor=0.5)
    assert "select" in query.lower()

    stream_query = bench.get_query(2, params={"stream_id": 0})
    assert "2" in stream_query

    schema = bench.get_schema()
    assert any(table["name"].lower() == "customer" for table in schema.values())

    ddl = bench.get_create_tables_sql()
    assert "create table" in ddl.lower()


def test_get_table_loading_order_is_fk_safe_for_available_subset(fake_tpch_components):
    """Regression test: DataLoader calls get_table_loading_order(available_tables)
    with whatever tables were actually generated/discovered (see
    benchbox/platforms/base/data_loading.py::_load_file_based_data). Before this
    fix, TPCHBenchmark had no such method, so the loader fell back to
    alphabetical order -- which loads lineitem before orders/part/supplier and
    violates FK references once constraints are enforced.
    """
    bench = TPCHBenchmark(scale_factor=0.1, output_dir=fake_tpch_components)

    # Deliberately shuffled/alphabetical-ish input, as a dict-keys() snapshot
    # from disk discovery would be in whatever order the filesystem returns.
    available = ["supplier", "lineitem", "customer", "orders", "region", "nation", "part", "partsupp"]
    order = bench.get_table_loading_order(available)

    assert set(order) == set(available)
    position = {name: i for i, name in enumerate(order)}
    assert position["region"] < position["nation"]
    assert position["nation"] < position["customer"]
    assert position["nation"] < position["supplier"]
    assert position["customer"] < position["orders"]
    assert position["orders"] < position["lineitem"]
    assert position["part"] < position["lineitem"]
    assert position["supplier"] < position["lineitem"]
    assert position["part"] < position["partsupp"]
    assert position["supplier"] < position["partsupp"]

    # A table missing from schema.TABLES (unknown/extra file) must still be
    # returned rather than dropped.
    order_with_extra = bench.get_table_loading_order([*available, "some_extra_table"])
    assert "some_extra_table" in order_with_extra
