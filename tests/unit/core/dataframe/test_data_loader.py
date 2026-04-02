"""Unit tests for DataFrame Data Loading Strategy.

Tests for:
- DataFrameDataLoader
- SchemaMapper
- FormatConverter
- DataCache

Copyright 2026 Joe Harris / BenchBox Project
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from benchbox.core.dataframe.capabilities import DataFormat
from benchbox.core.dataframe.data_loader import (
    DATAFRAME_CACHE_VERSION,
    CacheManifest,
    ConversionStatus,
    DataCache,
    DataFrameDataLoader,
    DataLoadResult,
    FormatConverter,
    LoadedTable,
    SchemaMapper,
    _compute_source_hash,
    get_tpch_column_names,
)
from benchbox.core.dataframe.tuning.write_config import (
    DataFrameWriteConfiguration,
    SortColumn,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSchemaMapper:
    """Tests for SchemaMapper class."""

    def test_get_column_names(self):
        """Test extracting column names from a Table schema."""
        try:
            from benchbox.core.tpch.schema import CUSTOMER

            names = SchemaMapper.get_column_names(CUSTOMER)

            assert len(names) == 8
            assert names[0] == "c_custkey"
            assert "c_name" in names
            assert "c_mktsegment" in names
        except ImportError:
            pytest.skip("TPC-H schema not available")

    def test_get_polars_schema(self):
        """Test Polars schema conversion."""
        try:
            from benchbox.core.tpch.schema import LINEITEM

            schema = SchemaMapper.get_polars_schema(LINEITEM)

            assert schema["l_orderkey"] == "Int64"
            assert schema["l_quantity"] == "Float64"  # DECIMAL maps to Float64
            assert schema["l_returnflag"] == "Utf8"  # CHAR maps to Utf8
            assert schema["l_shipdate"] == "Date"
        except ImportError:
            pytest.skip("TPC-H schema not available")

    def test_get_pandas_schema(self):
        """Test Pandas schema conversion."""
        try:
            from benchbox.core.tpch.schema import ORDERS

            schema = SchemaMapper.get_pandas_schema(ORDERS)

            assert schema["o_orderkey"] == "int64"
            assert schema["o_totalprice"] == "float64"
            assert schema["o_orderstatus"] == "object"  # CHAR
            assert schema["o_orderdate"] == "datetime64[ns]"
        except ImportError:
            pytest.skip("TPC-H schema not available")

    def test_get_pyarrow_schema(self):
        """Test PyArrow schema conversion."""
        try:
            from benchbox.core.tpch.schema import SUPPLIER

            schema = SchemaMapper.get_pyarrow_schema(SUPPLIER)

            assert schema["s_suppkey"] == "int64"
            assert schema["s_acctbal"] == "float64"
            assert schema["s_name"] == "string"
        except ImportError:
            pytest.skip("TPC-H schema not available")


class TestFormatConverter:
    """Tests for FormatConverter class."""

    def test_convert_csv_to_parquet_basic(self):
        """Test basic CSV to Parquet conversion."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test CSV
            csv_path = tmpdir / "test.csv"
            csv_path.write_text("a,b,c\n1,2,3\n4,5,6\n")

            parquet_path = tmpdir / "test.parquet"

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 2
            assert parquet_path.exists()

    def test_convert_tbl_file(self):
        """Test TBL file conversion with pipe delimiter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test TBL file (has trailing delimiter per TPC spec)
            tbl_path = tmpdir / "test.tbl"
            tbl_path.write_text("1|Alice|100.00|\n2|Bob|200.00|\n")

            parquet_path = tmpdir / "test.parquet"
            column_names = ["id", "name", "amount"]

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=tbl_path,
                target_path=parquet_path,
                column_names=column_names,
                delimiter="|",
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 2

    def test_convert_tbl_file_without_trailing_delimiter(self):
        """Test TBL file conversion without trailing delimiter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            tbl_path = tmpdir / "test.tbl"
            tbl_path.write_text("1|Alice|100.00\n2|Bob|200.00\n")

            parquet_path = tmpdir / "test.parquet"
            column_names = ["id", "name", "amount"]

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=tbl_path,
                target_path=parquet_path,
                column_names=column_names,
                delimiter="|",
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 2

    def test_convert_compressed_tbl_file(self):
        """Test compressed TBL file conversion with pipe delimiter."""
        zstd = pytest.importorskip("zstandard")
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            tbl_path = tmpdir / "test.tbl"
            tbl_path.write_text("1|Alice|100.00|\n2|Bob|200.00|\n")

            compressed_path = tmpdir / "test.tbl.zst"
            compressor = zstd.ZstdCompressor(level=3)
            with open(tbl_path, "rb") as f_in, open(compressed_path, "wb") as f_out:
                compressor.copy_stream(f_in, f_out)

            parquet_path = tmpdir / "test.parquet"
            column_names = ["id", "name", "amount"]

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=compressed_path,
                target_path=parquet_path,
                column_names=column_names,
                delimiter="|",
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 2

    def test_convert_creates_parent_dirs(self):
        """Test that conversion creates parent directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("x,y\n1,2\n")

            # Target in non-existent nested directory
            parquet_path = tmpdir / "nested" / "deep" / "test.parquet"

            status, _ = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
            )

            assert status == ConversionStatus.SUCCESS
            assert parquet_path.exists()

    def test_convert_nonexistent_file(self):
        """Test conversion of non-existent file fails gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=tmpdir / "nonexistent.csv",
                target_path=tmpdir / "out.parquet",
            )

            assert status == ConversionStatus.FAILED
            assert row_count == 0

    def test_convert_csv_to_parquet_date_column_types(self):
        """Test that date columns are typed as date32 when column_types is provided.

        Regression test: without explicit column_types, PyArrow infers date
        strings (e.g. '1995-09-01') as string type, causing Polars queries
        to fail with 'cannot compare date/datetime/time to a string value'.
        """
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a TBL file with date columns (like TPC-H lineitem)
            tbl_path = tmpdir / "lineitem.tbl"
            tbl_path.write_text(
                "1|100|50|1|17.0|100.00|0.04|0.02|N|O|1996-03-13|1996-02-12|1996-03-22|DELIVER IN PERSON|TRUCK|comment|\n"
                "1|200|50|2|36.0|200.00|0.09|0.06|N|O|1996-04-12|1996-02-28|1996-04-20|TAKE BACK RETURN|MAIL|comment|\n"
            )

            parquet_path = tmpdir / "lineitem.parquet"
            column_names = [
                "l_orderkey",
                "l_partkey",
                "l_suppkey",
                "l_linenumber",
                "l_quantity",
                "l_extendedprice",
                "l_discount",
                "l_tax",
                "l_returnflag",
                "l_linestatus",
                "l_shipdate",
                "l_commitdate",
                "l_receiptdate",
                "l_shipinstruct",
                "l_shipmode",
                "l_comment",
            ]
            column_types = {
                "l_orderkey": "int64",
                "l_partkey": "int64",
                "l_suppkey": "int64",
                "l_linenumber": "int64",
                "l_quantity": "float64",
                "l_extendedprice": "float64",
                "l_discount": "float64",
                "l_tax": "float64",
                "l_returnflag": "string",
                "l_linestatus": "string",
                "l_shipdate": "date32",
                "l_commitdate": "date32",
                "l_receiptdate": "date32",
                "l_shipinstruct": "string",
                "l_shipmode": "string",
                "l_comment": "string",
            }

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=tbl_path,
                target_path=parquet_path,
                column_names=column_names,
                delimiter="|",
                column_types=column_types,
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 2

            # Verify the Parquet schema has date types, not strings
            table = pq.read_table(parquet_path)
            schema = table.schema

            import pyarrow as pa

            assert schema.field("l_shipdate").type == pa.date32()
            assert schema.field("l_commitdate").type == pa.date32()
            assert schema.field("l_receiptdate").type == pa.date32()

            # Verify date values are actual dates, not strings
            shipdate_col = table.column("l_shipdate")
            assert shipdate_col[0].as_py() == __import__("datetime").date(1996, 3, 13)

    def test_convert_tbl_with_column_types_casts_dates(self):
        """Test that column_types ensures date typing in TBL files.

        TBL files are headerless with pipe delimiters. Without column_types,
        auto_dict_encode may cause date columns to be dictionary-encoded as
        strings instead of proper date32 types. This is the scenario that
        caused the Polars regression.
        """
        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            tbl_path = tmpdir / "orders.tbl"
            tbl_path.write_text(
                "1|370|O|172799.49|1996-01-02|5-LOW|Clerk#000000951|0|comment|\n"
                "2|781|O|38426.09|1996-12-01|1-URGENT|Clerk#000000880|0|comment|\n"
            )

            parquet_path = tmpdir / "orders.parquet"
            column_names = [
                "o_orderkey",
                "o_custkey",
                "o_orderstatus",
                "o_totalprice",
                "o_orderdate",
                "o_orderpriority",
                "o_clerk",
                "o_shippriority",
                "o_comment",
            ]
            column_types = {
                "o_orderkey": "int64",
                "o_custkey": "int64",
                "o_orderstatus": "string",
                "o_totalprice": "float64",
                "o_orderdate": "date32",
                "o_orderpriority": "string",
                "o_clerk": "string",
                "o_shippriority": "int64",
                "o_comment": "string",
            }

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=tbl_path,
                target_path=parquet_path,
                column_names=column_names,
                delimiter="|",
                column_types=column_types,
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 2

            table = pq.read_table(parquet_path)
            assert table.schema.field("o_orderdate").type == pa.date32()
            assert table.column("o_orderdate")[0].as_py() == __import__("datetime").date(1996, 1, 2)


