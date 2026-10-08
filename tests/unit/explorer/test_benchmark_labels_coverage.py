from __future__ import annotations

import re
from pathlib import Path

import pytest

from benchbox.core.benchmark_registry import get_benchmark_surface, list_benchmark_ids

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
EXPLORER_UTILS = REPO_ROOT / "results-explorer" / "src" / "utils.ts"

KNOWN_DISPLAY_ALIASES = frozenset({"star_schema", "tsbs-devops"})


def _parse_label_keys(source: str) -> frozenset[str]:
    match = re.search(
        r"export const BENCHMARK_LABELS:\s*Record<string,\s*string>\s*=\s*{(.+?)};",
        source,
        re.DOTALL,
    )
    if match is None:
        raise AssertionError("Could not locate BENCHMARK_LABELS object in utils.ts")
    body = match.group(1)
    keys: set[str] = set()
    for entry in re.finditer(r'^\s*(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*:', body, re.MULTILINE):
        keys.add(entry.group(1) or entry.group(2))
    return frozenset(keys)


def test_explorer_labels_cover_every_canonical_benchmark_id() -> None:
    explorer_keys = _parse_label_keys(EXPLORER_UTILS.read_text(encoding="utf-8"))
    canonical = frozenset(bid for bid in list_benchmark_ids() if get_benchmark_surface(bid) == "public")

    missing = canonical - explorer_keys
    assert not missing, (
        f"BENCHMARK_LABELS is missing canonical benchmark ids: {sorted(missing)}. "
        f"Add a label entry in {EXPLORER_UTILS.relative_to(REPO_ROOT)} for each."
    )


def test_explorer_labels_have_no_unexplained_extras() -> None:
    explorer_keys = _parse_label_keys(EXPLORER_UTILS.read_text(encoding="utf-8"))
    canonical = frozenset(bid for bid in list_benchmark_ids() if get_benchmark_surface(bid) == "public")

    extras = explorer_keys - canonical - KNOWN_DISPLAY_ALIASES
    assert not extras, (
        f"BENCHMARK_LABELS has unexplained extra ids: {sorted(extras)}. "
        f"Either retire them, add them to the canonical registry, or list "
        f"them in KNOWN_DISPLAY_ALIASES with a comment explaining why."
    )
