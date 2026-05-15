"""Tests for _project/scripts/scan_explorer_stale_theme.py."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "_project" / "scripts" / "scan_explorer_stale_theme.py"


def _load_script():
    name = "scan_explorer_stale_theme"
    spec = importlib.util.spec_from_file_location(name, SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


scan = _load_script()


def test_stale_patterns_match_retired_phrases() -> None:
    line = "Adopt the dark BenchBox shell + light analytical data panels model."
    matches: list[str] = []
    for pattern in scan.STALE_PATTERNS:
        matches.extend(pattern.findall(line))
    assert "dark BenchBox shell + light analytical data panels" in matches
    assert "light analytical data" in matches


def test_stale_patterns_match_light_data_surface_contract() -> None:
    line = "keeps active matrix controls on the light data surface contract"
    matches: list[str] = []
    for pattern in scan.STALE_PATTERNS:
        matches.extend(pattern.findall(line))
    assert matches == ["light data surface contract"]


def test_stale_patterns_skip_current_language() -> None:
    line = "supports system / light / dark theme contracts"
    matches: list[str] = []
    for pattern in scan.STALE_PATTERNS:
        matches.extend(pattern.findall(line))
    assert matches == []


def test_allow_marker_excludes_line(tmp_path: Path) -> None:
    sample = tmp_path / "results-explorer" / "src" / "sample.tsx"
    sample.parent.mkdir(parents=True)
    sample.write_text(
        "// allow-stale-theme: documenting retired contract\n// dark BenchBox shell + light analytical data panels\n",
        encoding="utf-8",
    )
    hits = scan.scan_file(sample)
    # First line has the allow marker but no pattern; second has the pattern
    # but no allow marker. The marker only excludes the line it appears on.
    assert len(hits) == 1
    assert hits[0][0] == 2


def test_supersession_header_excludes_analysis_file(tmp_path: Path) -> None:
    analysis = tmp_path / "_project" / "analysis" / "historical.md"
    analysis.parent.mkdir(parents=True)
    analysis.write_text(
        "# Historical Analysis\n\n"
        "> Superseded on 2026-05-14 by benchbox-theme-contract.md.\n\n"
        "We chose the dark BenchBox shell + light analytical data panels model.\n",
        encoding="utf-8",
    )
    hits = scan.scan_file(analysis)
    assert hits == []


def test_supersession_header_does_not_apply_outside_analysis(tmp_path: Path) -> None:
    source = tmp_path / "results-explorer" / "src" / "stale.tsx"
    source.parent.mkdir(parents=True)
    source.write_text(
        "// Superseded note in the file header.\n// dark BenchBox shell + light analytical data panels\n",
        encoding="utf-8",
    )
    hits = scan.scan_file(source)
    assert len(hits) == 1


def test_cli_exits_nonzero_on_unallowed_match(tmp_path: Path) -> None:
    sample = tmp_path / "results-explorer" / "src" / "stale.tsx"
    sample.parent.mkdir(parents=True)
    sample.write_text("// light data surface contract\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(sample.parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "stale-theme reference" in result.stderr


def test_cli_exits_zero_on_clean_tree(tmp_path: Path) -> None:
    sample = tmp_path / "results-explorer" / "src" / "clean.tsx"
    sample.parent.mkdir(parents=True)
    sample.write_text("// system / light / dark theme contract\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(sample.parent)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert result.stderr == ""
