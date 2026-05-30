"""UAT regression: a Dask cluster/worker death must record a clean FAIL.

Motivated by uat-dask-stability-under-sweep. In the 2026-05-29 dataframe sweep,
dask-df ran tpcds and the run was observed to stop with a scheduler error
("Task ... marked as failed because 4 workers died while trying to run it")
without cleanly recording a FAIL and advancing. The resource-envelope handling
in the Dask adapter must classify such a death and surface it as a failed query
result (so the orchestrator records FAIL and continues), never a hang or an
uncaught crash that truncates the sweep.

These tests pin that contract at the adapter boundary: a worker-death exception
during ``compute`` is classified as a :class:`DaskResourceEnvelopeError`, and a
query whose compute dies returns a failure result dict rather than propagating
an uncaught exception.
"""

from __future__ import annotations

import importlib
from types import SimpleNamespace

import pytest

mod = importlib.import_module("benchbox.platforms.dataframe.dask_df")

pytestmark = pytest.mark.fast


def _make_local_envelope_adapter():
    """Build a Dask adapter in the default constrained local envelope.

    Mirrors the construction used in the unit coverage suite but avoids starting
    a real cluster; only the resource-envelope classification paths are exercised.
    """
    adapter = object.__new__(mod.DaskDataFrameAdapter)
    adapter._log_verbose = lambda *_a, **_k: None
    adapter.n_workers = 1
    adapter.threads_per_worker = 2
    adapter.use_distributed = True
    adapter.scheduler_address = None
    adapter._client = None
    adapter._cluster = None
    adapter.verbose = False
    adapter.working_dir = "."
    adapter._memory_limit = "2GB"
    adapter._spill_to_disk = True
    adapter._configured_spill_directory = None
    adapter._spill_directory = None
    adapter._owns_spill_directory = False
    adapter._n_workers_configured = False
    adapter._threads_per_worker_configured = False
    adapter._memory_limit_configured = False
    return adapter


@pytest.mark.parametrize(
    "error_text",
    [
        # KilledWorker exception type name (the real exception .compute() raises).
        "KilledWorker: Attempt to run task has failed 4 times",
        # Scheduler-side message form from the verified UAT evidence.
        "Task ('_groupby_apply_funcs-abc', 0) marked as failed because 4 workers died while trying to run it",
        # Single-worker phrasing and OS OOM kill.
        "distributed.nanny - WARNING - worker died unexpectedly",
        "Worker process exited with exit code 137",
    ],
)
def test_worker_death_is_classified_as_resource_envelope_failure(error_text):
    """Each known cluster-death signature must produce a resource-envelope diagnostic."""
    adapter = _make_local_envelope_adapter()
    diagnostic = adapter._resource_envelope_diagnostic("compute", RuntimeError(error_text))
    assert diagnostic is not None, f"worker-death signature not classified: {error_text!r}"
    assert "Dask resource-envelope failure during compute" in diagnostic


def test_unrelated_error_is_not_classified_as_resource_envelope():
    """A normal query error must NOT be misattributed to the resource envelope."""
    adapter = _make_local_envelope_adapter()
    assert adapter._resource_envelope_diagnostic("compute", RuntimeError("Column not found: foo")) is None


def test_cluster_death_during_compute_raises_resource_envelope_error():
    """A worker death during a wrapped Dask operation surfaces as DaskResourceEnvelopeError."""
    adapter = _make_local_envelope_adapter()

    def _dies():
        raise RuntimeError("marked as failed because 4 workers died while trying to run it")

    with pytest.raises(mod.DaskResourceEnvelopeError) as excinfo:
        adapter._run_with_resource_diagnostics("compute", _dies)
    assert "resource-envelope failure" in str(excinfo.value)


def test_cluster_death_records_fail_result_and_does_not_hang():
    """A query whose compute dies must yield a FAIL result dict, not an uncaught crash.

    This is the FAIL-and-advance contract: the orchestrator records the failed
    cell and continues the sweep. We drive the real adapter ``execute_query`` with
    a compute that simulates a cluster death and assert a failure result is
    returned (success is False) carrying the resource-envelope diagnostic.
    """
    adapter = _make_local_envelope_adapter()

    # Stub the compute hook used by the base execute_query to simulate a worker death.
    def _worker_death():
        raise RuntimeError("marked as failed because 4 workers died while trying to run it")

    def _dying_compute(_df):
        return adapter._run_with_resource_diagnostics("compute", _worker_death)

    adapter.compute = _dying_compute

    class _LazyFrame:
        def compute(self):  # pragma: no cover - routed through adapter.compute
            raise AssertionError("adapter.compute should be used")

    def _impl(_ctx):
        return _LazyFrame()

    query = SimpleNamespace(
        query_id="query99",
        query_name="cluster death simulation",
        get_impl_for_family=lambda _family: _impl,
    )

    result = adapter.execute_query(ctx=SimpleNamespace(), query=query, query_id="query99")

    # FAIL-and-advance: a failure result dict is returned (no uncaught crash / hang),
    # carrying the resource-envelope diagnostic so the orchestrator records FAIL.
    assert str(result.get("status")).upper() == "FAILED"
    assert result.get("success") in (False, None)
    error = result.get("error") or ""
    assert "4 workers died" in error or "resource-envelope" in error
