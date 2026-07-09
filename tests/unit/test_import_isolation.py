"""Import-isolation contracts for the package and CLI startup paths."""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


HEAVY_MODULES = (
    "pandas",
    "polars",
    "pyarrow",
    "duckdb",
    "psycopg",
    "boto3",
    "google",
    "cloudpathlib",
)


ENTRYPOINTS = (
    pytest.param("import benchbox", "import benchbox", id="import-benchbox"),
    pytest.param("import benchbox.cli.main", "import benchbox.cli.main", id="import-cli-main"),
    pytest.param(
        "benchbox --help",
        """
        import runpy
        import shutil
        import sys

        script = shutil.which("benchbox")
        if script is None:
            raise AssertionError("benchbox console script is not on PATH")
        sys.argv = ["benchbox", "--help"]
        try:
            runpy.run_path(script, run_name="__main__")
        except SystemExit as exc:
            if exc.code not in (0, None):
                raise
        """,
        id="benchbox-help",
    ),
)


def _run_entrypoint(
    entrypoint_code: str, heavy_roots: tuple[str, ...] = HEAVY_MODULES
) -> subprocess.CompletedProcess[str]:
    code = "\n".join(
        [
            "import json",
            "import sys",
            textwrap.dedent(entrypoint_code).strip(),
            f"heavy_roots = {heavy_roots!r}",
            "loaded = {",
            "    root: sorted(name for name in sys.modules if name == root or name.startswith(root + '.'))",
            "    for root in heavy_roots",
            "    if any(name == root or name.startswith(root + '.') for name in sys.modules)",
            "}",
            "print(json.dumps(loaded, sort_keys=True))",
        ]
    )
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)


@pytest.mark.parametrize(("entrypoint", "entrypoint_code"), ENTRYPOINTS)
@pytest.mark.parametrize("module_name", HEAVY_MODULES)
def test_entrypoints_do_not_import_heavy_optional_modules(
    entrypoint: str, entrypoint_code: str, module_name: str
) -> None:
    result = _run_entrypoint(entrypoint_code)
    assert result.returncode == 0, (
        f"{entrypoint} failed before import isolation could be checked:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    loaded_by_root = json.loads(result.stdout.splitlines()[-1])
    assert module_name not in loaded_by_root, (
        f"{entrypoint} imported optional dependency {module_name}: {loaded_by_root.get(module_name, [])}"
    )


# --- break-root-import-cycle regression coverage -----------------------------
#
# benchbox/utils/version.py and benchbox/utils/datagen_manifest.py used to do
# `import benchbox` at module scope, creating a static import edge from these
# leaf utility modules back to the package root. Because
# benchbox/utils/verbosity.py imports utils.version and is itself imported by
# nearly every subsystem, that single edge pulled a large strongly-connected
# component into one cycle rooted at benchbox/__init__.py. See
# _project/TODO/main/planning/break-root-import-cycle.yaml.

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LEAF_MODULES_MUST_NOT_IMPORT_PACKAGE_ROOT = (
    _REPO_ROOT / "benchbox" / "utils" / "version.py",
    _REPO_ROOT / "benchbox" / "utils" / "datagen_manifest.py",
)


@pytest.mark.parametrize(
    "module_path",
    _LEAF_MODULES_MUST_NOT_IMPORT_PACKAGE_ROOT,
    ids=lambda path: path.name,
)
def test_version_no_root_import(module_path: Path) -> None:
    """utils/version.py and utils/datagen_manifest.py must not import the
    benchbox package root at module scope.

    This is a static (AST-based) check rather than a live sys.modules probe.
    Python's import machinery always fully initializes a parent package
    before importing any of its submodules, so a subprocess doing
    `import benchbox.utils.version` alone can never observe "benchbox absent
    from sys.modules" regardless of whether this file imports the root -
    parent-package initialization is unconditional. The meaningful,
    checkable claim is the static one: neither leaf module carries a
    source-level `import benchbox` dependency edge, which is what actually
    pulled these modules into the root-rooted strongly-connected component.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    root_imports = [
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name == "benchbox"
    ]
    assert not root_imports, (
        f"{module_path} imports the benchbox package root at module scope, "
        "recreating the cycle broken by break-root-import-cycle. Import a "
        "leaf submodule (e.g. benchbox.utils.*) instead of `import benchbox`."
    )


def test_bare_import_does_not_eagerly_load_nyctaxi() -> None:
    """`import benchbox` must not eagerly import NYCTaxi.

    NYCTaxi is routed through the lazy `_BENCHMARK_REGISTRY` /
    `__getattr__` mechanism like the other optional benchmarks (see
    break-root-import-cycle w5), so a bare `import benchbox` should not pull
    in `benchbox.nyctaxi` or `benchbox.core.nyctaxi` - which previously
    eagerly imported numpy via core/nyctaxi/downloader.py and
    core/nyctaxi/queries.py on every `import benchbox`.

    Note: this does not assert numpy itself is absent from sys.modules -
    benchbox.tpch_skew's generator already imports numpy eagerly via a
    separate, pre-existing import unrelated to NYCTaxi and out of scope for
    this fix, so numpy remains on the cold-start path regardless of this
    change. See break-root-import-cycle.yaml notes for w5.
    """
    nyctaxi_roots = ("benchbox.nyctaxi", "benchbox.core.nyctaxi")
    result = _run_entrypoint("import benchbox", heavy_roots=nyctaxi_roots)
    assert result.returncode == 0, (
        f"import benchbox failed before import isolation could be checked:\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    loaded_by_root = json.loads(result.stdout.splitlines()[-1])
    assert not loaded_by_root, f"import benchbox eagerly loaded NYCTaxi: {loaded_by_root}"
