"""Drift guard: localResult.ts must track the canonical schema versions.

Why a *test* and not a generated file: the explorer ships as a pre-built
SPA and the canonical version set lives in
``benchbox.core.results.schema_policy``. A code-gen step would add build
coupling that doesn't pay for itself yet. A test is enough — it fires on
develop the moment a schema version is added without updating the local
preview gate, which is when the catch is needed. It also pins key-presence
selection for the version aliases so an explicit null is not silently
replaced by a legacy value.

If a new canonical version appears here, update
``SUPPORTED_SCHEMA_VERSIONS`` in ``results-explorer/src/lib/localResult.ts``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from benchbox.core.results.schema_policy import KNOWN_SCHEMA_V2_VERSIONS

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL_RESULT_TS = REPO_ROOT / "results-explorer" / "src" / "lib" / "localResult.ts"

_VERSION_SET_RE = re.compile(r"const SUPPORTED_SCHEMA_VERSIONS = new Set\(\[(?P<versions>[^\]]*)\]\)")


def _source() -> str:
    return LOCAL_RESULT_TS.read_text(encoding="utf-8")


def test_supported_versions_match_canonical_set() -> None:
    match = _VERSION_SET_RE.search(_source())
    assert match is not None, "SUPPORTED_SCHEMA_VERSIONS declaration not found"
    found = re.findall(r'"([^"]+)"', match.group("versions"))
    assert sorted(found) == sorted(KNOWN_SCHEMA_V2_VERSIONS)


def test_version_fallback_chain_matches_helper() -> None:
    source = _source()
    assert 'hasOwn("result_schema_version")' in source
    assert 'hasOwn("version")' in source
    assert "result_schema_version and version must match" in source


TRANSFORMER_PY = REPO_ROOT / "_project" / "scripts" / "explorer_pipeline" / "transformer.py"

_LITERAL_RE = re.compile(r"""['"]2\.[012]['"]""")


def test_transformer_funnels_versions_through_shared_policy() -> None:
    """The pipeline must not hardcode bundle schema versions of its own."""
    source = TRANSFORMER_PY.read_text(encoding="utf-8")
    assert "EXPLORER_INPUT_SCHEMA_POLICY" in source
    assert "result_schema_version_value" in source
    assert _LITERAL_RE.search(source) is None, "bundle schema version literal outside the shared policy"


def test_consumer_policies_share_canonical_set() -> None:
    """Every bundle-input policy must accept exactly the canonical family."""
    from benchbox.core.results.schema_policy import (
        EXPLORER_INPUT_SCHEMA_POLICY,
        LOADER_SCHEMA_POLICY,
        NORMALIZER_SCHEMA_POLICY,
        PUBLIC_SUBMISSION_SCHEMA_POLICY,
        RUNTIME_SCHEMA_POLICY,
    )

    for policy in (
        RUNTIME_SCHEMA_POLICY,
        LOADER_SCHEMA_POLICY,
        NORMALIZER_SCHEMA_POLICY,
        PUBLIC_SUBMISSION_SCHEMA_POLICY,
        EXPLORER_INPUT_SCHEMA_POLICY,
    ):
        assert set(policy.accepted_versions) == set(KNOWN_SCHEMA_V2_VERSIONS), policy.policy_name
