"""Data Vault row count validation utilities.

Provides validation of Data Vault table row counts against expected values
based on TPC-H scale factor specifications.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


def _load_validation_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("validation_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_VALIDATION_SPECS = _load_validation_specs()

# TPC-H base row counts at SF=1 (from TPC-H specification)
TPCH_BASE_COUNTS = dict(_VALIDATION_SPECS["tpch_base_counts"])


# Data Vault expected row counts relative to TPC-H
# Format: (source_table, multiplier) or fixed count
# Hubs have same count as source (1:1 with business key)
# Links have same count as source relationship table
# Satellites have same count as their parent hub/link
DATAVAULT_ROW_EXPECTATIONS = {
    table: tuple(expectation) for table, expectation in _VALIDATION_SPECS["datavault_row_expectations"].items()
}


@dataclass
class ValidationResult:
    """Result of validating a single table's row count."""

    table_name: str
    actual_count: int
    expected_count: int
    tolerance_pct: float = 1.0  # Allow 1% variance for lineitem approximation
    is_valid: bool = field(init=False)
    variance_pct: float = field(init=False)

    def __post_init__(self) -> None:
        """Calculate validation status."""
        if self.expected_count == 0:
            self.variance_pct = 0.0 if self.actual_count == 0 else 100.0
        else:
            self.variance_pct = abs(self.actual_count - self.expected_count) / self.expected_count * 100

        self.is_valid = self.variance_pct <= self.tolerance_pct


@dataclass
class DataVaultValidationReport:
    """Complete validation report for a Data Vault dataset."""

    scale_factor: float
    results: list[ValidationResult]
    tables_validated: int = field(init=False)
    tables_passed: int = field(init=False)
    tables_failed: int = field(init=False)
    is_valid: bool = field(init=False)

    def __post_init__(self) -> None:
        """Calculate summary statistics."""
        self.tables_validated = len(self.results)
        self.tables_passed = sum(1 for r in self.results if r.is_valid)
        self.tables_failed = self.tables_validated - self.tables_passed
        self.is_valid = self.tables_failed == 0

    def to_dict(self) -> dict:
        """Convert report to dictionary for serialization."""
        return {
            "scale_factor": self.scale_factor,
            "is_valid": self.is_valid,
            "summary": {
                "tables_validated": self.tables_validated,
                "tables_passed": self.tables_passed,
                "tables_failed": self.tables_failed,
            },
            "results": [
                {
                    "table": r.table_name,
                    "actual": r.actual_count,
                    "expected": r.expected_count,
                    "variance_pct": round(r.variance_pct, 2),
                    "is_valid": r.is_valid,
                }
                for r in self.results
            ],
        }

    def __str__(self) -> str:
        """Human-readable report summary."""
        lines = [
            f"Data Vault Validation Report (SF={self.scale_factor})",
            f"{'=' * 50}",
            f"Status: {'PASSED' if self.is_valid else 'FAILED'}",
            f"Tables: {self.tables_passed}/{self.tables_validated} passed",
            "",
        ]

        if self.tables_failed > 0:
            lines.append("Failed Tables:")
            for r in self.results:
                if not r.is_valid:
                    lines.append(
                        f"  - {r.table_name}: {r.actual_count:,} rows "
                        f"(expected {r.expected_count:,}, variance {r.variance_pct:.1f}%)"
                    )

        return "\n".join(lines)


def get_expected_row_count(table_name: str, scale_factor: float) -> int:
    """Calculate expected row count for a Data Vault table.

    Args:
        table_name: Name of the Data Vault table (e.g., 'hub_customer')
        scale_factor: TPC-H scale factor

    Returns:
        Expected row count for the table

    Raises:
        ValueError: If table_name is not a known Data Vault table
    """
    table_lower = table_name.lower()

    if table_lower not in DATAVAULT_ROW_EXPECTATIONS:
        raise ValueError(f"Unknown Data Vault table: {table_name}")

    source_table, multiplier = DATAVAULT_ROW_EXPECTATIONS[table_lower]
    base_count = TPCH_BASE_COUNTS[source_table]

    # Scale the count based on scale factor
    # Some tables scale linearly, others are fixed
    if source_table in ("region", "nation"):
        # Region and nation are fixed counts
        return int(base_count * multiplier)
    else:
        # Other tables scale with SF
        return int(base_count * scale_factor * multiplier)


def count_rows_in_file(file_path: Path, delimiter: str = "|") -> int:
    """Count rows in a delimited file.

    Args:
        file_path: Path to the data file
        delimiter: Field delimiter (default: pipe for TPC-H format)

    Returns:
        Number of data rows in the file
    """
    count = 0
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            # Skip empty lines
            if line.strip():
                count += 1
    return count


