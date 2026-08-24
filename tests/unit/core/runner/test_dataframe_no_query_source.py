"""A DataFrame run that executes no queries must fail, not report a clean pass.

`_get_queries_for_benchmark` dispatches to a handler for tpch, tpcds and
clickbench, and otherwise falls back to `benchmark.get_dataframe_queries()`.
Seven benchmark families have neither, so DataFrame mode discovered zero
queries for them -- and both builders then logged a warning, returned an empty
list, marked `power_test` COMPLETED, and emitted a bundle reporting 0/0
queries with exit 0.

Sixty such bundles are in the public corpus, every one from those seven
families: amplab, coffeeshop, h2odb, nyctaxi, ssb, tpch_skew, tsbs_devops.
Measured on develop, the split is absolute -- 60 DataFrame bundles with no
query data and zero SQL bundles with the same problem.

Reproduced live before the fix:
`benchbox run --platform polars-df --benchmark ssb --scale 0.01` exited 0 with
`{"failed": 0, "passed": 0, "total": 0}`. After it, exit 1 with a message
naming the benchmark and pointing at SQL mode.
"""

from __future__ import annotations

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.core.runner.dataframe_runner import no_dataframe_queries_message

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_the_message_distinguishes_a_narrow_filter_from_a_missing_source() -> None:
    """The two causes need different advice.

    An over-narrow `--queries` selection is the user's to correct; a benchmark
    with no DataFrame query source is a coverage gap they cannot fix from the
    command line, and telling them to check their filter would send them in a
    circle.
    """
    filtered = no_dataframe_queries_message("tpch", {"99"})
    missing = no_dataframe_queries_message("ssb", None)

    assert "--queries" in filtered and "'99'" in filtered
    assert "--queries" not in missing
    assert "no DataFrame query source" in missing
    assert "SQL mode" in missing


def test_discovery_really_returns_nothing_for_an_unwired_benchmark() -> None:
    """The premise, against the production dispatch rather than a fixture."""
    from benchbox.core.runner.dataframe_runner import _get_queries_for_benchmark
    from benchbox.core.schemas import BenchmarkConfig

    config = BenchmarkConfig(name="ssb", display_name="SSB", scale_factor=0.01)

    assert _get_queries_for_benchmark(config, None, stream_id=0) == []


def test_the_runner_raises_instead_of_returning_an_empty_result_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fix itself, exercised through the real caller.

    Patching discovery to empty reproduces the exact state the seven unwired
    families reach. Before the fix this returned `[]` and the caller went on to
    mark power_test COMPLETED.
    """
    from benchbox.core.runner import dataframe_runner
    from benchbox.core.schemas import BenchmarkConfig

    monkeypatch.setattr(dataframe_runner, "_get_queries_for_benchmark", lambda *a, **k: [])
    config = BenchmarkConfig(name="ssb", display_name="SSB", scale_factor=0.01)

    with pytest.raises(ConfigurationError, match="no DataFrame query source"):
        dataframe_runner._execute_dataframe_queries(
            adapter=object(),
            ctx=object(),
            benchmark_config=config,
            benchmark_instance=None,
            monitor=None,
        )


@pytest.mark.parametrize(
    "benchmark_id", ["amplab", "coffeeshop", "h2odb", "nyctaxi", "ssb", "tpch_skew", "tsbs_devops"]
)
def test_the_seven_affected_families_still_have_no_dataframe_queries(benchmark_id: str) -> None:
    """Pin the coverage gap so closing it for one family is a visible change.

    This does not assert the gap is acceptable. It records which families
    discover zero DataFrame queries today, so a PR that wires one of them up
    must update this list rather than change corpus behaviour silently.
    """
    from benchbox.core.runner.dataframe_runner import _get_queries_for_benchmark
    from benchbox.core.schemas import BenchmarkConfig

    config = BenchmarkConfig(name=benchmark_id, display_name=benchmark_id, scale_factor=0.01)

    assert _get_queries_for_benchmark(config, None, stream_id=0) == []
