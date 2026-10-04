from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

ROOT = Path(__file__).resolve().parents[2]

ASTRO_HEADER = "website/src/components/SiteHeader.astro"
ASTRO_LINKS = "website/src/lib/header-links.ts"
ASTRO_THEME_TOGGLE = "website/src/components/ThemeToggle.astro"
ASTRO_FOOTER = "website/src/components/SiteFooter.astro"
CONTRACT_IMPORT = "results-explorer/src/components/shellModel.ts"
SHELL_MODEL = "results-explorer/src/components/shellModel.ts"
PREACT_SHELL = "results-explorer/src/components/SiteShell.tsx"
SHARED_SHELL_CSS = "landing/shared/site-shell.css"

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
        (PREACT_SHELL, "results"),
        (ASTRO_HEADER, "astro header"),
        (ASTRO_LINKS, "astro links"),
    ],
)
def test_global_header_has_no_header_theme_control(path: str, surface: str) -> None:
    source = _read(path)

    assert "data-benchbox-theme-toggle" not in source, f"{surface} header should not expose a theme toggle button"
    assert "benchbox-site-header__theme" not in source, f"{surface} header should not carry the removed theme class"


def test_astro_header_renders_the_explorer_header_contract() -> None:
    header = _read(ASTRO_HEADER)
    links = _read(ASTRO_LINKS)
    model = _read(SHELL_MODEL)
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert CONTRACT_IMPORT in links, "astro shell must import the model the Explorer renders"
    assert "./headerContract.ts" in model, "shell model must derive from the header contract"
    for name in (
        "HEADER_BRAND",
        "HEADER_CTA",
        "HEADER_LINKS",
        "HEADER_NAV_ARIA_LABEL",
        "HEADER_TOGGLE_ARIA_LABEL",
    ):
        assert name in model, f"shell model does not consume {name}"
    for label, href in EXPECTED_LINKS:
        assert label in contract, f"contract missing label {label!r}"
        assert href in contract, f"contract missing href {href!r}"
        assert href not in header, f"astro header must not hard-code {href!r}"
    assert "shellLinks(" in header
    assert "shellCta()" in header
    assert "aria-label={shellLabels.nav}" in header
    assert "aria-label={shellLabels.toggle}" in header
    assert 'id="benchbox-site-header-nav"' in header
    assert 'aria-controls="site-header-panel"' in header
    assert "data-site-header-toggle" in header


def test_astro_header_links_resolve_to_site_paths_in_contract_order() -> None:
    model = _read(SHELL_MODEL)
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert 'SITE_ORIGIN = "https://benchbox.dev"' in model
    assert "HEADER_LINKS.map(" in model
    labels = [label for label, _ in EXPECTED_LINKS if label != "Run benchmark"]
    positions = [contract.find(f'label: "{label}"') for label in labels]
    assert all(position >= 0 for position in positions)
    assert positions == sorted(positions)
    assert "activeOnSurface" in model


def test_astro_header_has_no_theme_toggle_component() -> None:
    header = _read(ASTRO_HEADER)

    assert "ThemeToggle" not in header, "astro header must not render the theme control"
    assert 'role="radiogroup"' not in header
    assert "data-theme-option" not in header
    assert "theme-toggle" not in header


def test_astro_footer_radiogroup_binds_the_shared_theme_labels() -> None:
    toggle = _read(ASTRO_THEME_TOGGLE)
    footer = _read(ASTRO_FOOTER)

    assert "import ThemeToggle" in footer
    assert "<ThemeToggle />" in footer, "astro footer must render the theme radiogroup"
    assert toggle.count('role="radiogroup"') == 1
    assert "aria-label={shellLabels.theme}" in toggle
    assert "aria-label={option.label}" in toggle
    assert "THEME_OPTIONS.map(" in toggle
    assert "THEME_ICON_SHAPES" in toggle
    assert "data-theme-option" in toggle
    assert "data-pagefind-ignore" in footer


