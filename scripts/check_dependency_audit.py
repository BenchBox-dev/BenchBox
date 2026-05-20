"""Release-visible dependency audit for BenchBox.

Checks both directions that matter for release safety:

* declared-but-unused: a package appears in pyproject.toml but has no import
  sites and is not an explicit CLI/plugin/guarded-optional exception.
* imported-but-undeclared: source imports a third-party module that has no
  matching pyproject.toml declaration.
"""

from __future__ import annotations

import argparse
import ast
import functools
import importlib.metadata
import pathlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10 only.
    import tomli as tomllib  # type: ignore[import-not-found, no-redef]

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCAN_PATHS = ("benchbox", "scripts", "tests", "docs/conf.py", "docs/_static")
LOCAL_IMPORT_ROOTS = frozenset({"benchbox", "scripts", "tests", "docs"})
LOCAL_PATH_IMPORT_DIRS = ("scripts", "examples", "tests/utilities")
STDLIB_MODULES = frozenset(getattr(sys, "stdlib_module_names", ()))

# Distribution name -> import module candidates. Most dependencies import as
# their normalized package name with '-' replaced by '_'; this table covers
# mismatches and namespace packages.
PKG_TO_IMPORTS: dict[str, set[str]] = {
    "ablog": {"ablog"},
    "ansi2html": {"ansi2html"},
    "azure-identity": {"azure.identity"},
    "azure-storage-file-datalake": {"azure.storage.filedatalake"},
    "boto3": {"boto3", "botocore"},
    "chdb": {"chdb"},
    "click": {"click"},
    "clickhouse-connect": {"clickhouse_connect"},
    "clickhouse-driver": {"clickhouse_driver"},
    "cloudpathlib": {"cloudpathlib"},
    "codespell": {"codespell_lib"},
    "dask": {"dask", "distributed"},
    "databend-driver": {"databend_driver"},
    "databricks-connect": {"databricks.connect"},
    "databricks-sdk": {"databricks.sdk"},
    "databricks-sql-connector": {"databricks.sql"},
    "datafusion": {"datafusion"},
    "deltalake": {"deltalake"},
    "delta-spark": {"delta"},
    "duckdb": {"duckdb"},
    "firebolt-sdk": {"firebolt"},
    "furo": {"furo"},
    "google-cloud-bigquery": {"google.cloud.bigquery", "google.cloud.bigquery_storage"},
    "google-cloud-dataproc": {"google.cloud.dataproc", "google.cloud.dataproc_v1"},
    "google-cloud-storage": {"google.cloud.storage"},
    "influxdb3-python": {"influxdb_client_3"},
    "keyring": {"keyring"},
    "mcp": {"mcp"},
    "modin": {"modin"},
    "mutmut": {"mutmut"},
    "myst-parser": {"myst_parser"},
    "numpy": {"numpy"},
    "packaging": {"packaging"},
    "pandas": {"pandas"},
    "pillow": {"PIL"},
    "polars": {"polars"},
    "presto-python-client": {"prestodb"},
    "psutil": {"psutil"},
    "psycopg": {"psycopg"},
    "psycopg2-binary": {"psycopg2"},
    "pyarrow": {"pyarrow"},
    "pyathena": {"pyathena"},
    "pydantic": {"pydantic"},
    "pygments": {"pygments"},
    "pyiceberg": {"pyiceberg"},
    "pymysql": {"pymysql"},
    "pyodbc": {"pyodbc"},
    "pyspark": {"pyspark"},
    "pytest": {"pytest"},
    "pytest-benchmark": {"pytest_benchmark"},
    "pytest-cov": {"coverage", "pytest_cov"},
    "pytest-timeout": {"pytest_timeout"},
    "pytest-xdist": {"xdist"},
    "pyyaml": {"yaml"},
    "redshift-connector": {"redshift_connector"},
    "requests": {"requests"},
    "roman-numerals": {"roman_numerals"},
    "ruff": {"ruff"},
    "sentence-transformers": {"sentence_transformers"},
    "singlestoredb": {"singlestoredb"},
    "snowflake-connector-python": {"snowflake.connector"},
    "snowflake-snowpark-python": {"snowflake.snowpark"},
    "spacy": {"spacy"},
    "sphinx": {"sphinx"},
    "sphinx-design": {"sphinx_design"},
    "sphinx-tags": {"sphinx_tags"},
    "sphinxcontrib-mermaid": {"sphinxcontrib.mermaid"},
    "sqlglot": {"sqlglot"},
    "textblob": {"textblob"},
    "textcharts": {"textcharts"},
    "tomli": {"tomli"},
    "torch": {"torch"},
    "tox": {"tox"},
    "trino": {"trino"},
    "ty": {"ty"},
    "vortex-data": {"vortex"},
    "zstandard": {"zstandard"},
}

