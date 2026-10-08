# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from abc import ABC, abstractmethod
from typing import Any


class OperationExecutor(ABC):
    @abstractmethod
    def execute_operation(
        self,
        operation_id: str,
        connection: Any,
        **kwargs: Any,
    ) -> Any:
        pass

    @abstractmethod
    def get_all_operations(self) -> dict[str, Any]:
        pass

    @abstractmethod
    def get_operation_categories(self) -> list[str]:
        pass
