"""Contract tests for the documented MCP benchmark run surface."""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Any

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

pytest.importorskip("mcp", reason="MCP SDK not installed. Install with: uv add benchbox --extra mcp")

REPO_ROOT = Path(__file__).resolve().parents[3]
MCP_DOC = REPO_ROOT / "docs/reference/mcp.md"
MCP_SOURCE_ROOT = REPO_ROOT / "benchbox/mcp"

EXPECTED_TOOLS = {
    "analyze_results",
    "check_dependencies",
    "generate_chart",
    "get_benchmark_info",
    "get_query_details",
    "get_query_plan",
    "get_results",
    "list_available",
    "run_benchmark",
    "suggest_charts",
    "system_profile",
    "validate_results",
}

STALE_TOOL_NAMES = {
    "aggregate_results",
    "compare_results",
    "detect_regressions",
    "dry_run",
    "export_results",
    "export_summary",
    "generate_data",
    "get_performance_trends",
    "list_benchmarks",
    "list_platforms",
    "list_recent_runs",
    "validate_config",
}

EXPECTED_RUN_PARAMS = {
    "platform": {"type": "string", "required": True, "default": None},
    "benchmark": {"type": "string", "required": True, "default": None},
    "scale_factor": {"type": "number", "required": False, "default": 0.01},
    "queries": {"type": "string or null", "required": False, "default": None},
    "phases": {"type": "string or null", "required": False, "default": None},
    "mode": {"type": "string or null", "required": False, "default": None},
    "capture_plans": {"type": "boolean", "required": False, "default": False},
    "dry_run": {"type": "boolean", "required": False, "default": False},
    "validate_only": {"type": "boolean", "required": False, "default": False},
}

OMITTED_CLI_OPTIONS = {
    "--benchmark-option": "benchmark_option",
    "--compression": "compression",
    "--force": "force",
    "--global-cache": "global_cache",
    "--iterations": "iterations",
    "--non-interactive": "non_interactive",
    "--no-monitoring": "no_monitoring",
    "--no-progress": "no_progress",
    "--official": "official",
    "--output": "output",
    "--platform-option": "platform_option",
    "--plan-config": "plan_config",
    "--presort": "presort",
    "--publish": "publish",
    "--publish-label": "publish_label",
    "--publish-target": "publish_target",
    "--quiet": "quiet",
    "--seed": "seed",
    "--table-format": "table_format",
    "--table-mode": "table_mode",
    "--tuning": "tuning",
    "--validation": "validation",
    "--verbose": "verbose",
}


def _registered_tools() -> dict[str, Any]:
    from benchbox.mcp import create_server

    server = create_server(log_level="ERROR")
    return dict(getattr(server._tool_manager, "_tools", {}))


def _doc_text() -> str:
    return MCP_DOC.read_text(encoding="utf-8")


def _section(text: str, start_heading: str, end_heading: str) -> str:
    start = text.index(start_heading)
    end = text.index(end_heading, start)
    return text[start:end]


def _tool_section(text: str, tool_name: str) -> str:
    match = re.search(rf"^#### `{re.escape(tool_name)}`\s*$", text, flags=re.MULTILINE)
    if match is None:
        raise AssertionError(f"Missing documented tool heading for {tool_name}")
    next_heading = re.search(r"^(##|###|####) ", text[match.end() :], flags=re.MULTILINE)
    if next_heading is None:
        return text[match.end() :]
    return text[match.end() : match.end() + next_heading.start()]


def _documented_inventory_tools(text: str) -> set[str]:
    inventory = _section(text, "### Actual Tool Inventory", "### Run Surface Contract")
    return set(re.findall(r"^\| `([^`]+)` \|", inventory, flags=re.MULTILINE))


def _normalize_doc_default(value: str) -> Any:
    cleaned = value.strip()
    if cleaned == "-":
        return None
    cleaned = cleaned.strip("`")
    if cleaned == "null":
        return None
    if cleaned == '""':
        return ""
    if cleaned == "false":
        return False
    if cleaned == "true":
        return True
    try:
        return int(cleaned)
    except ValueError:
        pass
    try:
        return float(cleaned)
    except ValueError:
        return cleaned