DECLARED_WITHOUT_IMPORT_ALLOWLIST = frozenset(
    {
        # pytest plugins and test/development CLIs.
        "codespell",
        "mutmut",
        "pre-commit",
        "pytest",
        "pytest-benchmark",
        "pytest-cov",
        "pytest-timeout",
        "pytest-xdist",
        "ruff",
        "tox",
        "ty",
        # Sphinx/theme plugins loaded from config instead of direct imports.
        "ablog",
        "furo",
        "myst-parser",
        "roman-numerals",
        "sphinx-design",
        "sphinx-tags",
        "sphinxcontrib-mermaid",
        # Forward declarations for optional GPU placeholders.
        "cudf",
        "cuml",
        "cupy",
    }
)

IMPORTED_WITHOUT_DECLARATION_ALLOWLIST = frozenset(
    {
        # Optional platform/tooling imports that are guarded at runtime or
        # supplied by platform-specific installation channels.
        "chardet",
        "cryptography",
        "cudf",
        "cugraph",
        "cuml",
        "cupy",
        "dask_cudf",
        "dask_sql",
        "flightsql",
        "importlib_metadata",
        "influxdb3",
        "pygments_cobalt2",
        "pynvml",
        "pysail",
        "ray",
        "rmm",
        "urllib3",
    }
)


@dataclass(frozen=True)
class AuditResult:
    declared_count: int
    imported_count: int
    declared_with_import_sites: int
    allowed_declared_without_import: set[str]
    declared_without_import: dict[str, list[str]]
    imported_without_declaration: dict[str, list[str]]

    @property
    def passed(self) -> bool:
        return not self.declared_without_import and not self.imported_without_declaration


def _normalize_name(name: str) -> str:
    return name.split("[", 1)[0].lower().replace("_", "-")


def _requirement_name(spec: str) -> str:
    match = re.match(r"^\s*([A-Za-z0-9_.-]+)", spec)
    return _normalize_name(match.group(1)) if match else ""


def collect_declared(root: pathlib.Path) -> set[str]:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    declared: set[str] = set()

    for entry in pyproject.get("project", {}).get("dependencies", []):
        declared.add(_requirement_name(entry))
    for entries in pyproject.get("project", {}).get("optional-dependencies", {}).values():
        for entry in entries:
            if isinstance(entry, str):
                declared.add(_requirement_name(entry))
    for entries in pyproject.get("dependency-groups", {}).values():
        for entry in entries:
            if isinstance(entry, str):
                declared.add(_requirement_name(entry))

    declared.discard("")
    return declared


def _iter_python_files(root: pathlib.Path, paths: Iterable[str]) -> Iterable[pathlib.Path]:
    for item in paths:
        path = root / item
        if path.is_dir():
            yield from path.rglob("*.py")
        elif path.is_file():
            yield path


