from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.tuning.applied_ledger import (
    EXECUTED,
    FAILED,
    NOOP,
    PHASE_DDL,
    PHASE_POST_LOAD,
    AppliedTuningLedger,
)
from benchbox.platforms.base import tuning_trust
from benchbox.platforms.base.adapter import PlatformAdapter
from benchbox.platforms.clickhouse.adapter import ClickHouseAdapter
from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.platforms.snowflake import SnowflakeAdapter

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[4]
ADAPTER_PATH = ROOT / "benchbox" / "platforms" / "base" / "adapter.py"


@pytest.mark.parametrize(
    ("method", "function", "args"),
    [
        ("_corroborate_applied_ledger", "corroborate_applied_ledger", ("conn", "applied_unverified")),
        ("_attach_applied_ledger_payload", "attach_applied_ledger_payload", ("result", "applied_unverified")),
        ("_build_drift_check_payload", "build_drift_check_payload", ()),
        ("_fold_layout_operations_into_ledger", "fold_layout_operations_into_ledger", ()),
    ],
)
def test_adapter_method_delegates_to_tuning_trust(method: str, function: str, args: tuple) -> None:
    adapter = MagicMock()
    sentinel = object()
    with patch.object(tuning_trust, function, return_value=sentinel) as delegate:
        returned = getattr(PlatformAdapter, method)(adapter, *args)
    delegate.assert_called_once_with(adapter, *args)
    if method in {"_corroborate_applied_ledger", "_build_drift_check_payload"}:
        assert returned is sentinel
    else:
        assert returned is None


def test_read_back_degrades_to_apply_phase_status_when_ledger_missing() -> None:
    adapter = MagicMock()
    adapter._applied_tuning_ledger = None
    result = tuning_trust.read_back_applied_ledger(adapter, "conn", "applied_unverified", True)
    assert result == ("applied_unverified", None, None, None)


def test_read_back_carries_receipt_status_and_ledger_payload() -> None:
    adapter = MagicMock()
    ledger = adapter._applied_tuning_ledger
    ledger.overall_status.return_value = "applied_unverified"
    ledger.is_empty.return_value = False
    adapter._corroborate_applied_ledger.return_value = ("applied_verified", {"receipt": 1})
    adapter._build_drift_check_payload.return_value = None
    status, payload, ledger_hash, receipt = tuning_trust.read_back_applied_ledger(adapter, "conn", "noop", True)
    assert status == "applied_verified"
    assert receipt == {"receipt": 1}
    assert payload is ledger.to_payload.return_value
    assert ledger_hash is ledger.applied_ledger_hash.return_value
    ledger.overall_status.assert_called_once_with(tuning_enabled=adapter.tuning_enabled, has_config=True)
    ledger.to_payload.assert_called_once_with(status="applied_verified", receipt={"receipt": 1}, drift_check=None)


def test_apply_phase_status_matches_ledger_overall_status() -> None:
    adapter = MagicMock()
    assert tuning_trust.apply_phase_status(adapter, True) is adapter._applied_tuning_ledger.overall_status.return_value
    adapter._applied_tuning_ledger.overall_status.assert_called_once_with(
        tuning_enabled=adapter.tuning_enabled, has_config=True
    )


@pytest.mark.parametrize(
    ("adapter_cls", "factory", "attrs", "factory_args"),
    [
        (DuckDBAdapter, "duckdb_tuning_introspector", {}, ()),
        (ClickHouseAdapter, "clickhouse_tuning_introspector", {}, ()),
        (SnowflakeAdapter, "snowflake_tuning_introspector", {"schema": "PUBLIC"}, ("PUBLIC",)),
    ],
)
def test_introspector_override_delegates_to_gated_factory(
    adapter_cls, factory: str, attrs: dict, factory_args: tuple
) -> None:
    """Each override must route through the gated ``tuning_trust`` factory.

    Rebuilding the introspector inline (ignoring the factory) returns a real
    object instead of the sentinel, so this fails if the override stops going
    through the gated module.
    """
    adapter = object.__new__(adapter_cls)
    for key, value in attrs.items():
        setattr(adapter, key, value)
    sentinel = object()
    with patch.object(tuning_trust, factory, return_value=sentinel) as delegate:
        returned = adapter.get_tuning_introspector()
    delegate.assert_called_once_with(*factory_args)
    assert returned is sentinel


def _run_enhanced_benchmark_source() -> str:
    source = ADAPTER_PATH.read_text(encoding="utf-8")
    start = source.index("    def run_enhanced_benchmark(")
    end = source.index("\n    def ", start + 1)
    return source[start:end]


