"""Static checks for the shared public-site theme contract."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[2]

if not (ROOT / "_project").exists() or not (ROOT / "results-explorer").exists():
    pytest.skip("public site theme contract requires _project/ and results-explorer/", allow_module_level=True)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _load_token_scan():
    name = "scan_explorer_tokens_public_site_contract"
    path = ROOT / "_project" / "scripts" / "scan_explorer_tokens.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _css_block(css: str, selector: str) -> str:
    start = css.index(selector)
    brace = css.index("{", start)
    depth = 0
    for index in range(brace, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return css[brace + 1 : index]
    raise AssertionError(f"unterminated CSS block for {selector}")


def _variables(css: str, selector: str) -> dict[str, str]:
    block = _css_block(css, selector)
    return dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", block))


def _relative_luminance(hex_color: str) -> float:
    raw = hex_color.removeprefix("#")
    channels = [int(raw[index : index + 2], 16) / 255 for index in (0, 2, 4)]
    linear = [channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted([_relative_luminance(foreground), _relative_luminance(background)], reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


@pytest.mark.parametrize(
    "path",
    [
        "landing/index.html",
        "landing/prompts/index.html",
        "docs/_templates/page.html",
        "results-explorer/index.html",
    ],
)
def test_early_theme_bootstrap_normalizes_stored_choice(path: str) -> None:
    source = _read(path)

    assert 'localStorage.getItem("benchbox:theme")' in source
    assert 'stored === "light" || stored === "dark" || stored === "system" ? stored : "system"' in source
    assert "document.documentElement.dataset.bbThemeChoice = choice" in source


def test_shared_theme_script_normalizes_public_api_inputs() -> None:
    source = _read("landing/shared/site-theme.js")

    assert "function normalizeChoice(value)" in source
    assert "choice = normalizeChoice(choice)" in source
    assert "return normalizeChoice(window.localStorage.getItem(storageKey))" in source


def test_public_site_token_scan_covers_landing_shell_css() -> None:
    makefile = _read("Makefile")
    scan = _load_token_scan()

    assert "landing/style.css" in makefile
    assert scan.scan_file(ROOT / "landing" / "style.css") == []


def test_results_dark_chart_palette_has_panel_contrast() -> None:
    css = _read("results-explorer/src/index.css")
    light = _variables(css, ":root")
    dark = _variables(css, ':root[data-bb-theme="dark"]')

    chart_tokens = [
        "bb-chart-cat-1",
        "bb-chart-cat-2",
        "bb-chart-cat-3",
        "bb-chart-cat-4",
        "bb-chart-cat-5",
        "bb-chart-cat-6",
        "bb-chart-success",
        "bb-chart-warning",
        "bb-chart-danger",
    ]
    for token in chart_tokens:
        assert token in light, f"light chart token missing: {token}"
        assert token in dark, f"dark chart token missing: {token}"
        assert _contrast(light[token], light["bb-surface-data"]) >= 3.0, token
        assert _contrast(dark[token], dark["bb-surface-data"]) >= 3.0, token

    for token in ["bb-chart-label", "bb-chart-label-muted", "bb-chart-axis", "bb-chart-axis-strong"]:
        assert _contrast(light[token], light["bb-surface-data"]) >= 4.5, token
        assert _contrast(dark[token], dark["bb-surface-data"]) >= 4.5, token
