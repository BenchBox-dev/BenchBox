from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .downloader import download, sha256_of
from .errors import ChecksumMismatchError, DataFetchError
from .locking import archive_lock
from .logical_hash import logical_columns_from_schema, logical_table_hash_from_parquet
from .manifest import DataManifest, load_manifest


@dataclass(frozen=True)
class _BadFile:
    file: str
    kind: Literal["missing", "sha_mismatch"]
    expected_sha256: str | None = None
    actual_sha256: str | None = None


class ExtractionRequiredError(DataFetchError):
    def __init__(self, archive_path: str, output_dir: str):
        self.archive_path = archive_path
        self.output_dir = output_dir
        super().__init__(
            f"archive downloaded to {archive_path}; extract into {output_dir} "
            "and re-call fetch_data() to verify per-table sha256s"
        )


def _verify_table_files(manifest: DataManifest, data_dir: Path) -> list[_BadFile]:
    bad: list[_BadFile] = []
    for entry in manifest.tables:
        p = data_dir / entry.file
        if not p.exists():
            bad.append(_BadFile(file=entry.file, kind="missing"))
            continue
        actual = sha256_of(p)
        if actual != entry.sha256:
            bad.append(
                _BadFile(
                    file=entry.file,
                    kind="sha_mismatch",
                    expected_sha256=entry.sha256,
                    actual_sha256=actual,
                )
            )
    return bad


@dataclass(frozen=True)
class LogicalMismatch:
    table: str
    kind: Literal["missing", "no_schema", "row_count_mismatch", "hash_mismatch"]
    expected: str | None = None
    actual: str | None = None


def verify_logical_content(
    manifest: DataManifest,
    data_dir: str | Path,
    *,
    con: object | None = None,
) -> list[LogicalMismatch]:
    if not manifest.is_logical:
        raise DataFetchError(
            f"manifest {manifest.dataset_version} does not pin per-table logical_sha256; "
            "logical verification requires a logical-mode manifest"
        )

    data_dir = Path(data_dir)
    owns_con = con is None
    if con is None:
        import duckdb

        con = duckdb.connect()
    try:
        mismatches: list[LogicalMismatch] = []
        for entry in manifest.tables:
            parquet_path = data_dir / entry.file
            if not parquet_path.exists():
                mismatches.append(LogicalMismatch(table=entry.name, kind="missing"))
                continue
            if not entry.schema:
                mismatches.append(LogicalMismatch(table=entry.name, kind="no_schema"))
                continue
            result = logical_table_hash_from_parquet(
                con=con,
                parquet_path=parquet_path,
                table=entry.name,
                columns=logical_columns_from_schema(entry.schema),
            )
            if result.row_count != entry.row_count:
                mismatches.append(
                    LogicalMismatch(
                        table=entry.name,
                        kind="row_count_mismatch",
                        expected=str(entry.row_count),
                        actual=str(result.row_count),
                    )
                )
            elif result.sha256 != entry.logical_sha256:
                mismatches.append(
                    LogicalMismatch(
                        table=entry.name,
                        kind="hash_mismatch",
                        expected=entry.logical_sha256,
                        actual=result.sha256,
                    )
                )
        return mismatches
    finally:
        if owns_con:
            con.close()


def fetch_data(
    benchmark_id: str,
    manifest_path: str | Path,
    output_dir: str | Path,
    *,
    downloader: object | None = None,
    archive_filename: str | None = None,
) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(manifest_path)

    bad = _verify_table_files(manifest, out)
    if not bad:
        return out

    mismatches = [b for b in bad if b.kind == "sha_mismatch"]
    if mismatches:
        first = mismatches[0]
        raise ChecksumMismatchError(
            path=str(out / first.file),
            expected_sha256=first.expected_sha256 or "",
            actual_sha256=first.actual_sha256 or "",
        )

    archive_name = archive_filename or Path(manifest.url).name or f"{benchmark_id}.tar.zst"
    archive_path = out / archive_name

    with archive_lock(archive_path):
        bad = _verify_table_files(manifest, out)
        if not bad:
            return out

        mismatches = [b for b in bad if b.kind == "sha_mismatch"]
        if mismatches:
            first = mismatches[0]
            raise ChecksumMismatchError(
                path=str(out / first.file),
                expected_sha256=first.expected_sha256 or "",
                actual_sha256=first.actual_sha256 or "",
            )

        if archive_path.exists() and sha256_of(archive_path) == manifest.archive_sha256:
            raise ExtractionRequiredError(archive_path=str(archive_path), output_dir=str(out))

        fetch = downloader or download
        fetch(manifest.url, archive_path, expected_sha256=manifest.archive_sha256)

        bad = _verify_table_files(manifest, out)
        if not bad:
            return out

        mismatches = [b for b in bad if b.kind == "sha_mismatch"]
        if mismatches:
            first = mismatches[0]
            raise ChecksumMismatchError(
                path=str(out / first.file),
                expected_sha256=first.expected_sha256 or "",
                actual_sha256=first.actual_sha256 or "",
            )

        raise ExtractionRequiredError(archive_path=str(archive_path), output_dir=str(out))
