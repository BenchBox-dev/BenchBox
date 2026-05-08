"""Tests for _project/scripts/scan_explorer_tokens.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_script():
    name = "scan_explorer_tokens"
    path = REPO_ROOT / "_project" / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scan = _load_script()


def test_literal_re_matches_palette_class() -> None:
    matches = scan.LITERAL_RE.findall('<div class="text-gray-700" />')
    assert matches == ["text-gray-700"]


def test_literal_re_skips_token_var() -> None:
    matches = scan.LITERAL_RE.findall('<div class="text-[var(--bb-data-fg-primary)]" />')
    assert matches == []


def test_literal_re_word_boundary_does_not_match_partial() -> None:
    # Embedded inside a larger token must not match.
    assert scan.LITERAL_RE.findall("mytext-gray-700-foo") == []


def test_allow_marker_requires_non_empty_reason() -> None:
    assert scan.ALLOW_MARKER_RE.search("// allow-explorer-token-literal: legacy alias")
    assert scan.ALLOW_MARKER_RE.search("/* allow-explorer-token-literal: x */")
    assert not scan.ALLOW_MARKER_RE.search("// allow-explorer-token-literal:")
    assert not scan.ALLOW_MARKER_RE.search("// allow-explorer-token-literal:   ")


def test_scan_file_reports_unallowlisted_hit(tmp_path: Path) -> None:
    target = tmp_path / "Component.tsx"
    target.write_text('<div class="bg-blue-500" />\n', encoding="utf-8")
    hits = scan.scan_file(target)
    assert len(hits) == 1
    lineno, line, matches = hits[0]
    assert lineno == 1
    assert "bg-blue-500" in matches
    assert "bg-blue-500" in line


def test_scan_file_skips_line_with_allow_marker(tmp_path: Path) -> None:
    target = tmp_path / "Component.tsx"
    target.write_text(
        '<div class="bg-blue-500" /> // allow-explorer-token-literal: third-party skin\n',
        encoding="utf-8",
    )
    assert scan.scan_file(target) == []


def test_main_returns_2_on_missing_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "does-not-exist"
    monkeypatch.setattr(sys, "argv", ["scan_explorer_tokens", str(missing)])
    assert scan.main() == 2
    err = capsys.readouterr().err
    assert "missing path" in err


def test_main_returns_1_on_planted_literal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "Bad.tsx").write_text('<div class="text-red-500" />\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["scan_explorer_tokens", str(src)])
    assert scan.main() == 1
    err = capsys.readouterr().err
    assert "text-red-500" in err
    assert "literal(s) found" in err


def test_main_returns_0_on_clean_tree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / "Good.tsx").write_text('<div class="text-[var(--bb-data-fg-primary)]" />\n', encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["scan_explorer_tokens", str(src)])
    assert scan.main() == 0
