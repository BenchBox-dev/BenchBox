"""Regression guard: every dsdgen invocation must pin ``-terminate n``.

Unlike TPC-H's ``dbgen`` (whose row framing is fixed at compile time via
``EOL_HANDLING``), TPC-DS ``dsdgen`` exposes framing as a *runtime* flag:
``-terminate n`` disables the trailing field separator. BenchBox relies on
passing ``-terminate n`` on every invocation so TPC-DS output is byte-identical
across platforms regardless of how the binary was compiled -- the same
no-trailing-separator convention the bundled TPC-H binaries enforce via
``-DEOL_HANDLING`` (see ``tests/unit/core/tpch/test_tpch_dbgen_framing.py``).

If a new dsdgen call site forgets ``-terminate n`` (or passes ``-terminate y``),
that platform's generated data would silently regain trailing delimiters and
diverge. This test parses the generator source so it catches such regressions
without needing to execute dsdgen.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import benchbox

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_TPCDS_GENERATOR_DIR = Path(benchbox.__file__).parent / "core" / "tpcds" / "generator"

# Matches a ``"-terminate", "<value>"`` pair in a command list, tolerating
# newlines/whitespace between the two string literals.
_TERMINATE_PAIR = re.compile(r'"-terminate"\s*,\s*"([^"]+)"')
# Catches a bare ``"-terminate"`` not immediately followed by a string literal.
_TERMINATE_TOKEN = re.compile(r'"-terminate"')


def _generator_sources() -> list[Path]:
    return sorted(_TPCDS_GENERATOR_DIR.glob("*.py"))


def test_generator_sources_present() -> None:
    sources = _generator_sources()
    assert sources, f"no TPC-DS generator sources under {_TPCDS_GENERATOR_DIR}"


@pytest.mark.parametrize("source", _generator_sources(), ids=lambda p: p.name)
def test_every_terminate_flag_is_n(source: Path) -> None:
    text = source.read_text(encoding="utf-8")

    token_count = len(_TERMINATE_TOKEN.findall(text))
    if token_count == 0:
        pytest.skip(f"{source.name} issues no dsdgen -terminate flag")

    values = _TERMINATE_PAIR.findall(text)
    assert len(values) == token_count, (
        f"{source.name}: {token_count} '-terminate' token(s) but "
        f"{len(values)} were followed by a string value -- a call site may pass "
        "the flag without an argument."
    )
    for value in values:
        assert value == "n", (
            f"{source.name}: dsdgen invoked with '-terminate {value}'; must be "
            "'n' to disable trailing field separators (BenchBox framing "
            "convention)."
        )
