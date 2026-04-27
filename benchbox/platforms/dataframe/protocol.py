"""Structural-typing protocol for native DataFrames wrapped by UnifiedLazyFrame.

The wrapper in unified_frame.py is generic over a `DF` TypeVar. Today that
TypeVar is unconstrained, which forces every method that accepts a native
frame to type its parameter as ``Any``. This module defines a minimal
protocol - ``LazyFrameLike`` - that captures the small surface
UnifiedLazyFrame actually requires from any native backend.

Why the protocol is intentionally small
---------------------------------------
The expression-family backends (Polars, PySpark, DataFusion) share almost
no method names: Polars uses ``group_by``, PySpark uses ``groupBy``,
DataFusion uses ``aggregate``. UnifiedLazyFrame exists precisely to paper
over these differences via runtime dispatch. So the protocol captures
ONLY the operations that are genuinely common across all three:

  * ``columns`` - every backend exposes a column-name attribute or
    method, though the access path varies. The wrapper accepts both
    ``df.columns`` (Polars/Pandas) and ``df.schema()`` (DataFusion) by
    runtime introspection; the protocol lists ``columns`` as the
    canonical attribute.

Anything more specific belongs in a backend-specific narrowing, not in
a shared protocol - because forcing structural conformance where the
backends genuinely diverge would either lie about the type or require
shim methods on the upstream libraries that we cannot add.

Use as
------

    from benchbox.platforms.dataframe.protocol import LazyFrameLike

    def takes_native(df: LazyFrameLike) -> list[str]:
        return list(df.columns)

For runtime conformance verification (used by the test suite):

    from benchbox.platforms.dataframe.protocol import LazyFrameLike
    assert isinstance(my_polars_lf, LazyFrameLike)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LazyFrameLike(Protocol):
    """Minimum structural surface required of any native DataFrame.

    Backends that satisfy this protocol today: Polars LazyFrame and
    DataFrame, Pandas DataFrame, PyArrow Table, PySpark DataFrame.

    DataFusion DataFrames satisfy this via the ``schema()`` method
    routing in ``UnifiedLazyFrame.columns`` rather than a direct
    ``columns`` attribute - they are accepted at runtime but do not
    pass ``isinstance(df, LazyFrameLike)``. This is intentional; see
    module docstring.
    """

    @property
    def columns(self) -> list[str] | tuple[str, ...]:
        """Column names of the frame, in declaration order."""
        ...
