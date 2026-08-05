"""Dictionary-recovery privacy gate for the curated results corpus.

``find_public_path_leaks`` only sees *plaintext* absolute paths. Pseudonyms
minted with the empty default salt are a confirmation oracle: a short
dictionary of low-entropy public candidates recovers them with certainty.
This gate closes that hole for the unread-identifier drop (ADR
``adr-published-identifier-field-set``):

1. Drop-field keys must be absent from every corpus JSON file after re-derive.
2. Measured recoverable tokens that lived under dropped fields must be gone.
3. Optional: a fixed safe dictionary of low-entropy *public* candidates must
   not recover a path/machine/host pseudonym still present in the corpus
   (prefixes that only the dropped fields used to mint at those keys).

Retained fields (``endpoint``, ``database_name``, ``submission_path``) still
publish pseudonyms; their salt question is open. Do not record or print
recovered plaintext values in comments, commits, or PR bodies — tokens only.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.core.results.anonymization import AnonymizationManager

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DATA = REPO_ROOT / "results-data"

# Exact JSON keys dropped at the public anonymization boundary.
DROP_FIELD_KEYS = frozenset(
    {
        "machine_id",
        "working_dir",
        "driver_runtime_python_executable",
        "database_path",
        "data_path",
        "engine_host",
    }
)

# Measured recoverable tokens from the pre-drop corpus audit. The path token
# lived under working_dir (dropped). Absence is the re-derive acceptance bar
# for the unread-field work. Tokens only — never embed recovered plaintext.
FORBIDDEN_RECOVERABLE_TOKENS = ("path_1c98692f827e",)

# Low-entropy *public* candidates only (generic product / local defaults). No
# personal names, home directories, or hostnames. Used to attempt recovery
# against prefixes the dropped fields used to emit.
_SAFE_PUBLIC_DICTIONARY = (
    "benchbox",
    "BenchBox",
    "duckdb",
    "sqlite",
    "polars",
    "datafusion",
    "localhost",
    "127.0.0.1",
    ":memory:",
    "main",
    "test",
    "default",
)


def _corpus_json_files() -> list[Path]:
    return sorted(RESULTS_DATA.rglob("*.json"))


def _walk_keys(value: object, *, found: set[str]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            found.add(str(key))
            _walk_keys(child, found=found)
    elif isinstance(value, list):
        for item in value:
            _walk_keys(item, found=found)


def _corpus_blob() -> str:
    """Concatenate corpus file bytes for token scans without echoing contents."""
    parts: list[str] = []
    for path in _corpus_json_files():
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def test_corpus_directory_is_present() -> None:
    assert RESULTS_DATA.is_dir(), f"missing corpus directory: {RESULTS_DATA}"
    assert _corpus_json_files(), "corpus scan found no JSON files - the gate would be vacuous"


def test_drop_field_keys_are_absent_from_corpus() -> None:
    """Unread identifier keys must not reappear after re-derive."""
    offenders: list[str] = []
    unreadable: list[str] = []

    for path in _corpus_json_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            unreadable.append(f"{rel}: {type(exc).__name__}")
            continue
        keys: set[str] = set()
        _walk_keys(payload, found=keys)
        present = sorted(keys & DROP_FIELD_KEYS)
        if present:
            offenders.append(f"{rel}: {', '.join(present)}")

    assert not unreadable, "corpus files could not be parsed (failing closed):\n" + "\n".join(unreadable)
    assert not offenders, f"{len(offenders)} corpus file(s) still publish drop-field keys:\n" + "\n".join(
        offenders[:20]
    )


def test_measured_recoverable_tokens_from_dropped_fields_are_absent() -> None:
    """Tokens recovered under dropped fields must not remain in the corpus."""
    blob = _corpus_blob()
    remaining = [token for token in FORBIDDEN_RECOVERABLE_TOKENS if token in blob]
    assert not remaining, f"recoverable tokens still present after re-derive: {remaining}"


def test_safe_dictionary_does_not_recover_dropped_field_pseudonyms() -> None:
    """A fixed public dictionary must not confirm path/machine/host tokens.

    Only prefixes that dropped fields used to mint at those keys are checked.
    Retained-field prefixes (database, endpoint) stay out of this sweep until
    the open salt decision lands — pinning them here would fight the keep-list
    and the publication fixed point.
    """
    manager = AnonymizationManager()
    blob = _corpus_blob()
    hits: list[str] = []

    for candidate in _SAFE_PUBLIC_DICTIONARY:
        for prefix in ("path", "machine", "host"):
            token = manager._hash_public_identifier(candidate, prefix)
            if token in blob:
                hits.append(token)

    # Deduplicate while preserving order for a stable failure message.
    unique_hits = list(dict.fromkeys(hits))
    assert not unique_hits, f"dictionary-recoverable dropped-field tokens remain: {unique_hits}"
