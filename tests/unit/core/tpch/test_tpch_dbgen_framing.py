# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_REPO_ROOT = Path(__file__).resolve().parents[4]

_BUILD_CONFIG_FILES = (
    _REPO_ROOT / "_sources" / "tpc-h" / "dbgen" / "makefile.suite",
    _REPO_ROOT / "_sources" / "compilation" / "scripts" / "compile-all-platforms.sh",
    _REPO_ROOT / "benchbox" / "utils" / "tpc_compilation.py",
)


@pytest.mark.parametrize("config_file", _BUILD_CONFIG_FILES, ids=lambda p: p.name)
def test_config_defines_eol_handling(config_file: Path) -> None:
    if not config_file.exists():
        pytest.skip(f"source tree not available: {config_file}")
    text = config_file.read_text(encoding="utf-8")
    assert "-DEOL_HANDLING" in text, (
        f"{config_file} does not define -DEOL_HANDLING; TPC-H row framing "
        "would diverge from BenchBox's canonical no-trailing-separator "
        "convention."
    )
