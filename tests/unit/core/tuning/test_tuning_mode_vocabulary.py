"""Shared Python<->TypeScript `tuning_mode` vocabulary pin (ADR-2).

From the 2026-07-12 tuning review, finding R7 / ADR-002
(docs/development/tuning-adr-002-mode-vocabulary-fallback-facets.md): there
was no single shared source for the pinned `tuning_mode` vocabulary, so
`benchbox/cli/tuning.py` (`tuned`/`notuning`/`auto`/`balanced`) and
`results-explorer/src/components/TuningBadge.tsx` (`tuned`/`notuning`/`auto`)
independently hardcoded different, non-agreeing sets.

ADR-2 §2 pins the vocabulary as *exactly* `{tuned, tuned-fallback, notuning,
auto, custom}` plus a distinct "not recorded" state for absent/legacy data,
and requires "a single shared artifact consumed by both the Python and
TypeScript test suites, so the two sides cannot drift independently again".

This module is the Python half of that pin:
`tests/unit/core/tuning/fixtures/tuning_mode_vocabulary.yaml` is the shared
artifact (note: not under a `data/` directory -- the repo's `.gitignore`
blanket-ignores any directory literally named `data/`, which would silently
drop this checked-in fixture); `results-explorer/src/lib/__tests__/tuningModeVocabulary.test.ts`
is the TypeScript half (it loads the *same* YAML file via a `uv run --
python -c` subprocess -- the same shell-out pattern already established by
`db-remediation-pin.test.ts` -- rather than hardcoding its own mirror, so
there is exactly one place the vocabulary is declared).

This pins the ADR-2 TARGET vocabulary as a test contract. It intentionally
does NOT assert current-emitter compliance: `benchbox/cli/tuning.py` still
emits `"balanced"` and the explorer's `TuningBadge.tsx` still only
recognizes `tuned`/`notuning`/`auto`. Migrating production code to this
vocabulary is `tuning-mode-vocabulary-and-facet-implementation-20260712`, a
separate, unstarted TODO.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

VOCAB_PATH = Path(__file__).resolve().parent / "fixtures" / "tuning_mode_vocabulary.yaml"

# ADR-2 §2's decided vocabulary, in the order the ADR lists it.
EXPECTED_MODES = ["tuned", "tuned-fallback", "notuning", "auto", "custom"]
EXPECTED_NOT_RECORDED_SENTINEL = "not-recorded"


def _load_vocabulary_artifact() -> dict[str, Any]:
    return yaml.safe_load(VOCAB_PATH.read_text(encoding="utf-8"))


class TestSharedVocabularyArtifactMatchesADR2:
    def test_artifact_exists(self) -> None:
        assert VOCAB_PATH.exists(), (
            f"Shared vocabulary artifact missing at {VOCAB_PATH}; "
            "results-explorer/src/lib/__tests__/tuningModeVocabulary.test.ts loads this same "
            "file and will also fail if it moves. Keep it out of any 'data/' directory -- "
            "the repo .gitignore blanket-ignores those."
        )

    def test_modes_match_adr2_decided_set(self) -> None:
        spec = _load_vocabulary_artifact()
        assert spec["modes"] == EXPECTED_MODES

    def test_not_recorded_sentinel_matches_adr2(self) -> None:
        spec = _load_vocabulary_artifact()
        assert spec["not_recorded_sentinel"] == EXPECTED_NOT_RECORDED_SENTINEL

    def test_raw_file_paths_are_not_part_of_the_vocabulary(self) -> None:
        # ADR-2 §2: "Raw file paths are not a legal tuning_mode value under
        # any circumstance." Pin that no artifact entry looks like a path.
        spec = _load_vocabulary_artifact()
        for mode in spec["modes"]:
            assert "/" not in mode
            assert "\\" not in mode
            assert not mode.endswith(".yaml")

    def test_balanced_is_not_part_of_the_vocabulary(self) -> None:
        # ADR-2 §2: the wizard's "balanced" string is a template flavor
        # selector, not a tuning_mode value, and must not appear verbatim.
        spec = _load_vocabulary_artifact()
        assert "balanced" not in spec["modes"]
