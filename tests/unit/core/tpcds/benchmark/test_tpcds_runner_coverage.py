from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from benchbox.core.tpcds.benchmark.runner import TPCDSBenchmark
from benchbox.core.tpcds.schema import TABLES
from benchbox.core.validation import ValidationResult

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def tpcds_benchmark(tmp_path, monkeypatch):
    class FakeQueryManager:
        def get_query(self, query_id, **kwargs):
            return f"SELECT {query_id}"

        def get_all_queries(self, **kwargs):
            return {1: "SELECT 1"}

    class FakeDataGenerator:
        def __init__(self, scale_factor=1.0, parallel=1, output_dir=None, **kwargs):
            self.scale_factor = scale_factor
            self.parallel = parallel
            self.output_dir = Path(output_dir) if output_dir else Path.cwd()

        def generate(self):
            return {"store_sales": self.output_dir / "store_sales.dat"}

    class FakeCTools:
        def get_tools_info(self):
            return {"available_tools": []}

    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSQueryManager", FakeQueryManager)
    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSDataGenerator", FakeDataGenerator)
    monkeypatch.setattr("benchbox.core.tpcds.benchmark.runner.TPCDSCTools", FakeCTools)

    return TPCDSBenchmark(scale_factor=1.0, output_dir=tmp_path, verbose=False)


def test_get_query_validates_inputs(tpcds_benchmark):
    with pytest.raises(TypeError):
        tpcds_benchmark.get_query("1")
    with pytest.raises(ValueError):
        tpcds_benchmark.get_query(0)
    with pytest.raises(TypeError):
        tpcds_benchmark.get_query(1, seed="x")
    with pytest.raises(ValueError):
        tpcds_benchmark.get_query(1, scale_factor=0)


def test_get_query_variant_fallback_without_dsqgen(tpcds_benchmark):
    class NoDSQGen:
        def get_query(self, query_id, **kwargs):
            return f"SELECT {query_id}"

    tpcds_benchmark.query_manager = NoDSQGen()

    query = tpcds_benchmark.get_query(14, variant="a", dialect="duckdb", base_dialect="netezza")

    assert "SELECT" in query


def test_normalize_interval_syntax(tpcds_benchmark):
    raw = "select cast('2000-01-01' as date) + 60 days - 30 days"
    normalized = tpcds_benchmark._normalize_interval_syntax(raw)
    assert "+ INTERVAL 60 DAY" in normalized
    assert "- INTERVAL 30 DAY" in normalized


def test_spark_q90_rewrite_guards_zero_denominator(tpcds_benchmark):
    query = "SELECT CAST(`amc` AS DECIMAL(15, 4)) / CAST(`pmc` AS DECIMAL(15, 4)) AS `am_pm_ratio` FROM counts"

    rewritten = tpcds_benchmark._apply_target_dialect_overrides(90, query, "spark")

    assert "/ NULLIF(CAST(`pmc` AS DECIMAL(15, 4)), 0)" in rewritten


def test_postgres_q90_rewrite_guards_zero_denominator(tpcds_benchmark):
    query = "SELECT CAST(amc AS DECIMAL(15, 4)) / CAST(pmc AS DECIMAL(15, 4)) AS am_pm_ratio FROM counts"

    rewritten = tpcds_benchmark._apply_target_dialect_overrides(90, query, "postgres")

    assert "/ NULLIF(CAST(pmc AS DECIMAL(15, 4)), 0)" in rewritten


def test_postgres_rollup_order_alias_rewrite_repeats_grouping_expression(tpcds_benchmark):
    query = (
        "SELECT GROUPING(i_category) + GROUPING(i_class) AS lochierarchy "
        "FROM store_sales GROUP BY ROLLUP (i_category, i_class) "
        "ORDER BY lochierarchy DESC, CASE WHEN lochierarchy = 0 THEN i_category END, rank_within_parent"
    )

    rewritten = tpcds_benchmark._apply_target_dialect_overrides(36, query, "postgres")

    assert "CASE WHEN lochierarchy = 0" not in rewritten
    assert (
        "ORDER BY GROUPING(i_category) + GROUPING(i_class) DESC, "
        "CASE WHEN GROUPING(i_category) + GROUPING(i_class) = 0 THEN i_category END"
    ) in rewritten


