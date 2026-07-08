"""Tests for TPC-H file-mode trailing-delimiter normalization.

Classic dbgen file mode (binaries without the BenchBox stdout-streaming
patch, e.g. the bundled Linux dbgen) terminates every row with a field
delimiter, while the patched -z streaming mode does not. The generator
normalizes file-mode output so generated data is identical across platforms
(release PR #1043 canary caught the Linux divergence).

These tests exercise the post-processing directly with synthetic .tbl files
so the behavior is verified on every platform, including macOS where the
streaming path normally hides the bug.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

import benchbox.core.tpch.generator as generator_module
from benchbox.core.tpch.generator import TPCHDataGenerator, normalize_tbl_trailing_delimiters

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.tpch,
]

DIRTY_CUSTOMER = (
    b"1|Customer#000000001|IVhzIApeRb|15|25-989-741-2988|711.56|BUILDING|to the even, regular platelets|\n"
    b"2|Customer#000000002|XSTf4,NCwDVaW|13|23-768-687-3665|121.65|AUTOMOBILE|l accounts. blithely|\n"
)
CLEAN_CUSTOMER = (
    b"1|Customer#000000001|IVhzIApeRb|15|25-989-741-2988|711.56|BUILDING|to the even, regular platelets\n"
    b"2|Customer#000000002|XSTf4,NCwDVaW|13|23-768-687-3665|121.65|AUTOMOBILE|l accounts. blithely\n"
)


class TestNormalizeTblTrailingDelimiters:
    """Unit tests for the streaming normalization function."""

    def test_strips_exactly_one_trailing_pipe_per_line(self, tmp_path: Path):
        tbl = tmp_path / "customer.tbl"
        tbl.write_bytes(DIRTY_CUSTOMER)

        assert normalize_tbl_trailing_delimiters(tbl) is True
        assert tbl.read_bytes() == CLEAN_CUSTOMER

    def test_preserves_interior_and_trailing_empty_fields(self, tmp_path: Path):
        # In .tbl format the trailing empty field is a delimiter artifact, not
        # a NULL; only the final delimiter may be removed.
        tbl = tmp_path / "table.tbl"
        tbl.write_bytes(b"1|a||b|\n2|||\n")

        assert normalize_tbl_trailing_delimiters(tbl) is True
        assert tbl.read_bytes() == b"1|a||b\n2||\n"

    def test_clean_file_left_untouched(self, tmp_path: Path):
        tbl = tmp_path / "customer.tbl"
        tbl.write_bytes(CLEAN_CUSTOMER)

        assert normalize_tbl_trailing_delimiters(tbl) is False
        assert tbl.read_bytes() == CLEAN_CUSTOMER

    def test_empty_file_left_untouched(self, tmp_path: Path):
        tbl = tmp_path / "empty.tbl"
        tbl.write_bytes(b"")

        assert normalize_tbl_trailing_delimiters(tbl) is False
        assert tbl.read_bytes() == b""

    def test_final_line_without_newline(self, tmp_path: Path):
        tbl = tmp_path / "table.tbl"
        tbl.write_bytes(b"1|a|\n2|b|")

        assert normalize_tbl_trailing_delimiters(tbl) is True
        assert tbl.read_bytes() == b"1|a\n2|b"

    def test_idempotent(self, tmp_path: Path):
        tbl = tmp_path / "customer.tbl"
        tbl.write_bytes(DIRTY_CUSTOMER)

        assert normalize_tbl_trailing_delimiters(tbl) is True
        assert normalize_tbl_trailing_delimiters(tbl) is False
        assert tbl.read_bytes() == CLEAN_CUSTOMER

    @pytest.mark.parametrize("chunk_size", [1, 2, 3, 7, 64])
    def test_chunk_boundary_carry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, chunk_size: int):
        # Force the "|" / "\n" pair to straddle read-chunk boundaries so the
        # carry-byte logic is exercised.
        monkeypatch.setattr(generator_module, "_NORMALIZE_CHUNK_SIZE", chunk_size)
        tbl = tmp_path / "table.tbl"
        tbl.write_bytes(b"1|aa||\n22|b|\n|\n")

        assert normalize_tbl_trailing_delimiters(tbl) is True
        assert tbl.read_bytes() == b"1|aa|\n22|b\n\n"

    def test_no_temp_file_left_behind(self, tmp_path: Path):
        tbl = tmp_path / "customer.tbl"
        tbl.write_bytes(DIRTY_CUSTOMER)

        normalize_tbl_trailing_delimiters(tbl)
        assert sorted(p.name for p in tmp_path.iterdir()) == ["customer.tbl"]


TPCH_TABLES = ["customer", "lineitem", "nation", "orders", "part", "partsupp", "region", "supplier"]


class TestFinalizeGenerationNormalization:
    """The file-mode fallback pipeline must normalize before returning/compressing."""

    def _write_all_tables(self, target_dir: Path, payload: bytes, chunked: tuple[str, int] | None = None) -> None:
        """Write synthetic .tbl files for all 8 tables (avoids dbgen fallback lookups)."""
        for table in TPCH_TABLES:
            if chunked and table == chunked[0]:
                for chunk_id in range(1, chunked[1] + 1):
                    (target_dir / f"{table}.tbl.{chunk_id}").write_bytes(payload)
            else:
                (target_dir / f"{table}.tbl").write_bytes(payload)

    def test_file_mode_single_tables_normalized(self, tmp_path: Path):
        generator = TPCHDataGenerator(scale_factor=0.01, output_dir=tmp_path, compress_data=False)
        self._write_all_tables(tmp_path, DIRTY_CUSTOMER)

        result = generator._finalize_generation(tmp_path)

        assert set(result) == set(TPCH_TABLES)
        for table in TPCH_TABLES:
            path = result[table]
            assert isinstance(path, Path)
            assert path.read_bytes() == CLEAN_CUSTOMER

    def test_file_mode_chunked_tables_normalized(self, tmp_path: Path):
        generator = TPCHDataGenerator(scale_factor=0.01, output_dir=tmp_path, compress_data=False, parallel=2)
        self._write_all_tables(tmp_path, DIRTY_CUSTOMER, chunked=("customer", 2))

        result = generator._finalize_generation(tmp_path)

        chunks = result["customer"]
        assert isinstance(chunks, list)
        assert len(chunks) == 2
        for chunk in chunks:
            assert chunk.read_bytes() == CLEAN_CUSTOMER

    def test_normalization_happens_before_compression(self, tmp_path: Path):
        generator = TPCHDataGenerator(
            scale_factor=0.01,
            output_dir=tmp_path,
            compress_data=True,
            compression_type="gzip",
        )
        self._write_all_tables(tmp_path, DIRTY_CUSTOMER)

        result = generator._finalize_generation(tmp_path)

        compressed = result["customer"]
        assert isinstance(compressed, Path)
        assert compressed.name == "customer.tbl.gz"
        assert gzip.decompress(compressed.read_bytes()) == CLEAN_CUSTOMER

    def test_chunked_compression_normalized_before_compressing(self, tmp_path: Path):
        generator = TPCHDataGenerator(
            scale_factor=0.01,
            output_dir=tmp_path,
            compress_data=True,
            compression_type="gzip",
            parallel=2,
        )
        self._write_all_tables(tmp_path, DIRTY_CUSTOMER, chunked=("customer", 2))

        result = generator._finalize_generation(tmp_path)

        chunks = result["customer"]
        assert isinstance(chunks, list)
        assert [c.name for c in chunks] == ["customer.tbl.1.gz", "customer.tbl.2.gz"]
        for chunk in chunks:
            assert gzip.decompress(chunk.read_bytes()) == CLEAN_CUSTOMER

    def test_clean_file_mode_output_unchanged(self, tmp_path: Path):
        # macOS patched dbgen already emits clean rows in file mode; the
        # normalization pass must not alter them.
        generator = TPCHDataGenerator(scale_factor=0.01, output_dir=tmp_path, compress_data=False)
        self._write_all_tables(tmp_path, CLEAN_CUSTOMER)

        result = generator._finalize_generation(tmp_path)

        customer = result["customer"]
        assert isinstance(customer, Path)
        assert customer.read_bytes() == CLEAN_CUSTOMER
