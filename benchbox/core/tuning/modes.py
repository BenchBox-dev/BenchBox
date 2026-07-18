"""Canonical `tuning_mode` vocabulary (ADR-2).

Single production source of truth for the pinned `tuning_mode` value set
decided in `docs/development/tuning-adr-002-mode-vocabulary-fallback-facets.md`.

The vocabulary is also pinned as a test contract shared with the TypeScript
side at `tests/unit/core/tuning/fixtures/tuning_mode_vocabulary.yaml` (see
`tests/unit/core/tuning/test_tuning_mode_vocabulary.py` and
`results-explorer/src/lib/__tests__/tuningModeVocabulary.test.ts`). This
module is what production code (resolver, schema emission, explorer ingest)
should import from; the YAML fixture is the cross-language test pin, not a
second production source.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

#: `--tuning tuned` resolved via a curated auto-discovered or explicit template.
TUNED = "tuned"

#: `--tuning tuned` requested but no template was found; basic constraints-only
#: config was used instead. Distinct from ``TUNED`` so fallback runs never
#: facet-match curated-template runs (ADR-2 finding C4).
TUNED_FALLBACK = "tuned-fallback"

#: Tuning explicitly disabled (baseline).
NOTUNING = "notuning"

#: Platform/engine automatic tuning selection (smart defaults).
AUTO = "auto"

#: User-supplied tuning file. Recorded as this canonical mode plus a separate
#: template reference/hash field -- never the raw local file path.
CUSTOM = "custom"

#: The complete pinned vocabulary, in ADR-2 §2's declared order.
MODES: tuple[str, ...] = (TUNED, TUNED_FALLBACK, NOTUNING, AUTO, CUSTOM)

#: Sentinel for "no tuning_mode was recorded" (older bundles, ingest gaps).
#: Never a legal `tuning_mode` value in a freshly emitted bundle; distinct
#: from -- and never coerced to or from -- NOTUNING.
NOT_RECORDED = "not-recorded"


def is_canonical_mode(value: str | None) -> bool:
    """Whether ``value`` is one of the five pinned `tuning_mode` values."""
    return value in MODES
