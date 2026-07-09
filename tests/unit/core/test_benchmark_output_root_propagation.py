"""Regression tests for benchmark output-root propagation.

These tests guard the lifecycle-ordering fix described in the
``benchmark-runs-output-root-propagation`` task: generator-backed benchmarks
must honor an explicit ``BENCHBOX_OUTPUT_DIR`` (or post-construction output-root
assignment) all the way down to their nested data generators, instead of
leaving them pointed at a worktree-local ``cwd/benchmark_runs`` default.

The assertions deliberately inspect the *nested generator* output paths (not
just ``benchmark.output_dir``) so a benchmark that silently keeps a stale
generator path fails here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchbox.core.amplab.benchmark import AMPLabBenchmark
from benchbox.core.benchmark_registry import (
    get_all_benchmarks,
    get_benchmark_default_scale,
    get_public_benchmark_class,
)
from benchbox.core.clickbench.benchmark import ClickBenchBenchmark
from benchbox.core.coffeeshop.benchmark import CoffeeShopBenchmark
from benchbox.core.flightdata.benchmark import FlightDataBenchmark
from benchbox.core.h2odb.benchmark import H2OBenchmark
from benchbox.core.nyctaxi.benchmark import NYCTaxiBenchmark
from benchbox.core.ssb.benchmark import SSBBenchmark
from benchbox.core.tpch.benchmark import TPCHBenchmark
from benchbox.core.tsbs_devops.benchmark import TSBSDevOpsBenchmark
from benchbox.core.vector_search.benchmark import VectorSearchBenchmark

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _nested_generators(benchmark) -> list:
    """Return the concrete nested generator/downloader objects on a benchmark."""
    generators = []
    for attr in getattr(benchmark, "OUTPUT_DIR_GENERATOR_ATTRS", ("data_generator",)):
        gen = benchmark.__dict__.get(attr)
        if gen is not None and hasattr(gen, "output_dir"):
            generators.append(gen)
    return generators


# Representative generator-backed benchmark families. ``data_generator`` covers
# the common case; nyctaxi/flightdata expose download-based generators instead.
CONSTRUCTOR_CASES = [
    (H2OBenchmark, {}),
    (SSBBenchmark, {}),
    (VectorSearchBenchmark, {}),
    (TPCHBenchmark, {}),
    (ClickBenchBenchmark, {}),
    (AMPLabBenchmark, {}),
    (CoffeeShopBenchmark, {}),
    (TSBSDevOpsBenchmark, {}),
    (NYCTaxiBenchmark, {}),
    (FlightDataBenchmark, {}),
]


@pytest.mark.parametrize("benchmark_cls,kwargs", CONSTRUCTOR_CASES)
def test_env_output_root_honored_at_construction(benchmark_cls, kwargs, tmp_path, monkeypatch):
    """BENCHBOX_OUTPUT_DIR redirects datagen output before generators are built."""
    root = tmp_path / "shared_runs"
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(root))

    benchmark = benchmark_cls(scale_factor=0.01, **kwargs)

    output_dir = Path(str(benchmark.output_dir))
    assert str(output_dir).startswith(str(root)), output_dir
    # The stale-default failure mode lands under cwd/benchmark_runs.
    assert Path.cwd() not in output_dir.parents, output_dir

    generators = _nested_generators(benchmark)
    assert generators, f"{benchmark_cls.__name__} exposed no nested generator to verify"
    for gen in generators:
        gen_dir = Path(str(gen.output_dir))
        assert str(gen_dir).startswith(str(root)), (benchmark_cls.__name__, gen_dir)
        assert Path.cwd() not in gen_dir.parents, (benchmark_cls.__name__, gen_dir)


@pytest.mark.parametrize("benchmark_cls,kwargs", CONSTRUCTOR_CASES)
def test_explicit_output_root_propagates_post_construction(benchmark_cls, kwargs, tmp_path, monkeypatch):
    """An output-root assigned after construction reaches nested generators.

    This mirrors the runner/orchestrator path that resolves an explicit CLI
    ``--output`` root and assigns ``benchmark.output_dir`` after the benchmark
    (and its generators) have already been constructed.
    """
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
    benchmark = benchmark_cls(scale_factor=0.01, **kwargs)

    explicit = tmp_path / "explicit_root" / "data"
    benchmark.output_dir = str(explicit)

    assert str(benchmark.output_dir) == str(explicit)
    for gen in _nested_generators(benchmark):
        assert str(gen.output_dir) == str(explicit), (benchmark_cls.__name__, gen.output_dir)


def test_default_falls_back_to_cwd_when_unset(monkeypatch):
    """With neither CLI --output nor BENCHBOX_OUTPUT_DIR set, the cwd default holds."""
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

    benchmark = H2OBenchmark(scale_factor=0.01)

    expected = Path.cwd() / "benchmark_runs" / "datagen" / "h2odb_sf001"
    assert Path(str(benchmark.output_dir)) == expected
    assert Path(str(benchmark.data_generator.output_dir)) == expected


def test_nyctaxi_optional_downloaders_all_track_output_dir(tmp_path, monkeypatch):
    """Multi-type NYC Taxi keeps every optional downloader in sync."""
    from benchbox.core.nyctaxi.schema import TaxiType

    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
    benchmark = NYCTaxiBenchmark(
        scale_factor=0.01,
        taxi_types=[TaxiType.YELLOW, TaxiType.GREEN, TaxiType.HVFHV],
    )

    target = tmp_path / "nyc" / "data"
    benchmark.output_dir = str(target)

    assert str(benchmark.downloader.output_dir) == str(target)
    assert str(benchmark.green_downloader.output_dir) == str(target)
    assert str(benchmark.hvfhv_downloader.output_dir) == str(target)


def test_tpch_variant_skew_inherits_propagation(tmp_path, monkeypatch):
    """A TPC-H-family variant (skew) honors the env root for its own generator."""
    from benchbox.core.tpch_skew.benchmark import TPCHSkewBenchmark

    root = tmp_path / "runs"
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(root))

    benchmark = TPCHSkewBenchmark(scale_factor=0.01)

    assert str(benchmark.output_dir).startswith(str(root))
    assert str(benchmark.data_generator.output_dir).startswith(str(root))
    assert Path.cwd() not in Path(str(benchmark.data_generator.output_dir)).parents


# ---------------------------------------------------------------------------
# Registry-wide guards (benchmark-output-root-regression-guard)
#
# The per-family cases above cover representative benchmarks; the tests below
# parametrize over the full registry so every current AND future benchmark is
# held to the same contract automatically.
# ---------------------------------------------------------------------------

_ALL_BENCHMARK_IDS = sorted(get_all_benchmarks())

#: Benchmarks whose output_dir reassignment does not reach the nested
#: generator. Empty since benchmark-output-root-explicit-override-propagation
#: gave tpcds/tpcdi the mixin; add an id here (with a strict xfail reason and
#: tracking TODO) only if a new benchmark ships with a known gap.
_REASSIGNMENT_GAP_BIDS: frozenset[str] = frozenset()


def _registry_construct(benchmark_id: str):
    """Construct a benchmark via its public class at its default scale."""
    benchmark_class = get_public_benchmark_class(benchmark_id)
    assert benchmark_class is not None, f"{benchmark_id}: no public benchmark class"
    return benchmark_class(scale_factor=get_benchmark_default_scale(benchmark_id))


def _core_object(benchmark):
    """Return the core implementation when a public wrapper delegates."""
    return getattr(benchmark, "_impl", benchmark)


@pytest.mark.parametrize("benchmark_id", _ALL_BENCHMARK_IDS)
def test_registry_env_output_root_honored_at_construction(benchmark_id, tmp_path, monkeypatch):
    """Every registered benchmark honors BENCHBOX_OUTPUT_DIR at construction.

    Asserts both ``benchmark.output_dir`` and every nested generator/downloader
    declared via ``OUTPUT_DIR_GENERATOR_ATTRS`` resolve under the env root, with
    ``Path.cwd()`` not an ancestor (the stale-default failure mode).
    """
    root = tmp_path / "shared_runs"
    monkeypatch.setenv("BENCHBOX_OUTPUT_DIR", str(root))

    benchmark = _registry_construct(benchmark_id)

    output_dir = Path(str(benchmark.output_dir))
    assert output_dir.is_relative_to(root), (benchmark_id, output_dir)
    assert Path.cwd() not in output_dir.parents, (benchmark_id, output_dir)

    core = _core_object(benchmark)
    for gen in _nested_generators(core):
        gen_dir = Path(str(gen.output_dir))
        assert gen_dir.is_relative_to(root), (benchmark_id, gen_dir)
        assert Path.cwd() not in gen_dir.parents, (benchmark_id, gen_dir)


def _reassignment_params():
    for benchmark_id in _ALL_BENCHMARK_IDS:
        marks = []
        if benchmark_id in _REASSIGNMENT_GAP_BIDS:
            marks.append(
                pytest.mark.xfail(
                    reason=(
                        f"{benchmark_id} builds its data_generator in __init__ without "
                        "GeneratorOutputDirMixin, so output_dir reassignment does not "
                        "reach it. Tracked: benchmark-output-root-explicit-override-propagation"
                    ),
                    strict=True,
                )
            )
        yield pytest.param(benchmark_id, marks=marks, id=benchmark_id)


@pytest.mark.parametrize("benchmark_id", _reassignment_params())
def test_registry_explicit_root_reassignment_propagates(benchmark_id, tmp_path, monkeypatch):
    """Reassigning output_dir after construction reaches nested generators.

    Mirrors the runner/orchestrator path that resolves an explicit CLI
    ``--output`` root after the benchmark (and its generators) already exist.
    Benchmarks without a nested generator built in ``__init__`` are skipped —
    there is nothing to keep in sync.
    """
    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)

    benchmark = _registry_construct(benchmark_id)
    core = _core_object(benchmark)

    generators = _nested_generators(core)
    if not generators:
        pytest.skip(f"{benchmark_id}: no nested generator constructed in __init__")

    explicit = tmp_path / "explicit_root" / "data"
    benchmark.output_dir = str(explicit)

    assert str(core.output_dir) == str(explicit), (benchmark_id, core.output_dir)
    for gen in generators:
        assert str(gen.output_dir) == str(explicit), (benchmark_id, gen.output_dir)


def test_tpcdi_explicit_override_rederives_etl_dirs(tmp_path, monkeypatch):
    """A tpcdi output_dir reassignment re-derives config and ETL directories.

    TPC-DI derives source/staging/warehouse and its data_generator path from
    the config output root, so an explicit override must update all of them —
    leaving none pointed at the construction-time default.
    """
    from benchbox.core.tpcdi.benchmark import TPCDIBenchmark

    monkeypatch.delenv("BENCHBOX_OUTPUT_DIR", raising=False)
    benchmark = TPCDIBenchmark(scale_factor=0.01)

    explicit = tmp_path / "custom_root"
    benchmark.output_dir = explicit

    assert Path(str(benchmark.output_dir)) == explicit
    assert Path(str(benchmark.config.output_dir)) == explicit
    assert benchmark.source_dir == explicit / "source"
    assert benchmark.staging_dir == explicit / "staging"
    assert benchmark.warehouse_dir == explicit / "warehouse"
    assert Path(str(benchmark.data_generator.output_dir)) == explicit


# ---------------------------------------------------------------------------
# Cloud output roots (w4): cloud-wrapped paths must survive propagation
# ---------------------------------------------------------------------------


def test_databricks_output_root_propagates_without_rewrap(tmp_path):
    """A DatabricksPath output root reaches the nested generator unchanged.

    ``create_path_handler`` passes existing DatabricksPath instances through
    as-is, so the exact object (and its dbfs target) must survive the
    benchmark -> generator propagation chain.
    """
    from benchbox.core.tpch.benchmark import TPCHBenchmark
    from benchbox.utils.cloud_storage import DatabricksPath

    staging = DatabricksPath(str(tmp_path / "staging"), "dbfs:/Volumes/cat/schema/vol")
    benchmark = TPCHBenchmark(scale_factor=0.01)

    benchmark.output_dir = staging

    assert benchmark.output_dir is staging, benchmark.output_dir
    assert benchmark.data_generator.output_dir is staging, benchmark.data_generator.output_dir
    assert benchmark.data_generator.output_dir.dbfs_target == "dbfs:/Volumes/cat/schema/vol"


def test_cloud_staging_output_root_preserves_local_staging_root(tmp_path):
    """A CloudStagingPath output root keeps generators on its local staging dir.

    ``create_path_handler`` resolves a CloudStagingPath to its local staging
    path (the cloud upload is owned by the platform adapter), so the nested
    generator must land exactly on that staging directory — not on a stale
    cwd-local default and not re-wrapped with a different root.
    """
    from benchbox.core.ssb.benchmark import SSBBenchmark
    from benchbox.utils.cloud_storage import CloudStagingPath

    local_stage = tmp_path / "local_stage"
    staging = CloudStagingPath(local_stage, "gs://bucket/benchbox/ssb")
    benchmark = SSBBenchmark(scale_factor=0.01)

    benchmark.output_dir = staging

    assert Path(str(benchmark.output_dir)) == local_stage, benchmark.output_dir
    assert Path(str(benchmark.data_generator.output_dir)) == local_stage, benchmark.data_generator.output_dir


def test_generator_output_dir_mixin_forwards_to_impl():
    """A class combining GeneratorOutputDirMixin with the _impl wrapper pattern
    forwards output_dir to _impl.

    The mixin precedes BaseBenchmark in the MRO, so its setter governs. It must
    still mirror BaseBenchmark's _impl forwarding, otherwise a wrapper's inner
    _impl keeps generating under a stale path while the wrapper reports the new
    root.
    """
    from benchbox.base import GeneratorOutputDirMixin

    class _Impl:
        def __init__(self):
            self.output_dir = None

    class _Wrapper(GeneratorOutputDirMixin):
        def __init__(self):
            self._impl = _Impl()
            self.output_dir = "/tmp/initial"

    wrapper = _Wrapper()
    assert str(wrapper._impl.output_dir) == "/tmp/initial"

    wrapper.output_dir = "/tmp/reassigned"
    assert str(wrapper._impl.output_dir) == "/tmp/reassigned"