def get_row_counts_from_manifest(manifest_path: Path) -> dict[str, int]:
    """Extract row counts from a datagen manifest file.

    Args:
        manifest_path: Path to _datagen_manifest.json

    Returns:
        Dictionary mapping table names to row counts
    """
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    counts = {}
    tables = manifest.get("tables", {})

    for table_name, table_info in tables.items():
        formats = table_info.get("formats", {})
        # Use first available format
        for fmt_info in formats.values():
            if fmt_info and len(fmt_info) > 0:
                counts[table_name] = fmt_info[0].get("row_count", 0)
                break

    return counts


def get_row_counts_from_directory(
    data_dir: Path,
    file_extension: str = "tbl",
) -> dict[str, int]:
    """Count rows in all data files in a directory.

    Args:
        data_dir: Directory containing data files
        file_extension: File extension to look for

    Returns:
        Dictionary mapping table names to row counts
    """
    counts = {}

    for file_path in data_dir.glob(f"*.{file_extension}"):
        table_name = file_path.stem.lower()
        counts[table_name] = count_rows_in_file(file_path)

    return counts


def validate_row_counts(
    data_dir: Path,
    scale_factor: float,
    use_manifest: bool = True,
    tolerance_pct: float = 1.0,
) -> DataVaultValidationReport:
    """Validate Data Vault table row counts against expected values.

    Args:
        data_dir: Directory containing Data Vault data files
        scale_factor: TPC-H scale factor used for generation
        use_manifest: If True, use manifest for counts; otherwise count files
        tolerance_pct: Allowed variance percentage (default 1% for lineitem)

    Returns:
        DataVaultValidationReport with validation results
    """
    manifest_path = data_dir / "_datagen_manifest.json"

    # Get actual row counts
    if use_manifest and manifest_path.exists():
        logger.info("Reading row counts from manifest")
        actual_counts = get_row_counts_from_manifest(manifest_path)
    else:
        logger.info("Counting rows from data files")
        actual_counts = get_row_counts_from_directory(data_dir)

    # Validate each known Data Vault table
    results = []
    for table_name in DATAVAULT_ROW_EXPECTATIONS:
        actual = actual_counts.get(table_name, 0)
        expected = get_expected_row_count(table_name, scale_factor)

        # Use higher tolerance for lineitem-derived tables
        tol = tolerance_pct
        if "lineitem" in table_name:
            tol = max(tolerance_pct, 1.0)  # At least 1% for lineitem variance

        results.append(
            ValidationResult(
                table_name=table_name,
                actual_count=actual,
                expected_count=expected,
                tolerance_pct=tol,
            )
        )

    return DataVaultValidationReport(scale_factor=scale_factor, results=results)


def validate_referential_integrity(
    data_dir: Path,
    use_manifest: bool = True,
) -> dict[str, bool]:
    """Validate referential integrity between Data Vault tables.

    Checks that:
    - Link tables don't reference non-existent hub keys
    - Satellite tables don't reference non-existent hub/link keys

    Args:
        data_dir: Directory containing Data Vault data files
        use_manifest: If True, use manifest for validation hints

    Returns:
        Dictionary mapping relationship names to validity status

    Note:
        This is a structural check based on row counts. For full RI validation,
        load the data into a database with FK constraints enabled.
    """
    manifest_path = data_dir / "_datagen_manifest.json"

    if use_manifest and manifest_path.exists():
        counts = get_row_counts_from_manifest(manifest_path)
    else:
        counts = get_row_counts_from_directory(data_dir)

    integrity_checks = {}

    # Check that satellites have same count as their parent hub
    hub_sat_pairs = [
        ("hub_region", "sat_region"),
        ("hub_nation", "sat_nation"),
        ("hub_customer", "sat_customer"),
        ("hub_supplier", "sat_supplier"),
        ("hub_part", "sat_part"),
        ("hub_order", "sat_order"),
        ("hub_lineitem", "sat_lineitem"),
    ]

    for hub, sat in hub_sat_pairs:
        hub_count = counts.get(hub, 0)
        sat_count = counts.get(sat, 0)
        # For initial load, satellite should have exactly same count as hub
        integrity_checks[f"{sat}→{hub}"] = hub_count == sat_count

    # Check link->hub relationships (links should not exceed source counts)
    link_checks = [
        ("link_nation_region", "hub_nation"),
        ("link_customer_nation", "hub_customer"),
        ("link_supplier_nation", "hub_supplier"),
        ("link_part_supplier", "hub_part"),  # Should be >= hub_part (many suppliers per part)
        ("link_order_customer", "hub_order"),
        ("link_lineitem", "hub_lineitem"),
    ]

    for link, hub in link_checks:
        link_count = counts.get(link, 0)
        hub_count = counts.get(hub, 0)
        # Link should have at least as many rows as hub (or equal for 1:1)
        integrity_checks[f"{link}→{hub}"] = link_count >= hub_count or link_count == 0

    return integrity_checks