class TestSourceFileDiscovery:
    """Tests for source file discovery with sharded paths."""

    def test_get_source_files_with_list_paths(self, tmp_path):
        loader = DataFrameDataLoader(platform="polars")
        shard1 = tmp_path / "customer.tbl.1"
        shard2 = tmp_path / "customer.tbl.2"
        shard1.write_text("1|Alice|100.00\n")
        shard2.write_text("2|Bob|200.00\n")

        class DummyBenchmark:
            tables = {"customer": [shard1, shard2]}

        result = loader._get_source_files(DummyBenchmark(), data_dir=None)
        assert result["customer"] == [shard1, shard2]


class TestSourceFormatDetection:
    """Tests for source format detection with list paths."""

    def test_detect_source_format_with_list(self, tmp_path):
        loader = DataFrameDataLoader(platform="polars")
        shard1 = tmp_path / "orders.tbl.1"
        shard2 = tmp_path / "orders.tbl.2"
        shard1.write_text("1|A|100.00\n")
        shard2.write_text("2|B|200.00\n")

        source_files = {"orders": [shard1, shard2]}
        assert loader._detect_source_format(source_files) == DataFormat.CSV


class TestCacheManifest:
    """Tests for CacheManifest dataclass."""

    def test_to_dict(self):
        """Test manifest serialization."""
        manifest = CacheManifest(
            benchmark="tpch",
            scale_factor=1.0,
            format="parquet",
            created_at="2025-01-01T00:00:00",
            source_hash="abc123",
            tables={"customer": {"file": "customer.parquet", "row_count": 150000}},
        )

        data = manifest.to_dict()

        assert data["benchmark"] == "tpch"
        assert data["scale_factor"] == 1.0
        assert data["format"] == "parquet"
        assert data["tables"]["customer"]["row_count"] == 150000

    def test_from_dict(self):
        """Test manifest deserialization."""
        data = {
            "benchmark": "tpcds",
            "scale_factor": 10.0,
            "format": "parquet",
            "created_at": "2025-01-01T00:00:00",
            "source_hash": "xyz789",
            "tables": {"store": {"file": "store.parquet"}},
        }

        manifest = CacheManifest.from_dict(data)

        assert manifest.benchmark == "tpcds"
        assert manifest.scale_factor == 10.0
        assert "store" in manifest.tables

    def test_roundtrip(self):
        """Test serialization roundtrip."""
        original = CacheManifest(
            benchmark="tpch",
            scale_factor=0.01,
            format="parquet",
            created_at="2025-06-15T12:00:00",
            source_hash="hash123",
            tables={
                "lineitem": {"file": "lineitem.parquet", "row_count": 60012},
                "orders": {"file": "orders.parquet", "row_count": 15000},
            },
        )

        data = original.to_dict()
        restored = CacheManifest.from_dict(data)

        assert restored.benchmark == original.benchmark
        assert restored.scale_factor == original.scale_factor
        assert len(restored.tables) == len(original.tables)


