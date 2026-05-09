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


def test_literal_re_does_not_match_unsupported_stop() -> None:
    # 7000 is not a Tailwind stop. The regex tries `700` against `7000`,
    # but the trailing `\b` between `0` and `0` fails (both word chars),
    # so no match. Same for stops outside the 50/100/200/.../950 set.
    assert scan.LITERAL_RE.findall('<div class="text-gray-7000" />') == []
    assert scan.LITERAL_RE.findall('<div class="text-gray-75" />') == []
    assert scan.LITERAL_RE.findall('<div class="text-gray-1000" />') == []


def test_literal_re_is_case_sensitive() -> None:
    # Tailwind utilities are lowercase. Capital-cased near-misses (e.g.
    # custom design-system classes) must not trip the gate. Re-confirm
    # case sensitivity so a future "case-insensitive for robustness"
    # change is a deliberate decision, not an accident.
    assert scan.LITERAL_RE.findall('<div class="Text-gray-700" />') == []
    assert scan.LITERAL_RE.findall('<div class="text-Gray-700" />') == []
    assert scan.LITERAL_RE.findall('<div class="TEXT-GRAY-700" />') == []


def test_literal_re_matches_inside_comments_and_strings_by_design() -> None:
    # Documents the gate's known conservatism: the regex matches the
    # literal whether it appears in a className, a comment, a JSDoc, a
    # string literal, or a URL fragment. The allow-marker
    # (`// allow-explorer-token-literal: <reason>`) is the escape hatch
    # for any legitimate non-className use. Future readers tempted to
    # narrow the regex (e.g. only match inside class= attributes)
    # should weigh that change against this contract.
    assert scan.LITERAL_RE.findall("// avoid using text-gray-700 in new code") == ["text-gray-700"]
    assert scan.LITERAL_RE.findall('const docsUrl = "/docs/text-gray-700.md";') == ["text-gray-700"]
    assert scan.LITERAL_RE.findall("/* JSDoc: bg-blue-500 example */") == ["bg-blue-500"]


def test_literal_re_matches_when_followed_by_dash_word() -> None:
    # `text-gray-700-typography` contains the literal `text-gray-700` with
    # a word boundary between the trailing `0` and the next `-`. The gate
    # matches; the operational answer for legitimate uses is the
    # allow-marker. This test pins the behavior so a future "extend the
    # boundary check" change is deliberate rather than accidental.
    assert scan.LITERAL_RE.findall('<div class="text-gray-700-typography" />') == ["text-gray-700"]


def test_scan_file_reports_every_match_on_a_line(tmp_path: Path) -> None:
    # Tailwind classes are typically space-joined inside a single string,
    # so multiple literals can share a line. `scan_file` must surface all
    # of them in one hit tuple so a contributor debugging "what does the
    # gate want me to fix?" sees the full set, not just the first.
    target = tmp_path / "Component.tsx"
    target.write_text(
        '<div class="text-gray-700 bg-blue-500 border-red-300" />\n',
        encoding="utf-8",
    )
    hits = scan.scan_file(target)
    assert len(hits) == 1
    lineno, line, matches = hits[0]
    assert lineno == 1
    assert matches == ["text-gray-700", "bg-blue-500", "border-red-300"]
    assert "text-gray-700" in line
    assert "bg-blue-500" in line
    assert "border-red-300" in line


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
