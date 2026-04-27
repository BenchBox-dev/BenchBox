"""Shared base classes for transactional benchmark families.

Provides ``OperationsRegistryBase`` and ``TransactionalBenchmarkBase``
factored out of ``transaction_primitives`` and ``write_primitives``.
"""

from benchbox.core.transactional.benchmark_base import TransactionalBenchmarkBase
from benchbox.core.transactional.operations_registry_base import OperationsRegistryBase

__all__ = ["OperationsRegistryBase", "TransactionalBenchmarkBase"]
