"""Dependency audit CI guard for BenchBox.

Fails (exit 1) when:
  (a) A declared package has zero import sites AND is not in either allowlist.
  (b) [Future] An imported top-level module is undeclared and not in the
      guarded-optional allowlist. (Not yet enabled — Phase 5.)

Usage:
    uv run -- python _project/scripts/dependency_audit/check_deps.py
    uv run -- python _project/scripts/dependency_audit/check_deps.py --help

Exit codes:
    0  All checks pass.
    1  One or more violations found.

See also:
    _project/scripts/dependency_audit/plugin_cli_allowlist.yaml
    _project/scripts/dependency_audit/guarded_optional_allowlist.yaml
    docs/development/dependency-inventory.md (Methodology section)
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from collections import defaultdict

import tomllib

try:
    import yaml
except ImportError:
    print("pyyaml is required. Run: uv run --project _project/scripts -- python check_deps.py", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Paths (all relative to the repo root, resolved at runtime)
# ---------------------------------------------------------------------------
_HERE = pathlib.Path(__file__).resolve().parent
_ROOT = _HERE.parents[2]  # BenchBox repo root

PLUGIN_CLI_ALLOWLIST = _HERE / "plugin_cli_allowlist.yaml"
GUARDED_OPTIONAL_ALLOWLIST = _HERE / "guarded_optional_allowlist.yaml"

# Scan targets: main source + test dirs (does NOT include _project/scripts/ —
# tooling-only imports belong in the isolated env, not the main manifest).
SCAN_PATHS = ["benchbox", "scripts", "tests", "docs/conf.py", "docs/_static"]

# ---------------------------------------------------------------------------
# Package → top-level import-name map.
# Must stay in sync with scan_imports.py and dependency-inventory.md.
# ---------------------------------------------------------------------------
PKG_TO_IMPORTS: dict[str, set[str]] = {
    "pyyaml": {"yaml"},
    "psycopg2-binary": {"psycopg2"},
    "google-cloud-bigquery": {"google.cloud.bigquery", "google.cloud.bigquery_storage"},
    "google-cloud-storage": {"google.cloud.storage"},
    "google-cloud-dataproc": {"google.cloud.dataproc_v1", "google.cloud.dataproc"},
    "snowflake-connector-python": {"snowflake.connector"},
    "snowflake-snowpark-python": {"snowflake.snowpark"},
    "azure-identity": {"azure.identity"},
    "azure-storage-file-datalake": {"azure.storage.filedatalake"},
    "databricks-sql-connector": {"databricks.sql"},
    "databricks-sdk": {"databricks.sdk"},
    "databricks-connect": {"databricks.connect"},
    "presto-python-client": {"prestodb"},
    "redshift-connector": {"redshift_connector"},
    "firebolt-sdk": {"firebolt"},
    "pillow": {"PIL"},
    "pyiceberg": {"pyiceberg"},
    "deltalake": {"deltalake"},
    "delta-spark": {"delta"},
    "pyspark": {"pyspark"},
    "polars": {"polars"},
    "modin": {"modin"},
    "dask": {"dask", "distributed"},
    "datafusion": {"datafusion"},
    "pyarrow": {"pyarrow"},
    "ablog": {"ablog"},
    "myst-parser": {"myst_parser"},
    "sphinx-tags": {"sphinx_tags"},
    "sphinx-design": {"sphinx_design"},
    "sphinxcontrib-mermaid": {"sphinxcontrib.mermaid"},
    "roman-numerals": {"roman_numerals"},
    "influxdb3-python": {"influxdb_client_3"},
    "pyathena": {"pyathena"},
    "trino": {"trino"},
    "pymysql": {"pymysql"},
    "pyodbc": {"pyodbc"},
    "singlestoredb": {"singlestoredb"},
    "databend-driver": {"databend_driver"},
    "vortex-data": {"vortex"},
    "textcharts": {"textcharts"},
    "tomli": {"tomli"},
    "ty": {"ty"},
    "ruff": {"ruff"},
    "tox": {"tox"},
    "mutmut": {"mutmut"},
    "codespell": {"codespell_lib"},
    "mcp": {"mcp"},
    "boto3": {"boto3", "botocore"},
    "cloudpathlib": {"cloudpathlib"},
    "click": {"click"},
    "rich": {"rich"},
    "psutil": {"psutil"},
    "pydantic": {"pydantic"},
    "packaging": {"packaging"},
    "jsonschema": {"jsonschema"},
    "numpy": {"numpy"},
    "zstandard": {"zstandard"},
    "sqlglot": {"sqlglot"},
    "duckdb": {"duckdb"},
    "clickhouse-driver": {"clickhouse_driver"},
    "clickhouse-connect": {"clickhouse_connect"},
    "chdb": {"chdb"},
    "pandas": {"pandas"},
    "pytest": {"pytest"},
    "pytest-cov": {"pytest_cov"},
    "pytest-benchmark": {"pytest_benchmark"},
    "pytest-xdist": {"xdist"},
    "pytest-timeout": {"pytest_timeout"},
    "requests": {"requests"},
    "sphinx": {"sphinx"},
    "furo": {"furo"},
    "pygments": {"pygments"},
    "sentence-transformers": {"sentence_transformers"},
    "torch": {"torch"},
    "textblob": {"textblob"},
    "spacy": {"spacy"},
    "ansi2html": {"ansi2html"},
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_extras(name: str) -> str:
    return name.split("[", 1)[0]


def _normalize(name: str) -> str:
    return _strip_extras(name).lower().replace("_", "-")


def _collect_declared(root: pathlib.Path) -> set[str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    out: set[str] = set()
    for s in data["project"].get("dependencies", []):
        out.add(_normalize(re.split(r"[><=!;@\[]", s.strip())[0].strip()))
    for g in data["project"].get("optional-dependencies", {}).values():
        for s in g:
            if isinstance(s, str):
                out.add(_normalize(re.split(r"[><=!;@\[]", s.strip())[0].strip()))
    for g in data.get("dependency-groups", {}).values():
        for s in g:
            if isinstance(s, str):
                out.add(_normalize(re.split(r"[><=!;@\[]", s.strip())[0].strip()))
    out.discard("")
    return out


def _collect_python_imports(root: pathlib.Path, paths: list[str]) -> dict[str, list[str]]:
    import ast

    out: dict[str, list[str]] = defaultdict(list)
    files: list[pathlib.Path] = []
    for p in paths:
        base = root / p
        if base.is_dir():
            files.extend(base.rglob("*.py"))
        elif base.is_file():
            files.append(base)
    for path in files:
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = str(path.relative_to(root))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    out[a.name].append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                if node.module and node.level == 0:
                    out[node.module].append(f"{rel}:{node.lineno}")
                    for a in node.names:
                        if a.name != "*":
                            out[f"{node.module}.{a.name}"].append(f"{rel}:{node.lineno}")
    return out


def _package_uses(pkg: str, imports: dict[str, list[str]]) -> list[str]:
    candidates = PKG_TO_IMPORTS.get(pkg)
    if candidates is None:
        candidates = {pkg.replace("-", "_")}
    sites: list[str] = []
    for name in candidates:
        if name in imports:
            sites.extend(imports[name])
        prefix = name + "."
        for k, v in imports.items():
            if k.startswith(prefix):
                sites.extend(v)
    return sorted(set(sites))


def _load_allowlist(path: pathlib.Path) -> set[str]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {_normalize(k) for k in data}


# ---------------------------------------------------------------------------
# Main check
# ---------------------------------------------------------------------------

def run_check(root: pathlib.Path, verbose: bool = False) -> int:
    plugin_allow = _load_allowlist(PLUGIN_CLI_ALLOWLIST)
    guarded_allow = _load_allowlist(GUARDED_OPTIONAL_ALLOWLIST)
    all_allowed = plugin_allow | guarded_allow

    declared = _collect_declared(root)
    imports = _collect_python_imports(root, SCAN_PATHS)

    violations: list[str] = []
    ok_count = 0
    allowed_count = 0

    for pkg in sorted(declared):
        sites = _package_uses(pkg, imports)
        if sites:
            ok_count += 1
            if verbose:
                print(f"  OK  {pkg} ({len(sites)} import sites)")
        elif pkg in all_allowed:
            allowed_count += 1
            if verbose:
                list_name = "plugin/CLI" if pkg in plugin_allow else "guarded-optional"
                print(f"  OK  {pkg} (allowlisted: {list_name})")
        else:
            violations.append(pkg)

    print(f"Dependency audit: {len(declared)} declared, {ok_count} with import sites, "
          f"{allowed_count} allowlisted, {len(violations)} violations")

    if violations:
        print("\nVIOLATIONS — declared packages with zero import sites (not allowlisted):")
        for v in violations:
            print(f"  - {v}")
        print(
            "\nFor each violation, either:\n"
            "  (a) Remove the declaration from pyproject.toml if the package is unused, or\n"
            "  (b) Add it to plugin_cli_allowlist.yaml (CLI/plugin tools), or\n"
            "  (c) Add it to guarded_optional_allowlist.yaml (guarded try/except imports).\n"
            "\nSee docs/development/dependency-inventory.md for guidance."
        )
        return 1

    print("All checks passed.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check declared deps against import sites. Fails if any unused dep is found.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show all packages, not just violations.")
    parser.add_argument("--root", type=pathlib.Path, default=_ROOT, help="Repo root (default: auto-detected).")
    args = parser.parse_args()

    return run_check(root=args.root, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