class TestDataCache:
    """Tests for DataCache class."""

    def test_explicit_string_cache_dir_is_normalized_to_path(self):
        """String cache_dir values should be normalized and usable for path joins."""
        cache = DataCache("tmp/cache")
        assert isinstance(cache.cache_dir, Path)

        path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
        assert path == Path("tmp/cache") / "tpch_sf1" / "parquet" / DATAFRAME_CACHE_VERSION

    def test_default_cache_uses_runtime_cwd(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
        """Default cache path should resolve from current CWD at DataCache construction time."""
        with patch.dict("os.environ", {}, clear=True):
            monkeypatch.chdir(tmp_path)
            cache = DataCache()
            assert cache.cache_dir == tmp_path / "benchmark_runs" / "datagen"

    def test_get_cache_path(self):
        """Test cache path generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)

            assert "tpch_sf1" in str(path)
            assert "parquet" in str(path)
            assert DATAFRAME_CACHE_VERSION in str(path)

    def test_get_manifest_path(self):
        """Test manifest path generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            path = cache.get_manifest_path("tpch", 0.01, DataFormat.PARQUET)

            assert path.name == "_manifest.json"

    def test_old_cache_layout_is_ignored(self):
        """Old cache layout without version segment should not be used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cache = DataCache(tmpdir)

            old_cache_path = tmpdir / "tpch" / "sf_1.0" / "parquet"
            old_cache_path.mkdir(parents=True)
            (old_cache_path / "customer.parquet").touch()
            with open(old_cache_path / "_manifest.json", "w") as f:
                json.dump(
                    {
                        "benchmark": "tpch",
                        "scale_factor": 1.0,
                        "format": "parquet",
                        "created_at": "2025-01-01T00:00:00",
                        "source_hash": "abc123",
                        "tables": {"customer": {"file": "customer.parquet"}},
                    },
                    f,
                )

            assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is False

    def test_has_cached_data_empty(self):
        """Test cache check on empty cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is False

    def test_has_cached_data_valid(self):
        """Test cache check with valid cached data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            # Create cache structure
            cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
            cache_path.mkdir(parents=True)

            # Create dummy parquet files
            (cache_path / "customer.parquet").touch()
            (cache_path / "orders.parquet").touch()

            # Create manifest
            manifest = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "format": "parquet",
                "created_at": "2025-01-01T00:00:00",
                "source_hash": "abc123",
                "tables": {
                    "customer": {"file": "customer.parquet"},
                    "orders": {"file": "orders.parquet"},
                },
            }

            with open(cache_path / "_manifest.json", "w") as f:
                json.dump(manifest, f)

            assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is True

    def test_has_cached_data_missing_file(self):
        """Test cache check with missing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
            cache_path.mkdir(parents=True)

            # Only create one file but manifest references two
            (cache_path / "customer.parquet").touch()

            manifest = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "format": "parquet",
                "created_at": "2025-01-01T00:00:00",
                "source_hash": "abc123",
                "tables": {
                    "customer": {"file": "customer.parquet"},
                    "missing": {"file": "missing.parquet"},
                },
            }

            with open(cache_path / "_manifest.json", "w") as f:
                json.dump(manifest, f)

            assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET) is False

    def test_has_cached_data_hash_mismatch(self):
        """Test cache check with hash mismatch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
            cache_path.mkdir(parents=True)

            (cache_path / "test.parquet").touch()

            manifest = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "format": "parquet",
                "created_at": "2025-01-01T00:00:00",
                "source_hash": "old_hash",
                "tables": {"test": {"file": "test.parquet"}},
            }

            with open(cache_path / "_manifest.json", "w") as f:
                json.dump(manifest, f)

            # Different hash should invalidate cache
            assert cache.has_cached_data("tpch", 1.0, DataFormat.PARQUET, source_hash="new_hash") is False

    def test_get_cached_files(self):
        """Test retrieving cached file paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
            cache_path.mkdir(parents=True)

            manifest = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "format": "parquet",
                "created_at": "2025-01-01T00:00:00",
                "source_hash": "abc123",
                "tables": {
                    "customer": {"file": "customer.parquet"},
                    "orders": {"file": "orders.parquet"},
                },
            }

            with open(cache_path / "_manifest.json", "w") as f:
                json.dump(manifest, f)

            files = cache.get_cached_files("tpch", 1.0, DataFormat.PARQUET)

            assert files is not None
            assert "customer" in files
            assert "orders" in files
            assert files["customer"].name == "customer.parquet"

    def test_save_manifest(self):
        """Test saving a manifest."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            cache.save_manifest(
                benchmark="tpch",
                scale_factor=1.0,
                format=DataFormat.PARQUET,
                source_hash="test_hash",
                tables={"lineitem": {"file": "lineitem.parquet", "row_count": 60000}},
            )

            manifest_path = cache.get_manifest_path("tpch", 1.0, DataFormat.PARQUET)
            assert manifest_path.exists()

            with open(manifest_path) as f:
                data = json.load(f)

            assert data["benchmark"] == "tpch"
            assert data["source_hash"] == "test_hash"
            assert data["tables"]["lineitem"]["row_count"] == 60000

    def test_clear_cache_specific(self):
        """Test clearing specific cache entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = DataCache(Path(tmpdir))

            # Create cache structure
            cache_path = cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
            cache_path.mkdir(parents=True)
            (cache_path / "test.parquet").touch()
            (cache_path / "_manifest.json").touch()

            removed = cache.clear_cache("tpch", 1.0, DataFormat.PARQUET)

            assert removed >= 2
            assert not cache_path.exists()


