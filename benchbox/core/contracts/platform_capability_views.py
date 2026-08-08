"""Runtime compatibility views for narrow platform capability protocols."""

from __future__ import annotations

from typing import Any, TypeVar, cast

from benchbox.core.contracts.platform_capabilities import (
    CapabilityContractError,
    CategorizedQueryBenchmark,
    ConnectionFactory,
    ConnectionLifecycle,
    DataFrameBenchmarkExecutor,
    DataFrameQueryRuntime,
    ExternalTableLoader,
    NativeTableLoader,
    PlanCaptureRuntime,
    SQLBenchmarkExecutor,
    StatisticsPhaseRunner,
    TuningLedgerWriter,
)

_CapabilityT = TypeVar("_CapabilityT")


def _capability_view(
    candidate: object,
    contract: type[_CapabilityT],
    capability_name: str,
    *,
    required_callables: tuple[str, ...],
    required_data: tuple[str, ...] = (),
) -> _CapabilityT:
    """Return a structural view or fail with actionable member evidence."""

    missing = [member for member in (*required_callables, *required_data) if not hasattr(candidate, member)]
    if missing:
        detail = f"; missing: {', '.join(missing)}"
        raise CapabilityContractError(f"{type(candidate).__name__} does not provide {capability_name}{detail}")
    non_callable = [member for member in required_callables if not callable(getattr(candidate, member))]
    if non_callable:
        detail = f"; not callable: {', '.join(non_callable)}"
        raise CapabilityContractError(f"{type(candidate).__name__} does not provide {capability_name}{detail}")
    # Runtime checks cannot validate signatures. The strict type island owns
    # that proof; this boundary preserves dynamic mocks and third-party adapters.
    return cast(_CapabilityT, candidate)


def as_sql_benchmark_executor(candidate: object) -> SQLBenchmarkExecutor:
    return _capability_view(
        candidate,
        SQLBenchmarkExecutor,
        "SQL benchmark execution",
        required_callables=("run_benchmark",),
    )


def as_dataframe_benchmark_executor(candidate: object) -> DataFrameBenchmarkExecutor:
    return _capability_view(
        candidate,
        DataFrameBenchmarkExecutor,
        "DataFrame benchmark execution",
        required_callables=("run_benchmark",),
    )


def as_connection_lifecycle(candidate: object) -> ConnectionLifecycle:
    return _capability_view(
        candidate,
        ConnectionLifecycle,
        "connection lifecycle",
        required_callables=("create_connection", "close_connection"),
    )


def as_connection_factory(candidate: object) -> ConnectionFactory:
    return _capability_view(
        candidate,
        ConnectionFactory,
        "connection creation",
        required_callables=("create_connection",),
    )


def as_native_table_loader(candidate: object) -> NativeTableLoader:
    return _capability_view(
        candidate,
        NativeTableLoader,
        "native table loading",
        required_callables=("create_schema", "load_data"),
    )


def as_external_table_loader(candidate: object) -> ExternalTableLoader:
    return _capability_view(
        candidate,
        ExternalTableLoader,
        "external table loading",
        required_callables=("create_external_tables",),
        required_data=("supports_external_tables",),
    )


def as_dataframe_query_runtime(candidate: object) -> DataFrameQueryRuntime:
    return _capability_view(
        candidate,
        DataFrameQueryRuntime,
        "DataFrame query runtime",
        required_callables=("create_context", "load_table", "execute_query"),
        required_data=("platform_name",),
    )


def as_statistics_phase_runner(candidate: object) -> StatisticsPhaseRunner:
    return _capability_view(
        candidate,
        StatisticsPhaseRunner,
        "statistics phase",
        required_callables=("run_statistics_phase",),
    )


def as_tuning_ledger_writer(candidate: object) -> TuningLedgerWriter:
    return _capability_view(
        candidate,
        TuningLedgerWriter,
        "tuning ledger writing",
        required_callables=("_write_applied_tuning_ledger",),
    )


def as_plan_capture_runtime(candidate: object) -> PlanCaptureRuntime:
    return _capability_view(
        candidate,
        PlanCaptureRuntime,
        "plan capture",
        required_callables=("capture_query_plan",),
    )


def run_categorized_query_benchmark(
    candidate: object,
    connection: Any,
    category: str,
    iterations: int = 1,
) -> dict[str, Any]:
    """Run one category through the specialized direct-run contract."""

    runner = _capability_view(
        candidate,
        CategorizedQueryBenchmark,
        "categorized query benchmark",
        required_callables=("run_benchmark",),
    )
    return runner.run_benchmark(connection, None, iterations, [category])