def _fold_adapter(
    applied_ops: list[dict] | None = None, skipped_ops: list[dict] | None = None
) -> tuple[MagicMock, AppliedTuningLedger]:
    adapter = MagicMock()
    ledger = AppliedTuningLedger()
    adapter._applied_tuning_ledger = ledger
    adapter._applied_layout_operations = list(applied_ops or [])
    adapter._skipped_layout_operations = list(skipped_ops or [])
    return adapter, ledger


def test_fold_records_applied_as_executed() -> None:
    adapter, ledger = _fold_adapter(
        [{"statement": "OPTIMIZE T", "phase": PHASE_POST_LOAD, "status": "applied", "mechanism": "optimize"}]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert [s.status for s in ledger.statements] == [EXECUTED]


def test_fold_records_skipped_as_dropped_not_failed() -> None:
    adapter, ledger = _fold_adapter(
        [{"statement": "OPTIMIZE T", "phase": PHASE_POST_LOAD, "status": "skipped", "mechanism": "optimize"}]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert ledger.statements == []
    assert len(ledger.dropped) == 1
    assert ledger.dropped[0].reason.startswith("skipped:")


def test_fold_records_skipped_with_error_as_failed() -> None:
    adapter, ledger = _fold_adapter(
        [
            {
                "statement": "OPTIMIZE T",
                "phase": PHASE_POST_LOAD,
                "status": "skipped",
                "mechanism": "optimize",
                "error_message": "boom",
            }
        ]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert ledger.dropped == []
    assert [s.status for s in ledger.statements] == [FAILED]


def test_fold_records_skipped_with_empty_error_message_as_failed() -> None:
    adapter, ledger = _fold_adapter(
        [
            {
                "statement": "OPTIMIZE T",
                "phase": PHASE_POST_LOAD,
                "status": "skipped",
                "mechanism": "optimize",
                "error_class": "TimeoutError",
                "error_message": "",
            }
        ]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert ledger.dropped == []
    assert [s.status for s in ledger.statements] == [FAILED]


def test_fold_records_unknown_status_as_failed() -> None:
    adapter, ledger = _fold_adapter(
        [{"statement": "OPTIMIZE T", "phase": PHASE_POST_LOAD, "status": "weird", "mechanism": "optimize"}]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert [s.status for s in ledger.statements] == [FAILED]


def test_fold_consumes_skipped_layout_operations_as_dropped() -> None:
    adapter, ledger = _fold_adapter(
        skipped_ops=[
            {
                "statement": "OPTIMIZE LINEITEM ZORDER BY (L_ORDERKEY)",
                "phase": PHASE_DDL,
                "status": "skipped",
                "mechanism": "z_order",
                "table": "LINEITEM",
            }
        ]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert ledger.statements == []
    assert [d.intent for d in ledger.dropped] == ["OPTIMIZE LINEITEM ZORDER BY (L_ORDERKEY)"]


def test_hudi_skips_yield_dropped_intents_and_non_failed_status() -> None:
    adapter, ledger = _fold_adapter(
        skipped_ops=[
            {
                "statement": "OPTIMIZE LINEITEM ZORDER BY (L_ORDERKEY)",
                "phase": "ddl",
                "status": "skipped",
                "mechanism": "z_order",
                "table": "LINEITEM",
            },
            {
                "statement": "OPTIMIZE LINEITEM",
                "phase": "ddl",
                "status": "skipped",
                "mechanism": "optimize",
                "table": "LINEITEM",
            },
        ]
    )
    tuning_trust.fold_layout_operations_into_ledger(adapter)
    assert len(ledger.dropped) == 2
    assert ledger.overall_status(tuning_enabled=True, has_config=True) == NOOP


def test_no_ledger_phase_literal_outside_closed_set() -> None:
    stray: list[str] = []
    for path in (ROOT / "benchbox").rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if 'phase="pre_load"' in line or "phase='pre_load'" in line or 'phase="manual"' in line:
                stray.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert stray == []


def test_run_enhanced_benchmark_routes_trust_through_tuning_trust() -> None:
    """Pin the read-back (and apply-phase/failure-path) call sites.

    If the read-back stops going through ``tuning_trust.read_back_applied_ledger``,
    or the apply-phase status / failure-path attach stop going through the gated
    module, the corresponding reference disappears from ``run_enhanced_benchmark``
    and this fails.
    """
    body = _run_enhanced_benchmark_source()
    assert "tuning_trust.read_back_applied_ledger(" in body
    assert "tuning_trust.apply_phase_status(" in body
    assert "_attach_applied_ledger_payload(" in body
    assert "._applied_tuning_ledger.overall_status(" not in body
