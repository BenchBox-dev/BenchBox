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
    source = TRANSFORMER_PY.read_text(encoding="utf-8")
    assert "EXPLORER_INPUT_SCHEMA_POLICY" in source
    assert "result_schema_version_value" in source
    assert _LITERAL_RE.search(source) is None, "bundle schema version literal outside the shared policy"


def test_consumer_policies_share_canonical_set() -> None:
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
