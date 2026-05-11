"""Build canonical JoinOrder IMDb data artifacts.

This script is intentionally outside the BenchBox runtime package. It owns the
network, Docker, and PostgreSQL tooling needed to turn the upstream Harvard
Dataverse pg_dump into build artifacts consumed by later foundation slices.

w4 scope:
  - resolve and download the Harvard Dataverse pg_dump for doi:10.7910/DVN/2QYZBT
  - compute and record the upstream sha256 in a local build manifest
  - restore the custom-format pg_dump into a pinned PostgreSQL container
  - validate expected JOB tables and row counts within the TODO's +/-1% gate
  - tear down the container by default
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

DATASET_VERSION = "joinorder-imdb-2013-v1"
SOURCE_DOI = "10.7910/DVN/2QYZBT"
SOURCE_PERSISTENT_ID = f"doi:{SOURCE_DOI}"
DATAVERSE_DATASET_API = f"https://dataverse.harvard.edu/api/datasets/:persistentId?persistentId={SOURCE_PERSISTENT_ID}"
DATAVERSE_FILE_ACCESS_TEMPLATE = "https://dataverse.harvard.edu/api/access/datafile/{file_id}"
DEFAULT_POSTGRES_IMAGE = "postgres:16.2"
DEFAULT_POSTGRES_DB = "imdb"
DEFAULT_POSTGRES_USER = "postgres"
BUILD_MANIFEST_NAME = "build_manifest.json"
PGDUMP_MAGIC = b"PGDMP"
ROW_COUNT_TOLERANCE = 0.01

# JOB / IMDb cardinalities published with the canonical CSV import flow and
# cross-checked during w4 against the restored Dataverse pg_dump. Small lookup
# tables effectively require exact matches under the +/-1% gate.
EXPECTED_ROW_COUNTS: dict[str, int] = {
    "aka_name": 901_343,
    "aka_title": 361_472,
    "cast_info": 36_244_344,
    "char_name": 3_140_339,
    "comp_cast_type": 4,
    "company_name": 234_997,
    "company_type": 4,
    "complete_cast": 135_086,
    "info_type": 113,
    "keyword": 134_170,
    "kind_type": 7,
    "link_type": 18,
    "movie_companies": 2_609_129,
    "movie_info": 14_835_720,
    "movie_info_idx": 1_380_035,
    "movie_keyword": 4_523_930,
    "movie_link": 29_997,
    "name": 4_167_491,
    "person_info": 2_963_664,
    "role_type": 12,
    "title": 2_528_312,
}


class JoinOrderBuildError(RuntimeError):
    """Raised when the canonical JoinOrder build pipeline cannot proceed."""


class DataverseMetadataError(JoinOrderBuildError):
    """Raised when the Dataverse metadata does not expose the expected pg_dump."""


class DownloadIntegrityError(JoinOrderBuildError):
    """Raised when a downloaded pg_dump fails declared Dataverse integrity checks."""


class DockerUnavailableError(JoinOrderBuildError):
    """Raised when Docker is not available for the PostgreSQL restore step."""


@dataclasses.dataclass(frozen=True)
class DataverseFile:
    """Dataverse file metadata needed to download and verify the upstream pg_dump."""

    file_id: int
    label: str
    filesize: int
    checksum_type: str
    checksum_value: str
    download_url: str


@dataclasses.dataclass(frozen=True)
class PgDumpArtifact:
    """Local pg_dump file plus computed integrity data."""

    path: Path
    size: int
    sha256: str
    md5: str
    dataverse_file: DataverseFile


@dataclasses.dataclass(frozen=True)
class RowCountFailure:
    """A table whose restored row count is outside the allowed tolerance."""

    table: str
    expected: int
    actual: int
    allowed_delta: int


@dataclasses.dataclass(frozen=True)
class RestoreValidation:
    """Validation result for the restored PostgreSQL database."""

    row_counts: dict[str, int]
    missing_tables: list[str]
    unexpected_tables: list[str]
    row_count_failures: list[RowCountFailure]

    @property
    def ok(self) -> bool:
        return not self.missing_tables and not self.row_count_failures


def utc_now_iso() -> str:
    """Return a stable UTC timestamp string for provenance records."""

    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def default_build_root() -> Path:
    """Resolve the default build directory without adding a new env var."""

    output_root = os.environ.get("BENCHBOX_OUTPUT_DIR")
    base = Path(output_root).expanduser() if output_root else Path("~/Developer/benchmark_runs").expanduser()
    return base / "joinorder" / "build" / DATASET_VERSION


def work_dir_from_arg(raw: str | None) -> Path:
    return Path(raw).expanduser().resolve() if raw else default_build_root().resolve()


def build_manifest_path(work_dir: Path) -> Path:
    return work_dir / BUILD_MANIFEST_NAME


def load_build_manifest(work_dir: Path) -> dict[str, Any]:
    path = build_manifest_path(work_dir)
    if not path.exists():
        return {
            "dataset_version": DATASET_VERSION,
            "source_doi": SOURCE_DOI,
            "created_at": utc_now_iso(),
        }
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise JoinOrderBuildError(f"{path} must contain a JSON object")
    return data


def write_build_manifest(work_dir: Path, updates: Mapping[str, Any]) -> Path:
    work_dir.mkdir(parents=True, exist_ok=True)
    data = load_build_manifest(work_dir)
    data.update(updates)
    data["updated_at"] = utc_now_iso()

    path = build_manifest_path(work_dir)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")
    tmp_path.replace(path)
    return path


def _load_json_url(url: str, *, timeout: float = 60.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "BenchBox-JoinOrder-Builder/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DataverseMetadataError(f"Unable to read Dataverse metadata from {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DataverseMetadataError(f"Dataverse metadata from {url} must be a JSON object")
    return payload


def select_pgdump_file(metadata: Mapping[str, Any]) -> DataverseFile:
    """Select the single custom-format pg_dump from a Dataverse dataset response."""

    try:
        files = metadata["data"]["latestVersion"]["files"]
    except KeyError as exc:
        raise DataverseMetadataError("Dataverse response is missing data.latestVersion.files") from exc
    if not isinstance(files, list):
        raise DataverseMetadataError("Dataverse response field data.latestVersion.files must be a list")

    candidates: list[DataverseFile] = []
    for entry in files:
        if not isinstance(entry, Mapping):
            continue
        data_file = entry.get("dataFile")
        if not isinstance(data_file, Mapping):
            continue
        label = str(entry.get("label") or data_file.get("filename") or "")
        checksum = data_file.get("checksum")
        if not label or not isinstance(checksum, Mapping):
            continue
        if label != "imdb_pg11":
            continue
        file_id = data_file.get("id")
        filesize = data_file.get("filesize")
        checksum_type = checksum.get("type")
        checksum_value = checksum.get("value")
        if not isinstance(file_id, int) or not isinstance(filesize, int):
            raise DataverseMetadataError(f"Dataverse file {label!r} is missing integer id/filesize")
        if not isinstance(checksum_type, str) or not isinstance(checksum_value, str):
            raise DataverseMetadataError(f"Dataverse file {label!r} is missing checksum metadata")
        candidates.append(
            DataverseFile(
                file_id=file_id,
                label=label,
                filesize=filesize,
                checksum_type=checksum_type.upper(),
                checksum_value=checksum_value.lower(),
                download_url=DATAVERSE_FILE_ACCESS_TEMPLATE.format(file_id=file_id),
            )
        )

    if len(candidates) != 1:
        raise DataverseMetadataError(
            f"Expected exactly one Dataverse pg_dump file named imdb_pg11; found {len(candidates)}"
        )
    return candidates[0]


def resolve_dataverse_file() -> DataverseFile:
    metadata = _load_json_url(DATAVERSE_DATASET_API)
    return select_pgdump_file(metadata)


def hash_file(path: Path) -> tuple[str, str, int]:
    sha256 = hashlib.sha256()
    md5 = hashlib.md5(usedforsecurity=False)
    size = 0
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            sha256.update(chunk)
            md5.update(chunk)
            size += len(chunk)
    return sha256.hexdigest(), md5.hexdigest(), size


def validate_pgdump_file(path: Path, dataverse_file: DataverseFile) -> PgDumpArtifact:
    if not path.exists():
        raise JoinOrderBuildError(f"pg_dump file does not exist: {path}")
    sha256, md5, size = hash_file(path)
    if size != dataverse_file.filesize:
        raise DownloadIntegrityError(
            f"Downloaded pg_dump size mismatch: expected {dataverse_file.filesize} bytes, got {size}"
        )
    if dataverse_file.checksum_type == "MD5" and md5 != dataverse_file.checksum_value:
        raise DownloadIntegrityError(
            f"Downloaded pg_dump MD5 mismatch: expected {dataverse_file.checksum_value}, got {md5}"
        )
    with path.open("rb") as handle:
        if handle.read(len(PGDUMP_MAGIC)) != PGDUMP_MAGIC:
            raise DownloadIntegrityError(f"{path} is not a PostgreSQL custom-format pg_dump")
    return PgDumpArtifact(path=path, size=size, sha256=sha256, md5=md5, dataverse_file=dataverse_file)


def download_pgdump(work_dir: Path, *, force: bool = False) -> PgDumpArtifact:
    """Download the Dataverse pg_dump, verify MD5, and record sha256 provenance."""

    dataverse_file = resolve_dataverse_file()
    source_dir = work_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    destination = source_dir / dataverse_file.label
    tmp_path = destination.with_name(destination.name + ".part")

    if destination.exists() and not force:
        try:
            artifact = validate_pgdump_file(destination, dataverse_file)
        except DownloadIntegrityError:
            if tmp_path.exists():
                tmp_path.unlink()
            destination.replace(tmp_path)
        else:
            write_source_manifest(work_dir, artifact, reused=True)
            return artifact
    elif force and tmp_path.exists():
        tmp_path.unlink()

    print(
        f"Downloading Dataverse file {dataverse_file.file_id} to {tmp_path} ({dataverse_file.filesize} bytes expected)",
        flush=True,
    )
    download_to_file(dataverse_file.download_url, tmp_path)
    artifact = validate_pgdump_file(tmp_path, dataverse_file)
    tmp_path.replace(destination)
    artifact = dataclasses.replace(artifact, path=destination)
    write_source_manifest(work_dir, artifact, reused=False)
    return artifact


def download_to_file(url: str, destination: Path) -> None:
    if shutil.which("curl"):
        stream_command(
            [
                "curl",
                "--fail",
                "--location",
                "--show-error",
                "--retry",
                "5",
                "--retry-delay",
                "5",
                "--retry-all-errors",
                "--connect-timeout",
                "30",
                "--continue-at",
                "-",
                "--output",
                str(destination),
                url,
            ]
        )
        return

    existing_size = destination.stat().st_size if destination.exists() else 0
    headers = {"User-Agent": "BenchBox-JoinOrder-Builder/1.0"}
    if existing_size:
        headers["Range"] = f"bytes={existing_size}-"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            mode = "ab" if existing_size and getattr(response, "status", None) == 206 else "wb"
            with destination.open(mode) as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JoinOrderBuildError(f"Unable to download Dataverse pg_dump: {exc}") from exc


def write_source_manifest(work_dir: Path, artifact: PgDumpArtifact, *, reused: bool) -> Path:
    return write_build_manifest(
        work_dir,
        {
            "source": {
                "doi": SOURCE_DOI,
                "persistent_id": SOURCE_PERSISTENT_ID,
                "metadata_url": DATAVERSE_DATASET_API,
                "download_url": artifact.dataverse_file.download_url,
                "dataverse_file_id": artifact.dataverse_file.file_id,
                "label": artifact.dataverse_file.label,
                "bytes": artifact.size,
                "dataverse_checksum_type": artifact.dataverse_file.checksum_type,
                "dataverse_checksum": artifact.dataverse_file.checksum_value,
                "md5": artifact.md5,
                "sha256": artifact.sha256,
                "path": str(artifact.path),
                "reused_existing_file": reused,
                "retrieved_at": utc_now_iso(),
            }
        },
    )


def require_docker() -> None:
    if shutil.which("docker") is None:
        raise DockerUnavailableError("Docker CLI is not available on PATH")
    result = run_command(["docker", "version", "--format", "{{.Server.Version}}"], check=False)
    if result.returncode != 0:
        raise DockerUnavailableError(
            "Docker daemon is not available: "
            + (result.stderr.strip() or result.stdout.strip() or "docker version failed")
        )


def run_command(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, check=False, capture_output=True, text=True)
    if check and result.returncode != 0:
        command = " ".join(args)
        tail = (result.stderr or result.stdout).strip()
        raise JoinOrderBuildError(f"Command failed ({result.returncode}): {command}\n{tail}")
    return result


def stream_command(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[None]:
    result = subprocess.run(args, check=False)
    if check and result.returncode != 0:
        command = " ".join(args)
        raise JoinOrderBuildError(f"Command failed ({result.returncode}): {command}")
    return result


def ensure_postgres_image(image: str) -> None:
    if run_command(["docker", "image", "inspect", image], check=False).returncode == 0:
        return
    stream_command(["docker", "pull", image])


def default_container_name() -> str:
    return f"benchbox-joinorder-w4-{os.getpid()}"


def remove_container(container_name: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", container_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def start_postgres_container(
    *,
    container_name: str,
    image: str,
    database: str,
    user: str,
    replace_existing: bool,
) -> None:
    if replace_existing:
        remove_container(container_name)
    stream_command(
        [
            "docker",
            "run",
            "--detach",
            "--name",
            container_name,
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "-e",
            f"POSTGRES_DB={database}",
            image,
        ]
    )
    wait_for_postgres(container_name=container_name, database=database, user=user)


def wait_for_postgres(*, container_name: str, database: str, user: str, timeout_seconds: int = 90) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_message = ""
    while time.monotonic() < deadline:
        result = run_command(
            ["docker", "exec", container_name, "pg_isready", "-U", user, "-d", database],
            check=False,
        )
        if result.returncode == 0:
            return
        last_message = result.stderr.strip() or result.stdout.strip()
        time.sleep(1)
    raise JoinOrderBuildError(f"PostgreSQL did not become ready within {timeout_seconds}s: {last_message}")


def restore_pgdump(
    artifact: PgDumpArtifact,
    *,
    work_dir: Path,
    postgres_image: str = DEFAULT_POSTGRES_IMAGE,
    container_name: str | None = None,
    database: str = DEFAULT_POSTGRES_DB,
    user: str = DEFAULT_POSTGRES_USER,
    keep_container: bool = False,
    replace_existing: bool = True,
) -> RestoreValidation:
    """Restore the pg_dump into a pinned PostgreSQL container and validate it."""

    require_docker()
    ensure_postgres_image(postgres_image)

    actual_container_name = container_name or default_container_name()
    started = False
    try:
        start_postgres_container(
            container_name=actual_container_name,
            image=postgres_image,
            database=database,
            user=user,
            replace_existing=replace_existing,
        )
        started = True
        container_dump_path = f"/tmp/{artifact.path.name}"
        stream_command(["docker", "cp", str(artifact.path), f"{actual_container_name}:{container_dump_path}"])
        stream_command(
            [
                "docker",
                "exec",
                actual_container_name,
                "pg_restore",
                "-U",
                user,
                "-d",
                database,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                container_dump_path,
            ]
        )
        validation = validate_restored_database(
            container_name=actual_container_name,
            database=database,
            user=user,
        )
        write_restore_manifest(
            work_dir,
            artifact,
            validation,
            postgres_image=postgres_image,
            container_name=actual_container_name,
            database=database,
            keep_container=keep_container,
        )
        if not validation.ok:
            raise JoinOrderBuildError(format_restore_failures(validation))
        return validation
    finally:
        if started and not keep_container:
            remove_container(actual_container_name)


def write_restore_manifest(
    work_dir: Path,
    artifact: PgDumpArtifact,
    validation: RestoreValidation,
    *,
    postgres_image: str,
    container_name: str,
    database: str,
    keep_container: bool,
) -> Path:
    return write_build_manifest(
        work_dir,
        {
            "restore": {
                "postgres_image": postgres_image,
                "database": database,
                "container_name": container_name,
                "container_kept": keep_container,
                "pg_dump_sha256": artifact.sha256,
                "validated_at": utc_now_iso(),
                "row_count_tolerance": ROW_COUNT_TOLERANCE,
                "expected_table_count": len(EXPECTED_ROW_COUNTS),
                "actual_table_count": len(validation.row_counts),
                "missing_tables": validation.missing_tables,
                "unexpected_tables": validation.unexpected_tables,
                "row_count_failures": [dataclasses.asdict(failure) for failure in validation.row_count_failures],
                "row_counts": validation.row_counts,
            }
        },
    )


def validate_restored_database(*, container_name: str, database: str, user: str) -> RestoreValidation:
    table_sql = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
    )
    result = psql(container_name=container_name, database=database, user=user, sql=table_sql)
    restored_tables = [line.strip() for line in result.splitlines() if line.strip()]
    restored_table_set = set(restored_tables)

    row_counts: dict[str, int] = {}
    missing_tables = sorted(set(EXPECTED_ROW_COUNTS) - restored_table_set)
    unexpected_tables = sorted(restored_table_set - set(EXPECTED_ROW_COUNTS))
    for table in sorted(set(EXPECTED_ROW_COUNTS) & restored_table_set):
        count_sql = f"SELECT count(*) FROM public.{quote_ident(table)}"
        count_raw = psql(container_name=container_name, database=database, user=user, sql=count_sql).strip()
        try:
            row_counts[table] = int(count_raw)
        except ValueError as exc:
            raise JoinOrderBuildError(f"Unable to parse row count for {table}: {count_raw!r}") from exc

    return validate_row_counts(row_counts, missing_tables=missing_tables, unexpected_tables=unexpected_tables)


def validate_row_counts(
    row_counts: Mapping[str, int],
    *,
    missing_tables: Sequence[str] | None = None,
    unexpected_tables: Sequence[str] | None = None,
) -> RestoreValidation:
    """Validate restored row counts against the canonical JOB cardinalities."""

    missing = sorted(set(missing_tables or []) | (set(EXPECTED_ROW_COUNTS) - set(row_counts)))
    failures: list[RowCountFailure] = []
    for table, expected in EXPECTED_ROW_COUNTS.items():
        if table not in row_counts:
            continue
        actual = int(row_counts[table])
        allowed_delta = math.floor(expected * ROW_COUNT_TOLERANCE)
        if abs(actual - expected) > allowed_delta:
            failures.append(
                RowCountFailure(
                    table=table,
                    expected=expected,
                    actual=actual,
                    allowed_delta=allowed_delta,
                )
            )

    return RestoreValidation(
        row_counts=dict(sorted((table, int(count)) for table, count in row_counts.items())),
        missing_tables=missing,
        unexpected_tables=sorted(unexpected_tables or []),
        row_count_failures=failures,
    )


def quote_ident(identifier: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
        raise JoinOrderBuildError(f"Unsafe SQL identifier: {identifier!r}")
    return '"' + identifier.replace('"', '""') + '"'


def psql(*, container_name: str, database: str, user: str, sql: str) -> str:
    result = run_command(
        [
            "docker",
            "exec",
            container_name,
            "psql",
            "-U",
            user,
            "-d",
            database,
            "-Atq",
            "-v",
            "ON_ERROR_STOP=1",
            "-c",
            sql,
        ]
    )
    return result.stdout


def format_restore_failures(validation: RestoreValidation) -> str:
    parts: list[str] = ["JoinOrder PostgreSQL restore validation failed"]
    if validation.missing_tables:
        parts.append(f"missing tables: {', '.join(validation.missing_tables)}")
    if validation.row_count_failures:
        failure_lines = [
            f"{failure.table}: expected {failure.expected}, got {failure.actual}, allowed_delta {failure.allowed_delta}"
            for failure in validation.row_count_failures
        ]
        parts.append("row count failures: " + "; ".join(failure_lines))
    return "\n".join(parts)


def print_source_summary(artifact: PgDumpArtifact, manifest_path: Path) -> None:
    print("Dataverse pg_dump ready")
    print(f"  doi:      {SOURCE_DOI}")
    print(f"  file id:  {artifact.dataverse_file.file_id}")
    print(f"  label:    {artifact.dataverse_file.label}")
    print(f"  bytes:    {artifact.size}")
    print(f"  md5:      {artifact.md5}")
    print(f"  sha256:   {artifact.sha256}")
    print(f"  manifest: {manifest_path}")


def print_restore_summary(validation: RestoreValidation, manifest_path: Path) -> None:
    print("PostgreSQL restore validation complete")
    print(f"  tables:   {len(validation.row_counts)}/{len(EXPECTED_ROW_COUNTS)} expected")
    print(f"  rows:     {sum(validation.row_counts.values())}")
    print(f"  manifest: {manifest_path}")


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--work-dir",
        default=None,
        help=(
            "Build directory. Defaults to $BENCHBOX_OUTPUT_DIR/joinorder/build/"
            f"{DATASET_VERSION}, or ~/Developer/benchmark_runs if BENCHBOX_OUTPUT_DIR is unset."
        ),
    )


def add_restore_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--postgres-image", default=DEFAULT_POSTGRES_IMAGE, help="Pinned PostgreSQL image tag.")
    parser.add_argument("--container-name", default=None, help="Optional Docker container name.")
    parser.add_argument("--database", default=DEFAULT_POSTGRES_DB, help="Database created by the Postgres image.")
    parser.add_argument("--user", default=DEFAULT_POSTGRES_USER, help="PostgreSQL superuser inside the container.")
    parser.add_argument(
        "--keep-container",
        action="store_true",
        help="Leave the restored container running for manual inspection. Default tears it down.",
    )
    parser.add_argument(
        "--no-replace-container",
        action="store_true",
        help="Do not remove an existing container with the requested name before starting.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    download = subparsers.add_parser("download-pgdump", help="Download and verify the Dataverse pg_dump.")
    add_common_args(download)
    download.add_argument("--force", action="store_true", help="Re-download even when the pg_dump already exists.")

    restore = subparsers.add_parser(
        "restore-postgres",
        help="Download, restore into PostgreSQL, validate tables/row counts, and tear down.",
    )
    add_common_args(restore)
    restore.add_argument("--force-download", action="store_true", help="Re-download before restoring.")
    add_restore_args(restore)

    w4 = subparsers.add_parser("w4", help="Run the complete w4 download + PostgreSQL restore validation gate.")
    add_common_args(w4)
    w4.add_argument("--force-download", action="store_true", help="Re-download before restoring.")
    add_restore_args(w4)

    return parser


def run_download(args: argparse.Namespace) -> int:
    work_dir = work_dir_from_arg(args.work_dir)
    artifact = download_pgdump(work_dir, force=bool(args.force))
    print_source_summary(artifact, build_manifest_path(work_dir))
    return 0


def run_restore(args: argparse.Namespace) -> int:
    work_dir = work_dir_from_arg(args.work_dir)
    artifact = download_pgdump(work_dir, force=bool(args.force_download))
    print_source_summary(artifact, build_manifest_path(work_dir))
    validation = restore_pgdump(
        artifact,
        work_dir=work_dir,
        postgres_image=args.postgres_image,
        container_name=args.container_name,
        database=args.database,
        user=args.user,
        keep_container=bool(args.keep_container),
        replace_existing=not bool(args.no_replace_container),
    )
    print_restore_summary(validation, build_manifest_path(work_dir))
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "download-pgdump":
            return run_download(args)
        if args.command in {"restore-postgres", "w4"}:
            return run_restore(args)
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        return 130
    except JoinOrderBuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
