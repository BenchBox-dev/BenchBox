"""Trust-boundary tests for the dedicated skill-integrity CI lane."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from skill_sync_ci_policy import (
    VERIFIER_REF,
    PolicyError,
    compare_manifest_texts,
    normalize_ref_only_manifest,
    validate_manifest_text,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]
ROOT = Path(__file__).resolve().parents[3]
MANIFEST = (ROOT / "skill-sync.yaml").read_text(encoding="utf-8")


def _canonical_ref(text: str) -> str:
    match = re.search(r"name:\s*canonical.*?ref:\s*([0-9a-f]{40})", text, re.DOTALL)
    assert match is not None
    return match.group(1)


def _replace_ref(text: str, old: str, new: str) -> str:
    assert old in text
    return text.replace(old, new, 1)


def test_current_manifest_satisfies_source_and_target_policy() -> None:
    validate_manifest_text(MANIFEST)
    assert len(VERIFIER_REF) == 40
    assert VERIFIER_REF == "6d09682dabe2ff0d68f400d60f8ba8b87f8c02aa"


def test_approved_immutable_ref_only_change_is_narrow_eligible() -> None:
    head = _replace_ref(
        MANIFEST,
        _canonical_ref(MANIFEST),
        "a" * 40,
    )

    decision = compare_manifest_texts(MANIFEST, head, base_ref="b" * 40)

    assert decision.narrow_eligible is True
    assert decision.reason == "approved_ref_only_change"
    assert normalize_ref_only_manifest(MANIFEST) == normalize_ref_only_manifest(head)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (
            "https://github.com/joeharris76/skill-sync-skills.git",
            "https://example.invalid/hostile.git",
        ),
        ("subdir: skills", "subdir: other"),
        ("dir: .claude/skills", "dir: ../outside"),
        ("install_mode: mirror", "install_mode: copy"),
        ("source_name: product", "source_name: canonical"),
    ],
)
def test_structural_trust_boundary_change_forces_full_ci(old: str, new: str) -> None:
    decision = compare_manifest_texts(MANIFEST, _replace_ref(MANIFEST, old, new))

    assert decision.narrow_eligible is False
    assert decision.reason.startswith(("manifest_policy_error:", "manifest_structural_change"))


def test_floating_manifest_ref_is_rejected() -> None:
    head = _replace_ref(
        MANIFEST,
        _canonical_ref(MANIFEST),
        "main",
    )

    with pytest.raises(PolicyError, match="40-character commit SHA"):
        validate_manifest_text(head)


def test_missing_or_malformed_manifest_fails_closed() -> None:
    decision = compare_manifest_texts("version: 1\n", MANIFEST)

    assert decision.narrow_eligible is False
    assert decision.reason.startswith("manifest_policy_error:")


def test_comments_or_non_ref_config_edits_are_structural() -> None:
    head = MANIFEST.replace("version: 1\n", "version: 1\n# changed policy prose\n", 1)

    decision = compare_manifest_texts(MANIFEST, head)

    assert decision.narrow_eligible is False
    assert decision.reason == "manifest_structural_change"