class TestDataFrameDataLoader:
    """Tests for DataFrameDataLoader class."""

    def test_init_default(self):
        """Test default initialization."""
        loader = DataFrameDataLoader()

        assert loader.platform == "polars"
        assert loader.prefer_parquet is True
        assert loader.force_regenerate is False

    def test_init_with_platform(self):
        """Test initialization with platform."""
        loader = DataFrameDataLoader(platform="pandas-df")

        assert loader.platform == "pandas"

    def test_get_optimal_format_parquet(self):
        """Test optimal format selection prefers Parquet."""
        loader = DataFrameDataLoader(platform="polars")

        format = loader.get_optimal_format(scale_factor=1.0)

        assert format == DataFormat.PARQUET

    def test_get_optimal_format_csv(self):
        """Test optimal format when Parquet disabled."""
        loader = DataFrameDataLoader(platform="polars", prefer_parquet=False)

        format = loader.get_optimal_format(scale_factor=1.0)

        assert format == DataFormat.CSV

    def test_discover_files(self):
        """Test file discovery in data directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test files
            (tmpdir / "customer.tbl").touch()
            (tmpdir / "orders.tbl").touch()
            (tmpdir / "lineitem.parquet").touch()

            loader = DataFrameDataLoader()
            files = loader._discover_files(tmpdir)

            assert "customer" in files
            assert "orders" in files
            assert "lineitem" in files

    def test_detect_source_format_tbl(self):
        """Test source format detection for TBL files."""
        loader = DataFrameDataLoader()

        files = {"customer": Path("customer.tbl")}
        format = loader._detect_source_format(files)

        assert format == DataFormat.CSV

    def test_detect_source_format_parquet(self):
        """Test source format detection for Parquet files."""
        loader = DataFrameDataLoader()

        files = {"customer": Path("customer.parquet")}
        format = loader._detect_source_format(files)

        assert format == DataFormat.PARQUET

    def test_get_source_files_from_benchmark(self):
        """Test getting source files from benchmark.tables."""
        loader = DataFrameDataLoader()

        benchmark = MagicMock()
        benchmark.tables = {
            "customer": "/data/customer.tbl",
            "orders": "/data/orders.tbl",
        }

        files = loader._get_source_files(benchmark, None)

        assert "customer" in files
        assert "orders" in files
        assert files["customer"] == [Path("/data/customer.tbl")]

    def test_get_source_files_rejects_directory_path(self):
        """Test that _get_source_files raises when benchmark.tables contains a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            # Create a directory where a file is expected (contamination scenario)
            (tmpdir / "customer").mkdir()

            loader = DataFrameDataLoader()
            benchmark = MagicMock()
            benchmark.tables = {"customer": str(tmpdir / "customer")}

            with pytest.raises(ValueError, match="customer.*expected file.*found directory"):
                loader._get_source_files(benchmark, None)

    def test_get_source_files_rejects_directory_in_list(self):
        """Test that _get_source_files raises when a sharded path list contains a directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            good_file = tmpdir / "orders.tbl.1"
            good_file.write_text("1|data\n")
            bad_dir = tmpdir / "orders"
            bad_dir.mkdir()

            loader = DataFrameDataLoader()
            benchmark = MagicMock()
            benchmark.tables = {"orders": [str(good_file), str(bad_dir)]}

            with pytest.raises(ValueError, match="orders.*expected file.*found directory"):
                loader._get_source_files(benchmark, None)

    def test_get_source_files_from_data_dir(self):
        """Test getting source files from data directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            (tmpdir / "region.tbl").touch()
            (tmpdir / "nation.tbl").touch()

            loader = DataFrameDataLoader()
            benchmark = MagicMock()
            benchmark.tables = None

            files = loader._get_source_files(benchmark, tmpdir)

            assert "region" in files
            assert "nation" in files
            assert files["region"] == [tmpdir / "region.tbl"]
            assert files["nation"] == [tmpdir / "nation.tbl"]

    def test_prepare_benchmark_data_cached(self):
        """Test prepare_benchmark_data uses cache when available."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            cache_dir = tmpdir / "cache"

            loader = DataFrameDataLoader(cache_dir=cache_dir)

            # Setup mock cache
            cache_path = loader.cache.get_cache_path("tpch", 1.0, DataFormat.PARQUET)
            cache_path.mkdir(parents=True)

            # Create cached files
            (cache_path / "customer.parquet").touch()

            # Create valid manifest
            manifest = {
                "benchmark": "tpch",
                "scale_factor": 1.0,
                "format": "parquet",
                "created_at": "2025-01-01T00:00:00",
                "source_hash": "any_hash",
                "tables": {"customer": {"file": "customer.parquet"}},
            }
            with open(cache_path / "_manifest.json", "w") as f:
                json.dump(manifest, f)

            # Setup benchmark
            benchmark = MagicMock()
            benchmark.name = "tpch"
            benchmark.tables = {"customer": Path(tmpdir / "customer.tbl")}

            # Create source file
            (tmpdir / "customer.tbl").touch()

            # Mock has_cached_data to return True
            with (
                patch.object(loader.cache, "has_cached_data", return_value=True),
                patch.object(
                    loader.cache,
                    "get_cached_files",
                    return_value={"customer": cache_path / "customer.parquet"},
                ),
            ):
                paths = loader.prepare_benchmark_data(benchmark, scale_factor=1.0)

            assert "customer" in paths

    def test_prepare_benchmark_data_preserves_shards(self):
        """Test prepare_benchmark_data preserves all shard paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            shard1 = tmpdir / "customer.tbl.1"
            shard2 = tmpdir / "customer.tbl.2"
            shard1.write_text("1|Alice|100.00\n")
            shard2.write_text("2|Bob|200.00\n")

            loader = DataFrameDataLoader(prefer_parquet=False)
            benchmark = MagicMock()
            benchmark.name = "tpch"
            benchmark.tables = {"customer": [shard1, shard2]}

            paths = loader.prepare_benchmark_data(benchmark, scale_factor=1.0)

            assert paths["customer"] == [shard1, shard2]


