"""Shared helpers for adapter tests that exercise resolver-backed CSV dialects."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from benchbox.platforms.base.data_loading import DataSource


def benchmark_stub(
    tables: dict[str, object] | None = None,
    *,
    csv_delimiter: str | None = None,
    csv_has_header: bool | None = None,
    csv_normalize_booleans: bool | None = None,
) -> SimpleNamespace:
    """Return a benchmark stub whose csv_* attributes are explicit, not child Mocks."""
    return SimpleNamespace(
        tables=tables or {},
        csv_delimiter=csv_delimiter,
        csv_has_header=csv_has_header,
        csv_normalize_booleans=csv_normalize_booleans,
    )


def unsafe_plain_mock_benchmark(tables: dict[str, object] | None = None) -> Mock:
    """Return a bare Mock benchmark to prove resolver code ignores Mock-polluted csv_* attrs."""
    mock_benchmark = Mock()
    mock_benchmark.tables = tables or {}
    return mock_benchmark


def resolver_data_source(
    table_name: str,
    file_path: Path,
    table_metadata: dict[str, Any],
    *,
    source_type: str = "manifest_v2",
) -> DataSource:
    """Build a DataSource with manifest-style lowercase CSV dialect metadata."""
    return DataSource(
        source_type=source_type,
        tables={table_name: [file_path]},
        table_metadata={table_name.lower(): table_metadata},
    )
