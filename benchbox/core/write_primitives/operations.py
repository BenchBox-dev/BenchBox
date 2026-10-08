# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from benchbox.core.transactional.operations_registry_base import OperationsRegistryBase
from benchbox.core.write_primitives.catalog import (
    WriteOperation,
    load_write_primitives_catalog,
)


class WriteOperationsManager(OperationsRegistryBase[WriteOperation]):
    def __init__(self) -> None:
        catalog = load_write_primitives_catalog()
        super().__init__(catalog.version, catalog.operations)


__all__ = ["WriteOperationsManager"]
