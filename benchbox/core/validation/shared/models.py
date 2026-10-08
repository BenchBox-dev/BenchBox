from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ValidationStatus(Enum):
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


@dataclass
class RowCountDiscrepancy:
    table_name: str
    expected_count: int
    actual_count: int
    difference: int
    percentage_diff: float
    tolerance_exceeded: bool
    status: ValidationStatus

    @property
    def is_significant(self) -> bool:
        return self.tolerance_exceeded

    def to_summary(self) -> str:
        return (
            f"Table '{self.table_name}': expected {self.expected_count:,}, "
            f"actual {self.actual_count:,} ({self.percentage_diff:+.2f}%)"
        )

    def __str__(self) -> str:
        return self.to_summary()


__all__ = ["ValidationStatus", "RowCountDiscrepancy"]