def test_fix_query58_ambiguity(tpcds_benchmark):
    query = (
        "WITH ss_items AS (SELECT 1 AS item_id), cs_items AS (SELECT 1 AS item_id), "
        'ws_items AS (SELECT 1 AS item_id) SELECT * FROM ss_items ORDER BY "item_id"'
    )
    fixed = tpcds_benchmark._fix_query58_ambiguity(query)
    assert 'ORDER BY "ss_items"."item_id"' in fixed


def test_get_create_tables_sql_uses_tuning_flags(tpcds_benchmark, monkeypatch):
    captured = {}

    def fake_get_create_all_tables_sql(enable_primary_keys=False, enable_foreign_keys=False):
        captured["pk"] = enable_primary_keys
        captured["fk"] = enable_foreign_keys
        return "-- schema"

    monkeypatch.setattr("benchbox.core.tpcds.schema.get_create_all_tables_sql", fake_get_create_all_tables_sql)

    tuning = SimpleNamespace(
        primary_keys=SimpleNamespace(enabled=True),
        foreign_keys=SimpleNamespace(enabled=False),
    )

    sql = tpcds_benchmark.get_create_tables_sql(tuning_config=tuning)

    assert sql == "-- schema"
    assert captured == {"pk": True, "fk": False}


def test_get_all_streams_info_skips_invalid(tpcds_benchmark, monkeypatch):
    def fake_get_stream_info(stream_id):
        if stream_id == 1:
            raise ValueError("bad stream")
        return {"stream_id": stream_id}

    monkeypatch.setattr(tpcds_benchmark, "get_stream_info", fake_get_stream_info)

    all_info = tpcds_benchmark.get_all_streams_info(num_streams=3)

    assert [item["stream_id"] for item in all_info] == [0, 2]


def test_validate_data_integrity_combines_results(tpcds_benchmark, monkeypatch):
    file_result = ValidationResult(is_valid=True, warnings=["w1"], details={"files": "ok"})
    db_result = ValidationResult(is_valid=False, errors=["db-fail"], details={"db": "bad"})

    monkeypatch.setattr(tpcds_benchmark, "validate_generated_data", lambda: file_result)
    monkeypatch.setattr(tpcds_benchmark, "validate_loaded_data", lambda _conn: db_result)

    combined = tpcds_benchmark.validate_data_integrity(connection=object())

    assert combined.is_valid is False
    assert combined.errors == ["db-fail"]
    assert combined.warnings == ["w1"]
    assert combined.details["file_validation"] == {"files": "ok"}
    assert combined.details["database_validation"] == {"db": "bad"}


def test_get_benchmark_info_includes_tools(tpcds_benchmark):
    info = tpcds_benchmark.get_benchmark_info()
    assert info["name"] == "TPC-DS"
    assert info["maintenance_test_supported"] is True
    assert "available_tools" in info["c_tools_info"]


class _Conn:
    def __init__(self, fail_on=None):
        self.fail_on = fail_on
        self.last_query = ""
        self.closed = False

    def execute(self, query, *args, **kwargs):
        self.last_query = str(query)
        if self.fail_on and self.fail_on in self.last_query:
            raise RuntimeError("forced failure")
        return self

    def fetchall(self):
        return [(1,)]

    def fetchone(self):
        return (0,)

    def close(self):
        self.closed = True


