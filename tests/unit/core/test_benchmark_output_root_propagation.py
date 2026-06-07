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
