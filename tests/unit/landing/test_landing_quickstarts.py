"""Tests for scripts/generate_landing_quickstarts.py.

Marked fast/unit — these are pure validator/template tests with no I/O
beyond reading the committed catalog.yaml.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_landing_quickstarts.py"
CATALOG_PATH = REPO_ROOT / "landing" / "prompts" / "catalog.yaml"
GENERATED_PATH = REPO_ROOT / "landing" / "prompts" / "catalog.generated.js"
FORBIDDEN_JSON = REPO_ROOT / "landing" / "prompts" / "recipes.json"
PROMPTS_INDEX_PATH = REPO_ROOT / "landing" / "prompts" / "index.html"
PROMPTS_JS_PATH = REPO_ROOT / "landing" / "prompts" / "prompts.js"
PROMPTS_CSS_PATH = REPO_ROOT / "landing" / "prompts" / "prompts.css"


def _load_generator():
    spec = importlib.util.spec_from_file_location("generate_landing_quickstarts", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("generate_landing_quickstarts", module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def gen():
    return _load_generator()


@pytest.fixture(scope="module")
def catalog():
    with CATALOG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def browser_catalog(gen, catalog):
    return gen.build_prompt_catalog(catalog)


pytestmark = [pytest.mark.fast, pytest.mark.unit]


def test_committed_catalog_validates(gen, catalog):
    assert gen.validate(catalog) == []


def test_generator_is_deterministic(gen, catalog):
    first = gen.render_js(catalog)
    second = gen.render_js(catalog)
    assert first == second


def test_check_passes_against_committed_include(gen):
    assert GENERATED_PATH.exists(), "catalog.generated.js must be committed"
    rc = gen.main(["--check"])
    assert rc == 0


def test_platform_inclusion_list_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["platforms"] = [{"id": "duckdb", "deployments": ["local"], "interfaces": ["sql"]}]
    errors = gen.validate(bad)
    assert any("platforms[] is no longer supported" in e for e in errors)


def test_unknown_benchmark_id_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["benchmarks"].append({"id": "definitely-not-a-benchmark"})
    errors = gen.validate(bad)
    assert any("definitely-not-a-benchmark" in e for e in errors)


def test_invalid_deployment_mode_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["deployments"].append({"id": "server", "label": "Server"})
    errors = gen.validate(bad)
    assert any("'server'" in e for e in errors)


def test_unknown_mcp_tool_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["mcp"]["run_tool"] = "tool_that_does_not_exist"
    errors = gen.validate(bad)
    assert any("tool_that_does_not_exist" in e for e in errors)


def test_unknown_mcp_prompt_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["mcp"]["prompts"]["benchmark_run"] = "prompt_that_does_not_exist"
    errors = gen.validate(bad)
    assert any("prompt_that_does_not_exist" in e for e in errors)


def test_credential_platforms_declare_safety_terms(browser_catalog):
    for platform in browser_catalog["platforms"]:
        if platform.get("credential_deployments"):
            safety = platform.get("safety_terms") or {}
            assert {"dependency", "dry_run", "no_secrets"} <= set(safety), platform["id"]


def test_compare_cli_template_uses_two_p_flags(gen, catalog):
    compare = catalog["templates"]["cli"]["compare"]
    assert compare.count("-p ") >= 2, compare
    bad = copy.deepcopy(catalog)
    bad["templates"]["cli"]["compare"] = "uv run benchbox compare -p {platform_a} -b {benchmark}"
    errors = gen.validate(bad)
    assert any("two -p flags" in e for e in errors)


def test_defaults_resolve_to_known_ids(browser_catalog):
    platform_ids = {p["id"] for p in browser_catalog["platforms"]}
    benchmark_ids = {b["id"] for b in browser_catalog["benchmarks"]}
    catalog = browser_catalog
    assert catalog["defaults"]["platform"] in platform_ids
    assert catalog["defaults"]["benchmark"] in benchmark_ids
    assert catalog["defaults"]["deployment"] in {"local", "self-hosted", "managed"}
    assert catalog["defaults"]["scale"] in catalog["scales"]
    assert all(isinstance(scale, str) for scale in catalog["scales"])
    assert "0.01" in catalog["scales"]
    assert "10.0" in catalog["scales"]


def test_agent_catalog_is_removed(catalog):
    assert "agents" not in catalog
    assert "agent" not in catalog["defaults"]


def test_agent_catalog_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["agents"] = [{"id": "codex", "label": "Codex"}]
    errors = gen.validate(bad)
    assert any("agents[] is no longer supported" in e for e in errors)


def test_agent_default_is_rejected(gen, catalog):
    bad = copy.deepcopy(catalog)
    bad["defaults"]["agent"] = "codex"
    errors = gen.validate(bad)
    assert any("defaults.agent is no longer supported" in e for e in errors)


def test_no_recipes_json_committed():
    # Either the file is absent, or the validator catches it.
    assert not FORBIDDEN_JSON.exists(), "landing/prompts/recipes.json is forbidden for MVP — see the decision record"


def test_generated_include_assigns_window_global():
    text = GENERATED_PATH.read_text(encoding="utf-8")
    assert "window.__BENCHBOX_PROMPT_CATALOG__" in text
    assert text.endswith(";\n")


def test_generated_platforms_cover_registry_ids(gen, browser_catalog):
    generated_ids = {p["id"] for p in browser_catalog["platforms"]}
    expected_ids = set(gen.PlatformRegistry.get_all_platform_metadata())
    assert generated_ids == expected_ids


def test_generated_platforms_include_install_commands(browser_catalog):
    assert all(platform.get("install_command") for platform in browser_catalog["platforms"])


def test_duckdb_is_sql_only_in_prompt_catalog(browser_catalog):
    duckdb = next(platform for platform in browser_catalog["platforms"] if platform["id"] == "duckdb")
    assert duckdb["interfaces"] == ["sql"]


def test_self_hosted_platforms_show_credential_safety(browser_catalog):
    postgresql = next(platform for platform in browser_catalog["platforms"] if platform["id"] == "postgresql")
    assert "self-hosted" in postgresql["deployments"]
    assert "self-hosted" in postgresql["credential_deployments"]
    assert "Do NOT paste credentials in chat" in postgresql["safety_terms"]["no_secrets"]


def test_removed_prompt_blocks_stay_removed():
    text = PROMPTS_INDEX_PATH.read_text(encoding="utf-8") + PROMPTS_JS_PATH.read_text(encoding="utf-8")
    assert "block-cli" not in text
    assert "block-mcp-prompt" not in text


def test_hidden_fields_override_flex_display():
    text = PROMPTS_CSS_PATH.read_text(encoding="utf-8")
    assert ".prompts-field[hidden]" in text
    assert ".prompts-block[hidden]" in text
    assert "display: none !important" in text


def test_agent_field_stays_removed_from_route():
    text = PROMPTS_INDEX_PATH.read_text(encoding="utf-8") + PROMPTS_JS_PATH.read_text(encoding="utf-8")
    assert "sel-agent" not in text
    assert 'name="agent"' not in text
    assert "state.agent" not in text
    assert "catalog.agents" not in text
    assert '["goal", "agent"' not in text


def test_credential_warning_box_is_credentials_only():
    text = PROMPTS_JS_PATH.read_text(encoding="utf-8")
    safety_block = text[text.index('var safetyList = $("cloud-safety-list")') : text.index("function platformLabel")]
    assert '"no_secrets"' in safety_block
    assert '"dependency"' not in safety_block
    assert '"dry_run"' not in safety_block


def test_prompt_includes_dependency_and_dry_run_safety():
    text = PROMPTS_JS_PATH.read_text(encoding="utf-8")
    assert "Check dependencies:" in text
    assert "Dry run first:" in text
    assert 'safetyTexts(entries, "dependency", deployment)' in text
    assert 'safetyTexts(entries, "dry_run", deployment)' in text
    assert "appendDeploymentSafetyLines(lines" in text


def test_agent_identity_sentence_stays_removed():
    text = PROMPTS_JS_PATH.read_text(encoding="utf-8")
    assert "You are a coding agent with shell access" not in text


def test_prompts_background_is_full_page():
    text = PROMPTS_CSS_PATH.read_text(encoding="utf-8")
    assert "body::before" in text
    assert ".prompts-main::before" not in text
    assert "position: fixed" in text
