"""Tests for CsvDialect and resolve_csv_dialect() precedence.

Covers the W2 decision gate: manifest > benchmark attributes > format defaults,
with logger.warning emitted on fallback and NOT emitted when manifest wins.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

from benchbox.core.flightdata.benchmark import FlightDataBenchmark
from benchbox.platforms.base.data_loading import CsvDialect, DataSource, resolve_csv_dialect
from tests.unit.platforms.csv_dialect_test_helpers import (
    benchmark_stub as _benchmark_stub,
    resolver_data_source as _resolver_data_source,
    unsafe_plain_mock_benchmark as _unsafe_plain_mock_benchmark,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_data_source(table_metadata: dict | None = None) -> DataSource:
    return DataSource(
        source_type="manifest_v2",
        tables={},
        table_metadata=table_metadata or {},
    )


@dataclass
class _Benchmark:
    """Benchmark stub with optional CSV dialect attributes."""

    csv_delimiter: str | None = None
    csv_has_header: bool | None = None
    csv_normalize_booleans: bool | None = None
    csv_null_marker: str | None = None


class _EmptyBenchmark:
    """Benchmark stub with no CSV dialect attributes at all."""


# ---------------------------------------------------------------------------
# (a) Manifest metadata wins
# ---------------------------------------------------------------------------


def test_manifest_metadata_wins_over_benchmark_attribute(caplog: pytest.LogCaptureFixture) -> None:
    """Manifest metadata takes precedence over benchmark attributes."""
    ds = _make_data_source({"customer": {"csv_has_header": True, "csv_delimiter": "\t"}})
    benchmark = _Benchmark(csv_delimiter=",", csv_has_header=False)
    file_path = Path("customer.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "customer", file_path, benchmark)

    assert dialect.delimiter == "\t"
    assert dialect.has_header is True
    # No warning when manifest wins
    assert not caplog.records


def test_manifest_metadata_wins_over_format_default(caplog: pytest.LogCaptureFixture) -> None:
    """Manifest metadata takes precedence over format-derived defaults."""
    ds = _make_data_source({"lineitem": {"csv_has_header": True, "csv_null_marker": None}})
    file_path = Path("lineitem.tbl")  # .tbl would normally give null_marker=''

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "lineitem", file_path, _EmptyBenchmark())

    assert dialect.has_header is True
    assert dialect.null_marker is None  # manifest wins over .tbl default
    assert not caplog.records


def test_manifest_metadata_normalize_booleans(caplog: pytest.LogCaptureFixture) -> None:
    """normalize_booleans from manifest is applied correctly."""
    ds = _make_data_source({"dbo_dimaccount": {"csv_normalize_booleans": True, "csv_delimiter": ","}})
    file_path = Path("dbo_dimaccount.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "dbo_dimaccount", file_path, _EmptyBenchmark())

    assert dialect.normalize_booleans is True
    assert not caplog.records


# ---------------------------------------------------------------------------
# (b) Benchmark attributes win over format defaults
# ---------------------------------------------------------------------------


def test_benchmark_attribute_wins_over_format_default(caplog: pytest.LogCaptureFixture) -> None:
    """Benchmark csv_* attributes win over format-derived defaults when no manifest metadata."""
    ds = _make_data_source()  # no metadata
    benchmark = _Benchmark(csv_delimiter="|", csv_has_header=True, csv_normalize_booleans=False)
    file_path = Path("hits.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "hits", file_path, benchmark)

    assert dialect.delimiter == "|"
    assert dialect.has_header is True
    assert dialect.normalize_booleans is False
    # Warning emitted on fallback
    assert any("hits" in r.message for r in caplog.records)


def test_benchmark_attribute_partial_override(caplog: pytest.LogCaptureFixture) -> None:
    """When only some benchmark attributes are present, others get format defaults."""
    ds = _make_data_source()
    benchmark = _Benchmark(csv_has_header=True)  # only has_header set
    file_path = Path("rides.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "rides", file_path, benchmark)

    assert dialect.has_header is True
    assert dialect.delimiter == ","  # format default for .csv
    assert caplog.records  # warning emitted


def test_benchmark_attribute_csv_null_marker_empty_string(caplog: pytest.LogCaptureFixture) -> None:
    """csv_null_marker='' on a benchmark class must produce CsvDialect(null_marker=''), not None.

    Regression guard for _get_optional_str_attr: empty string is a valid marker
    (meaning "empty CSV fields represent NULL") and must not be collapsed to None.
    JoinOrder is the canonical case — nullable integer columns produce lines
    like "1,Comedy Adventure,,4,1957,,,,,,," and need NULL DEFINED BY '' on
    strict-mode databases (SingleStore, PostgreSQL in strict mode).
    """
    ds = _make_data_source()  # no manifest — forces path (b)
    benchmark = _Benchmark(csv_delimiter=",", csv_null_marker="")
    file_path = Path("title.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "title", file_path, benchmark)

    assert dialect.null_marker == ""  # must be '' not None
    assert dialect.delimiter == ","
    assert caplog.records  # path (b) always warns


def test_flightdata_declares_empty_csv_fields_as_null(caplog: pytest.LogCaptureFixture, tmp_path: Path) -> None:
    """FlightData CSV files use empty fields for nullable delay metrics."""
    ds = _make_data_source()
    benchmark = FlightDataBenchmark(scale_factor=0.01, output_dir=tmp_path)

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "flights", Path("flights.csv"), benchmark)

    assert dialect.delimiter == ","
    assert dialect.has_header is True
    assert dialect.null_marker == ""
    assert caplog.records


# ---------------------------------------------------------------------------
# (c) Format-derived defaults
# ---------------------------------------------------------------------------


def test_format_default_tbl(caplog: pytest.LogCaptureFixture) -> None:
    """Format-derived defaults for .tbl: pipe delimiter, no header, null_marker=''."""
    ds = _make_data_source()
    file_path = Path("lineitem.tbl")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "lineitem", file_path, _EmptyBenchmark())

    assert dialect.delimiter == "|"
    assert dialect.has_header is False
    assert dialect.null_marker == ""
    assert dialect.normalize_booleans is False
    assert caplog.records  # warning emitted for unannotated


def test_format_default_dat(caplog: pytest.LogCaptureFixture) -> None:
    """Format-derived defaults for .dat (TPC-DS): same as .tbl."""
    ds = _make_data_source()
    file_path = Path("store_sales.dat")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "store_sales", file_path, _EmptyBenchmark())

    assert dialect.delimiter == "|"
    assert dialect.null_marker == ""
    assert caplog.records


def test_format_default_csv(caplog: pytest.LogCaptureFixture) -> None:
    """Format-derived defaults for .csv: comma delimiter, no header, null_marker=None."""
    ds = _make_data_source()
    file_path = Path("hits.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "hits", file_path, _EmptyBenchmark())

    assert dialect.delimiter == ","
    assert dialect.has_header is False
    assert dialect.null_marker is None
    assert dialect.normalize_booleans is False
    assert caplog.records


def test_format_default_compressed_tbl(caplog: pytest.LogCaptureFixture) -> None:
    """Format defaults work through compression suffix (.tbl.zst)."""
    ds = _make_data_source()
    file_path = Path("lineitem.tbl.zst")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "lineitem", file_path, _EmptyBenchmark())

    assert dialect.delimiter == "|"
    assert dialect.null_marker == ""
    assert caplog.records


# ---------------------------------------------------------------------------
# Warning emission contract
# ---------------------------------------------------------------------------


def test_no_warning_when_manifest_metadata_present(caplog: pytest.LogCaptureFixture) -> None:
    """No warning is emitted when manifest metadata is present (clean path)."""
    ds = _make_data_source({"customer": {"csv_has_header": True}})
    file_path = Path("customer.csv")

    with caplog.at_level(logging.WARNING):
        resolve_csv_dialect(ds, "customer", file_path, _EmptyBenchmark())

    assert not caplog.records


def test_warning_emitted_on_benchmark_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """Warning is emitted when falling back to benchmark attributes."""
    ds = _make_data_source()
    benchmark = _Benchmark(csv_has_header=True)
    file_path = Path("hits.csv")

    with caplog.at_level(logging.WARNING):
        resolve_csv_dialect(ds, "hits", file_path, benchmark)

    assert any("hits" in r.message for r in caplog.records)


def test_warning_emitted_on_format_fallback(caplog: pytest.LogCaptureFixture) -> None:
    """Warning is emitted when falling back to format-derived defaults."""
    ds = _make_data_source()
    file_path = Path("lineitem.tbl")

    with caplog.at_level(logging.WARNING):
        resolve_csv_dialect(ds, "lineitem", file_path, _EmptyBenchmark())

    assert any("lineitem" in r.message for r in caplog.records)


def test_metadata_lookup_is_case_insensitive(caplog: pytest.LogCaptureFixture) -> None:
    """Metadata stored under lowercase key is found when table name is mixed-case.

    Adapters pass table names from benchmark.tables which may be original-case
    (e.g., "Customer") while the resolver stores keys as lowercase ("customer").
    """
    ds = _make_data_source({"customer": {"csv_has_header": True, "csv_delimiter": ","}})
    file_path = Path("Customer.csv")

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "Customer", file_path, _EmptyBenchmark())

    assert dialect.has_header is True
    assert dialect.delimiter == ","
    assert not caplog.records  # manifest found → no warning


def test_shared_helper_manifest_metadata_beats_suffix(caplog: pytest.LogCaptureFixture) -> None:
    """Adapter tests can use the shared helper to assert metadata beats suffixes."""
    file_path = Path("lineitem.csv")
    ds = _resolver_data_source("lineitem", file_path, {"csv_delimiter": "|", "csv_null_marker": ""})

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "lineitem", file_path, _benchmark_stub({"lineitem": file_path}))

    assert dialect.delimiter == "|"
    assert dialect.null_marker == ""
    assert not caplog.records


def test_shared_helper_preserves_explicit_none_null_marker(caplog: pytest.LogCaptureFixture) -> None:
    """Adapter tests can lock in null_marker=None as explicit no-null conversion."""
    file_path = Path("hits.tbl")
    ds = _resolver_data_source("hits", file_path, {"csv_delimiter": "|", "csv_null_marker": None})

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "hits", file_path, _benchmark_stub({"hits": file_path}))

    assert dialect.delimiter == "|"
    assert dialect.null_marker is None
    assert not caplog.records


def test_plain_mock_benchmark_does_not_pollute_dialect(caplog: pytest.LogCaptureFixture) -> None:
    """Bare Mock child attrs must not trigger the benchmark-attribute branch."""
    file_path = Path("lineitem.tbl")
    ds = _make_data_source()

    with caplog.at_level(logging.WARNING):
        dialect = resolve_csv_dialect(ds, "lineitem", file_path, _unsafe_plain_mock_benchmark({"lineitem": file_path}))

    assert dialect.delimiter == "|"
    assert dialect.has_header is False
    assert dialect.null_marker == ""
    assert any("file extension heuristic" in r.message for r in caplog.records)


# Migrated adapter files that the regression guard sweeps. Add new entries here
# as adapters are converted to the CsvDialect pipeline (Snowflake, Fabric Warehouse,
# DataFusion, Azure Synapse, dataframe adapters are tracked in a separate TODO).
_MIGRATED_ADAPTER_PATHS = (
    "benchbox/platforms/duckdb.py",
    "benchbox/platforms/clickhouse/workload.py",
    "benchbox/platforms/starrocks/workload.py",
    "benchbox/platforms/databend/adapter.py",
    "benchbox/platforms/firebolt.py",
    "benchbox/platforms/redshift.py",
    "benchbox/platforms/bigquery.py",
    "benchbox/platforms/databricks/adapter.py",
    "benchbox/platforms/base/spark_execution_mixin.py",
    # Dataframe adapters migrated in w5 (migrate-remaining-sql-and-dataframe-adapters-to-csv-resolver)
    "benchbox/platforms/dataframe/pandas_df.py",
    "benchbox/platforms/dataframe/modin_df.py",
    "benchbox/platforms/dataframe/cudf_df.py",
    "benchbox/platforms/dataframe/dask_df.py",
    "benchbox/platforms/dataframe/pyspark_df.py",
    "benchbox/platforms/dataframe/lakesail_df.py",
)

_LEGACY_CSV_HEURISTIC_RE = re.compile(
    r"is_tpc_format"
    r"|get_delimiter_for_file"
    r"|getattr\([^)\n]*csv_(?:delimiter|null_marker|has_header|normalize_booleans|quote)"
)


def test_migrated_adapter_load_paths_do_not_use_legacy_csv_heuristics() -> None:
    """Regression guard: migrated adapters must route load dialects through CsvDialect."""
    repo_root = Path(__file__).resolve().parents[3]
    offenders: list[str] = []
    for rel_path in _MIGRATED_ADAPTER_PATHS:
        target = repo_root / rel_path
        for lineno, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
            if _LEGACY_CSV_HEURISTIC_RE.search(line):
                offenders.append(f"{rel_path}:{lineno}: {line.strip()}")

    assert not offenders, "Migrated adapters reintroduced legacy CSV heuristics:\n" + "\n".join(offenders)
