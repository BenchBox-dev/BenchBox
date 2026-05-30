"""Coverage tests for remaining TPC-DI ETL SCD processing paths."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from benchbox.core.tpcdi.etl.scd_processor import EnhancedSCDType2Processor

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


def test_scd_module_core_paths(tmp_path: Path):
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