def test_run_throughput_test_success(tpcds_benchmark, monkeypatch):
    monkeypatch.setattr(tpcds_benchmark, "get_query", lambda qid, **kwargs: f"SELECT {qid}")

    result = tpcds_benchmark.run_throughput_test(
        connection_factory=lambda: _Conn(),
        num_streams=1,
        query_timeout=1,
        stream_timeout=10,
        max_retries=0,
    )

    assert result.streams_executed == 1
    assert result.streams_successful == 1
    assert result.success is True
    assert result.throughput_at_size > 0
    assert result.stream_results[0]["queries_executed"] == 99


def test_run_power_test_collects_query_error(tpcds_benchmark, monkeypatch):
    monkeypatch.setattr(tpcds_benchmark, "get_query", lambda qid, **kwargs: f"SELECT {qid}")

    conn = _Conn(fail_on="SELECT 42")
    result = tpcds_benchmark.run_power_test(connection=conn, warm_up=False, verbose=False)

    assert result["total_time"] >= 0
    assert len(result["query_results"]) == 99
    assert result["errors"]
    assert result["query_results"][42]["status"] == "failed"


def test_run_maintenance_test_maps_operations(tpcds_benchmark, monkeypatch):
    class FakeMaintenanceTest:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def run(self, config):
            op = SimpleNamespace(
                operation_type="insert",
                table_name="store_sales",
                start_time=1.0,
                end_time=2.0,
                duration=1.0,
                rows_affected=10,
                success=True,
                error=None,
            )
            return {
                "total_time": 1.0,
                "total_operations": 1,
                "successful_operations": 1,
                "failed_operations": 0,
                "overall_throughput": 1.0,
                "operations": [op],
                "errors": [],
            }

    monkeypatch.setattr("benchbox.core.tpcds.maintenance_test.TPCDSMaintenanceTest", FakeMaintenanceTest)

    result = tpcds_benchmark.run_maintenance_test(connection=_Conn())
    assert result.total_operations == 1
    assert result.successful_operations == 1
    assert result.maintenance_operations[0]["operation"] == "insert_store_sales"


def test_validate_maintenance_data_integrity(tpcds_benchmark):
    conn = _Conn()
    result = tpcds_benchmark.validate_maintenance_data_integrity(connection=conn)
    assert len(result["validation_checks"]) == 3
    assert result["integrity_score"] == 1.0
    assert conn.closed is True


def test_run_official_benchmark_aggregates(tpcds_benchmark, monkeypatch):
    monkeypatch.setattr(
        tpcds_benchmark,
        "run_power_test",
        lambda **kwargs: {"total_time": 1.0, "power_at_size": 16.0},
    )
    monkeypatch.setattr(
        tpcds_benchmark,
        "run_throughput_test",
        lambda **kwargs: SimpleNamespace(throughput_at_size=9.0),
    )
    monkeypatch.setattr(
        tpcds_benchmark,
        "run_maintenance_test",
        lambda **kwargs: SimpleNamespace(successful_operations=1, total_operations=1),
    )

    result = tpcds_benchmark.run_official_benchmark(connection=_Conn(), num_streams=1)
    assert result["success"] is True
    assert result["power_at_size"] == 16.0
    assert result["throughput_at_size"] == 9.0
    assert result["qphds_at_size"] == pytest.approx(12.0)


def test_load_table_data_trims_padding_and_null_conversion(tpcds_benchmark, tmp_path):
    table_schema = next(table for table in TABLES if len(table.columns) >= 3)
    table_name = table_schema.name.lower()
    num_columns = len(table_schema.columns)
    data_file = tmp_path / f"{table_name}.dat"

    first_row = [f"v{i}" for i in range(num_columns)] + ["ignored"]
    second_row = ["", "x"]
    data_file.write_text("|".join(first_row) + "\n" + "|".join(second_row) + "\n")

    connection = Mock()

    loaded = tpcds_benchmark._load_table_data(connection, table_name, data_file)

    assert loaded == 2
    assert connection.execute.call_count == 2
    first_call = connection.execute.call_args_list[0]
    second_call = connection.execute.call_args_list[1]
    assert first_call.args[0].startswith(f"INSERT INTO {table_schema.name.upper()} VALUES")
    assert len(first_call.args[1]) == num_columns
    assert len(second_call.args[1]) == num_columns
    assert second_call.args[1][0] is None
    assert second_call.args[1][2:] == [None] * (num_columns - 2)


