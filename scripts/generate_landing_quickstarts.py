"""Generate landing/prompts/catalog.generated.js from landing/prompts/catalog.yaml.

Invocation (main project env so benchbox is importable):
    uv run -- python scripts/generate_landing_quickstarts.py --check
    uv run -- python scripts/generate_landing_quickstarts.py --write
    uv run -- python scripts/generate_landing_quickstarts.py --validate-only

The emitted file assigns `window.__BENCHBOX_PROMPT_CATALOG__` so the static
/prompts/ page can load it via a <script> tag. It is page implementation
detail, not a public API — do not introduce a fetchable recipes.json.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from benchbox.core.benchmark_registry import BENCHMARK_METADATA
from benchbox.core.platform_registry import PlatformRegistry
from benchbox.utils.dependencies import list_available_dependency_groups

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "landing" / "prompts" / "catalog.yaml"
OUTPUT = REPO_ROOT / "landing" / "prompts" / "catalog.generated.js"
FORBIDDEN_JSON = REPO_ROOT / "landing" / "prompts" / "recipes.json"

VALID_DEPLOYMENT_MODES = frozenset({"local", "self-hosted", "managed"})
MANAGED_SAFETY_KEYS = frozenset({"dependency", "dry_run", "no_secrets"})
DEPLOYMENT_ORDER = {"local": 0, "self-hosted": 1, "managed": 2}
LOCAL_CATEGORIES = frozenset({"analytical", "dataframe", "embedded"})
CLOUD_HINTS = frozenset({"aws", "azure", "cloud", "gcs", "multi_cloud", "onelake", "s3", "saas", "serverless"})
SELF_HOSTED_CATEGORIES = frozenset({"distributed", "relational", "timeseries"})
LOCAL_EXECUTION_HINTS = frozenset({"local", "embedded", "in-process", "in_memory", "file_based"})
DEPENDENCY_CHECK_ALIASES = {
    "fabric-lakehouse": "fabric",
    "fabric_dw": "fabric",
}


def load_catalog(path: Path = SOURCE) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise SystemExit(f"catalog.yaml must be a mapping, got {type(data).__name__}")
    return data


def _known_mcp_names() -> tuple[frozenset[str], frozenset[str]]:
    """Return (tool_names, prompt_names) registered in benchbox/mcp/."""
    mcp_dir = REPO_ROOT / "benchbox" / "mcp"
    tools: set[str] = set()
    prompts: set[str] = set()
    for py in mcp_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        in_tools = "@mcp.tool" in text
        in_prompts = "@mcp.prompt" in text
        if not (in_tools or in_prompts):
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("@mcp.tool"):
                for follow in lines[i + 1 : i + 6]:
                    fs = follow.strip()
                    if fs.startswith("def "):
                        name = fs[4:].split("(", 1)[0]
                        tools.add(name)
                        break
            elif stripped.startswith("@mcp.prompt"):
                for follow in lines[i + 1 : i + 6]:
                    fs = follow.strip()
                    if fs.startswith("def "):
                        name = fs[4:].split("(", 1)[0]
                        prompts.add(name)
                        break
    return frozenset(tools), frozenset(prompts)


def _ordered(values: set[str]) -> list[str]:
    return sorted(values, key=lambda value: (DEPLOYMENT_ORDER[value], value))


def _is_cloud_like(metadata: dict[str, Any]) -> bool:
    supports = set(metadata.get("supports") or [])
    return metadata.get("category") == "cloud" or bool(supports & CLOUD_HINTS)


def _has_local_execution_hint(metadata: dict[str, Any]) -> bool:
    supports = {str(value).lower() for value in metadata.get("supports") or []}
    if supports & LOCAL_EXECUTION_HINTS:
        return True
    text = " ".join(str(metadata.get(key) or "").lower() for key in ("description", "notes"))
    return any(hint.replace("_", " ") in text for hint in LOCAL_EXECUTION_HINTS)


def _infer_default_deployments(metadata: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Infer UI deployment modes when registry metadata has no deployment_modes block."""
    category = metadata.get("category")
    supports = set(metadata.get("supports") or [])

    if _is_cloud_like(metadata):
        return {"managed"}, {"managed"}
    if category in SELF_HOSTED_CATEGORIES or "self-hosted" in supports:
        if _has_local_execution_hint(metadata):
            return {"local", "self-hosted"}, {"self-hosted"}
        return {"self-hosted"}, {"self-hosted"}
    if category in LOCAL_CATEGORIES:
        return {"local"}, set()
    return {"local"}, set()


