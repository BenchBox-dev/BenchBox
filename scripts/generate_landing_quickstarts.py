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
import json
import sys
from pathlib import Path
from typing import Any

import yaml

from benchbox.core.benchmark_registry import BENCHMARK_METADATA
from benchbox.core.platform_registry import PlatformRegistry

REPO_ROOT = Path(__file__).resolve().parent.parent
SOURCE = REPO_ROOT / "landing" / "prompts" / "catalog.yaml"
OUTPUT = REPO_ROOT / "landing" / "prompts" / "catalog.generated.js"
FORBIDDEN_JSON = REPO_ROOT / "landing" / "prompts" / "recipes.json"

VALID_DEPLOYMENT_MODES = frozenset({"local", "self-hosted", "managed"})
MANAGED_SAFETY_KEYS = frozenset({"dependency", "dry_run", "no_secrets"})


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
    ifaces = entry.get("interfaces") or []
    if not ifaces:
        errors.append(f"platforms[{pid!r}]: at least one interface is required")
    for iface in ifaces:
        if iface not in {"sql", "dataframe"}:
            errors.append(f"platforms[{pid!r}].interfaces={iface!r}: must be 'sql' or 'dataframe'")
    return errors


def _validate_defaults(catalog: dict[str, Any], platform_ids: set[str], benchmark_ids: set[str]) -> list[str]:
    errors: list[str] = []
    defaults = catalog.get("defaults") or {}
    if defaults.get("platform") not in platform_ids:
        errors.append(f"defaults.platform={defaults.get('platform')!r}: not in platforms[]")
    if defaults.get("benchmark") not in benchmark_ids:
        errors.append(f"defaults.benchmark={defaults.get('benchmark')!r}: not in benchmarks[]")
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


def _validate_agents(catalog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for entry in catalog.get("agents") or []:
        if not isinstance(entry, dict):
            errors.append(f"agents[] entries must be mappings, got {type(entry).__name__}")
            continue
        label = str(entry.get("label") or "")
        if "manual" in label.lower():
            errors.append(f"agents[{entry.get('id')!r}].label must not contain 'manual'")
    return errors


def validate(catalog: dict[str, Any]) -> list[str]:
    """Return a list of validation error messages; empty means valid."""
    errors: list[str] = []
    known_platforms = set(PlatformRegistry.get_all_platform_metadata().keys())
    known_benchmarks = set(BENCHMARK_METADATA.keys())
    known_tools, known_prompts = _known_mcp_names()

    platforms = catalog.get("platforms") or []
    platform_ids = {p["id"] for p in platforms if isinstance(p, dict) and "id" in p}
    for entry in platforms:
        errors.extend(_validate_one_platform(entry, known_platforms))

    benchmarks = catalog.get("benchmarks") or []
    benchmark_ids = {b["id"] for b in benchmarks if isinstance(b, dict) and "id" in b}
    for entry in benchmarks:
        bid = entry.get("id")
        if bid not in known_benchmarks:
            errors.append(f"benchmarks[{bid!r}]: unknown benchmark id (not in BENCHMARK_METADATA)")

    for d in catalog.get("deployments") or []:
        did = d.get("id") if isinstance(d, dict) else None
        if did not in VALID_DEPLOYMENT_MODES:
            errors.append(f"deployments[{did!r}]: must be in {sorted(VALID_DEPLOYMENT_MODES)}")

    errors.extend(_validate_defaults(catalog, platform_ids, benchmark_ids))
    errors.extend(_validate_agents(catalog))
    errors.extend(_validate_mcp(catalog, known_tools, known_prompts))

    compare_tpl = ((catalog.get("templates") or {}).get("cli") or {}).get("compare") or ""
    if compare_tpl.count("-p ") < 2:
        errors.append(f"templates.cli.compare must include two -p flags (got: {compare_tpl!r})")

    if FORBIDDEN_JSON.exists():
        errors.append(f"forbidden file present: {FORBIDDEN_JSON.relative_to(REPO_ROOT)}")

    return errors


def render_js(catalog: dict[str, Any]) -> str:
    """Render the catalog as a deterministic catalog.generated.js include."""
    payload = json.dumps(catalog, sort_keys=True, indent=2, ensure_ascii=False)
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