def test_load_table_data_raises_for_unknown_table(tpcds_benchmark, tmp_path):
    data_file = tmp_path / "unknown.dat"
    data_file.write_text("1|2|3\n")

    with pytest.raises(ValueError, match="Unknown table"):
        tpcds_benchmark._load_table_data(Mock(), "not_a_table", data_file)


def test_load_data_requires_generated_tables(tpcds_benchmark):
    tpcds_benchmark.tables = {}

    with pytest.raises(ValueError, match="No data has been generated"):
        tpcds_benchmark._load_data(Mock())


def test_load_data_executes_split_schema_and_skips_missing_or_empty_files(tpcds_benchmark, tmp_path, monkeypatch):
    valid_table = "call_center"
    empty_table = "catalog_page"
    missing_table = "customer"
    valid_file = tmp_path / f"{valid_table}.dat"
    empty_file = tmp_path / f"{empty_table}.dat"
    missing_file = tmp_path / f"{missing_table}.dat"
    valid_file.write_text("1|2|3\n")
    empty_file.write_text("")

    tpcds_benchmark.tables = {
        valid_table: valid_file,
        empty_table: empty_file,
        missing_table: missing_file,
    }

    connection = Mock()
    monkeypatch.setattr(tpcds_benchmark, "get_create_tables_sql", lambda: "CREATE TABLE a; CREATE TABLE b;")
    monkeypatch.setattr(tpcds_benchmark, "_load_table_data", Mock(return_value=7))

    tpcds_benchmark._load_data(connection)

    assert connection.execute.call_args_list[0].args[0] == "CREATE TABLE a"
    assert connection.execute.call_args_list[1].args[0] == "CREATE TABLE b"
    tpcds_benchmark._load_table_data.assert_called_once_with(connection, valid_table, valid_file)
    assert connection.commit.call_count == 2


def test_run_power_phase_records_errors(tpcds_benchmark, monkeypatch):
    monkeypatch.setattr(tpcds_benchmark, "run_power_test", Mock(side_effect=RuntimeError("power boom")))
    result = {"errors": [], "success": True, "power_at_size": 0.0}

    tpcds_benchmark._run_power_phase(connection=object(), dialect="duckdb", logger=Mock(), result=result)

    assert result["success"] is False
    assert result["errors"] == ["Power Test failed: power boom"]


def test_run_throughput_phase_records_errors(tpcds_benchmark, monkeypatch):
    monkeypatch.setattr(tpcds_benchmark, "run_throughput_test", Mock(side_effect=RuntimeError("throughput boom")))
    result = {"errors": [], "success": True, "throughput_at_size": 0.0}

    tpcds_benchmark._run_throughput_phase(
        connection_factory=lambda: object(), num_streams=2, logger=Mock(), result=result
    )

    assert result["success"] is False
    assert result["errors"] == ["Throughput Test failed: throughput boom"]


def test_run_maintenance_phase_records_errors(tpcds_benchmark, monkeypatch):
    monkeypatch.setattr(tpcds_benchmark, "run_maintenance_test", Mock(side_effect=RuntimeError("maintenance boom")))
    result = {"errors": [], "success": True}

    tpcds_benchmark._run_maintenance_phase(connection=object(), dialect="duckdb", logger=Mock(), result=result)

    assert result["success"] is False
    assert result["errors"] == ["Maintenance Test failed: maintenance boom"]


def test_finalize_benchmark_result_populates_timing_fields(tpcds_benchmark):
    result = {
        "total_time": 0.0,
        "end_time": None,
        "power_at_size": 1.0,
        "throughput_at_size": 2.0,
        "qphds_at_size": 1.414,
        "success": True,
        "errors": [],
    }

    tpcds_benchmark._finalize_benchmark_result(result, benchmark_start_time=0.0, logger=Mock())

    assert result["total_time"] >= 0
    assert isinstance(result["end_time"], str)


