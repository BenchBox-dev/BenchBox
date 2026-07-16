"""Pin today's requested-config capture behavior (not applied verification).

From the 2026-07-12 tuning review, finding R7: there is no test covering
requested-vs-applied integrity -- whether `tunings_applied` on the result
record reflects what the adapter actually executed, or merely what was
asked for. Reading `benchbox/platforms/base/adapter.py`'s
`run_enhanced_benchmark` (lines ~781-785) and `tuning_config.py`'s
`_setup_fresh_database_phases` (which actually calls
`adapter.apply_unified_tuning`) shows the current wiring:

    tunings_applied_dict = effective_tuning_config.to_dict()
    tuning_validation_status = "APPLIED" if tuning_metadata_saved else "FAILED_TO_SAVE"

`tunings_applied` is always a serialization of the *requested*
`UnifiedTuningConfiguration` -- it is never derived from what
`apply_unified_tuning` actually executed against the connection.
`tuning_validation_status` reflects only whether the metadata *row* was
saved (`save_tuning_metadata`), not whether every requested tuning was
actually applied.

This test builds a stub adapter whose `apply_unified_tuning` deliberately
applies only a *subset* of the requested configuration (simulating a
platform quirk / partial failure that doesn't raise), runs
`_setup_fresh_database_phases`, and reconstructs the same
`tunings_applied`/`tuning_validation_status` derivation adapter.py performs.
It asserts the *documented gap*: `tunings_applied` still reports every
column of the full requested config, including the parts the stub adapter
never executed, and `tuning_validation_status` still reads "APPLIED" purely
because metadata-row-save succeeded.

TODO (tracked, not fixed here): once an applied-ledger lands (see this
TODO's `deferred` note, gated on ADR-1), this test's assertions on the gap
should flip to asserting the ledger *does* reflect only what was executed --
at which point this module's name and docstring should be revisited too.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from benchbox.core.tuning.interface import (
    TableTuning,
    TuningColumn,
    UnifiedTuningConfiguration,
)
from benchbox.platforms.base import PlatformAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class _RecordingConnection:
    """Stub connection that records every statement handed to it."""

    def __init__(self) -> None:
        self.executed_statements: list[str] = []

    def execute(self, sql: str) -> None:
        self.executed_statements.append(sql)


class _PartiallyApplyingStubAdapter(PlatformAdapter):
    """Minimal concrete adapter whose apply_unified_tuning only executes
    constraint statements, silently skipping table-level tunings (sorting,
    partitioning, etc.) -- simulating a real-world partial-application
    scenario without raising, so the run still "succeeds".
    """

    def __init__(self, **config: Any):
        super().__init__(**config)

    @staticmethod
    def add_cli_arguments(parser) -> None:  # pragma: no cover - shim
        return None

    @classmethod
    def from_config(cls, config: dict[str, Any]):
        return cls(**config)

    @property
    def platform_name(self) -> str:
        return "StubPlatform"

    def get_target_dialect(self) -> str | None:
        return None

    def create_connection(self, **connection_config):
        return _RecordingConnection()

    def create_schema(self, benchmark, connection):
        return 0.0

    def load_data(self, benchmark, connection, data_dir):
        return {}, 0.0, None

    def configure_for_benchmark(self, connection, benchmark_type):
        return None

    def execute_query(self, connection, query, query_id, **kwargs):
        return {"query_id": query_id, "status": "SUCCESS"}

    def apply_platform_optimizations(self, platform_config, connection):
        return None

    def apply_constraint_configuration(self, primary_key_config, foreign_key_config, connection):
        return None

    def apply_unified_tuning(self, unified_config: UnifiedTuningConfiguration, connection: Any) -> None:
        # Deliberately partial: only "apply" constraints, skip every
        # table-level tuning (this is the drift this test pins -- a real
        # adapter silently under-applying would look identical from
        # tunings_applied's perspective).
        connection.execute("APPLY CONSTRAINTS")

    def save_tuning_metadata(self, connection: Any) -> bool:
        return True


def _requested_config_with_table_tunings() -> UnifiedTuningConfiguration:
    config = UnifiedTuningConfiguration()
    config.table_tunings["orders"] = TableTuning(
        table_name="orders",
        sorting=[TuningColumn(name="o_orderkey", type="INTEGER", order=1)],
    )
    config.table_tunings["customer"] = TableTuning(
        table_name="customer",
        sorting=[TuningColumn(name="c_custkey", type="INTEGER", order=1)],
    )
    return config


class TestRequestedConfigCaptureNotAppliedVerification:
    """Pins today's `tunings_applied` derivation: requested config capture,
    not a verified record of executed statements.
    """

    def _run_setup_phase(self, effective_config: UnifiedTuningConfiguration, tmp_path):
        adapter = _PartiallyApplyingStubAdapter(
            tuning_enabled=True,
            unified_tuning_configuration=effective_config,
        )
        connection = adapter.create_connection()
        benchmark = SimpleNamespace(output_dir=tmp_path)

        (
            _schema_time,
            _schema_creation_phase,
            _loading_time,
            _table_stats,
            _data_loading_phase,
            tuning_metadata_saved,
        ) = adapter._setup_fresh_database_phases(benchmark, connection, effective_config)

        return adapter, connection, tuning_metadata_saved

    def test_adapter_under_applies_table_tunings_via_connection(self, tmp_path) -> None:
        effective_config = _requested_config_with_table_tunings()
        _adapter, connection, _saved = self._run_setup_phase(effective_config, tmp_path)

        # The stub only ever executes the constraint statement -- neither
        # requested table tuning (orders/customer sorting) reaches the
        # connection.
        assert connection.executed_statements == ["APPLY CONSTRAINTS"]

    def test_tunings_applied_reports_full_requested_config_regardless_of_execution(self, tmp_path) -> None:
        effective_config = _requested_config_with_table_tunings()
        adapter, connection, tuning_metadata_saved = self._run_setup_phase(effective_config, tmp_path)

        # Reproduce adapter.py's run_enhanced_benchmark derivation verbatim
        # (lines ~781-785) rather than re-deriving new logic, to pin the
        # actual production wiring.
        tunings_applied_dict = None
        tuning_validation_status = "NOT_APPLICABLE"
        if adapter.tuning_enabled and effective_config:
            tunings_applied_dict = effective_config.to_dict()
            tuning_validation_status = "APPLIED" if tuning_metadata_saved else "FAILED_TO_SAVE"

        assert tuning_validation_status == "APPLIED"

        # The documented gap: tunings_applied still lists both tables' sort
        # tunings even though the connection only ever saw "APPLY
        # CONSTRAINTS" -- tunings_applied is the *requested* config, not a
        # derivation of connection.executed_statements.
        assert set(tunings_applied_dict["table_tunings"]) == {"orders", "customer"}
        assert connection.executed_statements == ["APPLY CONSTRAINTS"]
        assert "sorting" not in connection.executed_statements[0]

    def test_tuning_validation_status_reflects_metadata_save_not_statement_execution(self, tmp_path) -> None:
        # save_tuning_metadata succeeding is orthogonal to whether every
        # requested tuning was actually executed -- pin that
        # tuning_validation_status="APPLIED" is possible even when the
        # connection demonstrably never saw most of the requested config.
        effective_config = _requested_config_with_table_tunings()
        adapter, connection, tuning_metadata_saved = self._run_setup_phase(effective_config, tmp_path)

        assert tuning_metadata_saved is True
        assert len(connection.executed_statements) == 1
