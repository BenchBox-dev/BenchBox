"""Scan source for `import X` / `from X` for every declared dep.

w2 of the dependency audit. Emits a JSON map { package -> [file:line] } so
later steps can classify each dep as KEEP / FLAG-UNUSED / etc.

Walks benchbox/, scripts/, tests/, docs/ and parses Python files via the `ast`
module. ast is robust against multi-line `import` statements, conditional
imports inside try/except, and string-content false positives that grep would
hit. Markdown/.rst docs are scanned with regex since they may carry code blocks
demonstrating dependency usage.
"""

from __future__ import annotations

import ast
import json
import pathlib
import re
import sys
from collections import defaultdict

import tomllib

# Package-name → top-level import-name(s) mapping. Most packages match their
# install name, but several do not. Update this map whenever you discover a new
# mismatch. Values are *sets* of import-names; an import-site for any of them
# counts as a use of the package.
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
}


def strip_extras(name: str) -> str:
    return name.split("[", 1)[0]


def collect_declared(root: pathlib.Path) -> set[str]:
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    out: set[str] = set()
    for s in data["project"].get("dependencies", []):
        out.add(strip_extras(re.split(r"[><=!;@\[]", s.strip())[0].strip().lower()))
    for g in data["project"].get("optional-dependencies", {}).values():
        for s in g:
            if isinstance(s, str):
                out.add(strip_extras(re.split(r"[><=!;@\[]", s.strip())[0].strip().lower()))
    for g in data.get("dependency-groups", {}).values():
        for s in g:
            if isinstance(s, str):
                out.add(strip_extras(re.split(r"[><=!;@\[]", s.strip())[0].strip().lower()))
    out.discard("")
    return out


def import_to_top(s: str) -> str:
    return s.split(".", 1)[0]


def collect_python_imports(root: pathlib.Path, paths: list[str]) -> dict[str, list[str]]:
    """Return { dotted_module_prefix -> [file:line] } across all .py files.

    For `from X import a, b`, records both the bare `X` and the synthesized
    `X.a`, `X.b` to make per-package matching reliable for namespace packages
    like `google.cloud`.
    """
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
        rel = path.relative_to(root)
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


def collect_doc_mentions(root: pathlib.Path) -> dict[str, list[str]]:
    """Regex-scan docs/ for `import X` / `from X import` in code blocks."""
    out: dict[str, list[str]] = defaultdict(list)
    pat = re.compile(r"^\s*(?:from\s+([A-Za-z0-9_.]+)\s+import|import\s+([A-Za-z0-9_.]+))", re.MULTILINE)
    docs = root / "docs"
    if not docs.exists():
        return out
    for path in list(docs.rglob("*.md")) + list(docs.rglob("*.rst")):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel = path.relative_to(root)
        for m in pat.finditer(text):
            mod = m.group(1) or m.group(2) or ""
            line = text.count("\n", 0, m.start()) + 1
            out[mod].append(f"{rel}:{line}")
    return out


def package_uses(pkg: str, imports: dict[str, list[str]]) -> list[str]:
    """Find import-sites for a package using PKG_TO_IMPORTS or a sensible default."""
    candidates = PKG_TO_IMPORTS.get(pkg)
    if candidates is None:
        # Default heuristic: hyphens → underscores, take everything before any extras
        candidates = {pkg.replace("-", "_")}
    sites: list[str] = []
    for name in candidates:
        if name in imports:
            sites.extend(imports[name])
        # Also count any submodule that starts with this name
        prefix = name + "."
        for k, v in imports.items():
            if k.startswith(prefix):
                sites.extend(v)
    return sorted(set(sites))


def main() -> int:
    root = pathlib.Path(__file__).resolve().parents[2]
    declared = collect_declared(root)

    # benchbox/scripts/tests are runtime; docs/conf.py + docs/_static for build.
    py_imports = collect_python_imports(
        root, ["benchbox", "scripts", "tests", "docs/conf.py", "docs/_static"]
    )
    # _project/ tooling is captured separately so we can flag deps used only by tooling.
    tooling_imports = collect_python_imports(root, ["_project/scripts"])
    doc_imports = collect_doc_mentions(root)

    # Merge — docs are tracked separately for visibility
    all_imports: dict[str, list[str]] = defaultdict(list)
    for k, v in py_imports.items():
        all_imports[k].extend(v)
    for k, v in doc_imports.items():
        all_imports[k].extend(v)

    pkg_sites: dict[str, list[str]] = {}
    pkg_doc_only: dict[str, list[str]] = {}
    pkg_tooling_only: dict[str, list[str]] = {}
    for pkg in sorted(declared):
        py_only_sites = package_uses(pkg, py_imports)
        doc_sites = package_uses(pkg, doc_imports)
        tooling_sites = package_uses(pkg, tooling_imports)
        pkg_sites[pkg] = py_only_sites
        if doc_sites and not py_only_sites:
            pkg_doc_only[pkg] = doc_sites
        if tooling_sites and not py_only_sites and not doc_sites:
            pkg_tooling_only[pkg] = tooling_sites

    out_path = pathlib.Path(__file__).resolve().parent / "import_sites.json"
    out_path.write_text(
        json.dumps(
            {
                "py_sites": dict(pkg_sites.items()),
                "doc_only": pkg_doc_only,
                "tooling_only": pkg_tooling_only,
                "all_top_modules": sorted({import_to_top(k) for k in all_imports}),
                "py_top_modules": sorted({import_to_top(k) for k in py_imports}),
                "tooling_top_modules": sorted({import_to_top(k) for k in tooling_imports}),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # Print summary
    no_use = [
        p for p, sites in pkg_sites.items()
        if not sites and p not in pkg_doc_only and p not in pkg_tooling_only
    ]
    print(f"declared packages: {len(declared)}")
    print(f"packages with python import sites: {sum(1 for v in pkg_sites.values() if v)}")
    print(f"packages with only doc mentions:   {len(pkg_doc_only)}")
    print(f"packages with only tooling use:    {len(pkg_tooling_only)}")
    print(f"packages with no import sites:     {len(no_use)}")
    print()
    print("Packages with NO runtime/test/doc import sites (review for FLAG-UNUSED):")
    for p in no_use:
        print(f"  - {p}")
    if pkg_doc_only:
        print()
        print("Packages used ONLY in docs:")
        for p in pkg_doc_only:
            print(f"  - {p}")
    if pkg_tooling_only:
        print()
        print("Packages used ONLY by _project/scripts tooling:")
        for p in pkg_tooling_only:
            print(f"  - {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
