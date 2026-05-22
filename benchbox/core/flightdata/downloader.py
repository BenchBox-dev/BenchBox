"""Flight data downloader for BTS On-Time Performance dataset.

Downloads US Bureau of Transportation Statistics (BTS) On-Time Performance
data and converts to the BenchBox flight data schema.

Data source: BTS TranStats On-Time Reporting
https://www.transtats.bts.gov/ontime/

Scale factor mapping (SF=1 ≈ 1GB raw data):
  SF=0.01  1 month    small synthetic/dev sample
  SF=0.1   ~4 months  development-sized sample
  SF=1.0   ~3.4 years ~24M flights    ~1GB
  SF=10    ~410 months ~9.6 GB         near-linear
  SF≥11.12 all 456 months exhausted    ~11.1 GB ceiling

The BTS corpus spans Jan 1987 - Dec 2024 (456 months). Beyond SF≈11.12,
all available months are used and data size caps at ~11.1 GB (456/41 SF-units
× ~1 GB per SF-unit). A warning is logged when this ceiling is reached.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import calendar
import contextlib
import csv
import io
import json
import logging
import random
import shutil
import urllib.error
import urllib.request
import zipfile
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.datagen_manifest import DataGenerationManifest, resolve_compression_metadata
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity

logger = logging.getLogger(__name__)


def _load_downloader_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("downloader_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_DOWNLOADER_SPECS = _load_downloader_specs()
_DATA_COVERAGE = _DOWNLOADER_SPECS["data_coverage"]
_FLIGHT_SHARDS = _DOWNLOADER_SPECS["flight_shards"]

# BTS TranStats On-Time Performance download URL template
# Format: YEAR_MONTH (e.g., 2023_1 for January 2023)
BTS_BASE_URL = _DOWNLOADER_SPECS["bts_base_url"]

# Data coverage
FIRST_AVAILABLE_YEAR = int(_DATA_COVERAGE["first_available_year"])
LAST_AVAILABLE_YEAR = int(_DATA_COVERAGE["last_available_year"])
APPROXIMATE_MONTHLY_FLIGHTS = int(_DATA_COVERAGE["approximate_monthly_flights"])
MONTHS_PER_SCALE_FACTOR = int(_DATA_COVERAGE["months_per_scale_factor"])
FLIGHTS_SHARD_ROW_TARGET = int(_FLIGHT_SHARDS["row_target"])
FLIGHTS_SHARD_DIRNAME = _FLIGHT_SHARDS["dirname"]
FLIGHTS_SHARD_PREFIX = _FLIGHT_SHARDS["prefix"]

# BTS CSV field names (subset used in BenchBox schema)
BTS_FIELD_NAMES = _DOWNLOADER_SPECS["bts_field_names"]


def _scale_to_months(scale_factor: float) -> int:
    """Convert scale factor to number of months of data to download.

    Args:
        scale_factor: BenchBox scale factor

    Returns:
        Number of months of data needed
    """
    # SF=1.0 ≈ 1GB ≈ ~41 months of data (~24M flights / ~600K per month)
    # SF=0.01 ≈ 10MB ≈ 1 week → round up to 1 month for data availability
    months = max(1, round(scale_factor * MONTHS_PER_SCALE_FACTOR))
    max_months = (LAST_AVAILABLE_YEAR - FIRST_AVAILABLE_YEAR + 1) * 12
    if months >= max_months:
        # Ceiling GB ≈ ceiling SF × 1 GB/SF (since SF=1 ≈ 1 GB by calibration).
        ceiling_gb = max_months / MONTHS_PER_SCALE_FACTOR
        logger.warning(
            "FlightData: BTS corpus exhausted at SF=%.1f (all %d months used). "
            "Data size is capped at ~%.1f GB regardless of scale factor.",
            scale_factor,
            max_months,
            ceiling_gb,
        )
    return min(months, max_months)


def _months_sequence(num_months: int, end_year: int = LAST_AVAILABLE_YEAR) -> list[tuple[int, int]]:
    """Generate (year, month) pairs working backwards from end_year.

    Args:
        num_months: Number of months to generate
        end_year: Last year to include (uses December of this year)

    Returns:
        List of (year, month) tuples, most recent first
    """
    result = []
    year, month = end_year, 12
    for _ in range(num_months):
        result.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
        if year < FIRST_AVAILABLE_YEAR:
            break
    return result


class FlightDataDownloader(CompressionMixin, VerbosityMixin):
    """Downloads and processes BTS On-Time Performance flight data.

    Supports downloading real BTS data or generating synthetic data as fallback.
    Uses time-based scale factors: larger SF = more years of historical data.
    """

    def __init__(
        self,
        scale_factor: float,
        output_dir: Path,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_redownload: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialize downloader.

        Args:
            scale_factor: Scale factor controlling data volume
            output_dir: Directory to write output CSV files
            seed: Random seed for synthetic data and sampling
            verbose: Verbosity level
            quiet: Suppress all output
            force_redownload: Re-download even if files exist
        """
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir)
        self.seed = seed if seed is not None else 42
        self.force_redownload = force_redownload
        self.logger = logger
        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self._rng = random.Random(self.seed)
        self._num_months = _scale_to_months(scale_factor)
        self._months = _months_sequence(self._num_months)
        self._stats: dict[str, Any] = {
            "scale_factor": scale_factor,
            "num_months": self._num_months,
            "months_downloaded": 0,
            "months_synthetic": 0,
            "total_flights": 0,
        }
        self._table_row_counts: dict[str, int] = {}
        self._table_file_row_counts: dict[Path, int] = {}

    def download(self) -> dict[str, Path | list[Path]]:
        """Download or generate flight data and reference tables.

        Returns:
            Dictionary mapping table names to local CSV file paths
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        flights_path = self.output_dir / self.get_compressed_filename("flights.csv")
        airlines_path = self.output_dir / self.get_compressed_filename("airlines.csv")
        airports_path = self.output_dir / self.get_compressed_filename("airports.csv")

        # Copy reference data from package
        if not airlines_path.exists() or self.force_redownload:
            self._copy_reference_file("airlines.csv", airlines_path)

        if not airports_path.exists() or self.force_redownload:
            self._copy_reference_file("airports.csv", airports_path)

        if airlines_path.exists() and airlines_path not in self._table_file_row_counts:
            self._record_existing_csv_file("airlines", airlines_path)
        if airports_path.exists() and airports_path not in self._table_file_row_counts:
            self._record_existing_csv_file("airports", airports_path)

        flight_files = self._ensure_flights_data(flights_path)

        table_files = {
            "flights": flight_files,
            "airlines": airlines_path,
            "airports": airports_path,
        }
        if self._table_file_row_counts:
            self._write_manifest(table_files)
        return table_files

    def repair_reusable_layout(self) -> dict[str, Path | list[Path]] | None:
        """Repair a reusable FlightData cache when its source layout is loader-hostile.

        Older SF1 caches used a single large zstd-compressed ``flights.csv.zst``.
        The file can be byte-valid while still failing several native readers.
        Replacing it with manifest-tracked CSV shards keeps the reusable corpus
        deterministic without forcing a network redownload.
        """
        if not self._should_use_sharded_flights():
            return None

        if self._existing_flight_shards():
            return None

        legacy_path = self._find_legacy_single_flights_path()
        if legacy_path is None:
            return None

        self.log_verbose(f"Repairing FlightData cache layout by sharding {legacy_path.name}")
        shard_paths = self._split_existing_flights_file(legacy_path)
        if not shard_paths:
            return None

        airlines_path = self._existing_reference_path("airlines")
        airports_path = self._existing_reference_path("airports")
        if airlines_path is None or airports_path is None:
            return None

        self._record_existing_csv_file("airlines", airlines_path)
        self._record_existing_csv_file("airports", airports_path)
        table_files: dict[str, Path | list[Path]] = {
            "flights": shard_paths,
            "airlines": airlines_path,
            "airports": airports_path,
        }
        self._write_manifest(table_files)

        with contextlib.suppress(OSError):
            legacy_path.unlink()

        return table_files

    def _copy_reference_file(self, filename: str, dest: Path) -> None:
        """Copy a reference data CSV from the package to the output directory."""
        ref_dir = Path(__file__).parent / "reference_data"
        src = ref_dir / filename
        if src.exists():
            row_count = 0
            with src.open(encoding="utf-8") as source, self.open_output_file(dest, "wt") as target:
                for line in source:
                    target.write(line)
                    row_count += 1
            # Subtract 1 for the header row
            table_name = dest.name.split(".")[0]
            self._table_row_counts[table_name] = max(0, row_count - 1)
            self._table_file_row_counts[dest] = max(0, row_count - 1)
            self.log_verbose(f"Copied reference data: {filename}")
        else:
            logger.warning(f"Reference file not found: {src}")

    def _ensure_flights_data(self, flights_path: Path) -> Path | list[Path]:
        """Return the active flights source files, generating or repairing when needed."""
        if self.force_redownload:
            self._remove_flights_outputs(flights_path)

        if self._should_use_sharded_flights():
            shard_paths = self._existing_flight_shards()
            if shard_paths and not self.force_redownload:
                for shard_path in shard_paths:
                    self._record_existing_csv_file("flights", shard_path)
                return shard_paths

            repaired = self.repair_reusable_layout()
            if repaired and isinstance(repaired.get("flights"), list):
                return repaired["flights"]

            return self._generate_flights_shards()

        if not flights_path.exists():
            self._generate_flights_csv(flights_path)
        elif flights_path not in self._table_file_row_counts:
            self._record_existing_csv_file("flights", flights_path)
        return flights_path

    def _should_use_sharded_flights(self) -> bool:
        """Return True when FlightData volume should avoid a single large CSV stream."""
        return self._num_months >= MONTHS_PER_SCALE_FACTOR

    def _remove_flights_outputs(self, flights_path: Path) -> None:
        """Remove stale FlightData fact outputs before force regeneration."""
        with contextlib.suppress(OSError):
            flights_path.unlink()
        for candidate in self.output_dir.glob("flights.csv.*"):
            with contextlib.suppress(OSError):
                candidate.unlink()
        shutil.rmtree(self._flights_shard_dir(), ignore_errors=True)

    def _flights_shard_dir(self) -> Path:
        return self.output_dir / FLIGHTS_SHARD_DIRNAME

    def _existing_flight_shards(self) -> list[Path]:
        shard_dir = self._flights_shard_dir()
        if not shard_dir.is_dir():
            return []
        return sorted(path for path in shard_dir.glob(f"{FLIGHTS_SHARD_PREFIX}*.csv*") if path.is_file())

    def _existing_reference_path(self, table_name: str) -> Path | None:
        for candidate in sorted(self.output_dir.glob(f"{table_name}.csv*")):
            if candidate.is_file():
                return candidate
        return None

    def _find_legacy_single_flights_path(self) -> Path | None:
        manifest_path = self.output_dir / "_datagen_manifest.json"
        if manifest_path.exists():
            with contextlib.suppress(Exception):
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                flights_data = manifest.get("tables", {}).get("flights")
                formats = flights_data.get("formats", {}) if isinstance(flights_data, dict) else {}
                entries = [entry for fmt_entries in formats.values() for entry in (fmt_entries or [])]
                if len(entries) == 1:
                    rel = entries[0].get("path")
                    if rel:
                        path = self.output_dir / rel
                        if path.is_file() and path.name.startswith("flights.csv"):
                            return path

        for candidate in sorted(self.output_dir.glob("flights.csv*")):
            if candidate.is_file():
                return candidate
        return None

    def _generate_flights_csv(self, output_path: Path) -> int:
        """Generate flights CSV by downloading BTS data or using synthetic fallback.

        Args:
            output_path: Path to write the combined flights CSV
        """
        self.log_verbose(f"Generating flight data for {self._num_months} months (SF={self.scale_factor})")

        with self.open_output_file(output_path, "wt") as f:
            writer = csv.writer(f)
            # Write header matching FLIGHT_SCHEMA columns
            writer.writerow(
                [
                    "flight_id",
                    "flight_date",
                    "year",
                    "month",
                    "day_of_month",
                    "day_of_week",
                    "reporting_airline",
                    "flight_number",
                    "origin",
                    "dest",
                    "crs_dep_time",
                    "dep_time",
                    "dep_delay",
                    "crs_arr_time",
                    "arr_time",
                    "arr_delay",
                    "cancelled",
                    "cancellation_code",
                    "diverted",
                    "crs_elapsed_time",
                    "actual_elapsed_time",
                    "air_time",
                    "distance",
                    "carrier_delay",
                    "weather_delay",
                    "nas_delay",
                    "security_delay",
                    "late_aircraft_delay",
                ]
            )

            flight_id = 1
            for year, month in self._months:
                rows_written = self._process_month(writer, year, month, flight_id)
                flight_id += rows_written
                self._stats["total_flights"] += rows_written

        self._table_row_counts["flights"] = self._stats["total_flights"]
        self._table_file_row_counts[output_path] = self._stats["total_flights"]
        self.log_verbose(f"Wrote {self._stats['total_flights']:,} flights to {output_path}")
        return self._stats["total_flights"]

    def _generate_flights_shards(self) -> list[Path]:
        """Generate one deterministic flights CSV shard per source month."""
        self.log_verbose(f"Generating sharded flight data for {self._num_months} months (SF={self.scale_factor})")
        shard_dir = self._flights_shard_dir()
        shutil.rmtree(shard_dir, ignore_errors=True)
        shard_dir.mkdir(parents=True, exist_ok=True)

        shard_paths: list[Path] = []
        flight_id = 1
        for shard_index, (year, month) in enumerate(self._months, start=1):
            shard_name = self.get_compressed_filename(f"{FLIGHTS_SHARD_PREFIX}{shard_index:04d}_{year}_{month:02d}.csv")
            shard_path = shard_dir / shard_name
            rows_written = self._write_flights_shard(shard_path, year, month, flight_id)
            flight_id += rows_written
            self._stats["total_flights"] += rows_written
            self._table_file_row_counts[shard_path] = rows_written
            shard_paths.append(shard_path)

        self._table_row_counts["flights"] = self._stats["total_flights"]
        self.log_verbose(f"Wrote {self._stats['total_flights']:,} flights across {len(shard_paths)} shards")
        return shard_paths

    def _write_flights_shard(self, shard_path: Path, year: int, month: int, flight_id: int) -> int:
        with self.open_output_file(shard_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerow(self._flight_header())
            return self._process_month(writer, year, month, flight_id)

    @staticmethod
    def _flight_header() -> list[str]:
        """Return the CSV header matching FLIGHT_SCHEMA columns."""
        return [
            "flight_id",
            "flight_date",
            "year",
            "month",
            "day_of_month",
            "day_of_week",
            "reporting_airline",
            "flight_number",
            "origin",
            "dest",
            "crs_dep_time",
            "dep_time",
            "dep_delay",
            "crs_arr_time",
            "arr_time",
            "arr_delay",
            "cancelled",
            "cancellation_code",
            "diverted",
            "crs_elapsed_time",
            "actual_elapsed_time",
            "air_time",
            "distance",
            "carrier_delay",
            "weather_delay",
            "nas_delay",
            "security_delay",
            "late_aircraft_delay",
        ]

    def _split_existing_flights_file(self, legacy_path: Path) -> list[Path]:
        """Split an existing single FlightData CSV into loader-friendly shards."""
        staging_dir = self.output_dir / ".flights-shards.tmp"
        final_dir = self._flights_shard_dir()
        shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)

        shard_paths: list[Path] = []
        shard_counts: dict[Path, int] = {}
        shard_index = 0
        rows_in_shard = 0
        target_cm: Any = None
        target_f: Any = None
        writer: csv.writer | None = None

        def close_target() -> None:
            nonlocal target_cm, target_f, writer, rows_in_shard
            if target_cm is not None:
                target_cm.__exit__(None, None, None)
            target_cm = None
            target_f = None
            writer = None
            rows_in_shard = 0

        def open_target(header: list[str]) -> tuple[csv.writer, Path]:
            nonlocal target_cm, target_f, shard_index, rows_in_shard
            shard_index += 1
            shard_name = self.get_compressed_filename(f"{FLIGHTS_SHARD_PREFIX}{shard_index:04d}.csv")
            shard_path = staging_dir / shard_name
            target_cm = self.open_output_file(shard_path, "wt")
            target_f = target_cm.__enter__()
            shard_writer = csv.writer(target_f)
            shard_writer.writerow(header)
            rows_in_shard = 0
            shard_paths.append(shard_path)
            shard_counts[shard_path] = 0
            return shard_writer, shard_path

        try:
            with self._open_existing_csv_for_read(legacy_path) as source:
                reader = csv.reader(source)
                header = next(reader, None)
                if header is None:
                    raise ValueError(f"FlightData source file {legacy_path} is empty")
                self._validate_flights_header(header, legacy_path)
                current_path: Path | None = None
                for line_number, row in enumerate(reader, start=2):
                    self._validate_flight_row_width(row, line_number, legacy_path, len(header))
                    if writer is None or rows_in_shard >= FLIGHTS_SHARD_ROW_TARGET:
                        close_target()
                        writer, current_path = open_target(header)
                    writer.writerow(row)
                    rows_in_shard += 1
                    assert current_path is not None
                    shard_counts[current_path] += 1
                    self._stats["total_flights"] += 1
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise
        finally:
            close_target()

        shutil.rmtree(final_dir, ignore_errors=True)
        staging_dir.replace(final_dir)

        final_paths: list[Path] = []
        final_counts: dict[Path, int] = {}
        for shard_path in shard_paths:
            final_path = final_dir / shard_path.name
            final_paths.append(final_path)
            final_counts[final_path] = shard_counts[shard_path]
            self._table_file_row_counts[final_path] = shard_counts[shard_path]

        self._table_row_counts["flights"] = sum(final_counts.values())
        return final_paths

    def _open_existing_csv_for_read(self, path: Path) -> Any:
        compression_type = self.compression_manager.detect_compression(path)
        compressor = self.compression_manager.get_compressor(compression_type)
        return compressor.open_for_read(path, "rt")

    def _record_existing_csv_file(self, table_name: str, path: Path) -> None:
        if path in self._table_file_row_counts:
            return
        row_count = self._count_flight_csv_rows(path) if table_name == "flights" else self._count_csv_rows(path)
        self._table_row_counts[table_name] = self._table_row_counts.get(table_name, 0) + row_count
        self._table_file_row_counts[path] = row_count

    def _count_csv_rows(self, path: Path) -> int:
        with self._open_existing_csv_for_read(path) as f:
            return max(0, sum(1 for _ in f) - 1)

    def _count_flight_csv_rows(self, path: Path) -> int:
        with self._open_existing_csv_for_read(path) as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                raise ValueError(f"FlightData source file {path} is empty")
            self._validate_flights_header(header, path)
            row_count = 0
            for line_number, row in enumerate(reader, start=2):
                self._validate_flight_row_width(row, line_number, path, len(header))
                row_count += 1
            return row_count

    def _validate_flights_header(self, header: list[str], path: Path) -> None:
        expected = self._flight_header()
        if header != expected:
            raise ValueError(
                f"FlightData source file {path} has invalid header: expected {len(expected)} columns "
                f"{expected!r}, found {len(header)} columns {header!r}"
            )

    @staticmethod
    def _validate_flight_row_width(row: list[str], line_number: int, path: Path, expected_columns: int) -> None:
        if len(row) != expected_columns:
            raise ValueError(
                f"FlightData source file {path} row {line_number} has {len(row)} columns; expected {expected_columns}"
            )

    def _write_manifest(self, table_files: dict[str, Path | list[Path]]) -> None:
        manifest = DataGenerationManifest(
            output_dir=self.output_dir,
            benchmark="flightdata",
            scale_factor=self.scale_factor,
            compression=resolve_compression_metadata(self),
            parallel=1,
            seed=self.seed,
            formats=["csv"],
        )
        metadata = {
            "csv_delimiter": ",",
            "csv_has_header": True,
            "csv_null_marker": None,
        }
        for table_name, paths_or_path in table_files.items():
            paths = paths_or_path if isinstance(paths_or_path, list) else [paths_or_path]
            for path in paths:
                manifest.add_entry(
                    table_name,
                    path,
                    row_count=self._table_file_row_counts.get(path, 0),
                    format="csv",
                    metadata=metadata,
                )
        manifest.write()

    def _process_month(self, writer: csv.writer, year: int, month: int, start_id: int) -> int:
        """Attempt to download BTS data for one month, fall back to synthetic.

        Args:
            writer: CSV writer to write rows to
            year: Year of data
            month: Month of data (1-12)
            start_id: Starting flight_id for this batch

        Returns:
            Number of rows written
        """
        # For small scale factors (SF < 0.1), always use synthetic to avoid
        # network calls in CI/testing. Users wanting real data should use SF >= 0.1.
        if self.scale_factor < 0.1:
            return self._generate_synthetic_month(writer, year, month, start_id)

        url = BTS_BASE_URL.format(year=year, month=month)
        try:
            rows = self._download_bts_month(writer, url, year, month, start_id)
            self._stats["months_downloaded"] += 1
            return rows
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, zipfile.BadZipFile) as e:
            logger.warning(f"BTS download failed for {year}-{month:02d}: {e}. Using synthetic data.")
            rows = self._generate_synthetic_month(writer, year, month, start_id)
            self._stats["months_synthetic"] += 1
            return rows

    def _download_bts_month(self, writer: csv.writer, url: str, year: int, month: int, start_id: int) -> int:
        """Download one month of BTS data and write to CSV.

        Args:
            writer: CSV writer
            url: BTS download URL
            year: Data year
            month: Data month
            start_id: Starting flight_id

        Returns:
            Number of rows written
        """
        self.log_verbose(f"  Downloading BTS data: {year}-{month:02d}")

        req = urllib.request.Request(
            url, headers={"User-Agent": "BenchBox/1.0 (https://github.com/joeharris76/BenchBox)"}
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            zip_bytes = response.read()

        rows_written = 0
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # Find the CSV file inside the ZIP
            csv_names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
            if not csv_names:
                raise ValueError(f"No CSV found in ZIP from {url}")

            with zf.open(csv_names[0]) as csv_file:
                reader = csv.DictReader(io.TextIOWrapper(csv_file, encoding="utf-8"))

                for bts_row in reader:
                    row = self._transform_bts_row(bts_row, start_id + rows_written)
                    if row is not None:
                        writer.writerow(row)
                        rows_written += 1

        return rows_written

    def _transform_bts_row(self, bts: dict[str, str], flight_id: int) -> list[Any] | None:
        """Transform a BTS CSV row to the BenchBox schema.

        Args:
            bts: Dictionary of BTS field names to values
            flight_id: Synthetic ID to assign

        Returns:
            List of values matching FLIGHT_SCHEMA columns, or None to skip row
        """

        def _float_or_null(val: str) -> str:
            """Return val as float string or empty string for NULL."""
            v = val.strip()
            if v in ("", ".", "NA", "N/A"):
                return ""
            try:
                return str(float(v))
            except ValueError:
                return ""

        def _int_or_null(val: str) -> str:
            v = val.strip()
            if v in ("", ".", "NA", "N/A"):
                return ""
            try:
                return str(int(float(v)))
            except ValueError:
                return ""

        flight_date = bts.get("FlightDate", "").strip()
        if not flight_date:
            return None

        cancelled = _int_or_null(bts.get("Cancelled", "0")) or "0"

        return [
            flight_id,
            flight_date,
            _int_or_null(bts.get("Year", "")),
            _int_or_null(bts.get("Month", "")),
            _int_or_null(bts.get("DayofMonth", "")),
            _int_or_null(bts.get("DayOfWeek", "")),
            bts.get("Reporting_Airline", "").strip(),
            _int_or_null(bts.get("Flight_Number_Reporting_Airline", "")),
            bts.get("Origin", "").strip(),
            bts.get("Dest", "").strip(),
            _int_or_null(bts.get("CRSDepTime", "")),
            _float_or_null(bts.get("DepTime", "")),
            _float_or_null(bts.get("DepDelay", "")),
            _int_or_null(bts.get("CRSArrTime", "")),
            _float_or_null(bts.get("ArrTime", "")),
            _float_or_null(bts.get("ArrDelay", "")),
            cancelled,
            bts.get("CancellationCode", "").strip(),
            _int_or_null(bts.get("Diverted", "0")) or "0",
            _float_or_null(bts.get("CRSElapsedTime", "")),
            _float_or_null(bts.get("ActualElapsedTime", "")),
            _float_or_null(bts.get("AirTime", "")),
            _float_or_null(bts.get("Distance", "")),
            _float_or_null(bts.get("CarrierDelay", "")),
            _float_or_null(bts.get("WeatherDelay", "")),
            _float_or_null(bts.get("NASDelay", "")),
            _float_or_null(bts.get("SecurityDelay", "")),
            _float_or_null(bts.get("LateAircraftDelay", "")),
        ]

    def _generate_synthetic_month(self, writer: csv.writer, year: int, month: int, start_id: int) -> int:
        """Generate realistic synthetic flight data for one month.

        Args:
            writer: CSV writer
            year: Year to generate data for
            month: Month to generate data for (1-12)
            start_id: Starting flight_id

        Returns:
            Number of rows written
        """
        rng = self._rng

        # Major routes and carriers
        carriers = ["AA", "DL", "UA", "WN", "B6", "AS", "NK", "F9", "HA", "OO"]
        airports = [
            "ATL",
            "LAX",
            "ORD",
            "DFW",
            "DEN",
            "JFK",
            "SFO",
            "SEA",
            "LAS",
            "MCO",
            "EWR",
            "PHX",
            "IAH",
            "MIA",
            "BOS",
            "MSP",
            "DTW",
            "FLL",
            "PHL",
            "LGA",
            "BWI",
            "SLC",
            "CLT",
            "IAD",
            "DCA",
            "MDW",
            "TPA",
            "PDX",
            "SAN",
            "AUS",
        ]

        # Typical distances (miles) between airport pairs
        route_distances = {
            ("ATL", "LAX"): 1946,
            ("ATL", "ORD"): 587,
            ("ATL", "DFW"): 731,
            ("LAX", "SFO"): 337,
            ("LAX", "SEA"): 954,
            ("LAX", "LAS"): 236,
            ("ORD", "JFK"): 740,
            ("ORD", "DFW"): 802,
            ("DFW", "LAX"): 1235,
            ("JFK", "LAX"): 2475,
            ("JFK", "MIA"): 1090,
            ("SFO", "SEA"): 679,
            ("DEN", "LAX"): 862,
            ("DEN", "ORD"): 888,
            ("PHX", "LAX"): 370,
        }

        _, days_in_month = calendar.monthrange(year, month)

        # Adjust flight volume for year (COVID dip in 2020)
        if year == 2020:
            daily_flights = rng.randint(5000, 12000)
        elif year == 2021:
            daily_flights = rng.randint(12000, 18000)
        else:
            daily_flights = rng.randint(18000, 25000)

        # Precompute per-origin destination lists to avoid O(n) list creation per flight
        dest_by_origin = {a: [b for b in airports if b != a] for a in airports}

        rows_written = 0

        for day in range(1, days_in_month + 1):
            flight_date = date(year, month, day)
            day_of_week = flight_date.weekday() + 1  # 1=Monday, 7=Sunday
            # Weekday adjustment (weekends slightly lower)
            day_count = int(daily_flights * (0.85 if day_of_week >= 6 else 1.0))

            for _ in range(day_count):
                carrier = rng.choice(carriers)
                origin = rng.choice(airports)
                dest = rng.choice(dest_by_origin[origin])

                # Look up or estimate distance
                dist = route_distances.get((origin, dest), route_distances.get((dest, origin), rng.randint(200, 2500)))

                # Scheduled times (HHMM format)
                dep_hour = rng.randint(5, 22)
                dep_min = rng.choice([0, 15, 30, 45])
                crs_dep = dep_hour * 100 + dep_min

                # Estimated flight duration (minutes): ~1hr for 500mi, +45min per 500mi
                crs_elapsed = max(60, int(60 + (dist / 500.0) * 45))
                arr_total_min = dep_hour * 60 + dep_min + crs_elapsed
                crs_arr = (arr_total_min // 60 % 24) * 100 + (arr_total_min % 60)

                # Cancellation (~2% rate, higher in winter months for weather)
                cancel_prob = 0.03 if month in (1, 2, 12) else 0.015
                cancelled = 1 if rng.random() < cancel_prob else 0

                if cancelled:
                    cancel_codes = ["A", "A", "B", "B", "C", "D"]
                    cancellation_code = rng.choice(cancel_codes)
                    dep_time = arr_time = dep_delay = arr_delay = ""
                    actual_elapsed = air_time = ""
                    carrier_delay = weather_delay = nas_delay = sec_delay = late_delay = ""
                    diverted = 0
                else:
                    cancellation_code = ""
                    # Departure delay: mostly on-time, some delayed
                    delay_prob = 0.22  # 22% of flights delayed
                    if rng.random() < delay_prob:
                        dep_delay_min = rng.expovariate(1 / 25)  # Exponential dist, mean ~25min
                        dep_delay_min = min(dep_delay_min, 300)
                    else:
                        # Early or minimal delay
                        dep_delay_min = rng.uniform(-10, 15)

                    dep_delay_min = round(dep_delay_min, 1)

                    # Actual departure time
                    actual_dep_min = dep_hour * 60 + dep_min + dep_delay_min
                    dep_time = (int(actual_dep_min // 60) % 24) * 100 + round(actual_dep_min % 60)

                    # Arrival: some delay recovery in flight
                    recovery = rng.uniform(0, min(abs(dep_delay_min) * 0.3, 15))
                    arr_delay_min = round(dep_delay_min - recovery, 1)

                    actual_arr_min = arr_total_min + arr_delay_min
                    arr_time = (int(actual_arr_min // 60) % 24) * 100 + round(actual_arr_min % 60)

                    actual_elapsed = crs_elapsed + arr_delay_min - dep_delay_min + recovery
                    air_time = actual_elapsed * 0.85  # ~85% of elapsed is airborne

                    dep_delay = dep_delay_min
                    arr_delay = arr_delay_min
                    diverted = 1 if rng.random() < 0.003 else 0

                    # Delay attribution (when late)
                    # Assign to categories ensuring sum equals arr_delay_min
                    if arr_delay_min > 15:
                        remaining = arr_delay_min
                        carrier_delay = round(remaining * rng.uniform(0, 0.5), 1)
                        remaining -= carrier_delay
                        weather_delay = round(remaining * rng.uniform(0, 0.4), 1)
                        remaining -= weather_delay
                        nas_delay = round(remaining * rng.uniform(0, 0.4), 1)
                        remaining -= nas_delay
                        sec_delay = round(remaining * rng.uniform(0, 0.05), 1)
                        # Assign all remaining to late_aircraft so components sum to total
                        late_delay = round(arr_delay_min - carrier_delay - weather_delay - nas_delay - sec_delay, 1)
                    else:
                        carrier_delay = weather_delay = nas_delay = sec_delay = late_delay = ""

                writer.writerow(
                    [
                        start_id + rows_written,
                        flight_date.isoformat(),
                        year,
                        month,
                        day,
                        day_of_week,
                        carrier,
                        rng.randint(1, 9999),
                        origin,
                        dest,
                        crs_dep,
                        dep_time if dep_time != "" else "",
                        dep_delay if dep_delay != "" else "",
                        crs_arr,
                        arr_time if arr_time != "" else "",
                        arr_delay if arr_delay != "" else "",
                        cancelled,
                        cancellation_code,
                        diverted,
                        crs_elapsed,
                        round(actual_elapsed, 1) if actual_elapsed != "" else "",
                        round(air_time, 1) if air_time != "" else "",
                        dist,
                        carrier_delay,
                        weather_delay,
                        nas_delay,
                        sec_delay,
                        late_delay,
                    ]
                )
                rows_written += 1

        return rows_written

    @property
    def months(self) -> list[tuple[int, int]]:
        """Get the (year, month) pairs this downloader will process.

        Returns:
            List of (year, month) tuples, most recent first
        """
        return self._months

    @property
    def num_months(self) -> int:
        """Get the number of months of data to process."""
        return self._num_months

    def get_download_stats(self) -> dict[str, Any]:
        """Return statistics about the download operation."""
        return dict(self._stats)
