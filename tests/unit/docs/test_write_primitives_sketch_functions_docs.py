"""Focused guardrails for write-primitives sketch function documentation."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_clickhouse_local_reproduction_uses_chdb_install_path() -> None:
    """The docs must match the registered clickhouse-local dependency contract."""

    doc = (REPO_ROOT / "docs" / "benchmarks" / "write-primitives-sketch-functions.md").read_text(encoding="utf-8")

    assert "uv add benchbox --extra clickhouse-local" in doc
    assert "uv add chdb" in doc
    assert "brew install clickhouse" not in doc
    assert "Homebrew / DEB / RPM ClickHouse package" not in doc
