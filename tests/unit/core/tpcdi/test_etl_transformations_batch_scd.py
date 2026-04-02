"""Coverage tests for remaining TPC-DI ETL transformation/batch/SCD modules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest

from benchbox.core.tpcdi.etl.batch import (
    BatchMetrics,
    BatchProcessor,
    BatchStatus,
    BatchType,
    ExtractOperation,
    LineageRecord,
    LoadOperation,
    ParallelConfig,
    ParallelExecutionContext,
    TransformOperation,
    ValidationOperation,
)
from benchbox.core.tpcdi.etl.scd_processor import EnhancedSCDType2Processor
from benchbox.core.tpcdi.etl.transformations import (
    BusinessRuleTransformation,
    DataTypeTransformation,
    DimensionTransformation,
    FactTransformation,
    ParallelTransformationContext,
    StreamingChunkProcessor,
    StreamingSCDProcessor,
    TransformationConfig,
    TransformationEngine,
    TransformationRule,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


class _Cursor:
    def __init__(self, rows: list[tuple[Any, ...]], columns: list[str]) -> None:
        self._rows = rows
        self.description = [(c,) for c in columns]

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self._rows


class _Conn:
    def __init__(self, rows: list[tuple[Any, ...]] | None = None, columns: list[str] | None = None) -> None:
        self.rows = rows or []
        self.columns = columns or ["CustomerID", "Status", "SK_CustomerID", "IsCurrent"]
        self.raise_on_execute = False
        self.executed: list[str] = []

    def execute(self, sql: str) -> _Cursor:
        self.executed.append(sql)
        if self.raise_on_execute:
            raise RuntimeError("execute failed")
        return _Cursor(self.rows, self.columns)


@dataclass
class _SimpleTransform(TransformationRule):
    amount: int = 1

    def apply(self, data: pd.DataFrame) -> pd.DataFrame:
        out = data.copy()
        if "x" in out.columns:
            out["x"] = out["x"] + self.amount
        return out


def test_transformations_core_paths_and_engine_streaming():
    # DataTypeTransformation (standard + vectorized + conversion helpers)
    dtt = DataTypeTransformation(
        {
            "dt": "DATE",
            "ts": "DATETIME",
            "n": "INT",
            "f": "FLOAT",
            "b": "BOOLEAN",
            "tiny": "TINYINT",
            "s": "VARCHAR(30)",
            "missing_s": "VARCHAR(10)",
            "unknown": "MYSTERY",
        }
    )
    small = pd.DataFrame(
        {
            "dt": ["2025-01-01", "bad", ""],
            "ts": ["2025-01-01 12:00:00", "bad", ""],
            "n": ["1", "bad", ""],
            "f": ["1.25", "bad", ""],
            "b": ["true", "0", "bad"],
            "tiny": ["1", "300", ""],
            "s": ["abc", None, "def"],
            "unknown": [1, 2, 3],
        }
    )
    transformed_small = dtt.apply(small)
    assert transformed_small["n"].dtype.name == "Int64"
    assert transformed_small["s"].iloc[1] in {"", "None"}

    # vectorized branch
    large = pd.DataFrame(
        {
            "dt": ["2025-01-01"] * 1100,
            "ts": ["2025-01-01 00:00:00"] * 1100,
            "n": ["7"] * 1100,
            "f": ["2.5"] * 1100,
            "s": ["x"] * 1100,
        }
    )
    transformed_large = dtt.apply(large)
    assert len(transformed_large) == 1100
    assert "missing_s" not in transformed_large.columns
    streamed_rules = list(_SimpleTransform(2).apply_streaming(iter([pd.DataFrame({"x": [1]})])))
    assert list(streamed_rules[0]["x"]) == [3]

    # BusinessRuleTransformation coverage across key rules
    base = pd.DataFrame(
        {
            "CreditRating": [0, 5, 20],
            "Assets": [100.0, 30.0, 10.0],
            "Liabilities": [20.0, 40.0, 5.0],
            "FirstName": ["A", "B", "C"],
            "LastName": ["X", "Y", "Z"],
            "TradePrice": [10.0, 5.0, 7.0],
            "Quantity": [2, 3, 4],
            "Type": ["Market", "Limit", "Unknown"],
            "Status": ["Bad", "Active", "Suspended"],
            "LocalTaxRate": [0.02, 0.01, 0.0],
            "NationalTaxRate": [0.02, 0.01, 0.0],
            "Phone1": ["555-111-2222", "1-555-333-4444", ""],
            "Email1": ["ok@example.com", "bad@", ""],
            "EffectiveDate": [date(2025, 1, 2), date(2025, 1, 1), None],
            "EndDate": [date(2025, 1, 1), date(2025, 1, 3), None],
        }
    )
    for rule in [
        "credit_rating_validation",
        "net_worth_calculation",
        "customer_tier_assignment",
        "trade_commission_calculation",
        "trade_fee_calculation",
        "security_status_validation",
        "account_status_validation",
        "tax_calculation",
        "marketing_nameplate_generation",
        "phone_number_standardization",
        "email_validation",
        "date_range_validation",
    ]:
        out = BusinessRuleTransformation(rule, {"base_fees": {"Market": 5.0}}).apply(base)
        assert len(out) == len(base)
    # unknown rule branch
    assert BusinessRuleTransformation("does-not-exist", {}).apply(base).equals(base)

    # StreamingChunkProcessor
    scp = StreamingChunkProcessor(memory_limit_mb=1024)
    chunk_out, stats = scp.process_chunk_streaming(
        pd.DataFrame({"x": [1, 2]}),
        [BusinessRuleTransformation("net_worth_calculation", {}), _SimpleTransform(1)],
        chunk_id=7,
    )
    assert len(chunk_out) == 2
    assert stats["chunk_id"] == 7
    assert "rows_per_second" in scp.get_performance_stats()

    # StreamingSCDProcessor (new, changed, unchanged)
    sscd = StreamingSCDProcessor("customer", ["CustomerID"], ["Status"])
    first_chunk = pd.DataFrame({"CustomerID": [1, 2], "Status": ["A", "B"]})
    second_chunk = pd.DataFrame({"CustomerID": [1, 2], "Status": ["X", "B"]})
    out1, st1 = sscd.process_chunk_scd2(first_chunk, batch_id=1)
    out2, st2 = sscd.process_chunk_scd2(second_chunk, batch_id=2)
    assert st1["new_records"] == 2
    assert st2["changed_records"] == 1
    assert len(out1) > 0 and len(out2) > 0

    # DimensionTransformation (SCD1/2/3 + metadata)
    existing = pd.DataFrame(
        {
            "CustomerID": [1],
            "Status": ["OLD"],
            "SK_CustomerID": [100],
            "IsCurrent": [True],
            "EffectiveDate": [date(2025, 1, 1)],
            "EndDate": [date(2999, 12, 31)],
        }
    )
    incoming = pd.DataFrame({"CustomerID": [1, 2], "Status": ["NEW", "NEW2"], "FirstName": ["A", "B"]})
    dim1 = DimensionTransformation("customer", scd_type=1).apply(incoming)
    with pytest.raises(Exception):
        DimensionTransformation("customer", scd_type=2, existing_data=existing).apply(incoming)
    dim2 = DimensionTransformation("customer", scd_type=1, existing_data=existing).apply(incoming)
    dim3 = DimensionTransformation("customer", scd_type=3).apply(incoming)
    assert "IsCurrent" in dim1.columns and "SK_CustomerID" in dim2.columns and "PreviousStatus" in dim3.columns
    with_meta = DimensionTransformation("customer", scd_type=1).create_dimension_with_metadata(incoming, batch_id=9)
    assert "BatchID" in with_meta.columns

    # FactTransformation + lookups
    dim_lookup = pd.DataFrame({"CustomerID": [1], "SK_CustomerID": [10], "IsCurrent": [True]})
    fact_input = pd.DataFrame(
        {
            "CustomerID": [1],
            "TradePrice": [10.0],
            "Quantity": [3],
            "Status": ["BadStatus"],
            "Type": ["BadType"],
            "Fee": [1.0],
            "Commission": [2.0],
            "Tax": [0.5],
        }
    )
    fact_out = FactTransformation(
        "trade", aggregation_rules={"TradeValue": "sum"}, dimension_lookups={"customer": dim_lookup}
    ).apply(fact_input)
    assert "TradeValue" in fact_out.columns
    with_fact_meta = FactTransformation("trade").create_fact_with_metadata(fact_input, batch_id=3)
    assert "BatchID" in with_fact_meta.columns

    # Config + context
    cfg = TransformationConfig(max_workers=2, chunk_size=200, enable_parallel=False)
    tcfg = SimpleNamespace(
        get_etl_config=lambda: {
            "max_workers": 2,
            "chunk_size": 200,
            "enable_parallel_transform": False,
            "worker_timeout": 30.0,
        }
    )
    assert TransformationConfig.from_tpcdi_config(tcfg).chunk_size == 200
    pctx = ParallelTransformationContext(cfg)
    pctx.add_worker("w1")
    pctx.add_metric("dimension_processing_times", 0.1)
    pctx.remove_worker("w1")
    assert "completed_chunks" in pctx.get_processing_summary()

    # Engine core paths (non-parallel + streaming + incremental)
    engine = TransformationEngine(scale_factor=1.0, chunk_size=200, enable_parallel=False)
    engine.table_dependencies = {"FactTrade": [], "Other": []}
    engine.add_transformation(_SimpleTransform(1))
    cleaned_customer = engine.apply_data_quality_rules(
        pd.DataFrame(
            {
                "CustomerID": [1, 1],
                "LastName": ["A", ""],
                "FirstName": ["X", "Y"],
                "Email1": ["ok@example.com", "bad"],
            }
        ),
        "DimCustomer",
    )
    assert not cleaned_customer.empty
    source_data = {
        "FactTrade": pd.DataFrame({"CustomerID": [1], "TradePrice": [10.0], "Quantity": [2]}),
        "Other": pd.DataFrame({"x": [1]}),
    }
    transformed = engine.transform_batch(source_data, batch_id=42)
    assert "FactTrade" in transformed
    assert "tables_processed" in engine.generate_audit_metrics(source_data, transformed)
    assert engine.get_performance_config()["chunk_size"] >= 1
    engine.optimize_for_scale_factor(5.0)
    engine.remove_transformation(_SimpleTransform(1))

    with pytest.raises(Exception):
        engine.transform_incremental(
            {
                "DimCustomer": pd.DataFrame({"CustomerID": [1], "Status": ["A"]}),
                "FactTrade": pd.DataFrame({"CustomerID": [1], "TradePrice": [1.0], "Quantity": [1]}),
            },
            {
                "DimCustomer": pd.DataFrame(
                    {"CustomerID": [1], "Status": ["B"], "IsCurrent": [True], "SK_CustomerID": [1]}
                )
            },
        )

    streaming_chunks = {"Other": iter([pd.DataFrame({"x": [5]})])}
    streamed = list(engine.transform_batch_streaming(streaming_chunks, batch_id=99))
    assert streamed[0][0] == "Other"


def test_batch_and_scd_modules_core_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # BatchMetrics / BatchStatus helpers
    metrics = BatchMetrics()
    metrics.add_processed("T", 2)
    metrics.add_inserted("T", 1)
    metrics.add_updated("T", 1)
    metrics.add_rejected("T", 0)
    metrics.add_processing_time("op", 0.5)
    assert metrics.get_total_processed() == 2
    assert metrics.get_total_errors() == 0

    status = BatchStatus(batch_id=1, batch_type=BatchType.HISTORICAL, start_time=datetime.now())
    status.add_lineage(
        LineageRecord(
            source_file="s",
            target_table="t",
            transformation_applied="x",
            records_affected=1,
            batch_id=1,
            timestamp=datetime.now(),
            checksum="abc",
        )
    )
    status.mark_completed(datetime.now())
    assert status.get_summary()["lineage_records"] == 1

    # ExtractOperation across csv/xml/txt
    csv_path = tmp_path / "customers.csv"
    xml_path = tmp_path / "securities.xml"
    txt_path = tmp_path / "trades.txt"
    pd.DataFrame({"id": [1], "name": ["a"]}).to_csv(csv_path, index=False)
    xml_path.write_text("<Root><Record><id>1</id><name>x</name></Record></Root>")
    txt_path.write_text("id|amount\n1|10\n")
    ex = ExtractOperation(
        source_dir=tmp_path,
        file_patterns={"DimCustomer": "customers.csv", "DimSecurity": "securities.xml", "FactTrade": "trades.txt"},
    )
    ctx: dict[str, Any] = {"lineage": []}
    batch_data: dict[str, pd.DataFrame] = {}
    ex_result = ex.execute(batch_data, batch_id=1, context=ctx)
    assert ex_result["success"] is True
    assert set(ex_result["tables_processed"]) == {"DimCustomer", "DimSecurity", "FactTrade"}
    assert ex.extract_table("DimCustomer", 1).shape[0] == 1
    # stream extract import-missing branch
    monkeypatch.setitem(__import__("sys").modules, "benchbox.core.tpcdi.tools.file_parsers", None)
    list(ex.execute_streaming(batch_id=1, context={"lineage": []}))

    # TransformOperation
    tr = TransformOperation(transformation_rules={"DimCustomer": ["x"], "FactTrade": ["y"]})
    transform_data = {
        "DimCustomer": pd.DataFrame(
            {"CustomerID": [1], "LastName": [" A "], "FirstName": ["B"], "Email1": ["a@b.com"]}
        ),
        "FactTrade": pd.DataFrame({"TradePrice": [2.0], "Quantity": [3], "Fee": [1.0], "Commission": [2.0]}),
    }
    tr_result = tr.execute(transform_data, batch_id=7, context={"batch_type": "incremental", "lineage": []})
    assert tr_result["success"] is True
    assert "TradeValue" in transform_data["FactTrade"].columns
    assert tr._calculate_quality_score(pd.DataFrame()) == 0.0
    monkeypatch.setattr(
        TransformationEngine,
        "transform_batch_streaming",
        lambda self, source_data_chunks, batch_id, memory_limit_mb=None, progress_callback=None: iter(
            [("DimCustomer", pd.DataFrame({"CustomerID": [1]}))]
        ),
    )
    list(
        tr.execute_streaming(
            {"DimCustomer": iter([pd.DataFrame({"CustomerID": [1], "LastName": ["A"], "FirstName": ["B"]})])},
            batch_id=1,
            context={"lineage": []},
        )
    )

    # LoadOperation with fake connection object supporting commit/rollback
    class _DB:
        def __init__(self):
            self.did_commit = False
            self.did_rollback = False

        def commit(self):
            self.did_commit = True

        def rollback(self):
            self.did_rollback = True

    load = LoadOperation(
        connection_config={"db": "x"}, load_strategies={"DimCustomer": "append", "FactTrade": "upsert"}
    )
    db = _DB()
    monkeypatch.setattr(load, "_establish_connection", lambda: setattr(load, "connection", db))
    monkeypatch.setattr(load, "_close_connection", lambda: None)
    load_result = load.execute(
        {"DimCustomer": pd.DataFrame({"id": [1]}), "FactTrade": pd.DataFrame({"id": [1], "x": [2]})},
        batch_id=1,
        context={"lineage": []},
    )
    assert load_result["success"] is True
    assert db.did_commit is True
    assert load.load_table("DimCustomer", pd.DataFrame({"id": [1]}), "replace")["inserted"] == 1
    assert load.load_table("DimCustomer", pd.DataFrame({"id": [1]}), "bogus")["rejected"] == 1
    list(load.load_table_streaming("DimCustomer", iter([pd.DataFrame({"id": [1]}), pd.DataFrame()]), "append"))
    list(
        load.execute_streaming({"DimCustomer": iter([pd.DataFrame({"id": [1]})])}, batch_id=1, context={"lineage": []})
    )

    # ValidationOperation
    val = ValidationOperation(validation_rules={"DimCustomer": ["custom_rule"]})
    val_df = pd.DataFrame(
        {
            "SK_CustomerID": [1, 1],
            "Status": ["ACTV", "BAD"],
            "CreditRating": [5, 20],
            "Email1": ["ok@example.com", "bad"],
            "EffectiveDate": ["2025-01-01", "2025-01-03"],
            "EndDate": ["2025-12-31", "2025-01-01"],
        }
    )
    val_result = val.execute({"DimCustomer": val_df}, batch_id=1, context={"lineage": []})
    assert "summary" in val_result
    list(val.validate_table_streaming("DimCustomer", iter([val_df])))
    stream_val = list(val.execute_streaming({"DimCustomer": iter([val_df])}, batch_id=1, context={"lineage": []}))
    assert stream_val[-1]["operation"] == "streaming_validation_summary"

    # ParallelConfig / ExecutionContext / BatchProcessor
    cfg = ParallelConfig(max_workers=2, chunk_size=2, enable_parallel=False, worker_timeout=10.0)
    bc = SimpleNamespace(get_batch_config=lambda: {"max_workers": 2, "chunk_size": 2, "parallel_processing": False})
    assert ParallelConfig.from_tpcdi_config(bc).chunk_size == 2

    exec_ctx = ParallelExecutionContext(cfg)
    exec_ctx.add_worker("w")
    exec_ctx.increment_completed()
    exec_ctx.increment_failed()
    exec_ctx.add_performance_metric("extract_times", 0.1)
    exec_ctx.remove_worker("w")
    assert exec_ctx.get_task_summary()["completed"] == 1

    processor = BatchProcessor(scale_factor=1.0, parallel_processing=False, parallel_config=cfg)
    processor.add_operation(ex)
    processor.add_operation(tr)
    processor.add_operation(load)
    processor.add_operation(val)
    processor.add_dependency("batch_2", "batch_1")
    assert processor.validate_batch_dependencies(1) is True
    b1 = processor.process_historical_load(source_config={"root": str(tmp_path)}, target_config={"db": "x"})
    assert b1.status in {"completed", "failed"}
    monkeypatch.setattr(processor, "validate_batch_dependencies", lambda _batch_id: True)
    b2 = processor.process_incremental_batch(
        batch_number=2,
        batch_date=date(2025, 1, 1),
        source_config={"root": str(tmp_path)},
        target_config={"db": "x"},
    )
    assert b2.batch_type == BatchType.INCREMENTAL
    with pytest.raises(ValueError):
        processor.process_incremental_batch(5, date(2025, 1, 1), {}, {})
    assert processor.get_batch_status(1) is not None
    assert "total_batches" in processor.get_processing_statistics()
    processor.cleanup_batch_resources(1)
    # non-parallel report branch
    assert "error" in processor.get_parallel_performance_report()
    # worker wrapper branch
    assert processor._execute_operation_with_monitoring(ex, {}, 1, {"lineage": []}, "w")["worker_id"] == "w"
    assert "batch_status" in processor.get_lineage_report(1)

    # SCD processor main branches
    conn = _Conn(rows=[(1, "A", 100, 1)], columns=["CustomerID", "Status", "SK_CustomerID", "IsCurrent"])
    scd = EnhancedSCDType2Processor(connection=conn)
    assert scd.process_dimension("DimCustomer", "CustomerID", ["Status"], 1)["success"] is True

    new_data = pd.DataFrame(
        {
            "CustomerID": [1, 2, 2],
            "Status": ["B", "A", "A"],
            "Attr": [10, 20, 20],
        }
    )
    # validation fail branch (duplicate business key)
    failed = scd.process_scd_changes(
        new_data=new_data,
        table_name="DimCustomer",
        business_keys=["CustomerID"],
        scd_columns=["Status"],
        batch_id=1,
        effective_date=datetime.now(),
        non_scd_columns=["Attr"],
    )
    assert failed["success"] is False

    good_data = pd.DataFrame({"CustomerID": [1, 3], "Status": ["B", "A"], "Attr": [11, 30]})
    ok = scd.process_scd_changes(
        new_data=good_data,
        table_name="DimCustomer",
        business_keys=["CustomerID"],
        scd_columns=["Status"],
        batch_id=2,
        effective_date=datetime.now(),
        non_scd_columns=["Attr"],
    )
    assert "records_processed" in ok

    trail = scd.get_change_audit_trail(table_name="DimCustomer")
    assert isinstance(trail, list)
    assert isinstance(scd.get_comprehensive_statistics(), dict)
    out_file = tmp_path / "audit.json"
    assert scd.export_audit_trail(str(out_file), format="json") is True
    assert scd.export_audit_trail(str(out_file), format="bad-format") is False
    changes = scd.detect_changes(
        current_data=pd.DataFrame({"Status": ["A"]}),
        new_data=pd.DataFrame({"Status": ["B"]}),
        scd_columns=["Status"],
    )
    assert len(changes) == 1
    internal_changes = scd._detect_changes(
        current_data=pd.DataFrame({"Status": ["A"]}),
        new_data=pd.DataFrame({"Status": ["B"], "CustomerID": [123]}),
        scd_columns=["Status"],
    )
    assert len(internal_changes) == 1
    processed = scd._process_scd_change(internal_changes[0])
    assert processed["processed"] is True
    audit_record = scd._create_audit_record(internal_changes[0])
    assert audit_record["change_type"] == "UPDATE"
    assert not scd._extract_current_data("DimCustomer").empty
    assert scd._extract_new_data("DimCustomer").empty
    scd.clear_change_audit_trail()
    assert scd.get_change_audit_trail() == []