class TestLoadedTable:
    """Tests for LoadedTable dataclass."""

    def test_creation(self):
        """Test LoadedTable creation."""
        table = LoadedTable(
            table_name="customer",
            file_path=Path("/data/customer.parquet"),
            format=DataFormat.PARQUET,
            row_count=150000,
            size_bytes=1024000,
        )

        assert table.table_name == "customer"
        assert table.row_count == 150000
        assert table.format == DataFormat.PARQUET


class TestDataLoadResult:
    """Tests for DataLoadResult dataclass."""

    def test_success_with_tables(self):
        """Test success property with tables."""
        result = DataLoadResult(
            tables={"customer": LoadedTable("customer", Path("c.parquet"), DataFormat.PARQUET)},
        )

        assert result.success is True

    def test_failure_with_errors(self):
        """Test success property with errors."""
        result = DataLoadResult(
            tables={"customer": LoadedTable("customer", Path("c.parquet"), DataFormat.PARQUET)},
            errors=["Something went wrong"],
        )

        assert result.success is False

    def test_failure_no_tables(self):
        """Test success property with no tables."""
        result = DataLoadResult()

        assert result.success is False


class TestSourceHash:
    """Tests for source hash computation."""

    def test_compute_source_hash(self):
        """Test source hash computation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test files
            (tmpdir / "a.tbl").write_text("data")
            (tmpdir / "b.tbl").write_text("more data")

            tables = {
                "a": tmpdir / "a.tbl",
                "b": tmpdir / "b.tbl",
            }

            hash1 = _compute_source_hash(tmpdir, tables)

            # Same files should produce same hash
            hash2 = _compute_source_hash(tmpdir, tables)
            assert hash1 == hash2

            # Modifying a file should change hash
            (tmpdir / "a.tbl").write_text("different data")
            hash3 = _compute_source_hash(tmpdir, tables)
            assert hash3 != hash1

    def test_compute_source_hash_stable_order(self):
        """Test that hash is stable regardless of dict order."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            (tmpdir / "x.tbl").write_text("x")
            (tmpdir / "y.tbl").write_text("y")
            (tmpdir / "z.tbl").write_text("z")

            tables1 = {"x": tmpdir / "x.tbl", "y": tmpdir / "y.tbl", "z": tmpdir / "z.tbl"}
            tables2 = {"z": tmpdir / "z.tbl", "x": tmpdir / "x.tbl", "y": tmpdir / "y.tbl"}

            assert _compute_source_hash(tmpdir, tables1) == _compute_source_hash(tmpdir, tables2)