def collect_python_imports(root: pathlib.Path, paths: Iterable[str]) -> dict[str, list[str]]:
    imports: dict[str, list[str]] = defaultdict(list)
    for path in _iter_python_files(root, paths):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue

        rel = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports[alias.name].append(f"{rel}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports[node.module].append(f"{rel}:{node.lineno}")
                for alias in node.names:
                    if alias.name != "*":
                        imports[f"{node.module}.{alias.name}"].append(f"{rel}:{node.lineno}")

    return {module: sorted(set(sites)) for module, sites in imports.items()}


def _import_candidates(package: str) -> set[str]:
    return PKG_TO_IMPORTS.get(package, {package.replace("-", "_")})


def _module_matches_candidate(module: str, candidate: str) -> bool:
    return module == candidate or module.startswith(f"{candidate}.") or candidate.startswith(f"{module}.")


def _package_import_sites(package: str, imports: dict[str, list[str]]) -> list[str]:
    sites: list[str] = []
    for candidate in _import_candidates(package):
        for module, module_sites in imports.items():
            if _module_matches_candidate(module, candidate):
                sites.extend(module_sites)
    return sorted(set(sites))


def _declared_import_candidates(declared: set[str]) -> set[str]:
    candidates: set[str] = set()
    for package in declared:
        candidates.update(_import_candidates(package))
    return candidates


def _local_import_roots(root: pathlib.Path, scan_paths: Iterable[str]) -> set[str]:
    roots = set(LOCAL_IMPORT_ROOTS)

    for child in root.iterdir():
        if child.name.startswith("."):
            continue
        if child.is_file() and child.suffix == ".py":
            roots.add(child.stem)
        elif child.is_dir() and any(child.rglob("*.py")):
            roots.add(child.name)

    for item in scan_paths:
        path = root / item
        if path.is_file() and path.suffix == ".py":
            roots.add(path.stem)
        elif path.is_dir():
            roots.add(path.name)
            roots.update(child.name for child in path.iterdir() if child.is_dir() and (child / "__init__.py").exists())

    for item in LOCAL_PATH_IMPORT_DIRS:
        path = root / item
        if path.is_dir():
            roots.update(child.stem for child in path.rglob("*.py"))

    return roots


def _is_local_or_stdlib(module: str, local_roots: set[str]) -> bool:
    root = module.split(".", 1)[0]
    return root in local_roots or root in STDLIB_MODULES or root.startswith("_")


@functools.cache
def _packages_distributions() -> dict[str, list[str]]:
    return importlib.metadata.packages_distributions()


def _declared_by_installed_distribution(module: str, declared: set[str]) -> bool:
    root = module.split(".", 1)[0]
    distributions = _packages_distributions().get(root, ())
    return bool({_normalize_name(distribution) for distribution in distributions} & declared)


def _is_declared_import(module: str, declared: set[str], declared_candidates: set[str]) -> bool:
    if any(_module_matches_candidate(module, candidate) for candidate in declared_candidates):
        return True
    return _declared_by_installed_distribution(module, declared)


def audit_dependencies(root: pathlib.Path, scan_paths: Iterable[str] = SCAN_PATHS) -> AuditResult:
    scan_paths = tuple(scan_paths)
    declared = collect_declared(root)
    imports = collect_python_imports(root, scan_paths)

    declared_without_import: dict[str, list[str]] = {}
    allowed_declared_without_import: set[str] = set()
    declared_with_import_sites = 0
    for package in sorted(declared):
        sites = _package_import_sites(package, imports)
        if sites:
            declared_with_import_sites += 1
        elif package in DECLARED_WITHOUT_IMPORT_ALLOWLIST:
            allowed_declared_without_import.add(package)
        else:
            declared_without_import[package] = []

    declared_candidates = _declared_import_candidates(declared)
    local_roots = _local_import_roots(root, scan_paths)
    imported_without_declaration: dict[str, list[str]] = defaultdict(list)
    for module, sites in sorted(imports.items()):
        import_root = module.split(".", 1)[0]
        if (
            _is_local_or_stdlib(module, local_roots)
            or import_root in IMPORTED_WITHOUT_DECLARATION_ALLOWLIST
            or _is_declared_import(module, declared, declared_candidates)
        ):
            continue
        imported_without_declaration[import_root].extend(sites)
    imported_without_declaration = {
        module: sorted(set(sites)) for module, sites in sorted(imported_without_declaration.items())
    }

    return AuditResult(
        declared_count=len(declared),
        imported_count=len(imports),
        declared_with_import_sites=declared_with_import_sites,
        allowed_declared_without_import=allowed_declared_without_import,
        declared_without_import=declared_without_import,
        imported_without_declaration=imported_without_declaration,
    )


def print_report(result: AuditResult, *, verbose: bool = False) -> None:
    print(
        "Dependency audit: "
        f"{result.declared_count} declared, "
        f"{result.declared_with_import_sites} with import sites, "
        f"{len(result.allowed_declared_without_import)} allowlisted without import sites, "
        f"{len(result.declared_without_import)} declared-but-unused violations, "
        f"{len(result.imported_without_declaration)} imported-but-undeclared violations"
    )

    if verbose and result.allowed_declared_without_import:
        print("\nAllowlisted declarations with no import sites:")
        for package in sorted(result.allowed_declared_without_import):
            print(f"  - {package}")

    if result.declared_without_import:
        print("\nVIOLATIONS - declared packages with zero import sites and no allowlist:")
        for package in sorted(result.declared_without_import):
            print(f"  - {package}")

    if result.imported_without_declaration:
        print("\nVIOLATIONS - imported modules with no matching dependency declaration:")
        for module, sites in result.imported_without_declaration.items():
            print(f"  - {module}")
            if verbose:
                for site in sites:
                    print(f"      {site}")

    if result.passed:
        print("All checks passed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check BenchBox dependency declarations against import sites.")
    parser.add_argument("--root", type=pathlib.Path, default=ROOT, help="Repo root (default: auto-detected).")
    parser.add_argument("--scan-path", action="append", dest="scan_paths", help="Path to scan; may be repeated.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show allowlisted packages and violation sites.")
    args = parser.parse_args(argv)

    result = audit_dependencies(args.root, args.scan_paths or SCAN_PATHS)
    print_report(result, verbose=args.verbose)
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
