"""Enforce the frozen-config policy from the spec Section 9.

Files in tests/uat/configs/ whose first line begins with `# FROZEN` are
immutable historical records. Their SHA-256 must match the entry in
.frozen-hashes.json. Edits are caught at PR time by this test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

pytestmark = pytest.mark.fast

CONFIGS_DIR = Path(__file__).resolve().parent / "configs"
HASH_FILE = CONFIGS_DIR / ".frozen-hashes.json"


def _frozen_files() -> list[Path]:
    out: list[Path] = []
    for p in CONFIGS_DIR.glob("*.yaml"):
        first_line = p.read_text(encoding="utf-8").splitlines()[0:1]
        if first_line and first_line[0].lstrip().startswith("# FROZEN"):
            out.append(p)
    return sorted(out)


def test_every_frozen_file_has_a_hash_entry():
    expected = json.loads(HASH_FILE.read_text(encoding="utf-8"))
    for p in _frozen_files():
        assert p.name in expected, f"missing hash entry for frozen file {p.name}"


def test_frozen_files_match_recorded_hash():
    expected = json.loads(HASH_FILE.read_text(encoding="utf-8"))
    for p in _frozen_files():
        actual = hashlib.sha256(p.read_bytes()).hexdigest()
        assert actual == expected[p.name], (
            f"FROZEN file {p.name} content drifted from .frozen-hashes.json. "
            "Either revert the edit or clone the file under a new name."
        )


def test_no_orphaned_hash_entries():
    expected = json.loads(HASH_FILE.read_text(encoding="utf-8"))
    frozen_names = {p.name for p in _frozen_files()}
    for name in expected:
        assert name in frozen_names, f"hash entry for {name} but file is missing or no longer marked FROZEN"
