"""Every TPC-DS query with a parameter adapter binds all the values dsqgen puts in its SQL.

For each adapted query, family, seed and stream, two things must hold:

* every value dsqgen logs that reaches the SQL template is read by the adapter, so no drawn value is
  dropped on the way to the DataFrame surface;
* every parameter key the implementation reads is supplied by the binding, so no implementation falls
  back to a default or a literal while the SQL uses a drawn value.

The inventory in ``test_parameter_consumption_inventory.py`` classifies queries by comparing implementations
with the defaults file; it is a diagnostic. This test is the check that a binding is complete.

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import collections
import re
import signal
from collections.abc import Iterator, Mapping

import pytest

from benchbox.core.tpcds.dataframe_queries.parameter_adapters import ADAPTERS, adapter_query_ids
from tests.unit.core.tpcds.test_parameter_consumption_inventory import _DEFINE, _TOKEN, _read_keys

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
    pytest.mark.tpcds,
    # Reading an implementation's keys is bounded with SIGALRM, which Windows does not have.
    pytest.mark.skipif(not hasattr(signal, "SIGALRM"), reason="needs SIGALRM"),
]

# dsqgen's default seed (19620718) and one other; each with the first two streams. The pairs draw
# different values for every adapted query, so a binding that ignores the seed or stream cannot pass.
RUNS = [(None, 0), (None, 1), (42, 0), (42, 1)]


class _RecordingValues(Mapping[str, str]):
    """The logged values, recording which ones the adapter looks up."""

    def __init__(self, values: Mapping[str, str]) -> None:
        self._values = dict(values)
        self.read: set[str] = set()

    def __getitem__(self, key: str) -> str:
        self.read.add(key)
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


@pytest.fixture(scope="module")
def dsqgen():
    from benchbox.core.tpcds.c_tools import DSQGenBinary, TPCDSError

    try:
        return DSQGenBinary()
    except (TPCDSError, FileNotFoundError, RuntimeError) as exc:
        pytest.skip(f"dsqgen binary or templates unavailable: {exc}")


def _flatten(values) -> Iterator[object]:
    for value in values:
        if isinstance(value, (list, tuple, set, frozenset)):
            yield from _flatten(value)
        else:
            yield value


def _values_in_sql(dsqgen, query_id: int, logged: Mapping[str, str]) -> set[str]:
    """The logged names (``NAME.NN``) whose own value reaches the SQL that BenchBox runs.

    BenchBox runs only a template's first statement (Q14 and Q23 have two), so only that statement counts.
    A name used inside another define reaches the SQL through that define's value; when dsqgen logs the
    outer define itself (Q1's STATE is drawn from COUNTY), the adapter binds the outer value and the inner
    one is not needed.
    """
    template = (dsqgen.templates_dir / f"query{query_id}.tpl").read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"--[^\n]*", "", template)
    defines = {match.group(1): match.group(2) for match in _DEFINE.finditer(text)}
    first_statement = _DEFINE.sub("", text).split(";")[0]
    logged_names = {key.rpartition(".")[0] for key in logged}

    used: dict[str, set[int]] = collections.defaultdict(set)
    pending = [first_statement]
    expanded: set[str] = set()
    while pending:
        for match in _TOKEN.finditer(pending.pop()):
            name = match.group(1)
            used[name].add(int(match.group(2) or 0))
            # An unlogged define passes its inputs through to the SQL.
            if name in defines and name not in logged_names and name not in expanded:
                expanded.add(name)
                pending.append(defines[name])

    reaching = set()
    for key in logged:
        name, _, index = key.rpartition(".")
        if name.startswith("_") or name not in used:
            continue
        # ``[NAME]`` in the template is index 0 and logs as ``NAME.01``.
        if int(index) in {max(i, 1) for i in used[name]}:
            reaching.add(key)
    return reaching


@pytest.mark.parametrize("seed,stream_id", RUNS)
@pytest.mark.parametrize("query_id", adapter_query_ids())
def test_adapter_reads_every_value_that_reaches_the_sql(dsqgen, query_id, seed, stream_id):
    logged = dict(dsqgen.generate_parameter_log(query_id, seed=seed, scale_factor=1, stream_id=stream_id).substitutions)
    recording = _RecordingValues(logged)
    parameters = ADAPTERS[query_id](recording)
    reaching = _values_in_sql(dsqgen, query_id, logged)
    unread = reaching - recording.read
    assert not unread, f"Q{query_id} seed={seed} stream={stream_id}: the adapter never reads {sorted(unread)}"
    # Reading a value is not enough: it must reach the output. A derived value (Q39's MONTH+1) sits
    # beside its base value, so the base value itself is still expected to appear.
    output = {str(value) for value in _flatten(parameters.values())}
    dropped = {key for key in reaching if logged[key] not in output}
    assert not dropped, f"Q{query_id} seed={seed} stream={stream_id}: the adapter drops {sorted(dropped)}"


@pytest.mark.parametrize("family", ["expression", "pandas"])
@pytest.mark.parametrize("seed,stream_id", RUNS)
@pytest.mark.parametrize("query_id", adapter_query_ids())
def test_binding_supplies_every_key_the_implementation_reads(dsqgen, query_id, seed, stream_id, family):
    from benchbox.core.tpcds.dataframe_queries.parameter_adapters import bind_parameters

    binding = bind_parameters(query_id, scale_factor=1, seed=seed, stream_id=stream_id, dsqgen=dsqgen)
    # The implementation sees only the binding, not the defaults file, so a key it reads that the
    # binding lacks shows up here instead of being filled in by a default.
    read, complete = _read_keys(query_id, family, {query_id: dict(binding.parameters)})
    assert complete, f"Q{query_id} {family}: the implementation did not run to completion against the stand-in"
    unsupplied = read - set(binding.parameters)
    assert not unsupplied, (
        f"Q{query_id} {family} seed={seed} stream={stream_id}: reads {sorted(unsupplied)}, "
        f"which the binding does not supply"
    )


def test_runs_draw_different_values(dsqgen):
    """The seeds and streams in RUNS must not collapse to one draw, or the tests above prove less."""
    for query_id in adapter_query_ids():
        draws = {
            tuple(
                sorted(
                    dsqgen.generate_parameter_log(query_id, seed=s, scale_factor=1, stream_id=n).substitutions.items()
                )
            )
            for s, n in RUNS
        }
        assert len(draws) >= 2, f"Q{query_id}: every run in RUNS drew the same values"