def _documented_run_params(text: str) -> dict[str, dict[str, Any]]:
    run_params_section = _section(text, "**MCP run parameter schema**", "**Behavior**")
    return _parse_params_table(run_params_section)


def _parse_params_table(markdown: str) -> dict[str, dict[str, Any]]:
    params: dict[str, dict[str, Any]] = {}
    for line in markdown.splitlines():
        if not line.startswith("| `"):
            continue
        columns = [column.strip() for column in line.strip("|").split("|")]
        name = columns[0].strip("`")
        params[name] = {
            "type": columns[1],
            "required": columns[2].startswith("Yes"),
            "default": _normalize_doc_default(columns[3]),
        }
    return params


def _documented_tool_params(text: str, tool_name: str) -> dict[str, dict[str, Any]]:
    if tool_name == "run_benchmark":
        return _documented_run_params(text)
    return _parse_params_table(_tool_section(text, tool_name))


def _schema_type(property_schema: dict[str, Any]) -> str:
    if "type" in property_schema:
        return property_schema["type"]
    if "anyOf" in property_schema:
        return " or ".join(option["type"] for option in property_schema["anyOf"])
    return "unknown"


def _schema_params(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    required = set(schema.get("required", []))
    params: dict[str, dict[str, Any]] = {}
    for name, property_schema in schema["properties"].items():
        params[name] = {
            "type": _schema_type(property_schema),
            "required": name in required,
            "default": None if name in required else property_schema.get("default"),
        }
    return params


class TestMCPDocsContract:
    def test_docs_identify_mcp_as_control_plane_not_cli_equivalent(self):
        text = _doc_text()
        normalized = " ".join(text.split())

        assert "beta-public smoke/control-plane surface" in normalized
        assert "not a CLI-equivalent execution surface" in normalized
        assert "schema-level comparable to CLI result bundles" in normalized
        assert "shared non-CLI execution service" in normalized

    def test_docs_tool_inventory_matches_registered_tools(self):
        tools = _registered_tools()
        text = _doc_text()

        assert set(tools) == EXPECTED_TOOLS
        assert _documented_inventory_tools(text) == EXPECTED_TOOLS
        assert not (STALE_TOOL_NAMES & _documented_inventory_tools(text))

    def test_docs_run_benchmark_table_matches_registered_schema(self):
        schema = _registered_tools()["run_benchmark"].parameters
        documented_params = _documented_run_params(_doc_text())

        assert list(schema["properties"]) == list(EXPECTED_RUN_PARAMS)
        assert documented_params == EXPECTED_RUN_PARAMS
        assert _schema_params(schema) == EXPECTED_RUN_PARAMS

    def test_docs_tool_parameter_tables_match_registered_schemas(self):
        tools = _registered_tools()
        text = _doc_text()

        for tool_name, tool in tools.items():
            assert _documented_tool_params(text, tool_name) == _schema_params(tool.parameters), tool_name

    def test_docs_record_cli_only_controls_as_intentional_omissions(self):
        schema = _registered_tools()["run_benchmark"].parameters
        text = _doc_text()

        assert not (set(schema["properties"]) & set(OMITTED_CLI_OPTIONS.values()))
        for option in OMITTED_CLI_OPTIONS:
            assert option in text
        assert "--sorted-ingestion-*" in text

    def test_docs_do_not_keep_stale_standalone_tool_sections(self):
        text = _doc_text()
        documented_headings = set(re.findall(r"^#### `([^`]+)`", text, flags=re.MULTILINE))

        assert not (STALE_TOOL_NAMES & documented_headings)


class TestMCPImplementationBoundary:
    def test_mcp_package_does_not_import_cli_command_internals(self):
        offenders: list[str] = []

        for path in sorted(MCP_SOURCE_ROOT.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name == "benchbox.cli" or alias.name.startswith("benchbox.cli."):
                            offenders.append(f"{path.relative_to(REPO_ROOT)} imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    if module == "benchbox.cli" or module.startswith("benchbox.cli."):
                        offenders.append(f"{path.relative_to(REPO_ROOT)} imports from {module}")

        assert offenders == []