def test_get_available_tables_returns_list(tpcds_benchmark):
    tables = tpcds_benchmark.get_available_tables()
    assert isinstance(tables, list)
    assert len(tables) > 0
    assert "store_sales" in tables


def test_get_available_queries_returns_1_to_99(tpcds_benchmark):
    queries = tpcds_benchmark.get_available_queries()
    assert queries == list(range(1, 100))


def test_get_table_loading_order_respects_fk_dependencies(tpcds_benchmark):
    available = ["store_sales", "date_dim", "store", "item"]
    order = tpcds_benchmark.get_table_loading_order(available)
    # All requested tables should be returned
    assert sorted(order) == sorted(available)
    # date_dim (parent dim) should appear before store_sales (fact)
    assert order.index("date_dim") < order.index("store_sales")


def test_get_table_loading_order_appends_unknown_tables(tpcds_benchmark):
    available = ["store_sales", "my_custom_table"]
    order = tpcds_benchmark.get_table_loading_order(available)
    assert "my_custom_table" in order
    assert "store_sales" in order


def test_get_schema_returns_all_tpcds_tables(tpcds_benchmark):
    schema = tpcds_benchmark.get_schema()
    assert isinstance(schema, dict)
    assert len(schema) > 0
    # Check structure of one entry
    first_table = next(iter(schema.values()))
    assert "name" in first_table
    assert "columns" in first_table
    col0 = first_table["columns"][0]
    assert "name" in col0
    assert "type" in col0
    assert "nullable" in col0


def test_generate_data_populates_tables(tpcds_benchmark, tmp_path):
    files = tpcds_benchmark.generate_data()
    assert isinstance(files, list)
    assert len(files) > 0
    # tables dict should be populated
    assert "store_sales" in tpcds_benchmark.tables


def test_aggregate_stream_results_sums_queries():
    import time

    from benchbox.core.tpcds.benchmark.runner import _aggregate_stream_results

    start = time.time() - 1.0
    streams = [
        {"queries_executed": 10, "queries_successful": 8, "queries_failed": 2, "success": True, "error": None},
        {"queries_executed": 5, "queries_successful": 5, "queries_failed": 0, "success": True, "error": None},
    ]
    result = _aggregate_stream_results(streams, start)

    assert result["num_streams"] == 2
    assert result["streams_executed"] == 2
    assert result["streams_successful"] == 2
    assert result["total_queries_executed"] == 15
    assert result["total_queries_successful"] == 13
    assert result["total_queries_failed"] == 2
    assert result["success"] is True
    assert result["errors"] == []
    assert result["total_duration"] > 0


def test_aggregate_stream_results_with_failures():
    import time

    from benchbox.core.tpcds.benchmark.runner import _aggregate_stream_results

    start = time.time()
    streams = [
        {"queries_executed": 3, "queries_successful": 2, "queries_failed": 1, "success": False, "error": "timeout"},
    ]
    result = _aggregate_stream_results(streams, start)

    assert result["success"] is False
    assert result["errors"] == ["timeout"]


def test_translate_query_text_returns_string(tpcds_benchmark):
    query = "SELECT * FROM store_sales WHERE ss_sold_date_sk = 1"
    translated = tpcds_benchmark.translate_query_text(query, "netezza", "duckdb")
    assert isinstance(translated, str)
    assert len(translated) > 0


def test_get_queries_returns_dict_with_string_keys(tpcds_benchmark):
    queries = tpcds_benchmark.get_queries()
    assert isinstance(queries, dict)
    assert len(queries) > 0
    # Keys should be strings (str(query_id))
    assert all(isinstance(k, str) for k in queries)
    # Values should be non-empty strings
    assert all(isinstance(v, str) and len(v) > 0 for v in queries.values())