class TestGetTPCHColumnNames:
    """Tests for get_tpch_column_names function."""

    def test_returns_all_tables(self):
        """Test that all TPC-H tables are returned."""
        columns = get_tpch_column_names()

        assert "lineitem" in columns
        assert "orders" in columns
        assert "customer" in columns
        assert "supplier" in columns
        assert "part" in columns
        assert "partsupp" in columns
        assert "nation" in columns
        assert "region" in columns

    def test_lineitem_columns(self):
        """Test lineitem table columns."""
        columns = get_tpch_column_names()

        assert "l_orderkey" in columns["lineitem"]
        assert "l_quantity" in columns["lineitem"]
        assert "l_shipdate" in columns["lineitem"]

    def test_orders_columns(self):
        """Test orders table columns."""
        columns = get_tpch_column_names()

        assert "o_orderkey" in columns["orders"]
        assert "o_orderdate" in columns["orders"]
        assert "o_totalprice" in columns["orders"]


class TestEnvironmentOverride:
    """Tests for environment variable overrides."""

    def test_cache_dir_env_override(self):
        """Test that BENCHBOX_CACHE_DIR environment variable is respected."""
        with tempfile.TemporaryDirectory() as tmpdir, patch.dict("os.environ", {"BENCHBOX_CACHE_DIR": tmpdir}):
            cache = DataCache()  # No explicit cache_dir

            assert str(cache.cache_dir) == tmpdir


