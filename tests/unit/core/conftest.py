"""Shared fixtures and utilities for core unit tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations


class MockExpr:
    """Minimal expression mock for DataFrame/expression API testing.

    Supports all operators needed by both Polars-style expression_impl and
    pandas-style pandas_impl functions: comparisons, booleans, arithmetic,
    item access, and method chaining - all return self.

    Exists because MagicMock raises TypeError for ``mock >= mock`` comparisons
    when the comparison result is used inside numpy/polars boolean contexts.
    """

    def __ge__(self, other: object) -> MockExpr:
        return self

    def __le__(self, other: object) -> MockExpr:
        return self

    def __gt__(self, other: object) -> MockExpr:
        return self

    def __lt__(self, other: object) -> MockExpr:
        return self

    def __eq__(self, other: object) -> MockExpr:  # type: ignore[override]
        return self

    def __ne__(self, other: object) -> MockExpr:  # type: ignore[override]
        return self

    def __and__(self, other: object) -> MockExpr:
        return self

    def __or__(self, other: object) -> MockExpr:
        return self

    def __invert__(self) -> MockExpr:
        return self

    def __add__(self, other: object) -> MockExpr:
        return self

    def __sub__(self, other: object) -> MockExpr:
        return self

    def __mul__(self, other: object) -> MockExpr:
        return self

    def __truediv__(self, other: object) -> MockExpr:
        return self

    def __radd__(self, other: object) -> MockExpr:
        return self

    def __rsub__(self, other: object) -> MockExpr:
        return self

    def __rmul__(self, other: object) -> MockExpr:
        return self

    def __rtruediv__(self, other: object) -> MockExpr:
        return self

    def __getitem__(self, key: object) -> MockExpr:
        return self

    def __setitem__(self, key: object, value: object) -> None:
        pass

    def __bool__(self) -> bool:
        return True

    def __len__(self) -> int:
        return 0

    def __iter__(self):
        return iter([])

    def __getattr__(self, name: str) -> MockExpr:
        return self

    def __call__(self, *args: object, **kwargs: object) -> MockExpr:
        return self
