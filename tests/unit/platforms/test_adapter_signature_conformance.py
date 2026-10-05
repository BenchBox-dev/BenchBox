"""Conformance: adapter tuning arity and pooled-connection dispatch.

Two signature-drift gates over every registered adapter:

1. ``apply_unified_tuning`` must accept the two arguments the base setup phase
   passes (``PlatformAdapter`` calls ``apply_unified_tuning(config, connection)``).
   A one-argument override raises ``TypeError`` on tuned runs.
2. ``get_connection_from_pool`` must call ``create_connection`` the way each
   adapter's signature requires: the whole platform config as keywords for
   adapters accepting arbitrary keywords, a single ``connection_config`` dict
   for MotherDuck-style signatures, and no arguments for Glue-style no-arg
   signatures.

No live connections are opened: part 1 inspects signatures statically, and
part 2 drives stub adapters plus a static sweep over registered classes.

Velox note: its ``create_connection`` signature is pool-compatible
(``**connection_config``). Its pooled failure inside the fake-driver harness
(``AttributeError: 'tuple' object has no attribute 'name'`` at
``catalog.listDatabases``) is a harness artifact — the generic fake yields raw
scripted tuples when iterated, while the real PySpark ``Catalog.listDatabases``
returns ``Database`` objects with ``.name`` (the same ``db.name`` pattern
``spark.py`` and ``lakesail.py`` use). It is recorded in
``POOL_FAKE_HARNESS_EXEMPTIONS``, not worked around in product code.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from benchbox.core.platform_registry import PlatformRegistry
from benchbox.platforms.base.connection_lifecycle import ConnectionLifecycleMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _adapter_names() -> list[str]:
    return sorted(PlatformRegistry.get_available_platforms())


def _pool_style(adapter_class: type) -> str:
    """Classify how the pooled path must call this adapter's create_connection."""
    parameters = inspect.signature(adapter_class.create_connection).parameters
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in parameters.values()):
        return "kwargs"
    if "connection_config" in parameters:
        return "config_dict"
    return "none"


# Adapters whose pooled failure inside the fake-driver harness is an asserted,
# documented harness artifact rather than a product defect.
POOL_FAKE_HARNESS_EXEMPTIONS: dict[str, str] = {
    "velox": (
        "The generic fake yields raw scripted tuples when iterated, so the fake "
        "catalog.listDatabases() items lack .name; the real PySpark API returns "
        "Database objects (same db.name pattern as spark.py and lakesail.py). "
        "The velox create_connection signature itself is pool-compatible."
    ),
}


@pytest.mark.parametrize("name", _adapter_names())
def test_apply_unified_tuning_accepts_config_and_connection(name: str) -> None:
    """Every adapter's apply_unified_tuning binds the two setup-phase arguments."""
    adapter_class = PlatformRegistry.get_adapter_class(name)
    signature = inspect.signature(adapter_class.apply_unified_tuning)
    try:
        signature.bind(object(), object(), object())
    except TypeError as exc:
        pytest.fail(f"{name}.{adapter_class.__name__}.apply_unified_tuning does not accept (config, connection): {exc}")


@pytest.mark.parametrize("name", _adapter_names())
def test_pooled_call_binds_for_registered_adapter(name: str) -> None:
    """The pooled dispatch shape binds for every registered create_connection.

    Any adapter whose signature fits none of the three supported shapes fails
    here, forcing an explicit dispatch rule instead of a runtime TypeError.
    """
    adapter_class = PlatformRegistry.get_adapter_class(name)
    signature = inspect.signature(adapter_class.create_connection)
    style = _pool_style(adapter_class)
    try:
        if style == "kwargs":
            signature.bind(object())
        elif style == "config_dict":
            signature.bind(object(), connection_config={})
        else:
            signature.bind(object())
    except TypeError as exc:
        pytest.fail(
            f"{name}.{adapter_class.__name__}.create_connection is not reachable via pooled style {style!r}: {exc}"
        )


@pytest.mark.parametrize(
    ("name", "expected_style"),
    [
        ("glue", "none"),
        ("motherduck", "config_dict"),
        ("clickhouse-server", "kwargs"),
        ("velox", "kwargs"),
        ("synapse-spark", "kwargs"),
    ],
)
def test_known_adapters_use_expected_pool_style(name: str, expected_style: str) -> None:
    """Pin the dispatch style of the adapters behind the reported failures."""
    adapter_class = PlatformRegistry.get_adapter_class(name)
    assert _pool_style(adapter_class) == expected_style, (
        f"{name}.{adapter_class.__name__}.create_connection signature changed shape; "
        "update the pooled dispatch or this expectation."
    )


class _StubAdapter(ConnectionLifecycleMixin):
    """Minimal pooled-path host: no pool, canned platform config, recorded calls."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.connection_pool = None
        self.platform_config = dict(config)
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []


class _KwargsAdapter(_StubAdapter):
    def create_connection(self, **connection_config: Any) -> Any:
        self.calls.append(((), dict(connection_config)))
        return "kwargs-conn"


class _ConfigDictAdapter(_StubAdapter):
    def create_connection(self, connection_config: dict[str, Any] | None = None) -> Any:
        self.calls.append(((), {"connection_config": connection_config}))
        return "dict-conn"


class _NoArgAdapter(_StubAdapter):
    def create_connection(self) -> Any:
        self.calls.append(((), {}))
        return "bare-conn"


def test_pool_passes_whole_config_to_kwargs_adapter() -> None:
    adapter = _KwargsAdapter({"host": "db.test", "database": "benchdb"})
    assert adapter.get_connection_from_pool() == "kwargs-conn"
    assert adapter.calls == [((), {"host": "db.test", "database": "benchdb"})]


def test_pool_passes_config_dict_to_single_dict_adapter() -> None:
    adapter = _ConfigDictAdapter({"host": "db.test", "database": "benchdb"})
    assert adapter.get_connection_from_pool() == "dict-conn"
    assert adapter.calls == [((), {"connection_config": {"host": "db.test", "database": "benchdb"}})]


def test_pool_calls_no_arg_adapter_bare() -> None:
    adapter = _NoArgAdapter({"host": "db.test", "database": "benchdb"})
    assert adapter.get_connection_from_pool() == "bare-conn"
    assert adapter.calls == [((), {})]


def test_pool_still_prefers_connection_pool() -> None:
    adapter = _KwargsAdapter({"host": "db.test"})

    class _Pool:
        def get_connection(self) -> str:
            return "pooled-conn"

    adapter.connection_pool = _Pool()
    assert adapter.get_connection_from_pool() == "pooled-conn"
    assert adapter.calls == []


def test_pool_fake_harness_exemptions_are_current() -> None:
    """Exemptions name registered adapters whose signatures are pool-compatible."""
    registered = set(PlatformRegistry.get_available_platforms())
    assert set(POOL_FAKE_HARNESS_EXEMPTIONS) <= registered
    for name in POOL_FAKE_HARNESS_EXEMPTIONS:
        adapter_class = PlatformRegistry.get_adapter_class(name)
        assert _pool_style(adapter_class) == "kwargs", (
            f"{name} is exempted as a harness artifact but its signature no longer fits the kwargs style; "
            "re-investigate instead of keeping a stale exemption."
        )
