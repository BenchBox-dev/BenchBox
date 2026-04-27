"""Manifest handling mixin for the TPC-DI data generator."""

from __future__ import annotations

from pathlib import Path

from benchbox.utils.datagen_manifest import DataGenerationManifest
from benchbox.utils.file_format import detect_compression, validate_tbl_compression_consistency

_TPCDI_CSV_METADATA = {
    "csv_normalize_booleans": True,
    "csv_null_marker": "",
}


class ManifestMixin:
    """Provide manifest persistence and validation helpers."""

    def _validate_file_format_consistency(self, target_dir: Path) -> None:
        """Ensure no raw .tbl files exist when compression is enabled; ensure no empty compressed files."""
        if not self.should_use_compression():
            return
        validate_tbl_compression_consistency(target_dir, self.get_compressor().get_file_extension())

    def _count_rows(self, p: Path) -> int:
        """Count rows in a data file, transparently handling common compression formats."""
        try:
            compression = detect_compression(p)
            if compression == "gzip":
                import gzip

                with gzip.open(p, "rt") as f:
                    return sum(1 for _ in f)
            if compression == "zstd":
                try:
                    import zstandard as zstd

                    dctx = zstd.ZstdDecompressor()
                    with open(p, "rb") as fh, dctx.stream_reader(fh) as reader:
                        import io

                        return sum(1 for _ in io.TextIOWrapper(reader, encoding="utf-8"))
                except Exception:
                    return 0
            if compression == "bzip2":
                import bz2

                with bz2.open(p, "rt") as f:
                    return sum(1 for _ in f)
            if compression == "xz":
                import lzma

                with lzma.open(p, "rt") as f:
                    return sum(1 for _ in f)
            with open(p, "rb") as f:
                return sum(1 for _ in f)
        except Exception:
            return 0

    def _write_manifest(self, output_dir: Path, table_paths: dict[str, str]) -> None:
        manifest = DataGenerationManifest(
            output_dir=output_dir,
            benchmark="tpcdi",
            scale_factor=self.scale_factor,
            compression={
                "enabled": self.should_use_compression(),
                "type": getattr(self, "compression_type", None),
                "level": getattr(self, "compression_level", None),
            },
            parallel=self.max_workers or 1,
        )
        for table, path_str in table_paths.items():
            p = Path(path_str)
            rows = self._count_rows(p)
            manifest.add_entry(table, p, row_count=rows, metadata=_TPCDI_CSV_METADATA)
        manifest.write()


__all__ = ["ManifestMixin"]