def _deployment_from_registry_mode(mode: str, requires_network: bool) -> str:
    if mode in VALID_DEPLOYMENT_MODES:
        return mode
    if mode == "remote":
        return "self-hosted" if requires_network else "local"
    raise ValueError(f"unsupported registry deployment mode {mode!r}")


def _derive_deployments(platform_id: str, metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
    caps = PlatformRegistry.get_platform_capabilities(platform_id)
    if caps is None:
        return [], []
    if not caps.deployment_modes:
        deployments, credential_deployments = _infer_default_deployments(metadata)
        return _ordered(deployments), _ordered(credential_deployments)

    deployments: set[str] = set()
    credential_deployments: set[str] = set()
    for dep in caps.deployment_modes.values():
        deployment = _deployment_from_registry_mode(dep.mode, dep.requires_network)
        deployments.add(deployment)
        if dep.requires_credentials:
            credential_deployments.add(deployment)
    return _ordered(deployments), _ordered(credential_deployments)


def _derive_interfaces(platform_id: str) -> list[str]:
    caps = PlatformRegistry.get_platform_capabilities(platform_id)
    if caps is None:
        return []
    interfaces: list[str] = []
    if caps.supports_sql:
        interfaces.append("sql")
    if caps.supports_dataframe:
        interfaces.append("dataframe")
    return interfaces


def _platform_label(metadata: dict[str, Any], platform_id: str) -> str:
    return str(metadata.get("display_name") or platform_id)


def _platform_safety_terms(platform_id: str, credential_deployments: list[str]) -> dict[str, str] | None:
    if not credential_deployments:
        return None
    return {
        "dependency": "Check platform SDK and connector dependencies before any live run.",
        "dry_run": "Use a dry run to inspect commands before any live run.",
        "no_secrets": "Configure platform connection credentials in your shell env or config files. "
        "Do NOT paste credentials in chat.",
    }


def _dependency_check_platform(platform_id: str) -> str | None:
    candidate = DEPENDENCY_CHECK_ALIASES.get(platform_id, platform_id)
    if candidate in _dependency_groups():
        return candidate
    return None


@cache
def _dependency_groups() -> dict[str, Any]:
    return list_available_dependency_groups()


def _derive_platform_entries() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    metadata_by_id = PlatformRegistry.get_all_platform_metadata()
    for platform_id, metadata in sorted(metadata_by_id.items()):
        interfaces = _derive_interfaces(platform_id)
        if not interfaces:
            continue
        deployments, credential_deployments = _derive_deployments(platform_id, metadata)
        if not deployments:
            continue
        entry: dict[str, Any] = {
            "id": platform_id,
            "install_command": metadata.get("installation_command") or f"uv add benchbox --extra {platform_id}",
            "label": _platform_label(metadata, platform_id),
            "deployments": deployments,
            "interfaces": interfaces,
        }
        dependency_check_platform = _dependency_check_platform(platform_id)
        if dependency_check_platform:
            entry["dependency_check_platform"] = dependency_check_platform
            entry["dependency_check_command"] = f"uv run benchbox check-deps --platform {dependency_check_platform}"
        if credential_deployments:
            entry["credential_deployments"] = credential_deployments
            safety_terms = _platform_safety_terms(platform_id, credential_deployments)
            if safety_terms:
                entry["safety_terms"] = safety_terms
        entries.append(entry)
    return entries


def build_prompt_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return the browser catalog with PlatformRegistry-derived platform entries."""
    expanded = copy.deepcopy(catalog)
    expanded["platforms"] = _derive_platform_entries()
    return expanded


def _validate_one_platform(entry: dict[str, Any], known_platforms: set[str]) -> list[str]:
    errors: list[str] = []
    pid = entry.get("id")
    if pid not in known_platforms:
        errors.append(f"platforms[{pid!r}]: unknown platform id (not in PlatformRegistry)")
    for d in entry.get("deployments") or []:
        if d not in VALID_DEPLOYMENT_MODES:
            errors.append(f"platforms[{pid!r}].deployments={d!r}: must be one of {sorted(VALID_DEPLOYMENT_MODES)}")
    if "managed" in (entry.get("deployments") or []):
        safety = entry.get("safety_terms") or {}
        missing = MANAGED_SAFETY_KEYS - set(safety.keys())
        if missing:
            errors.append(
                f"platforms[{pid!r}]: managed deployment requires safety_terms "
                f"covering {sorted(MANAGED_SAFETY_KEYS)}; missing {sorted(missing)}"
            )
    for d in entry.get("credential_deployments") or []:
        if d not in entry.get("deployments", []):
            errors.append(f"platforms[{pid!r}].credential_deployments={d!r}: must be in deployments[]")
    ifaces = entry.get("interfaces") or []
    if not ifaces:
        errors.append(f"platforms[{pid!r}]: at least one interface is required")
    for iface in ifaces:
        if iface not in {"sql", "dataframe"}:
            errors.append(f"platforms[{pid!r}].interfaces={iface!r}: must be 'sql' or 'dataframe'")
    return errors


def _catalog_entry_ids(catalog: dict[str, Any], key: str) -> set[str]:
    return {entry["id"] for entry in catalog.get(key) or [] if isinstance(entry, dict) and "id" in entry}


def _validate_defaults(
    catalog: dict[str, Any],
    platforms: list[dict[str, Any]],
    benchmarks: list[dict[str, Any]],
) -> list[str]:
    errors: list[str] = []
    defaults = catalog.get("defaults") or {}
    platform_by_id = {p["id"]: p for p in platforms if isinstance(p, dict) and "id" in p}
    benchmark_by_id = {b["id"]: b for b in benchmarks if isinstance(b, dict) and "id" in b}

    goal_ids = _catalog_entry_ids(catalog, "goals")
    surface_ids = _catalog_entry_ids(catalog, "surfaces")
    interface_ids = _catalog_entry_ids(catalog, "interfaces")
    deployment_ids = _catalog_entry_ids(catalog, "deployments")
    scale_ids = set(catalog.get("scales") or [])

    if defaults.get("goal") not in goal_ids:
        errors.append(f"defaults.goal={defaults.get('goal')!r}: not in goals[]")
    if defaults.get("surface") not in surface_ids:
        errors.append(f"defaults.surface={defaults.get('surface')!r}: not in surfaces[]")
    if defaults.get("interface") not in interface_ids:
        errors.append(f"defaults.interface={defaults.get('interface')!r}: not in interfaces[]")
    if defaults.get("deployment") not in deployment_ids:
        errors.append(f"defaults.deployment={defaults.get('deployment')!r}: not in deployments[]")
    if defaults.get("scale") not in scale_ids:
        errors.append(f"defaults.scale={defaults.get('scale')!r}: not in scales[]")

    default_platform = platform_by_id.get(defaults.get("platform"))
    default_benchmark = benchmark_by_id.get(defaults.get("benchmark"))
    default_interface = defaults.get("interface")
    default_deployment = defaults.get("deployment")

    if default_platform is None:
        errors.append(f"defaults.platform={defaults.get('platform')!r}: not in platforms[]")
    else:
        if default_interface not in (default_platform.get("interfaces") or []):
            errors.append(
                f"defaults.interface={default_interface!r}: not supported by "
                f"defaults.platform={defaults.get('platform')!r}"
            )
        if default_deployment not in (default_platform.get("deployments") or []):
            errors.append(
                f"defaults.deployment={default_deployment!r}: not supported by "
                f"defaults.platform={defaults.get('platform')!r}"
            )

    if default_benchmark is None:
        errors.append(f"defaults.benchmark={defaults.get('benchmark')!r}: not in benchmarks[]")
    elif default_interface not in (default_benchmark.get("interfaces") or []):
        errors.append(
            f"defaults.interface={default_interface!r}: not supported by "
            f"defaults.benchmark={defaults.get('benchmark')!r}"
        )

    if defaults.get("deployment") not in VALID_DEPLOYMENT_MODES:
        errors.append(
            f"defaults.deployment={defaults.get('deployment')!r}: must be in {sorted(VALID_DEPLOYMENT_MODES)}"
        )
    return errors


def _validate_mcp(catalog: dict[str, Any], known_tools: frozenset[str], known_prompts: frozenset[str]) -> list[str]:
    errors: list[str] = []
    mcp = catalog.get("mcp") or {}
    if mcp.get("run_tool") and mcp["run_tool"] not in known_tools:
        errors.append(f"mcp.run_tool={mcp['run_tool']!r}: not a registered MCP tool")
    if mcp.get("list_tool") and mcp["list_tool"] not in known_tools:
        errors.append(f"mcp.list_tool={mcp['list_tool']!r}: not a registered MCP tool")
    for key, name in (mcp.get("prompts") or {}).items():
        if name not in known_prompts:
            errors.append(f"mcp.prompts.{key}={name!r}: not a registered MCP prompt")
    return errors


def _validate_agent_removed(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if "agents" in catalog:
        errors.append("agents[] is no longer supported; /prompts/ uses agent-agnostic copy")
    if "agent" in (catalog.get("defaults") or {}):
        errors.append("defaults.agent is no longer supported; /prompts/ uses agent-agnostic copy")
    return errors


def _validate_platforms_are_derived(catalog: dict[str, Any]) -> list[str]:
    if "platforms" not in catalog:
        return []
    return ["platforms[] is no longer supported in catalog.yaml; prompt platforms are derived from PlatformRegistry"]


def validate(catalog: dict[str, Any]) -> list[str]:
    """Return a list of validation error messages; empty means valid."""
    errors: list[str] = []
    errors.extend(_validate_platforms_are_derived(catalog))
    known_platforms = set(PlatformRegistry.get_all_platform_metadata().keys())
    known_benchmarks = set(BENCHMARK_METADATA.keys())
    known_tools, known_prompts = _known_mcp_names()
    browser_catalog = build_prompt_catalog(catalog)

    platforms = browser_catalog.get("platforms") or []
    for entry in platforms:
        errors.extend(_validate_one_platform(entry, known_platforms))

    benchmarks = catalog.get("benchmarks") or []
    for entry in benchmarks:
        bid = entry.get("id")
        if bid not in known_benchmarks:
            errors.append(f"benchmarks[{bid!r}]: unknown benchmark id (not in BENCHMARK_METADATA)")

    for d in catalog.get("deployments") or []:
        did = d.get("id") if isinstance(d, dict) else None
        if did not in VALID_DEPLOYMENT_MODES:
            errors.append(f"deployments[{did!r}]: must be in {sorted(VALID_DEPLOYMENT_MODES)}")

    errors.extend(_validate_defaults(catalog, platforms, benchmarks))
    errors.extend(_validate_agent_removed(catalog))
    errors.extend(_validate_mcp(catalog, known_tools, known_prompts))

    cli_templates = (catalog.get("templates") or {}).get("cli") or {}
    compare_tpl = cli_templates.get("compare") or ""
    if compare_tpl.count("--platform ") < 2:
        errors.append(f"templates.cli.compare must include two --platform flags (got: {compare_tpl!r})")

    test_one_tpl = cli_templates.get("test_one") or ""
    dry_run_tpl = cli_templates.get("dry_run") or ""
    dependency_tpl = cli_templates.get("dependency_check") or ""
    if " -p " in test_one_tpl or " -b " in test_one_tpl or " -s " in test_one_tpl:
        errors.append(f"templates.cli.test_one must use long run flags (got: {test_one_tpl!r})")
    if " -p " in dry_run_tpl or " -b " in dry_run_tpl or " -s " in dry_run_tpl:
        errors.append(f"templates.cli.dry_run must use long run flags (got: {dry_run_tpl!r})")
    if "--dry-run {dry_run_dir}" not in dry_run_tpl:
        errors.append(f"templates.cli.dry_run must include an explicit dry-run output dir (got: {dry_run_tpl!r})")
    if dependency_tpl != "uv run benchbox check-deps --platform {platform}":
        errors.append(f"templates.cli.dependency_check must call check-deps --platform (got: {dependency_tpl!r})")

    if FORBIDDEN_JSON.exists():
        errors.append(f"forbidden file present: {FORBIDDEN_JSON.relative_to(REPO_ROOT)}")

    return errors


def render_js(catalog: dict[str, Any]) -> str:
    """Render the catalog as a deterministic catalog.generated.js include."""
    payload = json.dumps(build_prompt_catalog(catalog), sort_keys=True, indent=2, ensure_ascii=False)
    return (
        "// AUTO-GENERATED by scripts/generate_landing_quickstarts.py. Do not edit by hand.\n"
        "// Edit landing/prompts/catalog.yaml and re-run the generator.\n"
        "window.__BENCHBOX_PROMPT_CATALOG__ = " + payload + ";\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--write",
        action="store_true",
        help="Regenerate landing/prompts/catalog.generated.js from catalog.yaml.",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail non-zero if regenerating would change catalog.generated.js.",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate catalog.yaml without writing or comparing the include.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=SOURCE,
        help="Path to catalog.yaml (default: landing/prompts/catalog.yaml).",
    )
    args = parser.parse_args(argv)

    catalog = load_catalog(args.source)
    errors = validate(catalog)
    if errors:
        for e in errors:
            print(f"validation error: {e}", file=sys.stderr)
        return 2

    if args.validate_only:
        print("validate-only: OK")
        return 0

    rendered = render_js(catalog)

    if args.check:
        existing = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if existing != rendered:
            print(
                f"check: {OUTPUT.relative_to(REPO_ROOT)} is stale; "
                "run `uv run -- python scripts/generate_landing_quickstarts.py --write` "
                "to regenerate.",
                file=sys.stderr,
            )
            return 3
        print("check: OK")
        return 0

    if args.write:
        OUTPUT.write_text(rendered, encoding="utf-8")
        print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}")
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
