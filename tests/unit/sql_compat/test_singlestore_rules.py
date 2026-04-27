"""Unit tests for SingleStore DDL_OPTIMIZE registry rules.

Verifies that each of the four registered rules has the correct rule_id,
action type, payload type, and that its transformer_id names a callable
method on SingleStoreAdapter.  These are governance/structure tests;
behavioral tests live in tests/unit/platforms/test_singlestore_adapter.py.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _mock_singlestoredb(monkeypatch):
    """Stub the singlestoredb SDK so SingleStoreAdapter() succeeds without the optional driver.

    This file constructs SingleStoreAdapter() directly (no connection is opened),
    but the constructor still raises ImportError when ``_s2 is None``. The autouse
    _s2 mock that lives in test_singlestore_adapter.py is scoped to that file, so
    we install our own here.
    """
    fake_module = MagicMock(name="singlestoredb")
    monkeypatch.setitem(sys.modules, "singlestoredb", fake_module)
    monkeypatch.setattr("benchbox.platforms.singlestore._s2", fake_module, raising=False)
    yield


_EXPECTED_RULES = [
    {
        "rule_id": "ddl_optimize.singlestore.all.strip_foreign_keys",
        "transformer_id": "singlestore_strip_foreign_keys",
    },
    {
        "rule_id": "ddl_optimize.singlestore.all.reference_table_for_dimensions",
        "transformer_id": "singlestore_reference_table",
    },
    {
        "rule_id": "ddl_optimize.singlestore.all.inject_shard_key",
        "transformer_id": "singlestore_inject_shard_key",
    },
    {
        "rule_id": "ddl_optimize.singlestore.all.inject_sort_key",
        "transformer_id": "singlestore_inject_sort_key",
    },
]


@pytest.fixture(scope="module")
def singlestore_decisions():
    importlib.import_module("benchbox.sql_compat.rules.ddl_optimize.singlestore_ddl_rewrites")

    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform="singlestore",
        platform_version=None,
        benchmark="",
        query_id=None,
        phase=Phase.DDL_OPTIMIZE,
        mode="sql",
        dialect=None,
    )
    return REGISTRY.resolve_all(ctx)


class TestSingleStoreRuleStructure:
    """Each registered rule has the correct structure."""

    def test_exactly_four_rules_registered(self, singlestore_decisions):
        assert len(singlestore_decisions) == 4

    def test_rules_registered_in_correct_order(self, singlestore_decisions):
        actual_ids = [d.rule_id for d in singlestore_decisions]
        expected_ids = [r["rule_id"] for r in _EXPECTED_RULES]
        assert actual_ids == expected_ids

    @pytest.mark.parametrize("expected", _EXPECTED_RULES, ids=[r["rule_id"] for r in _EXPECTED_RULES])
    def test_rule_payload_is_rewrite_ddl(self, expected, singlestore_decisions):
        from benchbox.sql_compat.decision import RewriteDDLPayload

        decision = next(d for d in singlestore_decisions if d.rule_id == expected["rule_id"])
        assert isinstance(decision.payload, RewriteDDLPayload)

    @pytest.mark.parametrize("expected", _EXPECTED_RULES, ids=[r["rule_id"] for r in _EXPECTED_RULES])
    def test_transformer_id_matches_expected(self, expected, singlestore_decisions):
        decision = next(d for d in singlestore_decisions if d.rule_id == expected["rule_id"])
        assert decision.payload.transformer_id == expected["transformer_id"]

    @pytest.mark.parametrize("expected", _EXPECTED_RULES, ids=[r["rule_id"] for r in _EXPECTED_RULES])
    def test_transformer_id_is_callable_on_adapter(self, expected):
        # _mock_singlestoredb (autouse, top of file) installs a stand-in for the
        # singlestoredb SDK so SingleStoreAdapter() does not raise ImportError when
        # the optional driver is not installed in the current environment.
        from benchbox.platforms.singlestore import SingleStoreAdapter

        adapter = SingleStoreAdapter()
        method = getattr(adapter, expected["transformer_id"], None)
        assert callable(method), f"SingleStoreAdapter has no method {expected['transformer_id']!r}"

    @pytest.mark.parametrize("expected", _EXPECTED_RULES, ids=[r["rule_id"] for r in _EXPECTED_RULES])
    def test_rule_has_non_empty_description(self, expected, singlestore_decisions):
        decision = next(d for d in singlestore_decisions if d.rule_id == expected["rule_id"])
        assert decision.payload.description

    @pytest.mark.parametrize("expected", _EXPECTED_RULES, ids=[r["rule_id"] for r in _EXPECTED_RULES])
    def test_rule_has_non_empty_reason(self, expected, singlestore_decisions):
        decision = next(d for d in singlestore_decisions if d.rule_id == expected["rule_id"])
        assert decision.reason

    def test_rule_id_format_matches_convention(self, singlestore_decisions):
        """All rule_ids follow ddl_optimize.<platform>.<scope>.<name> convention."""
        for decision in singlestore_decisions:
            parts = decision.rule_id.split(".")
            assert len(parts) == 4, f"rule_id {decision.rule_id!r} should have 4 dot-separated parts"
            assert parts[0] == "ddl_optimize"
            assert parts[1] == "singlestore"


class TestSingleStoreResolveConflictGuard:
    """SingleStore intentionally registers multiple rules at the same key.

    REGISTRY.resolve() must raise CompatibilityRegistryConflict for this
    platform so callers know to use resolve_all() instead.  This test
    documents and enforces that contract.
    """

    def test_resolve_raises_conflict_for_singlestore(self, singlestore_decisions):
        from benchbox.sql_compat.context import CompatibilityContext, Phase
        from benchbox.sql_compat.registry import REGISTRY, CompatibilityRegistryConflict

        ctx = CompatibilityContext(
            platform="singlestore",
            platform_version=None,
            benchmark="",
            query_id=None,
            phase=Phase.DDL_OPTIMIZE,
            mode="sql",
            dialect=None,
        )
        with pytest.raises(CompatibilityRegistryConflict):
            REGISTRY.resolve(ctx)
