from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).parents[3]
API_DOCS = ROOT / "docs/reference/python-api"
SYMBOLS = ROOT / "_project/design/site-inventory/api-public-symbols.json"
WORKFLOW = ROOT / ".github/workflows/publication-deploy.yml"
ASTRO_CONFIG = ROOT / "website/astro.config.ts"
SPIKE_REPORT = ROOT / "_project/decisions/astro-spike-report.md"

HEADING = re.compile(r"^#{1,6}\s+(.*)$", re.MULTILINE)
ANCHOR = re.compile(r"""(?:\(([A-Za-z0-9_.-]+)\)=|\bid=["']([^"']+)["']|<a\s+name=["']([^"']+)["'])""")


def _authored_names() -> set[str]:
    names: set[str] = set()
    for page in API_DOCS.rglob("*.md"):
        text = page.read_text(encoding="utf-8")
        for heading in HEADING.findall(text):
            names.update(re.findall(r"[A-Za-z_][A-Za-z0-9_.]*", heading))
        for groups in ANCHOR.findall(text):
            names.update(group for group in groups if group)
    return names


def _documented(symbol: dict[str, str], names: set[str]) -> bool:
    candidates = {symbol["symbol"], *filter(None, [symbol.get("name")]), *symbol.get("aliases", [])}
    candidates |= {c.rsplit(".", 1)[-1] for c in candidates}
    return bool(candidates & names)


@pytest.mark.skipif(not SYMBOLS.exists(), reason="_project site inventory is not in this checkout (release tree)")
def test_every_public_symbol_has_an_authored_heading_or_anchor() -> None:
    names = _authored_names()
    inventory = json.loads(SYMBOLS.read_text(encoding="utf-8"))
    missing = sorted(s["symbol"] for s in inventory["symbols"] if not _documented(s, names))
    assert not missing, f"public symbols without an authored heading or anchor under {API_DOCS}: {missing}"


def test_api_docs_lane_output_path_matches_the_workflow() -> None:
    reference = (ROOT / "docs/reference/api-reference.md").read_text(encoding="utf-8")
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "in the `api-docs` lane at `reference/python-api/`" in reference
    assert "mkdir -p api-docs/reference/python-api" in workflow
    assert "docs/_build/html/reference/python-api api-docs/reference/" in workflow
    assert "Sphinx build" not in reference


@pytest.mark.skipif(
    not SPIKE_REPORT.exists(), reason="_project decision records are not in this checkout (release tree)"
)
def test_documented_starlight_overrides_match_the_astro_config() -> None:
    config = ASTRO_CONFIG.read_text(encoding="utf-8")
    block = re.search(r"components:\s*\{(.*?)\}", config, re.DOTALL)
    assert block
    configured = set(re.findall(r"^\s*(\w+):", block.group(1), re.MULTILINE))
    report = SPIKE_REPORT.read_text(encoding="utf-8")
    section = report.split("## Starlight overrides", 1)[1].split("- **Unchanged:**", 1)[0]
    documented = set(re.findall(r"`(\w+)`", section)) & {
        "Header",
        "PageTitle",
        "Footer",
        "ThemeProvider",
        "ThemeSelect",
        "Sidebar",
        "Search",
        "SocialIcons",
        "Hero",
        "MobileMenuToggle",
    }
    assert configured
    assert documented == configured