def test_results_footer_radiogroup_binds_the_shared_aria_label() -> None:
    shell = _read(PREACT_SHELL)
    model = _read(SHELL_MODEL)
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert 'role="radiogroup"' in shell, "results footer should expose a theme radiogroup"
    assert "aria-label={shellLabels.theme}" in shell, "results radiogroup missing accessible name binding"
    assert "THEME_OPTIONS.map(" in shell
    assert "THEME_ICON_SHAPES" in shell
    assert 'FOOTER_THEME_ARIA_LABEL = "Color theme"' in contract, "results theme aria label contract drifted"
    assert "theme: FOOTER_THEME_ARIA_LABEL" in model
    for option in ("system", "light", "dark"):
        assert f'"{option}"' in model, f"shell model missing {option} theme option"


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
    assert 'href="style.css?v=7"' in landing
    assert 'src="script.js?v=1"' in landing
    assert 'href="../style.css?v=7"' in prompts


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
    shell = _read(PREACT_SHELL)
    nav = _read("results-explorer/src/components/resultsNav.ts")
    contract = _read("results-explorer/src/components/headerContract.ts")

    assert 'export const HEADER_NAV_ARIA_LABEL = "BenchBox"' in contract
    assert "aria-label={shellLabels.nav}" in shell
    assert 'aria-label="Results Explorer"' in layout
    assert "RESULTS_NAV_SECTIONS" in layout
    for label in ["Overview", "Benchmarks", "Platforms", "Compare", "Find runs"]:
        assert f'label: "{label}"' in nav


def _classes(source: str, prefixes: tuple[str, ...]) -> set[str]:
    found = set(re.findall(r"[A-Za-z0-9_-]+", " ".join(re.findall(r'class(?:Name)?="([^"]*)"', source))))
    return {name for name in found if name.startswith(prefixes)}


SHELL_CLASS_PREFIXES = ("site-header", "site-footer", "theme-toggle")


def test_astro_and_preact_shells_render_the_same_class_vocabulary() -> None:
    astro = "".join(_read(path) for path in (ASTRO_HEADER, ASTRO_FOOTER, ASTRO_THEME_TOGGLE))
    preact = _read(PREACT_SHELL)

    astro_classes = _classes(astro, SHELL_CLASS_PREFIXES)
    preact_classes = _classes(preact, SHELL_CLASS_PREFIXES)

    assert astro_classes - preact_classes == set()
    assert preact_classes - astro_classes == set()
    assert {"site-header__link", "site-header__cta", "site-footer__link", "theme-toggle"} <= preact_classes


def test_astro_and_preact_shells_share_ids_and_hooks() -> None:
    astro = _read(ASTRO_HEADER) + _read(ASTRO_FOOTER) + _read(ASTRO_THEME_TOGGLE)
    preact = _read(PREACT_SHELL)

    for token in (
        'id="site-header-panel"',
        'id="benchbox-site-header-nav"',
        'aria-controls="site-header-panel"',
        "data-site-header-toggle",
        "data-site-header-panel",
        "data-site-header-nav",
        "data-site-footer",
        "data-theme-option",
        'role="radiogroup"',
        'role="radio"',
    ):
        assert token in astro, f"astro shell missing {token}"
        assert token in preact, f"preact shell missing {token}"


def test_shell_styles_have_one_source_consumed_by_site_and_explorer() -> None:
    shared = _read(SHARED_SHELL_CSS)
    site = _read("website/src/styles/shell.css")
    explorer = _read("results-explorer/src/index.css")

    assert "landing/shared/site-shell.css" in _read("website/src/layouts/Shell.astro")
    assert "../landing/shared/site-shell.css" in _read("website/astro.config.ts")
    assert "../../landing/shared/site-shell.css" in explorer
    for selector in (".site-header {", ".site-header__link", ".theme-toggle {", ".site-footer {"):
        assert selector in shared
        assert selector not in site
    assert re.search(r"\bsite-header|\bsite-footer|\btheme-toggle", re.sub(r"\.search-[\w-]+", "", site)) is None


def test_explorer_global_rules_are_scoped_to_the_explorer_root() -> None:
    explorer = _read("results-explorer/src/index.css")
    base = explorer[explorer.index("@layer base") : explorer.index("@layer components")]

    base = re.sub(r"/\*.*?\*/", "", base, flags=re.DOTALL)
    selectors = [
        selector.strip()
        for block in re.findall(r"(?<![^{}])\s*([^{}]+)\{", base)
        for selector in block.split(",")
        if selector.strip() and not selector.strip().startswith("@")
    ]
    assert len(selectors) > 5
    unscoped = [
        selector
        for selector in selectors
        if not selector.startswith(
            (".bb-explorer", ":where(.bb-explorer)", "body.bb-explorer-page", ".site-footer__link", "[")
        )
    ]
    assert unscoped == []
    assert 'class="bb-explorer-page"' in _read("results-explorer/index.html")


def test_explorer_header_has_no_search_box_by_design() -> None:
    astro = _read(ASTRO_HEADER)
    preact = _read(PREACT_SHELL)

    assert "<SearchBox />" in astro
    assert "SearchBox" not in preact
    assert "search-button" not in preact
    assert "data-search-open" not in preact


def test_explorer_keeps_its_header_non_sticky() -> None:
    css = _read("results-explorer/src/index.css")

    assert re.search(r"\.bb-explorer-page \.site-header\s*\{\s*position:\s*static;", css)
