"""Pin the real `tuning_validation_status` vocabulary.

From the 2026-07-12 tuning review, finding R7: `test_tpc_tuning_template_parity.py`
pinned a fixture value `"PASSED"` that production code never emits. The real
values are assigned in `benchbox/platforms/base/adapter.py` (`NOT_APPLICABLE`,
`APPLIED`, `FAILED_TO_SAVE`) and defaulted in `benchbox/core/results/models.py`
(`NOT_VALIDATED`).

Rather than hand-copy those four strings into a hardcoded set (which could
silently drift the moment adapter.py's literals change), this module
statically extracts every string literal actually assigned to the
`tuning_validation_status` local in adapter.py via `ast`, plus the dataclass
default from `BenchmarkResults`, and pins *that derived set* against the
reviewed vocabulary. A new/renamed/removed status in adapter.py changes the
derived set and fails this test, forcing a conscious update here -- the same
shape as `test_known_platform_set_stays_in_sync_with_compatibility_map` in
`test_platform_identity_keys.py`.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from benchbox.core.results.models import BenchmarkResults
from benchbox.platforms.base import adapter as adapter_module

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

# The reviewed, real vocabulary (finding R7). Production only ever assigns
# these four values to `tuning_validation_status` -- "PASSED"/"FAILED" (a
# pass/fail test-style vocabulary) do not exist anywhere in the codebase.
EXPECTED_VALIDATION_STATUSES = frozenset(
    {
        "NOT_APPLICABLE",
        "APPLIED",
        "FAILED_TO_SAVE",
        "NOT_VALIDATED",
    }
)


def _discover_adapter_assigned_statuses() -> set[str]:
    """Statically extract every string literal assigned to the
    `tuning_validation_status` local anywhere in adapter.py, including both
    arms of the `"APPLIED" if ... else "FAILED_TO_SAVE"` conditional
    assignment. This walks the real module source instead of redeclaring the
    values, so it fails the moment adapter.py's literals change.
    """
    source = inspect.getsource(adapter_module)
    tree = ast.parse(source)
    statuses: set[str] = set()

    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "tuning_validation_status" for target in node.targets):
            continue
        for sub in ast.walk(node.value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                statuses.add(sub.value)

    return statuses


def _models_default_validation_status() -> str:
    """Read `BenchmarkResults.tuning_validation_status`'s dataclass default."""
    for f in dataclasses.fields(BenchmarkResults):
        if f.name == "tuning_validation_status":
            assert f.default is not dataclasses.MISSING, (
                "tuning_validation_status must have a plain default (no default_factory) "
                "for this test to read it statically"
            )
            return f.default
    raise AssertionError("BenchmarkResults has no 'tuning_validation_status' field")


class TestValidationStatusVocabulary:
    def test_adapter_assigned_statuses_match_reviewed_set(self) -> None:
        discovered = _discover_adapter_assigned_statuses()
        assert discovered, "Expected to discover at least one tuning_validation_status literal in adapter.py"
        assert discovered == EXPECTED_VALIDATION_STATUSES - {"NOT_VALIDATED"}, (
            f"adapter.py's tuning_validation_status literals changed: {sorted(discovered)}. "
            "Update EXPECTED_VALIDATION_STATUSES (and any fixtures/docs referencing the "
            "vocabulary) to match, or revert the unintended change."
        )

    def test_models_default_is_not_validated(self) -> None:
        assert _models_default_validation_status() == "NOT_VALIDATED"

    def test_full_vocabulary_is_adapter_literals_plus_models_default(self) -> None:
        full_vocabulary = _discover_adapter_assigned_statuses() | {_models_default_validation_status()}
        assert full_vocabulary == EXPECTED_VALIDATION_STATUSES

    def test_pass_fail_style_values_are_not_part_of_the_vocabulary(self) -> None:
        # Regression guard for finding R7: "PASSED"/"FAILED" read like a
        # pass/fail test result, not a tuning-validation outcome, and were
        # never emitted by production -- pin that they never sneak back in.
        full_vocabulary = _discover_adapter_assigned_statuses() | {_models_default_validation_status()}
        assert "PASSED" not in full_vocabulary
        assert "FAILED" not in full_vocabulary
