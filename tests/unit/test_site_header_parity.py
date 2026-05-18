"""Static parity checks for the public BenchBox global header."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

ROOT = Path(__file__).resolve().parents[2]

if not (ROOT / "results-explorer").exists():
    pytest.skip("global header parity checks require results-explorer/", allow_module_level=True)

EXPECTED_LINKS = [
    ("Home", "https://benchbox.dev/"),
    ("Docs", "https://benchbox.dev/docs/"),
    ("Blog", "https://benchbox.dev/blog/"),
    ("Results", "https://benchbox.dev/results/"),
    ("Instruct an agent", "https://benchbox.dev/prompts/"),
    ("GitHub", "https://github.com/joeharris76/BenchBox"),
    ("Run benchmark", "https://benchbox.dev/docs/usage/installation.html"),
]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_shared_static_header_assets_are_the_static_source_of_truth() -> None:
    css = _read("landing/shared/site-header.css")
    js = _read("landing/shared/site-header.js")
    theme_css = _read("landing/shared/site-theme.css")
    theme_js = _read("landing/shared/site-theme.js")
    landing = _read("landing/index.html")
    docs_conf = _read("docs/conf.py")

    assert "benchbox-site-header__nav" in css
    assert "data-benchbox-site-header-toggle" in js
    assert "--bb-site-header-bg" in theme_css
    assert "benchbox:theme" in theme_js
    assert "shared/site-header.css" in landing
    assert "shared/site-header.js" in landing
    assert "shared/site-theme.css" in landing
    assert "shared/site-theme.js" in landing
    assert '"../landing/shared"' in docs_conf
    assert '"site-header.css"' in docs_conf
    assert '"site-header.js"' in docs_conf
    assert '"site-theme.css"' in docs_conf
    assert '"site-theme.js"' in docs_conf


@pytest.mark.parametrize(
    ("path", "surface"),
    [
        ("landing/index.html", "landing"),
        ("docs/_templates/page.html", "docs"),
        ("results-explorer/src/components/Layout.tsx", "results"),
    ],
)
def test_global_header_link_contract_is_identical_across_surfaces(path: str, surface: str) -> None:
    source = _read(path)
    if surface == "results":
        source = _read("results-explorer/src/components/headerContract.ts")

    positions = []
    for label, href in EXPECTED_LINKS:
        label_position = source.find(label)
        href_position = source.find(href)
        assert label_position >= 0, f"{surface} missing label {label!r}"
        assert href_position >= 0, f"{surface} missing href {href!r}"
        positions.append(href_position)

    assert positions == sorted(positions), f"{surface} global header link order drifted"


@pytest.mark.parametrize(
    ("path", "surface"),
    [
        ("landing/index.html", "landing"),
        ("landing/prompts/index.html", "prompts"),
        ("docs/_templates/page.html", "docs"),
        ("results-explorer/src/components/Layout.tsx", "results"),
    ],
)
def test_global_header_exposes_single_shared_theme_control(path: str, surface: str) -> None:
    source = _read(path)

    assert source.count("data-benchbox-theme-toggle") == 1, f"{surface} should expose exactly one shared theme toggle"
    assert "Theme:" in source, f"{surface} missing accessible theme label"


def test_results_secondary_nav_remains_separate_from_global_header() -> None:
    layout = _read("results-explorer/src/components/Layout.tsx")
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert 'export const HEADER_NAV_ARIA_LABEL = "BenchBox"' in contract
    assert "aria-label={HEADER_NAV_ARIA_LABEL}" in layout
    assert 'aria-label="Results Explorer"' in layout
    for label in ["Leaderboards", "Benchmarks", "Platforms", "Compare", "Query"]:
        assert label in layout
