"""Regression: generated DataFrame query impls live in a typed registry.

PR #603 injected factory-built query impls into module globals
(`globals()[name] = impl`), which made the dispatch (`_impl_for`) Any-typed
and the generated names invisible to `ty` and grep. This pins the fix: impls
register into the typed `_IMPLS` registry (no module-globals mutation) and stay
resolvable by name via PEP 562 `__getattr__`, so the globals-injection pattern
cannot silently return.
"""

from __future__ import annotations

import pytest

import benchbox.core.joinorder.dataframe_queries as jo
import benchbox.core.read_primitives.dataframe_queries as rp

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_read_primitives_generated_impl_in_registry_not_globals() -> None:
    name = "aggregation_distinct_groupby_pandas_impl"  # a factory-generated impl
    assert name in rp._IMPLS
    assert name not in vars(rp)  # not injected into module globals
    assert getattr(rp, name) is rp._IMPLS[name]  # served via __getattr__


def test_joinorder_generated_impls_in_registry_not_globals() -> None:
    assert jo._IMPLS  # joinorder registry holds every (generated) impl
    for name in jo._IMPLS:
        assert name not in vars(jo)  # none injected into module globals
    sample = next(iter(jo._IMPLS))
    assert getattr(jo, sample) is jo._IMPLS[sample]


def test_tpcds_generated_impls_in_registry_not_globals() -> None:
    from benchbox.core.tpcds.dataframe_queries import queries as tpcds

    for name in ("q3_expression_impl", "q19_pandas_impl"):
        assert name in tpcds._GENERATED_IMPLS
        assert name not in vars(tpcds)
        assert getattr(tpcds, name) is tpcds._GENERATED_IMPLS[name]


def test_dispatch_resolves_explicit_and_generated_from_registry() -> None:
    # _impl_for resolves both explicit module defs and generated impls via the
    # single typed registry.
    generated = rp._impl_for("aggregation_distinct_groupby", "pandas")
    assert generated is rp._IMPLS["aggregation_distinct_groupby_pandas_impl"]


def test_unknown_generated_name_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        rp.totally_missing_query_impl  # noqa: B018
    with pytest.raises(AttributeError):
        jo.totally_missing_query_impl  # noqa: B018
    from benchbox.core.tpcds.dataframe_queries import queries as tpcds

    with pytest.raises(AttributeError):
        tpcds.totally_missing_query_impl  # noqa: B018
