"""Compatibility inventory tool for BenchBox.

Walks benchbox/ source files and enumerates every dialect-branching
compatibility decision point. Outputs _project/compat/inventory.jsonl with
one JSON record per site:

    {"file": "...", "line": N, "kind": "...", "platforms": [...],
     "suggested_phase": "...", "description": "..."}

Kinds:
    skip             - query or benchmark skip decision
    rewrite          - query text rewrite (AST or string transform)
    ddl              - DDL modification (CREATE TABLE, PK handling)
    type_mapping     - legitimate local type mapping (compat_local)
    session_setting  - session policy (emitted before query)
    benchmark_gate   - pre-run platform×benchmark compatibility check

Usage:
    uv run -- python -m benchbox.sql_compat.inventory [--root BENCHBOX_DIR]
    uv run -- python -m benchbox.sql_compat.inventory --output PATH
"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Literal

CompatKind = Literal["skip", "rewrite", "ddl", "type_mapping", "session_setting", "benchmark_gate"]

_DIALECT_PLATFORMS = {
    "duckdb",
    "clickhouse",
    "starrocks",
    "datafusion",
    "snowflake",
    "bigquery",
    "spark",
    "redshift",
    "postgresql",
    "postgres",
    "sqlite",
    "mysql",
    "trino",
    "timescale",
    "timescaledb",
    "influxdb",
    "lakesail",
    "polars",
    "pandas",
    "motherduck",
    "firebolt",
    "netezza",
    "greenplum",
    "vertica",
}

# Functions whose existence at definition-site marks a compatibility decision.
_SKIP_FUNC_NAMES = {"get_platform_skip_queries", "get_df_platform_skip_queries"}
_DDL_FUNC_NAMES = {"_supports_primary_keys"}
_REWRITE_FUNC_NAMES = {
    "_inject_missing_subquery_aliases",
    "add_subquery_aliases",
    "add_query_settings",
}
# Names that mark an adapter as performing DDL optimization. New adapters should
# prefer one of the canonical names (_optimize_table_definition,
# _transform_create_statement); custom names are listed here so the drift checker
# stays accurate. If you add a new custom-named DDL transformer, add it here AND
# register a Phase.DDL_OPTIMIZE rule for the platform.
_DDL_OPTIMIZE_FUNC_NAMES = {
    "_optimize_table_definition",
    "_transform_create_statement",  # SingleStore: uses BaseDdlOptimizer dispatch instead
    "_inject_doris_ddl_clauses",  # Doris: monolithic transform (PK + FK + type maps + clauses)
    "_strip_pk_constraints",  # QuestDB: PK strip path
}
_TYPE_MAP_FUNC_NAMES = {"_map_type_to_dialect"}

# Map adapter file stems → registry platform keys (only needed for exceptions to the rule
# "stem == platform_key").  Nested adapter files (workload.py, adapter.py) use parent-dir name.
# The matching rule files are named after the platform_key (synapse_ddl_rewrites.py,
# fabric_dw_ddl_rewrites.py) so BaseDdlOptimizer's f"{platform_key}_ddl_rewrites" lookup works.
_FILE_STEM_TO_PLATFORM_KEY: dict[str, str] = {
    "azure_synapse": "synapse",
    "fabric_warehouse": "fabric_dw",
}

# Regex for session-setting patterns (grep over raw source)
_SESSION_SETTING_RES = [
    re.compile(r"SETTINGS\s+\w+\s*=\s*\d+"),  # ClickHouse SETTINGS clause
    re.compile(r"joined_subquery_requires_alias"),  # ClickHouse known setting
    re.compile(r"SET\s+enable_result_cache"),  # Redshift cache control
]

# Class-level query variant constants: _PLATFORM_Qn (e.g. _CLICKHOUSE_Q9)
_VARIANT_CONST_RE = re.compile(r"^_([A-Z]+)_Q(\d+)$")

# QUERY_VARIANTS dict name
_QUERY_VARIANTS_NAME = "QUERY_VARIANTS"


@dataclass
class InventoryEntry:
    file: str
    line: int
    kind: CompatKind
    platforms: list[str]
    suggested_phase: str
    description: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_string_literals(node: ast.expr) -> list[str]:
    """Collect all string literal values from a node tree."""
    result = []
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            result.append(child.value.lower())
    return result


def _extract_platforms(node: ast.expr) -> list[str]:
    """Extract platform names from a comparison value (tuple, list, or constant)."""
    strings = _extract_string_literals(node)
    return sorted({s for s in strings if s in _DIALECT_PLATFORMS})


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root.parent))


# ---------------------------------------------------------------------------
# AST-based detectors
# ---------------------------------------------------------------------------


def _detect_dialect_branches(tree: ast.Module, filepath: Path, root: Path) -> Iterator[InventoryEntry]:
    """Find `if dialect in (...)` / `if dialect == "..."` / `if "x" in dialect` patterns."""
    rel = _rel(filepath, root)

    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test

        # if dialect in ("a", "b", ...)  or  if dialect == "a"
        if isinstance(test, ast.Compare) and len(test.ops) == 1:
            left = test.left
            comparators = test.comparators

            # dialect in (...)  or  dialect == "x"
            if isinstance(left, ast.Name) and left.id == "dialect":
                op = test.ops[0]
                if isinstance(op, (ast.In, ast.Eq)):
                    platforms = _extract_platforms(comparators[0])
                    if platforms:
                        # Classify: inside _map_type_to_dialect → type_mapping, else ddl or skip
                        kind: CompatKind = "ddl"
                        suggested = "schema_emit"
                        yield InventoryEntry(
                            file=rel,
                            line=node.lineno,
                            kind=kind,
                            platforms=platforms,
                            suggested_phase=suggested,
                            description=f"Dialect branch: dialect {'in' if isinstance(op, ast.In) else '=='} {platforms}",
                        )
                        continue

            # "platform_name" in dialect  or  "platform_name" in x.lower()
            for comp in comparators:
                if isinstance(comp, ast.Name) and comp.id == "dialect":
                    plats = _extract_platforms(left)
                    if plats:
                        yield InventoryEntry(
                            file=rel,
                            line=node.lineno,
                            kind="ddl",
                            platforms=plats,
                            suggested_phase="schema_emit",
                            description=f"Dialect membership check: {plats} in dialect",
                        )

        # if "clickhouse" in dialect.lower() etc.
        if isinstance(test, ast.Call):
            continue  # handled via containment in comparators above

        # BoolOp: if dialect == "a" or dialect == "b"
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            platforms: list[str] = []
            for val in test.values:
                if isinstance(val, ast.Compare) and isinstance(val.ops[0], ast.Eq):
                    if isinstance(val.left, ast.Name) and val.left.id == "dialect":
                        platforms.extend(_extract_platforms(val.comparators[0]))
            platforms = sorted(set(platforms))
            if platforms:
                yield InventoryEntry(
                    file=rel,
                    line=node.lineno,
                    kind="ddl",
                    platforms=platforms,
                    suggested_phase="schema_emit",
                    description=f"Dialect OR-branch: {platforms}",
                )


def _detect_named_functions(tree: ast.Module, filepath: Path, root: Path) -> Iterator[InventoryEntry]:
    """Detect known compatibility function definitions."""
    rel = _rel(filepath, root)

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        name = node.name

        if name in _SKIP_FUNC_NAMES:
            # Extract platform names from string constants in the function body
            platforms = sorted(
                {
                    s.lower()
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                    for s in [child.value.lower()]
                    if s in _DIALECT_PLATFORMS
                }
            )
            is_df = "df" in name
            yield InventoryEntry(
                file=rel,
                line=node.lineno,
                kind="skip",
                platforms=platforms,
                suggested_phase="dataframe_filter" if is_df else "execution_filter",
                description=f"Skip-query predicate: {name}()",
            )

        elif name in _DDL_FUNC_NAMES:
            platforms = sorted(
                {
                    s.lower()
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                    for s in [child.value.lower()]
                    if s in _DIALECT_PLATFORMS
                }
            )
            yield InventoryEntry(
                file=rel,
                line=node.lineno,
                kind="ddl",
                platforms=platforms,
                suggested_phase="schema_emit",
                description=f"PK support predicate: {name}()",
            )

        elif name in _REWRITE_FUNC_NAMES:
            yield InventoryEntry(
                file=rel,
                line=node.lineno,
                kind="session_setting" if name == "add_query_settings" else "rewrite",
                platforms=[],
                suggested_phase="query_adapter",
                description=f"Query rewrite / session policy function: {name}()",
            )

        elif name in _DDL_OPTIMIZE_FUNC_NAMES:
            yield InventoryEntry(
                file=rel,
                line=node.lineno,
                kind="ddl",
                platforms=[],
                suggested_phase="ddl_optimize",
                description=f"DDL optimization function: {name}()",
            )

        elif name in _TYPE_MAP_FUNC_NAMES:
            platforms = sorted(
                {
                    s.lower()
                    for child in ast.walk(node)
                    if isinstance(child, ast.Constant) and isinstance(child.value, str)
                    for s in [child.value.lower()]
                    if s in _DIALECT_PLATFORMS
                }
            )
            yield InventoryEntry(
                file=rel,
                line=node.lineno,
                kind="type_mapping",
                platforms=platforms,
                suggested_phase="schema_emit",
                description=f"Legitimate type-mapping function: {name}()",
            )


def _detect_query_variants(tree: ast.Module, filepath: Path, root: Path) -> Iterator[InventoryEntry]:
    """Detect QUERY_VARIANTS dict assignments (non-sqlglot multi-platform query source).

    Handles both plain assignment (ast.Assign) and annotated assignment
    (ast.AnnAssign: ``QUERY_VARIANTS: dict[...] = {...}``).
    """
    rel = _rel(filepath, root)

    def _check_assign(target_name: str, value_node: ast.expr | None, lineno: int) -> InventoryEntry | None:
        if target_name != _QUERY_VARIANTS_NAME or value_node is None:
            return None
        platforms: list[str] = []
        if isinstance(value_node, ast.Dict):
            for key in value_node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    k = key.value.lower()
                    if k in _DIALECT_PLATFORMS:
                        platforms.append(k)
        platforms = sorted(set(platforms))
        return InventoryEntry(
            file=rel,
            line=lineno,
            kind="rewrite",
            platforms=platforms,
            suggested_phase="query_source",
            description=f"QUERY_VARIANTS: per-platform SQL variant dict ({len(platforms)} platforms)",
        )

    for node in ast.walk(tree):
        # Plain assignment: QUERY_VARIANTS = {...}
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    entry = _check_assign(target.id, node.value, node.lineno)
                    if entry:
                        yield entry
        # Annotated assignment: QUERY_VARIANTS: dict[...] = {...}
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name):
                entry = _check_assign(node.target.id, node.value, node.lineno)
                if entry:
                    yield entry


def _detect_platform_query_constants(tree: ast.Module, filepath: Path, root: Path) -> Iterator[InventoryEntry]:
    """Detect class-level _PLATFORM_Qn constants (pre-written variant SQL)."""
    rel = _rel(filepath, root)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, ast.Assign):
                continue
            for target in item.targets:
                if not isinstance(target, ast.Name):
                    continue
                m = _VARIANT_CONST_RE.match(target.id)
                if m:
                    platform = m.group(1).lower()
                    qid = m.group(2)
                    yield InventoryEntry(
                        file=rel,
                        line=item.lineno,
                        kind="rewrite",
                        platforms=[platform],
                        suggested_phase="query_source",
                        description=f"Class-level variant constant {target.id} - Q{qid} for {platform}",
                    )


def _detect_unsupported_benchmarks(tree: ast.Module, filepath: Path, root: Path) -> Iterator[InventoryEntry]:
    """Detect unsupported_benchmarks dict (benchmark_gate)."""
    rel = _rel(filepath, root)

    for node in ast.walk(tree):
        # Dict literal with "unsupported_benchmarks" key
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and key.value == "unsupported_benchmarks":
                    yield InventoryEntry(
                        file=rel,
                        line=key.lineno,
                        kind="benchmark_gate",
                        platforms=[],
                        suggested_phase="benchmark_gate",
                        description="unsupported_benchmarks dict entry in platform capabilities",
                    )
        # Field access: caps.unsupported_benchmarks
        if isinstance(node, ast.Attribute) and node.attr == "unsupported_benchmarks":
            yield InventoryEntry(
                file=rel,
                line=node.lineno,
                kind="benchmark_gate",
                platforms=[],
                suggested_phase="benchmark_gate",
                description="caps.unsupported_benchmarks access - benchmark_gate preflight",
            )


# ---------------------------------------------------------------------------
# Regex-based detectors (source-level)
# ---------------------------------------------------------------------------


def _docstring_line_ranges(tree: ast.Module) -> set[int]:
    """Return the set of 1-based line numbers that are inside string literals used as docstrings.

    Covers module, class, and function docstrings (first statement is ast.Expr(Constant(str))).
    Uses end_lineno so multi-line docstrings are fully excluded.
    """
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.body:
            continue
        first = node.body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
            and hasattr(first, "end_lineno")
        ):
            for ln in range(first.lineno, first.end_lineno + 1):  # type: ignore[attr-defined]
                docstring_lines.add(ln)
    return docstring_lines


def _detect_session_settings(
    source: str, filepath: Path, root: Path, docstring_lines: set[int] | None = None
) -> Iterator[InventoryEntry]:
    """Find session-policy patterns via regex. Skips comments and docstring interiors."""
    rel = _rel(filepath, root)
    lines = source.splitlines()
    excluded = docstring_lines or set()
    for lineno, line in enumerate(lines, 1):
        if lineno in excluded:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pattern in _SESSION_SETTING_RES:
            if pattern.search(line):
                yield InventoryEntry(
                    file=rel,
                    line=lineno,
                    kind="session_setting",
                    platforms=[],
                    suggested_phase="query_adapter",
                    description=f"Session policy pattern: {stripped[:80]}",
                )
                break  # one entry per line


def _detect_dataframe_skip_calls(source: str, filepath: Path, root: Path) -> Iterator[InventoryEntry]:
    """Find get_platform_skip_queries / get_df_platform_skip_queries call sites."""
    rel = _rel(filepath, root)
    lines = source.splitlines()
    call_re = re.compile(r"(get_platform_skip_queries|get_df_platform_skip_queries)\s*\(")
    for lineno, line in enumerate(lines, 1):
        if line.strip().startswith("#"):
            continue
        m = call_re.search(line)
        if m:
            is_df = "df" in m.group(1)
            yield InventoryEntry(
                file=rel,
                line=lineno,
                kind="skip",
                platforms=[],
                suggested_phase="dataframe_filter" if is_df else "execution_filter",
                description=f"Call site: {m.group(1)}() - skip-query lookup",
            )


# ---------------------------------------------------------------------------
# Main scan
# ---------------------------------------------------------------------------


def _should_scan(path: Path) -> bool:
    parts = path.parts
    return (
        path.suffix == ".py"
        and "__pycache__" not in parts
        and ".git" not in parts
        and "sql_compat" not in parts  # don't scan the inventory itself
        and not path.stem.startswith("test_")
        and path.stem != "conftest"
    )


def _reclassify_inside_type_mapping(entries: list[InventoryEntry], tree: ast.Module, rel: str) -> None:
    """Promote ddl entries inside _map_type_to_dialect to type_mapping.

    Dialect branches inside a known type-mapping function are legitimate local
    rendering, not compatibility policy. Uses end_lineno (Python 3.8+) to
    determine function scope.
    """
    ranges: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in _TYPE_MAP_FUNC_NAMES and hasattr(node, "end_lineno"):
                ranges.append((node.lineno, node.end_lineno))  # type: ignore[attr-defined]
    if not ranges:
        return
    for entry in entries:
        if entry.file == rel and entry.kind == "ddl":
            for start, end in ranges:
                if start <= entry.line <= end:
                    entry.kind = "type_mapping"
                    break


def scan(root: Path) -> list[InventoryEntry]:
    """Walk *root* and return all inventory entries, deduplicated by (file, line, kind)."""
    entries: list[InventoryEntry] = []
    seen: set[tuple[str, int, str]] = set()

    for filepath in sorted(root.rglob("*.py")):
        if not _should_scan(filepath):
            continue
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError):
            continue

        rel = _rel(filepath, root)
        file_entries: list[InventoryEntry] = []
        doc_lines = _docstring_line_ranges(tree)

        detectors = [
            _detect_dialect_branches(tree, filepath, root),
            _detect_named_functions(tree, filepath, root),
            _detect_query_variants(tree, filepath, root),
            _detect_platform_query_constants(tree, filepath, root),
            _detect_unsupported_benchmarks(tree, filepath, root),
            _detect_session_settings(source, filepath, root, doc_lines),
            _detect_dataframe_skip_calls(source, filepath, root),
        ]
        for detector in detectors:
            for entry in detector:
                key = (entry.file, entry.line, entry.kind)
                if key not in seen:
                    seen.add(key)
                    file_entries.append(entry)

        # Post-process: branches inside type-mapping functions are type_mapping, not ddl
        _reclassify_inside_type_mapping(file_entries, tree, rel)
        entries.extend(file_entries)

    # Sort by file then line number
    entries.sort(key=lambda e: (e.file, e.line))
    return entries


def write_jsonl(entries: list[InventoryEntry], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(asdict(entry)) + "\n")


def _validate_mandatory_sites(entries: list[InventoryEntry]) -> list[str]:
    """Return error messages for any mandatory sites not found."""
    errors: list[str] = []

    gate_sites = [e for e in entries if e.kind == "benchmark_gate" and "run.py" in e.file]
    if not gate_sites:
        errors.append("MISSING: benchmark_gate site in cli/commands/run.py not detected")

    variants_sites = [e for e in entries if e.suggested_phase == "query_source" and "vector_search" in e.file]
    if not variants_sites:
        errors.append("MISSING: QUERY_VARIANTS / version-gated site in core/vector_search/queries.py not detected")

    return errors


def _platform_key_from_adapter_path(filepath: Path) -> str:
    """Infer the registry platform key from an adapter file path.

    Most adapters follow the pattern ``platforms/{platform}.py`` where the
    file stem equals the registry key.  Nested layouts (e.g.,
    ``platforms/starrocks/workload.py``) use the parent directory name.  A
    small exception table handles cases where the file name and registry key
    diverge (azure_synapse → synapse; fabric_warehouse → fabric_dw).
    """
    stem = filepath.stem
    if stem in ("workload", "adapter"):
        stem = filepath.parent.name
    return _FILE_STEM_TO_PLATFORM_KEY.get(stem, stem)


@dataclass
class DdlDriftEntry:
    file: str
    line: int
    func_name: str
    inferred_platform_key: str


def check_ddl_drift(root: Path) -> list[DdlDriftEntry]:
    """Return unregistered DDL-optimize transforms found under *root*.

    Scans platform adapter files for ``_optimize_table_definition`` and
    ``_transform_create_statement`` definitions, infers the platform key
    from the file path, and checks whether a rule is registered under
    ``Phase.DDL_OPTIMIZE`` for that platform key.

    Returns a list of DdlDriftEntry for each unregistered transform; an
    empty list means the codebase is clean.

    Loads all rules from ``benchbox.sql_compat.rules.ddl_optimize`` before
    the check so rule files do not need to be imported elsewhere first.
    """
    import importlib
    import pkgutil

    import benchbox.sql_compat.rules.ddl_optimize as _ddl_pkg
    from benchbox.sql_compat.context import Phase
    from benchbox.sql_compat.registry import REGISTRY

    broken_modules: list[str] = []
    for _, mod_name, _ispkg in pkgutil.walk_packages(_ddl_pkg.__path__, _ddl_pkg.__name__ + "."):
        if not _ispkg:
            try:
                importlib.import_module(mod_name)
            except Exception as exc:
                broken_modules.append(f"{mod_name}: {exc}")
    if broken_modules:
        raise RuntimeError(
            "Cannot complete drift check — failed to import DDL rule module(s):\n"
            + "\n".join(f"  {m}" for m in broken_modules)
        )

    registered_platforms: set[str] = {
        platform for (phase, platform, _, _), _ in REGISTRY.all_rules() if phase == Phase.DDL_OPTIMIZE
    }

    drift: list[DdlDriftEntry] = []
    platforms_dir = root / "platforms"
    if not platforms_dir.exists():
        return drift

    for filepath in sorted(platforms_dir.rglob("*.py")):
        if "__pycache__" in filepath.parts:
            continue
        try:
            source = filepath.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(filepath))
        except (SyntaxError, UnicodeDecodeError):
            continue

        platform_key = _platform_key_from_adapter_path(filepath)
        rel = str(filepath.relative_to(root.parent))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name not in _DDL_OPTIMIZE_FUNC_NAMES:
                continue
            if platform_key not in registered_platforms:
                drift.append(
                    DdlDriftEntry(
                        file=rel,
                        line=node.lineno,
                        func_name=node.name,
                        inferred_platform_key=platform_key,
                    )
                )

    return drift


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="BenchBox compatibility inventory tool")
    parser.add_argument(
        "--root",
        default="benchbox",
        help="Root directory to scan (default: benchbox/)",
    )
    parser.add_argument(
        "--output",
        default="_project/compat/inventory.jsonl",
        help="Output JSONL path (default: _project/compat/inventory.jsonl)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print summary to stdout after writing",
    )
    parser.add_argument(
        "--check-ddl-drift",
        action="store_true",
        help=(
            "After scanning, verify every adapter with a DDL-optimize method has a "
            "registered Phase.DDL_OPTIMIZE rule.  Exits 1 on any drift finding."
        ),
    )
    args = parser.parse_args(argv)

    root = Path(args.root).resolve()
    output = Path(args.output)

    if not root.exists():
        print(f"ERROR: root directory not found: {root}", file=sys.stderr)
        return 1

    print(f"Scanning {root} ...", file=sys.stderr)
    entries = scan(root)
    write_jsonl(entries, output)
    print(f"Wrote {len(entries)} entries to {output}", file=sys.stderr)

    exit_code = 0

    errors = _validate_mandatory_sites(entries)
    if errors:
        for err in errors:
            print(f"VALIDATION ERROR: {err}", file=sys.stderr)
        exit_code = 1

    if args.summary:
        from collections import Counter

        kind_counts = Counter(e.kind for e in entries)
        phase_counts = Counter(e.suggested_phase for e in entries)
        print("\nKind distribution:")
        for kind, count in sorted(kind_counts.items()):
            print(f"  {kind:20s} {count}")
        print("\nSuggested phase distribution:")
        for phase, count in sorted(phase_counts.items()):
            print(f"  {phase:20s} {count}")

    if args.check_ddl_drift:
        print("\nChecking DDL drift ...", file=sys.stderr)
        drift = check_ddl_drift(root)
        if drift:
            print(f"DDL DRIFT: {len(drift)} unregistered DDL-optimize transform(s):", file=sys.stderr)
            for d in drift:
                print(
                    f"  {d.file}:{d.line}  {d.func_name}()  [inferred platform key: {d.inferred_platform_key!r}]",
                    file=sys.stderr,
                )
            print(
                "Register each unregistered transform in "
                "benchbox/sql_compat/rules/ddl_optimize/{platform}_ddl_rewrites.py "
                "before enabling --check-ddl-drift in CI.",
                file=sys.stderr,
            )
            exit_code = 1
        else:
            print("DDL drift check: CLEAN (0 unregistered transforms)", file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
