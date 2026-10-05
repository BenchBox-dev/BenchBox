from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.base import tuning_trust
from benchbox.platforms.base.adapter import PlatformAdapter

pytestmark = [pytest.mark.unit, pytest.mark.fast]


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