class TestFormatConverterWithWriteConfig:
    """Tests for FormatConverter with DataFrameWriteConfiguration."""

    def test_convert_with_sort_by(self):
        """Test CSV conversion with sorting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create test CSV with unordered data
            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,name,value\n3,charlie,300\n1,alice,100\n2,bob,200\n")

            parquet_path = tmpdir / "test.parquet"

            # Create write config with sorting
            write_config = DataFrameWriteConfiguration(sort_by=[SortColumn(name="id", order="asc")])

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 3
            assert parquet_path.exists()

            # Verify data is sorted
            import pyarrow.parquet as pq

            table = pq.read_table(parquet_path)
            ids = table.column("id").to_pylist()
            assert ids == [1, 2, 3], f"Expected [1, 2, 3], got {ids}"

    def test_convert_with_sort_by_descending(self):
        """Test CSV conversion with descending sort."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,name\n1,a\n3,c\n2,b\n")

            parquet_path = tmpdir / "test.parquet"

            write_config = DataFrameWriteConfiguration(sort_by=[SortColumn(name="id", order="desc")])

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS

            import pyarrow.parquet as pq

            table = pq.read_table(parquet_path)
            ids = table.column("id").to_pylist()
            assert ids == [3, 2, 1], f"Expected [3, 2, 1], got {ids}"

    def test_convert_with_row_group_size(self):
        """Test CSV conversion with row_group_size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,value\n1,a\n2,b\n3,c\n4,d\n5,e\n")

            parquet_path = tmpdir / "test.parquet"

            write_config = DataFrameWriteConfiguration(
                row_group_size=2  # Small for testing
            )

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS
            assert row_count == 5

            # Verify row groups
            import pyarrow.parquet as pq

            meta = pq.read_metadata(parquet_path)
            # Should have 3 row groups (5 rows / 2 per group = 3 groups)
            assert meta.num_row_groups >= 2

    def test_convert_with_compression(self):
        """Test CSV conversion with different compression."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,value\n1,hello\n2,world\n")

            parquet_path = tmpdir / "test.parquet"

            write_config = DataFrameWriteConfiguration(compression="gzip")

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS
            assert parquet_path.exists()

    def test_convert_with_compression_level(self):
        """Test CSV conversion with compression level."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,value\n1,a\n2,b\n")

            parquet_path = tmpdir / "test.parquet"

            write_config = DataFrameWriteConfiguration(
                compression="zstd",
                compression_level=9,  # High compression
            )

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS
            assert parquet_path.exists()

    def test_convert_with_data_page_version(self):
        """Test CSV conversion with data_page_version set to 2.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,value\n1,a\n2,b\n")

            parquet_path = tmpdir / "test.parquet"

            write_config = DataFrameWriteConfiguration(
                data_page_version="2.0",
            )

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS
            assert parquet_path.exists()
            assert row_count == 2

    def test_build_write_kwargs_data_page_version(self):
        """Test _build_write_kwargs includes data_page_version only when set."""
        import pyarrow as pa

        table = pa.table({"id": [1, 2], "value": ["a", "b"]})

        # Without data_page_version
        config_none = DataFrameWriteConfiguration()
        kwargs = FormatConverter._build_write_kwargs("zstd", config_none, table)
        assert "data_page_version" not in kwargs

        # With data_page_version v1.0
        config_v1 = DataFrameWriteConfiguration(data_page_version="1.0")
        kwargs = FormatConverter._build_write_kwargs("zstd", config_v1, table)
        assert kwargs["data_page_version"] == "1.0"

        # With data_page_version v2.0
        config_v2 = DataFrameWriteConfiguration(data_page_version="2.0")
        kwargs = FormatConverter._build_write_kwargs("zstd", config_v2, table)
        assert kwargs["data_page_version"] == "2.0"

    def test_convert_skips_invalid_sort_column(self):
        """Test that non-existent sort columns are skipped."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("id,name\n1,a\n2,b\n")

            parquet_path = tmpdir / "test.parquet"

            # Sort by column that doesn't exist
            write_config = DataFrameWriteConfiguration(
                sort_by=[
                    SortColumn(name="nonexistent", order="asc"),
                    SortColumn(name="id", order="asc"),
                ]
            )

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            # Should succeed despite invalid column
            assert status == ConversionStatus.SUCCESS
            assert row_count == 2

    def test_convert_with_default_write_config(self):
        """Test conversion with default (empty) write config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            csv_path = tmpdir / "test.csv"
            csv_path.write_text("x,y\n1,2\n")

            parquet_path = tmpdir / "test.parquet"

            write_config = DataFrameWriteConfiguration()  # Default config

            status, _ = FormatConverter.convert_csv_to_parquet(
                source_path=csv_path,
                target_path=parquet_path,
                delimiter=",",
                write_config=write_config,
            )

            assert status == ConversionStatus.SUCCESS


