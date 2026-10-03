from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Protocol, runtime_checkable

REQUIRED_RUNTIME_METHODS: tuple[str, ...] = (
    "generate_data",
    "get_query",
    "get_queries",
    "create_enhanced_benchmark_result",
)

EXTENDED_RUNTIME_METHODS: tuple[str, ...] = (
    "create_minimal_benchmark_result",
    "validate_preflight",
    "validate_manifest",
    "validate_loaded_data",
)


@runtime_checkable
class BenchmarkRuntimeContract(Protocol):
    scale_factor: float

    @property
    def benchmark_name(self) -> str:
        pass

    def generate_data(self, *args: Any, **kwargs: Any) -> Any:
        pass

    def get_queries(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        pass

    def get_query(self, query_id: int | str, *args: Any, **kwargs: Any) -> str:
        pass

    def create_enhanced_benchmark_result(
        self,
        platform: str,
        query_results: list[dict[str, Any]],
        **kwargs: Any,
    ) -> Any:
        pass


@runtime_checkable
class BenchmarkExtendedRuntimeContract(BenchmarkRuntimeContract, Protocol):
    def create_minimal_benchmark_result(self, **kwargs: Any) -> Any:
        pass

    def validate_preflight(self, **kwargs: Any) -> Any:
        pass

    def validate_manifest(self, **kwargs: Any) -> Any:
        pass

    def validate_loaded_data(self, connection: Any, **kwargs: Any) -> Any:
        pass


def get_missing_methods(instance: Any, method_names: Iterable[str]) -> list[str]:

    missing: list[str] = []
    for method_name in method_names:
        attr = getattr(instance, method_name, None)
        if not callable(attr):
            missing.append(method_name)
    return sorted(missing)


def has_runtime_contract(instance: Any) -> bool:

    return not get_missing_methods(instance, REQUIRED_RUNTIME_METHODS)


def has_extended_runtime_contract(instance: Any) -> bool:

    method_set = REQUIRED_RUNTIME_METHODS + EXTENDED_RUNTIME_METHODS
    return not get_missing_methods(instance, method_set)
