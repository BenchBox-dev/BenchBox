"""Fail-closed result checks for ClickHouse server certification artifacts.

The UAT runner records loaded rows per table in its result JSON and the data
generator records expected rows per file in ``_datagen_manifest``. Certification
compares those independently-produced records exactly; an aggregate total can
hide a table-level omission or duplication.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class CertificationArtifactError(ValueError):
    """Raised when a certification artifact cannot support an exact-row gate."""


@dataclass(frozen=True)
class ExactRowValidation:
    """Per-table manifest/result comparison."""

    expected: dict[str, int]
    actual: dict[str, int]

    @property
    def mismatches(self) -> dict[str, tuple[int | None, int | None]]:
        """Return every missing, extra, or differently-sized table."""
        mismatches: dict[str, tuple[int | None, int | None]] = {}
        for table in sorted(set(self.expected) | set(self.actual)):
            expected = self.expected.get(table)
            actual = self.actual.get(table)
            if expected != actual:
                mismatches[table] = (expected, actual)
        return mismatches

    @property
    def passed(self) -> bool:
        """Whether every manifest table has exactly its recorded result count."""
        return not self.mismatches

    def require_pass(self) -> None:
        """Raise with table-level diagnostics when exact row accounting fails."""
        if self.passed:
            return
        details = ", ".join(
            f"{table}: expected={expected!r} actual={actual!r}" for table, (expected, actual) in self.mismatches.items()
        )
        raise CertificationArtifactError(f"exact manifest row gate failed: {details}")


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CertificationArtifactError(f"could not read JSON artifact {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise CertificationArtifactError(f"JSON artifact {path} must contain an object")
    return payload


def _non_negative_count(value: Any, *, path: Path, table: str, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise CertificationArtifactError(f"{path}: {table}.{field} must be a non-negative integer")
    return value


def manifest_table_rows(path: Path) -> dict[str, int]:
    """Aggregate the selected manifest format into exact table row counts."""
    payload = _read_json(path)
    tables = payload.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise CertificationArtifactError(f"{path}: manifest has no tables")
    expected: dict[str, int] = {}
    for raw_table, raw_formats in tables.items():
        table = str(raw_table).strip().lower()
        if not table or not isinstance(raw_formats, dict):
            raise CertificationArtifactError(f"{path}: invalid manifest table {raw_table!r}")
        format_block = raw_formats.get("formats", raw_formats)
        if not isinstance(format_block, dict):
            raise CertificationArtifactError(f"{path}: {table} has invalid format data")
        preferred = payload.get("format_preference")
        formats = list(preferred) if isinstance(preferred, list) else []
        formats.extend(name for name in format_block if name not in formats)
        selected_entries: list[Any] | None = None
        for format_name in formats:
            candidate = format_block.get(format_name)
            if isinstance(candidate, list) and candidate:
                selected_entries = candidate
                break
        if selected_entries is None:
            raise CertificationArtifactError(f"{path}: {table} has no usable manifest entries")
        total = 0
        for index, entry in enumerate(selected_entries):
            if not isinstance(entry, dict) or "row_count" not in entry:
                raise CertificationArtifactError(f"{path}: {table} entry {index} lacks row_count")
            total += _non_negative_count(entry["row_count"], path=path, table=table, field="row_count")
        expected[table] = total
    return expected


def result_table_rows(path: Path) -> dict[str, int]:
    """Read per-table loaded rows from a benchmark result artifact."""
    payload = _read_json(path)
    tables = payload.get("tables")
    if not isinstance(tables, dict) or not tables:
        raise CertificationArtifactError(f"{path}: result has no per-table counts")
    actual: dict[str, int] = {}
    for raw_table, raw_stats in tables.items():
        table = str(raw_table).strip().lower()
        if not table or not isinstance(raw_stats, dict) or "rows" not in raw_stats:
            raise CertificationArtifactError(f"{path}: {table or raw_table!r} lacks a table row count")
        actual[table] = _non_negative_count(raw_stats["rows"], path=path, table=table, field="rows")
    return actual


def validate_exact_manifest_rows(manifest_path: Path, result_path: Path) -> ExactRowValidation:
    """Compare manifest and result counts without accepting aggregate-only proof."""
    validation = ExactRowValidation(
        expected=manifest_table_rows(Path(manifest_path)),
        actual=result_table_rows(Path(result_path)),
    )
    validation.require_pass()
    return validation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        validation = validate_exact_manifest_rows(args.manifest, args.result)
    except CertificationArtifactError as exc:
        print(f"FAIL {exc}", file=sys.stderr)
        return 2
    print(f"PASS exact manifest rows for {len(validation.expected)} tables")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised by the operator gate
    raise SystemExit(main())
