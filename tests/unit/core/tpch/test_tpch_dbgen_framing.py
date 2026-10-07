"""Fast guard: every TPC-H dbgen build entrypoint defines ``-DEOL_HANDLING``.

BenchBox's canonical TPC-H framing convention is **no trailing field
separator** (dbgen compiled ``-DEOL_HANDLING``), matching TPC-DS which is
always invoked with ``-terminate n``. ``core/tpch/generator.py`` streams raw
dbgen bytes straight into ``.tbl``/``.tbl.N.zst`` output, so a compile-time
framing difference between the per-platform binaries would silently produce
platform-dependent generated data -- a reproducibility defect (it once
surfaced as a DataFusion "Expected 8 columns, got 9" failure, worked around
at the reader layer in PR #1053).

This module is the host-independent guard: it asserts each dbgen build
entrypoint defines ``-DEOL_HANDLING`` so source drift is caught before it ever
reaches a compiled binary. The complementary runtime guard that executes the
bundled binaries lives in ``test_tpch_dbgen_framing_binaries.py`` (slow).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# Repo root: tests/unit/core/tpch/<this file> -> parents[4]
_REPO_ROOT = Path(__file__).resolve().parents[4]

# dbgen build entrypoints that must all agree on the framing convention.
_BUILD_CONFIG_FILES = (
    _REPO_ROOT / "_sources" / "tpc-h" / "dbgen" / "makefile.suite",
    _REPO_ROOT / "_sources" / "compilation" / "scripts" / "compile-all-platforms.sh",
    _REPO_ROOT / "benchbox" / "utils" / "tpc_compilation.py",
)


@pytest.mark.parametrize("config_file", _BUILD_CONFIG_FILES, ids=lambda p: p.name)
def test_config_defines_eol_handling(config_file: Path) -> None:
    """Each dbgen build entrypoint must define -DEOL_HANDLING."""
    if not config_file.exists():
        pytest.skip(f"source tree not available: {config_file}")
    text = config_file.read_text(encoding="utf-8")
    assert "-DEOL_HANDLING" in text, (
        f"{config_file} does not define -DEOL_HANDLING; TPC-H row framing "
        "would diverge from BenchBox's canonical no-trailing-separator "
        "convention."
    )


_DBGEN_SOURCE_DIR = "_sources/tpc-h/dbgen"
_RUNTIME_BUILD_OUTPUTS = ("Makefile.auto", "dbgen", "qgen", "rnd.o")


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=_REPO_ROOT, capture_output=True, text=True, check=False)


def _require_git_checkout() -> None:
    if shutil.which("git") is None or _git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git checkout")


def test_dbgen_source_tree_tracks_no_build_artifacts() -> None:
    _require_git_checkout()
    tracked = _git("ls-files", "--", f"{_DBGEN_SOURCE_DIR}/*.o", f"{_DBGEN_SOURCE_DIR}/Makefile.auto")
    assert tracked.stdout.split() == [], (
        "the runtime auto-compile fallback regenerates these files in place; tracking them leaves stale "
        f"objects that can be linked into a fresh build: {tracked.stdout.split()}"
    )


@pytest.mark.parametrize("name", _RUNTIME_BUILD_OUTPUTS)
def test_dbgen_runtime_build_outputs_are_ignored(name: str) -> None:
    _require_git_checkout()
    ignored = _git("check-ignore", "--no-index", "-q", f"{_DBGEN_SOURCE_DIR}/{name}")
    assert ignored.returncode == 0, f"{_DBGEN_SOURCE_DIR}/{name} is written by the auto-compile path but not ignored"
