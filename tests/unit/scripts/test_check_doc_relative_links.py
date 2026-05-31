"""Regression tests for scripts/check_doc_relative_links.py."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

import scripts.check_doc_relative_links as checker

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _configure_checker(monkeypatch: pytest.MonkeyPatch, root: Path) -> tuple[Path, Path]:
    docs_dir = root / "docs"
    baseline_path = root / "scripts" / "doc_relative_link_baseline.txt"
    docs_dir.mkdir()
    baseline_path.parent.mkdir()
    monkeypatch.setattr(checker, "REPO_ROOT", root)
    monkeypatch.setattr(checker, "DOCS_DIR", docs_dir)
    monkeypatch.setattr(checker, "BASELINE_PATH", baseline_path)
    monkeypatch.setattr(sys, "argv", ["check_doc_relative_links.py"])
    return docs_dir, baseline_path


def test_duplicate_broken_target_requires_matching_baseline_occurrence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs_dir, baseline_path = _configure_checker(monkeypatch, tmp_path)
    (docs_dir / "example.md").write_text("[old](missing.md)\n[new](missing.md)\n", encoding="utf-8")
    baseline_path.write_text("docs/example.md\tmissing.md\n", encoding="utf-8")

    assert checker.main() == 1

    output = capsys.readouterr().out
    assert "1 NEW broken relative link(s)" in output
    assert "docs/example.md:2 -> missing.md" in output


def test_write_baseline_preserves_duplicate_broken_occurrences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    docs_dir, baseline_path = _configure_checker(monkeypatch, tmp_path)
    (docs_dir / "example.md").write_text("[one](missing.md)\n[two](missing.md)\n", encoding="utf-8")

    assert checker.write_baseline(checker.collect_broken()) == 0

    data_lines = [
        line for line in baseline_path.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")
    ]
    assert data_lines == [
        "docs/example.md\tmissing.md",
        "docs/example.md\tmissing.md",
    ]
