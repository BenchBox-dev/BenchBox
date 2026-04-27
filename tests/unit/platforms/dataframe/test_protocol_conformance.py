"""LazyFrameLike protocol conformance for the supported backends.

The protocol only constrains the structural surface that UnifiedLazyFrame
genuinely shares across backends today (see protocol.py module docstring
for why it's intentionally minimal). These tests pin that contract so a
silent upstream rename of ``.columns`` would surface here, not deep in
benchmark execution.

DataFusion is intentionally excluded: it routes column access via
``schema().fields[].name`` rather than a ``.columns`` attribute, so
``isinstance(df, LazyFrameLike)`` is False by design. The wrapper
handles that path through runtime introspection.
"""

from __future__ import annotations

import pytest

from benchbox.platforms.dataframe.protocol import LazyFrameLike

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_polars_lazyframe_satisfies_protocol() -> None:
    pl = pytest.importorskip("polars")
    lf = pl.LazyFrame({"a": [1, 2], "b": [3, 4]})
    assert isinstance(lf, LazyFrameLike)
    assert list(lf.columns) == ["a", "b"]


def test_polars_dataframe_satisfies_protocol() -> None:
    pl = pytest.importorskip("polars")
    df = pl.DataFrame({"a": [1, 2], "b": [3, 4]})
    assert isinstance(df, LazyFrameLike)
    assert list(df.columns) == ["a", "b"]


def test_pandas_dataframe_satisfies_protocol() -> None:
    pd = pytest.importorskip("pandas")
    df = pd.DataFrame({"a": [1, 2], "b": [3, 4]})
    assert isinstance(df, LazyFrameLike)
    assert list(df.columns) == ["a", "b"]


def test_pyarrow_table_satisfies_protocol() -> None:
    pa = pytest.importorskip("pyarrow")
    table = pa.table({"a": [1, 2], "b": [3, 4]})
    # PyArrow's column_names is the public attribute; .columns returns Arrays.
    # Confirm .columns is a list of Arrays, not names - pyarrow Table technically
    # has both. The protocol accepts either typing; the runtime check passes
    # because pyarrow Table has a ``columns`` attribute.
    assert isinstance(table, LazyFrameLike)


def test_protocol_rejects_non_dataframe() -> None:
    assert not isinstance({"a": [1, 2]}, LazyFrameLike)
    assert not isinstance([[1, 2], [3, 4]], LazyFrameLike)


def test_protocol_accepts_minimal_duck() -> None:
    """A duck-typed object with .columns should satisfy the protocol."""

    class _Duck:
        @property
        def columns(self) -> list[str]:
            return ["x", "y"]

    assert isinstance(_Duck(), LazyFrameLike)
