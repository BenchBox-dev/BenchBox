"""Registry-completeness and NoOp-fallback tests for get_ddl_generator().

Covers the 2026-07-12 tuning review finding R2: questdb, pg_duckdb, and
pg_mooncake shipped dedicated DDL generators (with their own unit tests) that
were never wired into get_ddl_generator()'s platform mapping, so callers
silently got an empty-clauses NoOpDDLGenerator instead. These tests:

1. Pin the fix for the three specific platforms (registration + NoOp
   fallback is no longer silent for platforms that should have a real
   generator).
2. Add a general regression guard so a future generator module can't be
   added to benchbox/core/tuning/generators/ without being registered in
   get_ddl_generator(), by statically inspecting the function's own mapping
   literal rather than re-implementing (and risking drift from) its logic.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import ast
import inspect
import logging
import pkgutil
from importlib import import_module

import pytest

from benchbox.core.tuning import generators as generators_pkg
from benchbox.core.tuning.ddl_generator import (
    BaseDDLGenerator,
    NoOpDDLGenerator,
    get_ddl_generator,
)
from benchbox.core.tuning.generators.pg_duckdb import PgDuckDBDDLGenerator
from benchbox.core.tuning.generators.pg_mooncake import PgMooncakeDDLGenerator
from benchbox.core.tuning.generators.questdb import QuestDBDDLGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Generator classes intentionally NOT reachable via get_ddl_generator()'s
# platform-key dispatch. Keep this empty unless a generator is genuinely
# selected some other way - document the reason inline when adding an entry.
#
# IcebergDDLGenerator / ParquetDDLGenerator / HiveDDLGenerator: these are
# Spark table-format variants selected via SparkDDLGeneratorMixin's own
# SparkTableFormat dispatch (benchbox/platforms/base/cloud_spark/mixins.py),
# not via a get_ddl_generator() platform key. Only the Delta variant is
# reachable through get_ddl_generator (as "databricks"/"spark"/"delta"/
# "fabric_warehouse") because it is also usable standalone for dry-run.
_EXEMPT_GENERATOR_CLASSES: frozenset[str] = frozenset(
    {
        "IcebergDDLGenerator",
        "ParquetDDLGenerator",
        "HiveDDLGenerator",
    }
)


def _discover_concrete_generator_classes() -> dict[str, type[BaseDDLGenerator]]:
    """Find every concrete BaseDDLGenerator subclass defined in a module
    under benchbox/core/tuning/generators/.

    Walks the actual submodules (not just generators/__init__.py's __all__)
    so a new generator module is picked up even before anyone remembers to
    export it. Only classes *defined* in the module (not merely imported,
    e.g. PostgreSQLDDLGenerator re-used by timescaledb.py) are counted, and
    abstract classes (e.g. SparkBaseDDLGenerator) are excluded.
    """
    discovered: dict[str, type[BaseDDLGenerator]] = {}
    for module_info in pkgutil.iter_modules(generators_pkg.__path__, prefix=f"{generators_pkg.__name__}."):
        module = import_module(module_info.name)
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                obj.__module__ == module.__name__
                and issubclass(obj, BaseDDLGenerator)
                and obj is not BaseDDLGenerator
                and not inspect.isabstract(obj)
            ):
                discovered[name] = obj
    return discovered


def _registered_generator_class_names() -> set[str]:
    """Statically extract the class names in get_ddl_generator()'s `generators`
    mapping literal, by parsing the function's own source with `ast`.

    This deliberately does not re-import/re-declare the mapping (that would
    just be a second copy that could drift from the real one) - it inspects
    the actual dict literal inside get_ddl_generator() itself, so this test
    fails the moment a class stops being referenced there.
    """
    source = inspect.getsource(get_ddl_generator)
    tree = ast.parse(source)
    function_node = tree.body[0]
    assert isinstance(function_node, ast.FunctionDef)

    class_names: set[str] = set()
    for node in ast.walk(function_node):
        # `generators: dict[str, type[BaseDDLGenerator]] = {...}` is an
        # annotated assignment (ast.AnnAssign, single `target`), not a plain
        # ast.Assign (which has a `targets` list) - handle both forms.
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "generators"
            or isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "generators" for target in node.targets)
        ):
            dict_node = node.value
        else:
            continue

        assert isinstance(dict_node, ast.Dict), "Expected `generators` to be assigned a dict literal"
        for value in dict_node.values:
            assert isinstance(value, ast.Name), f"Expected a bare class name in generators dict, got {value!r}"
            class_names.add(value.id)
        break
    else:
        raise AssertionError("Could not find a `generators = {...}` assignment in get_ddl_generator()")

    return class_names


class TestDDLGeneratorRegistryCompleteness:
    """Every concrete generator module must be reachable via get_ddl_generator()."""

    def test_exempt_list_has_no_stale_entries(self) -> None:
        """Every exemption must correspond to a real, currently-unregistered generator.

        Keeps _EXEMPT_GENERATOR_CLASSES honest: if a class is registered later,
        its exemption entry must be removed too.
        """
        discovered = _discover_concrete_generator_classes()
        registered = _registered_generator_class_names()
        unregistered = set(discovered) - registered

        stale = _EXEMPT_GENERATOR_CLASSES - unregistered
        assert not stale, f"Stale exemptions (already registered or no longer exist): {sorted(stale)}"

    def test_every_generator_module_class_is_registered(self) -> None:
        """Every exported, concrete DDL generator class must have a platform key.

        Regression guard for review finding R2: questdb.py, pg_duckdb.py, and
        pg_mooncake.py shipped generator classes with dedicated unit tests but
        no entry in get_ddl_generator()'s mapping, so get_ddl_generator()
        silently returned NoOpDDLGenerator for those platforms.
        """
        discovered = _discover_concrete_generator_classes()
        assert discovered, "Expected to discover at least one concrete DDL generator class"

        registered = _registered_generator_class_names()
        missing = set(discovered) - registered - _EXEMPT_GENERATOR_CLASSES

        assert not missing, (
            f"Generator classes not reachable via get_ddl_generator(): {sorted(missing)}. "
            "Add a platform key -> class entry in get_ddl_generator()'s `generators` "
            "mapping, or add the class to _EXEMPT_GENERATOR_CLASSES with a reason."
        )


class TestNewPlatformGeneratorRegistration:
    """Pin the specific w1 registrations from review finding R2."""

    def test_questdb_is_registered(self) -> None:
        generator = get_ddl_generator("questdb")
        assert isinstance(generator, QuestDBDDLGenerator)
        assert not isinstance(generator, NoOpDDLGenerator)

    @pytest.mark.parametrize("platform_key", ["pg_duckdb", "pg-duckdb"])
    def test_pg_duckdb_is_registered(self, platform_key: str) -> None:
        generator = get_ddl_generator(platform_key)
        assert isinstance(generator, PgDuckDBDDLGenerator)
        assert not isinstance(generator, NoOpDDLGenerator)

    @pytest.mark.parametrize("platform_key", ["pg_mooncake", "pg-mooncake"])
    def test_pg_mooncake_is_registered(self, platform_key: str) -> None:
        generator = get_ddl_generator(platform_key)
        assert isinstance(generator, PgMooncakeDDLGenerator)
        assert not isinstance(generator, NoOpDDLGenerator)

    def test_lookup_is_case_insensitive(self) -> None:
        assert isinstance(get_ddl_generator("QuestDB"), QuestDBDDLGenerator)
        assert isinstance(get_ddl_generator("PG-DUCKDB"), PgDuckDBDDLGenerator)
        assert isinstance(get_ddl_generator("Pg_Mooncake"), PgMooncakeDDLGenerator)


class TestNoOpFallbackWarning:
    """w2: NoOp fallback must warn for platforms that aren't known tuning-free,
    but must never raise, and must stay silent for genuinely tuning-free
    platforms.
    """

    def test_unknown_platform_still_returns_noop_without_raising(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="benchbox.core.tuning.ddl_generator"):
            generator = get_ddl_generator("totally-unregistered-platform-xyz")

        assert isinstance(generator, NoOpDDLGenerator)
        assert generator.platform_name == "totally-unregistered-platform-xyz"

    def test_unknown_platform_logs_a_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="benchbox.core.tuning.ddl_generator"):
            get_ddl_generator("totally-unregistered-platform-xyz")

        assert any(
            "totally-unregistered-platform-xyz" in record.getMessage() and record.levelno == logging.WARNING
            for record in caplog.records
        )

    def test_starrocks_falls_back_loudly(self, caplog: pytest.LogCaptureFixture) -> None:
        """StarRocks has no generator yet (deferred pending ADR-3) - this is
        exactly the "silently-empty tuning preview" symptom from review finding
        R2, so it must now warn rather than stay silent.
        """
        with caplog.at_level(logging.WARNING, logger="benchbox.core.tuning.ddl_generator"):
            generator = get_ddl_generator("starrocks")

        assert isinstance(generator, NoOpDDLGenerator)
        assert any("starrocks" in record.getMessage() for record in caplog.records)

    @pytest.mark.parametrize("platform_key", ["sqlite", "sqlite3", "pandas", "modin", "cudf", "dask", "polars"])
    def test_known_tuning_free_platforms_stay_silent(self, platform_key: str, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="benchbox.core.tuning.ddl_generator"):
            generator = get_ddl_generator(platform_key)

        assert isinstance(generator, NoOpDDLGenerator)
        assert caplog.records == []

    def test_registered_platform_never_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING, logger="benchbox.core.tuning.ddl_generator"):
            get_ddl_generator("questdb")

        assert caplog.records == []