class TestDataFrameDataLoaderWithWriteConfig:
    """Tests for DataFrameDataLoader with write configuration."""

    def test_init_with_write_config(self):
        """Test initialization with write config."""
        write_config = DataFrameWriteConfiguration(sort_by=[SortColumn(name="id", order="asc")])
        loader = DataFrameDataLoader(write_config=write_config)

        assert loader.write_config is not None
        assert len(loader.write_config.sort_by) == 1

    def test_get_table_write_config_filters_columns(self):
        """Test that write config is filtered for table columns."""
        loader = DataFrameDataLoader()

        base_config = DataFrameWriteConfiguration(
            sort_by=[
                SortColumn(name="l_shipdate", order="asc"),
                SortColumn(name="l_orderkey", order="asc"),
                SortColumn(name="c_custkey", order="asc"),  # Not in lineitem
            ],
            row_group_size=1000000,
        )

        lineitem_cols = ["l_orderkey", "l_partkey", "l_shipdate", "l_quantity"]

        filtered = loader._get_table_write_config(base_config, "lineitem", lineitem_cols)

        assert filtered is not None
        # Should only have sort columns that exist in table
        assert len(filtered.sort_by) == 2
        sort_names = [s.name for s in filtered.sort_by]
        assert "l_shipdate" in sort_names
        assert "l_orderkey" in sort_names
        assert "c_custkey" not in sort_names

        # Non-column settings should be preserved
        assert filtered.row_group_size == 1000000

    def test_get_table_write_config_returns_none_for_none(self):
        """Test that None config returns None."""
        loader = DataFrameDataLoader()

        result = loader._get_table_write_config(None, "table", ["col1"])
        assert result is None

    def test_get_table_write_config_returns_default_unchanged(self):
        """Test that default config is returned unchanged."""
        loader = DataFrameDataLoader()

        default_config = DataFrameWriteConfiguration()
        result = loader._get_table_write_config(default_config, "table", ["col1"])

        assert result is default_config

    def test_get_table_write_config_no_columns_returns_original(self):
        """Test that config without column info returns original."""
        loader = DataFrameDataLoader()

        config = DataFrameWriteConfiguration(sort_by=[SortColumn(name="id", order="asc")])

        result = loader._get_table_write_config(config, "table", None)
        assert result is config
