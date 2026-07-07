"""Guardrail: plan CLI coverage suites that stub the real data-load path must
keep a sibling test that exercises the REAL path (qpc-11 w2 / finding F8.1).

The masking bug this prevents: all three plan CLI coverage suites used to
monkeypatch ``load_result_file`` (or ``PlanHistory``) with hand-built fakes
that DEFINED attributes the production objects lack (notably ``.phases``), so
the suites stayed green while every real invocation crashed. Fast fakes for
flag/option coverage are fine, but each such suite must ALSO contain at least
one test that drives the CLI through the real loader / real store with no
monkeypatch, so attribute drift is actually caught.

This is a lightweight text-level lint (mirrors the guardrail style in
tests/unit/test_todo_executable_docs.py) rather than an AST analysis: it keys
off the presence of a ``*real*`` test function in any suite that stubs the
data-load boundary.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_COMMANDS_DIR = Path(__file__).resolve().parent

# The plan CLI coverage suites guarded here, with the data-load symbol each one
# stubs for its fast flag/option tests. Any suite that monkeypatches that
# symbol must keep a real-path companion test.
_GUARDED_SUITES = {
    "test_show_plan_coverage.py": "load_result_file",
    "test_compare_plans_coverage.py": "load_result_file",
    "test_plan_history_coverage.py": "PlanHistory",
}


def _stubs_symbol(text: str, symbol: str) -> bool:
    """True if the suite monkeypatches ``symbol`` (the data-load boundary)."""
    return f'"{symbol}"' in text and "monkeypatch.setattr" in text


# A real-path companion test is identified by a ``real`` token in its OWN
# function name (e.g. ``test_show_plan_real_loader_...``,
# ``test_..._real_history_store_...``). Matching the function name -- not just
# any "real" appearing in a comment/docstring/helper -- is what makes deleting
# the companion test actually trip this guardrail.
_REAL_PATH_TEST_RE = re.compile(r"^def (test_\w*real\w*)\(", re.MULTILINE)


def _has_real_path_test(text: str) -> bool:
    """True if the suite defines at least one real-path test function."""
    return bool(_REAL_PATH_TEST_RE.search(text))


@pytest.mark.parametrize(("filename", "stubbed_symbol"), sorted(_GUARDED_SUITES.items()))
def test_plan_cli_suite_that_stubs_loader_has_real_path_test(filename: str, stubbed_symbol: str) -> None:
    suite_path = _COMMANDS_DIR / filename
    assert suite_path.exists(), f"guarded plan CLI suite missing: {filename}"
    text = suite_path.read_text(encoding="utf-8")

    if not _stubs_symbol(text, stubbed_symbol):
        # Suite no longer stubs the data-load boundary at all -> nothing to guard.
        return

    assert _has_real_path_test(text), (
        f"{filename} monkeypatches {stubbed_symbol!r} for fast coverage but has no "
        f"real-path (no-monkeypatch) companion test. Add one that drives the CLI "
        f"through the real loader/store on a tmp-file bundle so fake-shape drift "
        f"(e.g. a fabricated '.phases' attribute) is actually caught. See qpc-11 / F8.1."
    )
