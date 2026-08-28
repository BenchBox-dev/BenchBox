"""DataFrame query resolution must reach the registries every benchmark ships.

Eleven benchmarks ship a `benchbox/core/<id>/dataframe_queries/` package that
registers `DataFrameQuery` objects at import, and the cross-surface equivalence
gates execute them. Query resolution reached none of them: it named only tpch,
tpcds and clickbench, and the `get_dataframe_queries` instance hook is defined
by almost no benchmark class.

So seven families -- amplab, coffeeshop, h2odb, nyctaxi, ssb, tpch_skew,
tsbs_devops -- resolved to zero queries. Both DataFrame builders then logged a
warning, returned an empty list, marked power_test COMPLETED, and emitted a
bundle reporting 0/0 queries with exit 0. Sixty such bundles are in the public
corpus; the split by execution mode is absolute, 60 DataFrame and 0 SQL.

Measured end to end after wiring the registries, `--platform polars-df --scale 0.01`:

    amplab       24/24 pass, exit 0        nyctaxi       3/75 pass, exit 1
    coffeeshop   33/33 pass, exit 0        tsbs_devops   0/54 pass, exit 1
    h2odb        30/30 pass, exit 0
    ssb          39/39 pass, exit 0
    tpch_skew    66/66 pass, exit 0

Five families now work. The two that do not fail loudly with a real Polars
error instead of silently reporting a clean pass, which is the point.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from benchbox.core.dataframe.query import QueryRegistry
from benchbox.core.dataframe.query_resolution import registry_dataframe_queries
from benchbox.core.exceptions import ConfigurationError
from benchbox.core.runner.dataframe_runner import _get_queries_for_benchmark, no_dataframe_queries_message
from benchbox.core.schemas import BenchmarkConfig

pytestmark = [pytest.mark.unit, pytest.mark.fast]

#: Families that had no reachable DataFrame queries before the registry
#: fallback, with the count each registry actually holds.
PREVIOUSLY_UNREACHABLE = {
    "amplab": 8,
    "coffeeshop": 11,
    "h2odb": 10,
    "nyctaxi": 25,
    "ssb": 13,
    "tpch_skew": 22,
    "tsbs_devops": 18,
}


@pytest.mark.parametrize(("benchmark_id", "expected_count"), sorted(PREVIOUSLY_UNREACHABLE.items()))
def test_resolution_reaches_every_shipped_registry(benchmark_id: str, expected_count: int) -> None:
    """The fix: these resolve through the production path, not just in the gates."""
    config = BenchmarkConfig(name=benchmark_id, display_name=benchmark_id, scale_factor=0.01)

    queries = _get_queries_for_benchmark(config, None, stream_id=0)

    assert len(queries) == expected_count
    assert all(getattr(query, "query_id", None) for query in queries)


def test_resolution_detects_a_nonstandard_registry_name() -> None:
    """Registry discovery is type-based because valid constant names are not uniform."""
    queries = registry_dataframe_queries("tpcds_obt")

    assert [query.query_id for query in queries] == ["Q1", "Q2", "Q3"]


def test_the_registry_helper_is_quiet_about_a_benchmark_that_ships_none() -> None:
    """A benchmark with no dataframe_queries package resolves to nothing, not an error."""
    assert registry_dataframe_queries("no_such_benchmark") == []


def test_nested_module_import_error_is_not_hidden(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broken dependency in an existing query module must fail closed."""
    from benchbox.core.dataframe import query_resolution

    error = ModuleNotFoundError("No module named 'broken_dependency'", name="broken_dependency")

    def broken_import(_target: str) -> None:
        raise error

    monkeypatch.setattr(query_resolution.importlib, "import_module", broken_import)

    with pytest.raises(ModuleNotFoundError, match="broken_dependency"):
        registry_dataframe_queries("broken_benchmark")


def test_multiple_registries_are_rejected_as_ambiguous(monkeypatch: pytest.MonkeyPatch) -> None:
    """A module cannot silently choose one of multiple independent registries."""
    from benchbox.core.dataframe import query_resolution

    module = SimpleNamespace(first=QueryRegistry("first"), second=QueryRegistry("second"))
    monkeypatch.setattr(query_resolution.importlib, "import_module", lambda _target: module)

    with pytest.raises(RuntimeError, match="Multiple DataFrame query registries"):
        registry_dataframe_queries("ambiguous")


def test_registry_aliases_do_not_create_false_ambiguity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two exported names for the same registry still resolve deterministically."""
    from benchbox.core.dataframe import query_resolution

    registry = QueryRegistry("aliased")
    module = SimpleNamespace(primary=registry, compatibility_alias=registry)
    monkeypatch.setattr(query_resolution.importlib, "import_module", lambda _target: module)

    assert registry_dataframe_queries("aliased") == []


def test_the_message_distinguishes_a_narrow_filter_from_a_missing_source() -> None:
    """The two causes need different advice.

    An over-narrow `--queries` selection is the user's to correct; a benchmark
    that genuinely ships no DataFrame surface is not, and telling them to check
    their filter would send them in a circle.
    """
    filtered = no_dataframe_queries_message("tpch", {"99"})
    missing = no_dataframe_queries_message("tpcds_obt", None)

    assert "--queries" in filtered and "'99'" in filtered
    assert "--queries" not in missing
    assert "no DataFrame query source" in missing
    assert "SQL mode" in missing


def test_the_runner_raises_instead_of_returning_an_empty_result_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """A genuinely empty resolution must not be survivable.

    Patching resolution to empty reproduces the state the seven families used
    to reach. Before the fix this returned `[]` and the caller went on to mark
    power_test COMPLETED.
    """
    from benchbox.core.runner import dataframe_runner

    monkeypatch.setattr(dataframe_runner, "_get_queries_for_benchmark", lambda *a, **k: [])
    config = BenchmarkConfig(name="tpcds_obt", display_name="TPC-DS OBT", scale_factor=0.01)

    with pytest.raises(ConfigurationError, match="no DataFrame query source"):
        dataframe_runner._execute_dataframe_queries(
            adapter=object(),
            ctx=object(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )
