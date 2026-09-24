"""Select the release-canary tests that a set of changed paths can affect.

The daily release canary runs the full non-fast suite (about 644 tests in
72 files); running all of it in the merge queue would roughly double
merge-queue runner-minutes. This selector computes each canary test file's
dependencies from the tree under test and selects the tests whose
dependencies include a changed path.

Dependency rules (each closes a known gap in naive import scanning):

- static imports, including every parent package ``__init__.py`` (Python
  executes them on import);
- ``importlib.import_module("<literal>")`` and ``__import__("<literal>")``;
- repo paths built from constants: ``REPO_ROOT / "a" / "b"``,
  ``Path(__file__).with_name("x")``, and path string literals in path
  positions. A directory path depends on every file under it;
- ``tests/conftest.py`` and every module in its ``pytest_plugins`` list,
  with their dependencies, for every test;
- a changed non-Python file under ``benchbox/`` selects every canary test
  that imports a module in the same directory;
- changed or added canary test files always select themselves.

Fail-safe rules (when unsure, select -- the selector may over-select but
must never under-select silently):

- per test: a canary test containing a dynamic edge the selector cannot
  resolve (an import name or path built at runtime) is always selected;
- whole suite: ``pyproject.toml``, ``uv.lock``, pytest configuration,
  ``tests/conftest.py``, ``release-canary.yml``, or the selector itself
  changed;
- unmapped paths: a changed path that no dependency map references and
  that is not on the reviewed ``CANT_AFFECT_CANARY`` list runs the whole
  suite.

Stdlib-only and read-only: the selector never imports ``benchbox`` and
never executes test code. The marker expression and collection parsing
are imported from ``scripts/release_canary_sharding.py``, not copied.

Output is JSON with the selected node IDs, the reason each was selected
(which changed path, through which edge), whether a whole-suite fallback
fired and why, and the canary collection it was computed against.
"""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, NamedTuple

try:  # executed as ``python scripts/canary_impact.py`` (scripts/ on sys.path)
    from release_canary_sharding import MARKER_EXPRESSION, parse_collection_output
except ImportError:  # imported as ``scripts.canary_impact`` in tests
    from scripts.release_canary_sharding import MARKER_EXPRESSION, parse_collection_output


SELECTOR_REPO_PATH = "scripts/canary_impact.py"
CANARY_WORKFLOW_PATH = ".github/workflows/release-canary.yml"
CONFTEST_REPO_PATH = "tests/conftest.py"

# Changed paths that always run the whole suite. pytest configuration covers
# every file pytest reads at startup; the selector itself is included so a
# change to the selection rules cannot silently narrow selection.
WHOLE_SUITE_PATHS = frozenset(
    {
        "pyproject.toml",
        "uv.lock",
        "pytest.ini",
        "pytest-ci.ini",
        "tox.ini",
        "tests/conftest.py",
        CANARY_WORKFLOW_PATH,
        SELECTOR_REPO_PATH,
    }
)

# Changed paths that are known not to affect the canary even though no
# dependency edge references them. Entries ending in "/" are directory
# prefixes. Each entry MUST keep its comment stating why it is safe;
# adding an entry needs a stated reason in the PR.
# Verified 2026-09-24: none of these is read by any canary test, and the
# Sphinx docs build (tests/unit/docs/test_docs_build.py, source dir docs/)
# does not include any of them.
CANT_AFFECT_CANARY = frozenset(
    {
        # Release-notes ledger: only fast changelog-guard tests read it.
        "CHANGELOG.md",
        # Legal texts: no test asserts on their contents.
        "LICENSE",
        "DISCLAIMER.md",
        "COPYRIGHT.md",
        # Spellcheck dictionary: consumed by codespell, not by pytest.
        ".codespell-ignore.txt",
        # Decision and audit reports: read only by fast unit tests, never by
        # canary tests, and outside the docs build source tree.
        "_project/audits/",
    }
)


def _is_cant_affect(path: str) -> bool:
    """Return whether a changed path is on the reviewed safe list."""
    if path in CANT_AFFECT_CANARY:
        return True
    return any(entry.endswith("/") and path.startswith(entry) for entry in CANT_AFFECT_CANARY)


# Extra roots for resolving bare (non-dotted) module names, mirroring the
# sys.path manipulation canary-adjacent tests perform. Dotted names always
# resolve from the repo root.
BARE_MODULE_SEARCH_DIRS = ("", "scripts")

# Roots whose joined paths are test-local scratch space, never repo files.
TESTLOCAL_ROOTS = frozenset({"tmp_path", "tmpdir", "tmp_path_factory"})

# Keyword argument names that carry a path even when the value is a bare
# literal (e.g. open(file=...)). Positional arguments are evaluated when
# they look like paths; other keywords are ignored to avoid flagging
# values such as pytest.raises(match="a/b").
PATHLIKE_KEYWORDS = frozenset(
    {
        "path",
        "filename",
        "filepath",
        "fname",
        "dir",
        "directory",
        "root",
        "src",
        "dst",
        "target",
        "location",
    }
)

# Calls whose positional string arguments are always treated as paths.
PATH_CONSTRUCTOR_FUNCS = frozenset(
    {
        "open",
        "Path",
        "glob",
        "rglob",
        "join",
        "abspath",
        "realpath",
        "normpath",
        "dirname",
        "exists",
        "isfile",
        "isdir",
        "listdir",
        "read_text",
        "write_text",
        "mkdir",
    }
)


class FileDeps(NamedTuple):
    """Static dependency view of one Python file."""

    deps: frozenset[str]
    dynamic: bool
    dynamic_kinds: tuple[str, ...]


def normalize_rel(path: str) -> str:
    """Normalize a repo-relative path to posix form."""
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def _stdlib_names() -> frozenset[str]:
    return frozenset(sys.stdlib_module_names)


def _exists(path: Path) -> bool:
    """Return whether a path exists, tolerating unstatable literals."""
    try:
        return path.exists()
    except (OSError, ValueError):
        return False


def _is_dir(path: Path) -> bool:
    """Return whether a path is a directory, tolerating bad literals."""
    try:
        return path.is_dir()
    except (OSError, ValueError):
        return False


def _looks_external(top_level: str, root: Path) -> bool:
    """Return True when a top-level name is neither stdlib nor a repo module.

    ``importlib.util.find_spec`` on a top-level name only scans ``sys.path``
    without importing or executing anything, so it is safe to call here.
    """
    if top_level in _stdlib_names():
        return True
    for candidate in (
        root / f"{top_level}.py",
        root / top_level / "__init__.py",
        root / "scripts" / f"{top_level}.py",
    ):
        if candidate.is_file():
            return False
    try:
        import importlib.util

        return importlib.util.find_spec(top_level) is not None
    except (ImportError, AttributeError, ValueError):
        return False


def _module_file(dotted: str, root: Path) -> Path | None:
    """Return the file implementing a dotted module name, if it exists."""
    parts = dotted.split(".")
    module_path = root.joinpath(*parts).with_suffix(".py")
    if module_path.is_file():
        return module_path
    package_init = root.joinpath(*parts, "__init__.py")
    if package_init.is_file():
        return package_init
    # Namespace package member without __init__.py (e.g. scripts/*).
    namespace_member = root.joinpath(*parts).with_suffix(".py")
    if namespace_member.is_file():
        return namespace_member
    return None


def _parent_inits(module_file: Path, root: Path) -> list[Path]:
    """Return existing parent package ``__init__.py`` files, top-down."""
    inits: list[Path] = []
    try:
        relative_parent = module_file.parent.relative_to(root)
    except ValueError:
        return inits
    current = root
    for part in relative_parent.parts:
        current = current / part
        candidate = current / "__init__.py"
        if candidate.is_file():
            inits.append(candidate)
    return inits


def _rel(path: Path, root: Path) -> str | None:
    """Return a repo-relative posix path, or None when outside the repo."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _resolve_absolute(dotted: str, root: Path) -> tuple[set[str], bool]:
    """Resolve an absolute dotted name to repo files.

    Returns ``(deps, unknown)``: repo-relative dependency paths, and whether
    the name could not be resolved to either a repo file or an external
    module (a dynamic edge for the importing file).
    """
    top_level = dotted.split(".")[0]
    module_file = _module_file(dotted, root)
    if module_file is not None:
        deps = {_rel(module_file, root)}
        deps.update(_rel(init, root) for init in _parent_inits(module_file, root))
        return {dep for dep in deps if dep is not None}, False
    if root.joinpath(*dotted.split(".")).is_dir():
        # Namespace package without __init__.py (e.g. scripts/): importing
        # it executes no file, so there is no file edge. Submodule probing
        # by the caller adds the real target.
        return set(), False
    if _looks_external(top_level, root):
        return set(), False
    return set(), True


def _resolve_bare(name: str, root: Path) -> tuple[set[str], bool]:
    """Resolve a bare module name using the extra search roots."""
    for search_dir in BARE_MODULE_SEARCH_DIRS:
        base = root if not search_dir else root / search_dir
        for candidate in (base / f"{name}.py", base / name / "__init__.py"):
            if candidate.is_file():
                rel = _rel(candidate, root)
                deps = {rel} if rel else set()
                if not search_dir:
                    deps.update(
                        dep for dep in (_rel(init, root) for init in _parent_inits(candidate, root)) if dep is not None
                    )
                return deps, False
        if (base / name).is_dir():
            # Namespace package member: no file executes on import.
            return set(), False
    if _looks_external(name, root):
        return set(), False
    return set(), True


def _resolve_import(name: str, importer: Path, root: Path) -> tuple[set[str], bool]:
    """Resolve a static import name (absolute, relative, or bare)."""
    if name.startswith("."):
        level = len(name) - len(name.lstrip("."))
        remainder = name.lstrip(".")
        try:
            package_dir = importer.parent.relative_to(root)
        except ValueError:
            return set(), True
        # Level 1 is the importing file's own directory; each further
        # level walks one directory up.
        for _ in range(level - 1):
            package_dir = package_dir.parent
        dotted = ".".join([*package_dir.parts, remainder] if remainder else list(package_dir.parts))
        if not dotted:
            return set(), True
        return _resolve_absolute(dotted, root)
    if "." in name:
        return _resolve_absolute(name, root)
    return _resolve_bare(name, root)


# Resolution outcomes for path expressions.
_RESOLVED = "resolved"
_TESTLOCAL = "testlocal"
_EXTERNAL = "external"
_UNKNOWN = "unknown"


def _is_environ_expr(node: ast.AST) -> bool:
    """Return whether an expression reads the process environment.

    Environment-derived values (``os.environ.get(...)``, ``os.getenv(...)``)
    point outside the repo, so they are known-not-repo rather than unknown.
    """
    if isinstance(node, ast.Call):
        func_name = _call_name(node.func)
        if func_name == "getenv":
            return True
        return _is_environ_expr(node.func)
    if isinstance(node, ast.Attribute):
        if node.attr == "environ" and isinstance(node.value, ast.Name) and node.value.id == "os":
            return True
        return _is_environ_expr(node.value)
    if isinstance(node, ast.Subscript):
        return _is_environ_expr(node.value)
    return False


class _PathResolution(NamedTuple):
    outcome: str
    path: Path | None = None


class _FileAnalyzer(ast.NodeVisitor):
    """Collect repo dependencies and dynamic edges of one Python file."""

    def __init__(self, path: Path, root: Path) -> None:
        self.path = path
        self.root = root
        self.deps: set[str] = set()
        self.dynamic_kinds: list[str] = []
        # Simple name bindings: name -> _PathResolution. Module level and
        # one function level (functions see module bindings as fallback).
        self.module_env: dict[str, _PathResolution] = {}
        self.function_env: dict[str, _PathResolution] | None = None
        self.function_assigned: set[str] = set()
        self.class_env_stack: list[dict[str, _PathResolution]] = []

    def _note_dynamic(self, kind: str) -> None:
        if kind not in self.dynamic_kinds:
            self.dynamic_kinds.append(kind)

    def _add_dep_path(self, path: Path) -> None:
        rel = _rel(path, self.root)
        if rel is not None:
            self.deps.add(rel)
            if path.is_dir():
                # A directory path depends on every file under it; the
                # matcher treats directory deps as covering their subtree.
                pass

    def _add_repo_path(self, path: Path) -> None:
        self._add_dep_path(path)

    # -- name environments ------------------------------------------------

    def _is_bound(self, name: str) -> bool:
        """Return whether a name resolves in the current scope.

        Function parameters and names assigned in the body shadow module
        level: an assigned-but-unresolved name counts as unbound (it is a
        local like any parameter), never as its module namesake.
        """
        if self.function_env is not None:
            if name in self.function_env:
                return True
            if name in self.function_assigned:
                return False
        return name in self.module_env

    def _lookup(self, name: str) -> _PathResolution | None:
        if self.function_env is not None and name in self.function_env:
            return self.function_env[name]
        if self.function_env is not None and name in self.function_assigned:
            return None
        if self.function_env is None and self.class_env_stack and name in self.class_env_stack[-1]:
            return self.class_env_stack[-1][name]
        return self.module_env.get(name)

    def _bind(self, name: str, resolution: _PathResolution) -> None:
        if self.function_env is not None:
            self.function_env[name] = resolution
            self.function_assigned.add(name)
        elif self.class_env_stack:
            self.class_env_stack[-1][name] = resolution
        else:
            self.module_env[name] = resolution

    # -- path expression resolution ---------------------------------------

    def _resolve_expr(self, node: ast.AST) -> _PathResolution:  # noqa: C901
        """Resolve an expression to a repo path, test-local, or unknown."""
        if _is_environ_expr(node):
            return _PathResolution(_EXTERNAL)
        if isinstance(node, ast.Name):
            if node.id == "__file__":
                return _PathResolution(_RESOLVED, self.path)
            if node.id in TESTLOCAL_ROOTS:
                return _PathResolution(_TESTLOCAL)
            bound = self._lookup(node.id)
            if bound is not None:
                return bound
            return _PathResolution(_UNKNOWN)
        if isinstance(node, ast.Constant):
            value = node.value
            if isinstance(value, str) and _is_dir(self.root / value):
                # Bare directory name rooted at the repo (Path("docs")).
                # (_looks_like_path misses slash-less names; the existence
                # check keeps tmp-relative names out.)
                candidate = self.root / value
                return _PathResolution(_RESOLVED, candidate)
            if isinstance(value, str) and _looks_like_path(value):
                if value.startswith("/") or (len(value) > 2 and value[1] == ":" and value[2] in "/\\"):
                    # Absolute filesystem path: it can never equal a
                    # repo-relative changed path (test scratch or fixtures).
                    return _PathResolution(_EXTERNAL)
                if any(char in value for char in "*?["):
                    # Glob pattern: depend on the static parent directory,
                    # which covers every file the pattern can match.
                    static_prefix = value
                    for char in "*?[":
                        static_prefix = static_prefix.split(char, 1)[0]
                    parent = (self.root / static_prefix).parent
                    if parent.is_dir() and parent != self.root:
                        return _PathResolution(_RESOLVED, parent)
                    return _PathResolution(_UNKNOWN)
                candidate = self.root / value
                if _exists(candidate):
                    return _PathResolution(_RESOLVED, candidate)
                return _PathResolution(_UNKNOWN)
            return _PathResolution(_UNKNOWN)
        if isinstance(node, ast.Attribute):
            if node.attr == "parent":
                inner = self._resolve_expr(node.value)
                if inner.outcome == _RESOLVED and inner.path is not None:
                    return _PathResolution(_RESOLVED, inner.path.parent)
                return inner
            if (
                isinstance(node.value, ast.Name)
                and node.value.id in {"self", "cls"}
                and self.class_env_stack
                and node.attr in self.class_env_stack[-1]
            ):
                # self.REPO_ROOT / ... resolves through the class attribute.
                return self.class_env_stack[-1][node.attr]
            return _PathResolution(_UNKNOWN)
        if isinstance(node, ast.Subscript):
            # Only Path(__file__).parents[N] with an int index resolves.
            if (
                isinstance(node.value, ast.Attribute)
                and node.value.attr == "parents"
                and isinstance(node.slice, ast.Constant)
                and isinstance(node.slice.value, int)
            ):
                inner = self._resolve_expr(node.value.value)
                if inner.outcome == _RESOLVED and inner.path is not None:
                    # parents[N] applies .parent N+1 times: parents[0] is the
                    # immediate parent directory.
                    current = inner.path
                    for _ in range(node.slice.value + 1):
                        current = current.parent
                    return _PathResolution(_RESOLVED, current)
            # Indexing into test-local scratch (result_files[-1]) stays
            # test-local, and indexing a resolved directory stays inside it
            # (result_files[0] is a file under benchmark_runs/); indexing
            # anything else is opaque.
            base = self._resolve_expr(node.value)
            if base.outcome in (_TESTLOCAL, _EXTERNAL):
                return base
            if base.outcome == _RESOLVED and base.path is not None and base.path.is_dir():
                return base
            return _PathResolution(_UNKNOWN)
        if isinstance(node, ast.Call):
            return self._resolve_call_expr(node)
        if isinstance(node, ast.BinOp):
            left = self._resolve_expr(node.left)
            right = self._resolve_expr(node.right)
            # Locality propagates through string and arithmetic operators:
            # test-local joined with anything stays test-local.
            for side in (left, right):
                if side.outcome == _TESTLOCAL:
                    return side
            for side in (left, right):
                if side.outcome == _EXTERNAL:
                    return side
            if not isinstance(node.op, ast.Div) or left.outcome != _RESOLVED or left.path is None:
                return _PathResolution(_UNKNOWN)
            right_node = node.right
            if isinstance(right_node, ast.Constant) and isinstance(right_node.value, str):
                return _PathResolution(_RESOLVED, left.path / right_node.value)
            return _PathResolution(_UNKNOWN)
        if isinstance(node, ast.JoinedStr):
            if len(node.values) == 1 and isinstance(node.values[0], ast.FormattedValue):
                # A lone interpolation (f"{path}") behaves like the value.
                return self._resolve_expr(node.values[0].value)
            parts: list[str] = []
            for value in node.values:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    parts.append(value.value)
                elif isinstance(value, ast.FormattedValue):
                    inner = self._resolve_expr(value.value)
                    if inner.outcome == _RESOLVED and inner.path is not None:
                        parts.append(str(inner.path))
                    else:
                        return _PathResolution(_UNKNOWN)
                else:
                    return _PathResolution(_UNKNOWN)
            candidate = self.root / "".join(parts)
            if _exists(candidate):
                return _PathResolution(_RESOLVED, candidate)
            return _PathResolution(_UNKNOWN)
        return _PathResolution(_UNKNOWN)

    def _resolve_call_expr(self, node: ast.Call) -> _PathResolution:  # noqa: C901
        func_name = _call_name(node.func)
        # Standard-library temporary-path factories create test-local
        # scratch space, never repo paths.
        if func_name in {"mkdtemp", "mkstemp", "TemporaryDirectory", "NamedTemporaryFile"}:
            return _PathResolution(_TESTLOCAL)
        # Passthrough wrappers that preserve the inner path.
        if func_name in {"resolve", "absolute", "realpath", "abspath", "normpath"} and node.args:
            return self._resolve_expr(node.args[0])
        if func_name == "dirname" and node.args:
            inner = self._resolve_expr(node.args[0])
            if inner.outcome == _RESOLVED and inner.path is not None:
                parent = inner.path.parent
                # os.path.dirname on a file returns its directory; on a
                # directory-looking path it also returns the parent, which
                # is the safe (wider) reading.
                return _PathResolution(_RESOLVED, parent)
            return inner
        if func_name in {"join", "joinpath"}:
            current: Path | None = None
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if current is None:
                        candidate = self.root / arg.value
                        current = candidate
                    else:
                        current = current / arg.value
                    continue
                inner = self._resolve_expr(arg)
                if inner.outcome != _RESOLVED or inner.path is None:
                    return inner if inner.outcome != _RESOLVED else _PathResolution(_UNKNOWN)
                if current is None:
                    current = inner.path
                else:
                    # Absolute-looking join part resets; keep the wider one.
                    current = inner.path if inner.path.is_absolute() else current / inner.path.name
            if current is not None:
                return _PathResolution(_RESOLVED, current)
            return _PathResolution(_UNKNOWN)
        if func_name in {"Path", "path"} and node.args:
            # Path(x): x may itself be a path or a literal under the repo.
            inner = self._resolve_expr(node.args[0])
            if inner.outcome == _RESOLVED:
                return inner
            if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                candidate = self.root / node.args[0].value
                if _exists(candidate):
                    return _PathResolution(_RESOLVED, candidate)
            return inner
        if func_name == "with_name" and node.args:
            base = self._resolve_expr(node.func.value) if isinstance(node.func, ast.Attribute) else None
            if (
                base is not None
                and base.outcome == _RESOLVED
                and base.path is not None
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                return _PathResolution(_RESOLVED, base.path.parent / node.args[0].value)
            return _PathResolution(_UNKNOWN)
        if func_name == "with_suffix" and node.args:
            base = self._resolve_expr(node.func.value) if isinstance(node.func, ast.Attribute) else None
            if base is not None and base.outcome == _RESOLVED and base.path is not None:
                return _PathResolution(_RESOLVED, base.path)
            return _PathResolution(_UNKNOWN)
        # Unknown function or method. Transparent containers (sorted, list,
        # str) preserve their argument's nature; path-collecting calls
        # (glob, find_*) depend on the directory they read. Anything else
        # returns an opaque value: a builder object is not a path even when
        # it was built from one (gate.build(..., tmp_path)), while a value
        # built opaquely from a resolved path still binds UNKNOWN through
        # _touches_known so later path uses flag a dynamic edge.
        if func_name in {"sorted", "list", "tuple", "set", "frozenset", "reversed", "str"}:
            if node.args:
                return self._resolve_expr(node.args[0])
            return _PathResolution(_UNKNOWN)
        if func_name in {"glob", "rglob", "listdir", "iterdir", "walk", "scandir"} or (
            func_name is not None
            and (func_name.startswith(("find_", "glob_")) or func_name.endswith(("_files", "_paths")))
        ):
            candidates: list[ast.AST] = []
            if isinstance(node.func, ast.Attribute):
                candidates.append(node.func.value)
            candidates.extend(node.args)
            candidates.extend(kw.value for kw in node.keywords if kw.value is not None)
            for candidate in candidates:
                inner = self._resolve_expr(candidate)
                if inner.outcome == _RESOLVED and inner.path is not None:
                    return inner
            for candidate in candidates:
                inner = self._resolve_expr(candidate)
                if inner.outcome in (_TESTLOCAL, _EXTERNAL):
                    return inner
            return _PathResolution(_UNKNOWN)
        if isinstance(node.func, ast.Attribute):
            base = self._resolve_expr(node.func.value)
            if base.outcome == _RESOLVED and base.path is not None:
                # Reading a resolved file depends on it
                # (REFERENCE_CARDINALITIES.read_text()).
                return base
            if base.outcome in (_TESTLOCAL, _EXTERNAL):
                # Method results on scratch space stay local.
                return base
        return _PathResolution(_UNKNOWN)

    # -- statements ---------------------------------------------------------

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        outer_env = self.function_env
        outer_assigned = self.function_assigned
        self.function_env = {}
        # Parameters shadow module level from the start; so does any name
        # assigned in the body (tracked on visit) — later lookups must not
        # fall through to a same-named module global.
        self.function_assigned = {
            arg.arg
            for arg in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                node.args.vararg,
                node.args.kwarg,
            )
            if arg is not None
        }
        self.generic_visit(node)
        self.function_env = outer_env
        self.function_assigned = outer_assigned

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self.visit_FunctionDef(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.class_env_stack.append({})
        self.generic_visit(node)
        self.class_env_stack.pop()

    def visit_For(self, node: ast.For | ast.AsyncFor) -> None:
        self._mark_target_assigned(node.target)
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:  # noqa: N802
        self.visit_For(node)

    def visit_With(self, node: ast.With | ast.AsyncWith) -> None:
        for item in node.items:
            if item.optional_vars is not None:
                self._mark_target_assigned(item.optional_vars)
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        self.visit_With(node)

    def _mark_target_assigned(self, target: ast.AST) -> None:
        for child in ast.walk(target):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store) and self.function_env is not None:
                self.function_assigned.add(child.id)

    def visit_Assign(self, node: ast.Assign) -> None:
        self._handle_assignment(node.value, list(node.targets))
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self._handle_assignment(node.value, [node.target])
        self.generic_visit(node)

    def _handle_assignment(self, value: ast.AST, targets: list[ast.AST]) -> None:
        names = [t.id for t in targets if isinstance(t, ast.AST) and isinstance(t, ast.Name)]
        if not names:
            return
        if self.function_env is not None:
            # Even when the value resolves to nothing bindable, the names
            # become function locals and shadow the module level below.
            self.function_assigned.update(names)
        value_names = {n.id for n in ast.walk(value) if isinstance(n, ast.Name)}
        resolution = self._resolve_expr(value)
        if any(name in value_names for name in names):
            # Self-referential assignment (``x = Path(x)``): the right-hand
            # side sees the previous binding, so rebinding here would let the
            # statement poison its own name. Keep the previous binding; the
            # caller still visits the value normally.
            return
        if resolution.outcome == _RESOLVED and resolution.path is not None:
            self._add_repo_path(resolution.path)
        if resolution.outcome in (_RESOLVED, _TESTLOCAL, _EXTERNAL):
            for name in names:
                self._bind(name, resolution)
        elif resolution.outcome == _UNKNOWN and _touches_known(value, self):
            # A name built opaquely from known things (helper(REPO_ROOT))
            # stays suspicious in path positions; a name built from nothing
            # known (fixture.tables["x"]) is left unbound, like a parameter.
            for name in names:
                self._bind(name, resolution)

    # -- imports --------------------------------------------------------------

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            deps, unknown = _resolve_import(alias.name, self.path, self.root)
            self.deps.update(deps)
            if unknown:
                self._note_dynamic(f"unresolvable_import:{alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module is None and node.level == 0:
            self._note_dynamic("unresolvable_import:relative_without_module")
            self.generic_visit(node)
            return
        base = ("." * node.level + (node.module or "")).rstrip(".")
        # ``from . import x`` imports the sibling submodule x, not just the
        # package: resolve each imported name as a candidate submodule too.
        candidates = [base] if node.module else []
        if not node.module:
            try:
                package_dir = self.path.parent.relative_to(self.root)
                package = ".".join(package_dir.parts)
            except ValueError:
                package = ""
            for alias in node.names:
                if alias.name != "*":
                    candidates.append(f"{package}.{alias.name}" if package else alias.name)
        deps: set[str] = set()
        unknown = False
        for candidate in candidates:
            candidate_deps, candidate_unknown = _resolve_import(candidate, self.path, self.root)
            deps.update(candidate_deps)
            unknown = unknown or candidate_unknown
        # ``from package import submodule``: probe each name as a submodule.
        if node.module and not node.level:
            module_file = _module_file(node.module, self.root)
            package_dir = self.root.joinpath(*node.module.split("."))
            if module_file is None and package_dir.is_dir():
                for alias in node.names:
                    if alias.name == "*":
                        continue
                    sub = _module_file(f"{node.module}.{alias.name}", self.root)
                    if sub is not None:
                        rel = _rel(sub, self.root)
                        if rel is not None:
                            deps.add(rel)
                        deps.update(
                            dep
                            for dep in (_rel(init, self.root) for init in _parent_inits(sub, self.root))
                            if dep is not None
                        )
        self.deps.update(deps)
        if unknown:
            self._note_dynamic(f"unresolvable_import:{base or 'relative'}")
        self.generic_visit(node)

    # -- calls ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:
        func_name = _call_name(node.func)
        if func_name in {"import_module", "import_", "__import__", "importorskip"}:
            self._handle_dynamic_import(node)
        elif func_name == "patch":
            self._handle_mock_patch(node)
        elif func_name in {"exec", "eval"}:
            if any(_is_strong_path_signal(arg, self) for arg in (*node.args, *(kw.value for kw in node.keywords))):
                self._note_dynamic(f"dynamic_{func_name}")
        else:
            self._handle_path_call(node, func_name)
        self.generic_visit(node)

    def _handle_dynamic_import(self, node: ast.Call) -> None:
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            name = node.args[0].value
            package = None
            if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                package = node.args[1].value
            if name.startswith(".") and isinstance(package, str):
                level = len(name) - len(name.lstrip("."))
                full = "." * level + package + "." + name.lstrip(".")
                deps, unknown = _resolve_import(full, self.path, self.root)
            else:
                deps, unknown = _resolve_import(name, self.path, self.root)
            self.deps.update(deps)
            if unknown:
                self._note_dynamic(f"unresolvable_import:{name}")
        else:
            self._note_dynamic("dynamic_import")

    def _handle_mock_patch(self, node: ast.Call) -> None:
        # mock.patch("package.module.Attribute") patches that import path:
        # the target module is a real dependency edge, not a dynamic one.
        # Attribute chains are stripped to the longest resolvable module
        # prefix (Class.method -> module). patch.object(obj, "attr") patches
        # a runtime object, which carries no import edge either way.
        if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
            target = node.args[0].value
            parts = target.split(".")
            if all(part.isidentifier() for part in parts):
                for end in range(len(parts) - 1, 0, -1):
                    candidate = ".".join(parts[:end])
                    module_file = _module_file(candidate, self.root)
                    if module_file is not None:
                        rel = _rel(module_file, self.root)
                        if rel is not None:
                            self.deps.add(rel)
                        self.deps.update(
                            dep
                            for dep in (_rel(init, self.root) for init in _parent_inits(module_file, self.root))
                            if dep is not None
                        )
                        return
                if _looks_external(parts[0], self.root):
                    return
            self._note_dynamic(f"unresolvable_import:{target}")

    # Calls whose arguments are never path evidence (markers, assertions on
    # messages, warning filters). Everything else is evaluated when an
    # argument is a strong path signal; path-consuming calls evaluate
    # every positional argument deeply (e.g. subprocess argv lists).
    _SKIP_EVAL_FUNCS = frozenset(
        {
            "parametrize",
            "mark",
            "fixture",
            "raises",
            "warns",
            "skip",
            "skipif",
            "fail",
            "xfail",
            "filterwarnings",
            "deprecated_call",
        }
    )

    # Extra calls that always consume paths positionally (besides the
    # constructors in PATH_CONSTRUCTOR_FUNCS). Deliberately narrow:
    # subprocess-style argv lists and data-reader literals are still caught
    # through strong path signals without forcing every ``run``/``load``
    # method call in the tree to resolve.
    _PATH_CONSUMING_CALLS = frozenset(
        {
            "open",
            "copy",
            "copy2",
            "copytree",
            "move",
            "remove",
            "unlink",
            "chdir",
        }
    )

    # Pure string/regex methods: their arguments are patterns and messages,
    # never repo paths. The base object is evaluated on its own when it
    # carries a path, so skipping these calls loses no dependency edge.
    _STRING_METHODS = frozenset(
        {
            "startswith",
            "endswith",
            "removeprefix",
            "removesuffix",
            "strip",
            "lstrip",
            "rstrip",
            "split",
            "rsplit",
            "splitlines",
            "partition",
            "rpartition",
            "format",
            "format_map",
            "encode",
            "decode",
            "lower",
            "upper",
            "casefold",
            "replace",
            "match",
            "search",
            "fullmatch",
            "find",
            "rfind",
            "index",
            "rindex",
            "sub",
            "subn",
            "compile",
            "escape",
            "findall",
            "finditer",
        }
    )

    # Pure data reductions: their arguments are values being measured, not
    # paths being read. Inner calls are still visited on their own.
    _DATA_FUNCS = frozenset({"len", "sum", "min", "max", "any", "all"})

    def _handle_path_call(self, node: ast.Call, func_name: str | None) -> None:
        if func_name in self._SKIP_EVAL_FUNCS or func_name in self._STRING_METHODS or func_name in self._DATA_FUNCS:
            return
        if func_name is not None and func_name.endswith(("Error", "Exception", "Warning", "Exit")):
            # Exception constructors take messages and test-local names, not
            # repo paths (e.g. ChecksumMismatchError(path="title.parquet")).
            return
        if func_name == "join" and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Constant):
            # str.join (",".join(names)): message assembly, not os.path.join.
            # Arguments still get strong-signal evaluation below.
            force = False
        else:
            force = func_name in PATH_CONSTRUCTOR_FUNCS or func_name in self._PATH_CONSUMING_CALLS
        for arg in node.args:
            self._handle_call_arg(arg, force_path=force, call_name=func_name)
        for keyword in node.keywords:
            if keyword.arg is None:
                continue
            if force or keyword.arg in PATHLIKE_KEYWORDS:
                self._handle_call_arg(keyword.value, force_path=True, call_name=func_name)

    def _handle_call_arg(self, arg: ast.AST, *, force_path: bool, call_name: str | None) -> None:
        if isinstance(arg, (ast.List, ast.Tuple, ast.Set)):
            for element in arg.elts:
                self._handle_call_arg(element, force_path=force_path, call_name=call_name)
            return
        if isinstance(arg, ast.Dict):
            for value in arg.values:
                self._handle_call_arg(value, force_path=force_path, call_name=call_name)
            return
        if isinstance(arg, ast.Starred):
            self._handle_call_arg(arg.value, force_path=force_path, call_name=call_name)
            return
        if isinstance(arg, ast.Constant) and not (isinstance(arg.value, str) and _looks_like_path(arg.value)):
            # Non-path constants (encoding="utf-8", parents=True, timeouts)
            # are never path evidence, even in path-consuming calls.
            return
        if not force_path and not _is_strong_path_signal(arg, self):
            return
        resolution = self._resolve_expr(arg)
        if resolution.outcome == _RESOLVED and resolution.path is not None:
            self._add_repo_path(resolution.path)
        elif resolution.outcome == _UNKNOWN and not _is_unbound_root(arg, self):
            self._note_dynamic(f"dynamic_path:{call_name or 'call'}")


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _looks_like_path(value: str) -> bool:
    """Heuristic for string literals that denote repo paths."""
    if not value or value.startswith(("http://", "https://", "mailto:")):
        return False
    if "://" in value:
        # Connection strings and URIs (invalid://connection/string).
        return False
    if "{" in value or "}" in value:
        # Format template (PureWindowsPath("C:/.../{name}")), not a path.
        return False
    if " " in value and "/" not in value:
        return False
    if "/" in value or value.startswith("."):
        return True
    suffix = Path(value).suffix
    if not suffix or len(suffix) > 6:
        return False
    # A numeric stem is a version or measurement (``"-84.43"``), not a file.
    stem = value[: -len(suffix)]
    return any(char.isalpha() for char in stem)


def _expr_root_name(node: ast.AST) -> str | None:
    """Return the root Name id of an attribute/subscript/call/chain expression."""
    current = node
    while isinstance(current, (ast.Attribute, ast.Subscript, ast.Call, ast.BinOp)):
        if isinstance(current, ast.Call):
            current = current.func
        elif isinstance(current, ast.Attribute):
            current = current.value
        elif isinstance(current, ast.BinOp):
            current = current.left
        else:
            # Subscript: the root is the value being indexed, not the slice
            # (sys.argv[:4] is rooted at sys, not at 4).
            current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _touches_known(node: ast.AST, analyzer: _FileAnalyzer) -> bool:
    """Return whether an expression mentions a resolved repo path.

    Only resolved paths (and ``__file__``) count: a name built opaquely
    from a resolved path (helper(REPO_ROOT)) stays suspicious, while a name
    built from test-local values or unbound names (gate.build(..., tmp_path),
    fixture.tables["x"]) does not. Opaque computations over nothing
    path-like are left unbound, like parameters.
    """
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if child.id == "__file__":
                return True
            bound = analyzer._lookup(child.id)
            if bound is not None and bound.outcome == _RESOLVED:
                return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if _exists(analyzer.root / child.value):
                return True
    return False


def _is_unbound_root(node: ast.AST, analyzer: _FileAnalyzer) -> bool:
    """Return whether an expression mentions no bound name at all.

    Such expressions are built from function parameters, cross-function
    locals, and builtins, which in test code are conventionally test-local
    values rather than repo paths. Anything touching ``__file__``, a
    test-local root, or a tracked binding stays suspicious.
    """
    for child in ast.walk(node):
        if not isinstance(child, ast.Name):
            continue
        if child.id == "__file__" or child.id in TESTLOCAL_ROOTS:
            return False
        if analyzer._is_bound(child.id):
            return False
    return True


def _is_strong_path_signal(node: ast.AST, analyzer: _FileAnalyzer) -> bool:
    """Return whether an expression is worth resolving as a repo path use.

    Deliberately narrow: attribute access and opaque calls are only signals
    when rooted at ``__file__`` or a name already bound to a path, so
    ordinary code such as ``json.dumps(config.value)`` is never evaluated.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        # Numeric division (10000.0 / 0.8) is arithmetic, never a path join.
        if isinstance(node.left, ast.Constant) and not isinstance(node.left.value, str):
            return False
        return True
    if isinstance(node, ast.JoinedStr):
        # Only path-building f-strings: the slash must sit at the edge of a
        # literal span touching an interpolated value that is itself pathish
        # (f"{root}/a", f"a/{name}"). Message templates such as f"... and
        # {n} more skip/xfail markers" or f"Passed {passed}/{total}" keep
        # their slashes mid-span or next to plain values, and are never path
        # evidence. A lone interpolation (f"{path}") behaves like the value.
        values = node.values
        if len(values) == 1 and isinstance(values[0], ast.FormattedValue):
            return _is_strong_path_signal(values[0].value, analyzer)

        def _neighbor_is_pathish(index: int) -> bool:
            neighbor = values[index]
            return isinstance(neighbor, ast.FormattedValue) and _is_strong_path_signal(neighbor.value, analyzer)

        for index, value in enumerate(values):
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            text = value.value
            if index > 0 and text.startswith("/") and _neighbor_is_pathish(index - 1):
                return True
            if index + 1 < len(values) and text.endswith("/") and _neighbor_is_pathish(index + 1):
                return True
        return False
    if isinstance(node, ast.Constant):
        return isinstance(node.value, str) and _looks_like_path(node.value)
    if isinstance(node, ast.Name):
        if node.id == "__file__":
            return True
        bound = analyzer._lookup(node.id)
        return bound is not None and bound.outcome == _RESOLVED
    if isinstance(node, ast.Call):
        func_name = _call_name(node.func)
        return func_name in PATH_CONSTRUCTOR_FUNCS or func_name == "open"
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        root_name = _expr_root_name(node)
        if root_name == "__file__":
            return True
        if root_name is None:
            return False
        bound = analyzer._lookup(root_name)
        return bound is not None and bound.outcome == _RESOLVED
    return False


def analyze_python_file(path: Path, root: Path) -> FileDeps:
    """Return the static dependencies and dynamic edges of one file."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, ValueError):
        # An unparseable file cannot be proven safe: fail toward selection.
        return FileDeps(deps=frozenset(), dynamic=True, dynamic_kinds=("unparseable_file",))
    analyzer = _FileAnalyzer(path, root)
    analyzer.visit(tree)
    return FileDeps(
        deps=frozenset(analyzer.deps),
        dynamic=len(analyzer.dynamic_kinds) > 0,
        dynamic_kinds=tuple(analyzer.dynamic_kinds),
    )


def _read_pytest_plugins(conftest: Path) -> tuple[list[str], str | None]:
    """Return plugin module names from tests/conftest.py, or an error reason."""
    try:
        tree = ast.parse(conftest.read_text(encoding="utf-8"), filename=str(conftest))
    except (OSError, SyntaxError, ValueError):
        return [], "conftest_unparseable"
    plugins: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value if isinstance(node, ast.Assign) else node.value
            if value is None:
                continue
            if any(isinstance(t, ast.Name) and t.id == "pytest_plugins" for t in targets):
                if isinstance(value, (ast.List, ast.Tuple)) and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str) for e in value.elts
                ):
                    plugins.extend(e.value for e in value.elts)
                else:
                    return [], "pytest_plugins_not_a_literal_list"
    return plugins, None


def build_dependency_map(root: Path, test_files: list[str]) -> tuple[dict[str, FileDeps], str | None]:
    """Map each canary test file to its dependencies.

    Every entry includes ``tests/conftest.py`` and each ``pytest_plugins``
    module with their transitive dependencies. Returns ``(map, fallback)``
    where ``fallback`` is the whole-suite reason when the shared fixtures
    cannot be resolved (None on success).
    """
    root = root.resolve()
    conftest = root / CONFTEST_REPO_PATH
    if not conftest.is_file():
        return {}, "conftest_missing"
    plugins, plugins_error = _read_pytest_plugins(conftest)
    if plugins_error is not None:
        return {}, plugins_error
    shared = analyze_python_file(conftest, root)
    if shared.dynamic:
        return {}, f"conftest_dynamic:{','.join(shared.dynamic_kinds)}"
    shared_deps = set(shared.deps) | {CONFTEST_REPO_PATH}
    for plugin in plugins:
        deps, unknown = _resolve_import(plugin, conftest, root)
        if unknown or not deps:
            return {}, f"plugin_unresolvable:{plugin}"
        plugin_file = next((dep for dep in deps if dep.endswith(".py")), None)
        if plugin_file is None:
            return {}, f"plugin_unresolvable:{plugin}"
        analyzed = analyze_python_file(root / plugin_file, root)
        if analyzed.dynamic:
            return {}, f"plugin_dynamic:{plugin}:{','.join(analyzed.dynamic_kinds)}"
        shared_deps.update(analyzed.deps)
        shared_deps.add(plugin_file)
    dep_map: dict[str, FileDeps] = {}
    for test_file in test_files:
        analyzed = analyze_python_file(root / test_file, root)
        deps = set(analyzed.deps) | shared_deps
        test_path = root / test_file
        deps.update(dep for dep in (_rel(init, root) for init in _parent_inits(test_path, root)) if dep is not None)
        dep_map[test_file] = FileDeps(
            deps=frozenset(deps),
            dynamic=analyzed.dynamic,
            dynamic_kinds=analyzed.dynamic_kinds,
        )
    return dep_map, None


def collect_canary_node_ids(root: Path, timeout_seconds: int = 600) -> list[str]:
    """Collect canary node IDs with the canonical marker expression."""
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "-n",
            "0",
            "-p",
            "no:cacheprovider",
            "-m",
            MARKER_EXPRESSION,
            "tests",
        ],
        cwd=str(root),
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode not in (0, 5):
        raise RuntimeError(f"canary collection failed (exit {completed.returncode}): {completed.stderr[-2000:]}")
    return parse_collection_output(completed.stdout)


def files_from_node_ids(node_ids: list[str]) -> list[str]:
    """Return the sorted unique test files referenced by node IDs."""
    return sorted({node_id.split("::", 1)[0] for node_id in node_ids})


def _change_covers(changed: str, dep: str) -> bool:
    """Return whether a changed path can affect a dependency edge."""
    if changed == dep:
        return True
    if dep.endswith("/"):
        return changed.startswith(dep)
    # Directory deps cover their whole subtree (every file under them).
    if changed.startswith(dep + "/"):
        return True
    # A changed directory covers every dep beneath it.
    if dep.startswith(changed + "/"):
        return True
    return False


def _same_directory_non_python(changed: str, test_deps: frozenset[str]) -> bool:
    """Check the same-directory rule for a changed non-Python benchbox file."""
    if not changed.startswith("benchbox/") or changed.endswith(".py"):
        return False
    changed_dir = changed.rpartition("/")[0]
    return any(
        dep.startswith("benchbox/") and dep.endswith(".py") and dep.rpartition("/")[0] == changed_dir
        for dep in test_deps
    )


def compute_selection(  # noqa: C901
    changed_paths: list[str],
    dep_map: dict[str, FileDeps],
    node_ids: list[str],
    *,
    collection_info: dict[str, Any] | None = None,
    fallback_reason: str | None = None,
) -> dict[str, Any]:
    """Select canary node IDs affected by the changed paths.

    ``fallback_reason`` carries a whole-suite reason already established
    while building the map (unresolvable fixtures, failed collection).
    """
    changed = sorted({normalize_rel(path) for path in changed_paths if normalize_rel(path)})
    collection_info = collection_info or {}
    file_nodes: dict[str, list[str]] = {}
    for node_id in node_ids:
        file_nodes.setdefault(node_id.split("::", 1)[0], []).append(node_id)

    whole_suite: str | None = fallback_reason
    trigger_paths: list[str] = []
    if whole_suite is None:
        for path in changed:
            if path in WHOLE_SUITE_PATHS:
                whole_suite = f"whole_suite_path:{path}"
                trigger_paths.append(path)
    unmapped: list[str] = []
    if whole_suite is None:
        for path in changed:
            if _is_cant_affect(path):
                continue
            if any(_change_covers(path, dep) for deps in dep_map.values() for dep in deps.deps):
                continue
            if any(path == test_file or path.startswith(test_file + "/") for test_file in dep_map):
                continue
            # The same-directory rule handles non-Python benchbox files
            # without a direct edge; they are mapped, not unmapped.
            if any(_same_directory_non_python(path, deps.deps) for deps in dep_map.values()):
                continue
            unmapped.append(path)
        if unmapped:
            whole_suite = f"unmapped_path:{unmapped[0]}"
            trigger_paths.extend(unmapped)

    selected: dict[str, list[dict[str, str]]] = {}
    if whole_suite is not None:
        for node_id in node_ids:
            selected[node_id] = [{"changed_path": trigger, "edge": "whole_suite"} for trigger in trigger_paths] or [
                {"changed_path": "", "edge": "whole_suite"}
            ]
    elif changed:
        effective = [path for path in changed if not _is_cant_affect(path)]
        for test_file, file_deps in dep_map.items():
            nodes = file_nodes.get(test_file, [])
            if not nodes:
                continue
            if test_file in changed:
                for node_id in nodes:
                    selected.setdefault(node_id, []).append({"changed_path": test_file, "edge": "self"})
            for path in effective:
                if path == test_file:
                    continue
                if any(_change_covers(path, dep) for dep in file_deps.deps):
                    for node_id in nodes:
                        selected.setdefault(node_id, []).append({"changed_path": path, "edge": "dependency"})
                elif _same_directory_non_python(path, file_deps.deps):
                    for node_id in nodes:
                        selected.setdefault(node_id, []).append({"changed_path": path, "edge": "same_directory"})
            if file_deps.dynamic:
                for node_id in nodes:
                    for path in effective:
                        selected.setdefault(node_id, []).append(
                            {"changed_path": path, "edge": "unresolvable_dynamic_edge"}
                        )
    return {
        "marker_expression": MARKER_EXPRESSION,
        "collection": collection_info,
        "changed_paths": changed,
        "whole_suite": whole_suite is not None,
        "whole_suite_reason": whole_suite,
        "unmapped_changed_paths": unmapped,
        "selected": [
            {
                "node_id": node_id,
                "file": node_id.split("::", 1)[0],
                "reasons": selected[node_id],
            }
            for node_id in sorted(selected)
        ],
        "selected_count": len(selected),
        "total_count": len(node_ids),
    }


def _git_changed_paths(repo_root: Path, base_ref: str) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "diff", "--name-only", "--diff-filter=ACDMRT", f"{base_ref}...HEAD"],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"git diff {base_ref}...HEAD failed: {completed.stderr[-1000:]}")
    return [line for line in (normalize_rel(line) for line in completed.stdout.splitlines()) if line]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--changed-path", action="append", default=[], help="changed repo-relative path (repeatable)")
    source.add_argument("--base-ref", help="git ref to diff against HEAD (e.g. origin/develop)")
    source.add_argument("--from-stdin", action="store_true", help="read changed paths (one per line) from stdin")
    parser.add_argument("--collection-file", type=Path, help="newline-delimited node IDs (skip live collection)")
    parser.add_argument("--output", type=Path, help="write the JSON selection (default: stdout)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = args.repo_root.resolve()
    try:
        if args.base_ref:
            changed = _git_changed_paths(root, args.base_ref)
        elif args.from_stdin:
            changed = [line for line in (normalize_rel(line) for line in sys.stdin.read().splitlines()) if line]
        else:
            changed = list(args.changed_path)
        fallback_reason: str | None = None
        node_ids: list[str] = []
        if args.collection_file is not None:
            node_ids = parse_collection_output(args.collection_file.read_text(encoding="utf-8"))
            collection_info: dict[str, Any] = {"source": str(args.collection_file), "node_count": len(node_ids)}
        else:
            try:
                node_ids = collect_canary_node_ids(root)
            except (RuntimeError, subprocess.SubprocessError, OSError) as exc:
                fallback_reason = f"collection_failed:{exc}"
            collection_info = {
                "source": "live_collection",
                "marker_expression": MARKER_EXPRESSION,
                "node_count": len(node_ids),
            }
        dep_map: dict[str, FileDeps] = {}
        if fallback_reason is None:
            dep_map, map_fallback = build_dependency_map(root, files_from_node_ids(node_ids))
            if map_fallback is not None:
                fallback_reason = f"dependency_map_failed:{map_fallback}"
        selection = compute_selection(
            changed,
            dep_map,
            node_ids,
            collection_info=collection_info,
            fallback_reason=fallback_reason,
        )
        rendered = json.dumps(selection, indent=2) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered, encoding="utf-8")
        else:
            sys.stdout.write(rendered)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"canary-impact error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
