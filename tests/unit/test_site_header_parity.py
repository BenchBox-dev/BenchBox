"""Static parity checks for the public BenchBox global header."""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_LINKS = [
    ("Home", "https://benchbox.dev/"),
    ("Docs", "https://benchbox.dev/docs/"),
    ("Blog", "https://benchbox.dev/blog/"),
    ("Results", "https://benchbox.dev/results/"),
    ("GitHub", "https://github.com/BenchBox-dev/BenchBox"),
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
def test_global_header_has_no_header_theme_control(path: str, surface: str) -> None:
    source = _read(path)

    assert "data-benchbox-theme-toggle" not in source, f"{surface} header should not expose a theme toggle button"
    assert "benchbox-site-header__theme" not in source, f"{surface} header should not carry the removed theme class"


def test_results_footer_radiogroup_binds_the_shared_aria_label() -> None:
    layout = _read("results-explorer/src/components/Layout.tsx")
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert 'role="radiogroup"' in layout, "results footer should expose a theme radiogroup"
    # Results renders the accessible name from a shared constant rather than a literal string.
    assert "aria-label={FOOTER_THEME_ARIA_LABEL}" in layout, "results radiogroup missing accessible name binding"
    assert 'FOOTER_THEME_ARIA_LABEL = "Color theme"' in contract, "results theme aria label contract drifted"
    for option in ("system", "light", "dark"):
        assert f'"{option}"' in layout, f"results missing {option} theme option"


@pytest.mark.parametrize(
    ("path", "surface"),
    [
        ("landing/index.html", "landing"),
        ("landing/prompts/index.html", "prompts"),
        ("docs/_templates/page.html", "docs"),
    ],
)
def test_static_surface_footer_radiogroup_is_well_formed(path: str, surface: str) -> None:
    source = _read(path)

    assert source.count('role="radiogroup"') == 1, f"{surface} should expose exactly one theme radiogroup"
    assert 'aria-label="Color theme"' in source, f"{surface} footer radiogroup missing accessible name"
    for option in ("system", "light", "dark"):
        assert source.count(f'data-benchbox-theme-option="{option}"') == 1, (
            f"{surface} should expose exactly one {option} theme option"
        )
    for label in ("System theme", "Light theme", "Dark theme"):
        assert f'aria-label="{label}"' in source, f"{surface} missing the {label!r} option label"


def test_landing_has_no_duplicate_ai_assistants_section_and_mcp_links_to_prompts() -> None:
    source = _read("landing/index.html")

    assert 'id="ai-assistants"' not in source, "landing should not carry the removed #ai-assistants section"
    assert "#ai-assistants" not in source, "landing should not link to the removed #ai-assistants section"

    mcp_start = source.index('id="mcp"')
    mcp_section = source[mcp_start : source.index("</section>", mcp_start)]
    assert "https://benchbox.dev/prompts/" in mcp_section, "#mcp section should link to the prompt builder"


def test_landing_section_navigation_links_to_each_major_section_in_order() -> None:
    source = _read("landing/index.html")
    expected_links = [
        ("Overview", "#overview", "overview"),
        ("Public Results", "#results-explorer", "results"),
        ("Benchmarks", "#benchmarks", "benchmarks"),
        ("Platforms", "#platforms", "platforms"),
        ("Table Formats", "#formats", "formats"),
        ("AI Agents", "#mcp", "agents"),
        ("Get Started", "#install", "install"),
    ]

    nav_start = source.index('<nav class="section-nav"')
    nav = source[nav_start : source.index("</nav>", nav_start)]
    link_positions = []
    for label, href, accent in expected_links:
        link_start = nav.index(f'class="section-nav__link section-nav__link--{accent}"')
        link_positions.append(link_start)
        assert f'href="{href}"' in nav[link_start:]
        assert label in nav[link_start:]
        assert f'id="{href.removeprefix("#")}"' in source

    assert link_positions == sorted(link_positions)
    assert source.index("</section>") < nav_start < source.index('id="features"')


def test_landing_section_navigation_is_sticky_colored_and_tracks_the_current_section() -> None:
    css = _read("landing/style.css")
    script = _read("landing/script.js")

    assert ".section-nav {" in css
    assert "position: sticky" in css
    assert "top: 4rem" in css
    for color in ("--platforms-heading", "--formats-heading", "--mcp-heading"):
        assert color in css
    assert '.section-nav__link[aria-current="location"]' in css
    assert "function updateCurrentSection()" in script
    assert "link.setAttribute('aria-current', 'location')" in script
    assert "sectionNavigationOffset()" in script
    assert "sectionNavLinksContainer.scrollTo({ left: centeredLeft" in script
    assert "window.history.pushState(null, '', targetId)" in script

    landing = _read("landing/index.html")
    prompts = _read("landing/prompts/index.html")
    assert 'href="style.css?v=6"' in landing
    assert 'src="script.js?v=1"' in landing
    assert 'href="../style.css?v=6"' in prompts


def test_landing_introduces_results_explorer_with_public_compare_and_local_workflows() -> None:
    source = _read("landing/index.html")
    section_start = source.index('<section id="results-explorer"')
    section = source[section_start : source.index("</section>", section_start)]

    assert "Explore and Compare Benchmark Results" in section
    assert 'href="https://benchbox.dev/results/"' in section
    assert "Find relevant runs" in section
    assert "Compare like with like" in section
    assert "Check your own result" in section
    assert "without uploading it" in section
    assert "Four DuckDB versions, one comparable cohort" in section
    assert "281,041" in section
    assert "Box plots of query latency by DuckDB version" in section
    assert "Cumulative query latency by DuckDB version" in section
    assert section.count("compare?ids=6235bd1a,47bdcef5,282a4d75,19b96c85") == 3
    assert source.index('id="features"') < section_start < source.index('id="benchmarks"')


def test_results_secondary_nav_remains_separate_from_global_header() -> None:
    layout = _read("results-explorer/src/components/Layout.tsx")
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert 'export const HEADER_NAV_ARIA_LABEL = "BenchBox"' in contract
    assert "aria-label={HEADER_NAV_ARIA_LABEL}" in layout
    assert 'aria-label="Results Explorer"' in layout
    for label in ["Overview", "Benchmarks", "Platforms", "Compare", "Find runs"]:
        assert label in layout
