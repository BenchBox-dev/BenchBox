"""Unit tests for the DuckLake DDL_OPTIMIZE registry rule.

Verifies the registered ``strip_primary_keys`` rule has the correct rule_id,
action type, payload type, and that its transformer_id names a callable
method on DuckLakeAdapter through which _rewrite_schema_statement routes.
These are governance/structure tests; behavioral tests live in
tests/unit/platforms/test_ducklake_adapter.py.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(scope="module")
def ducklake_decisions():
    importlib.import_module("benchbox.sql_compat.rules.ddl_optimize.ducklake_ddl_rewrites")

    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.registry import REGISTRY

    ctx = CompatibilityContext(
        platform="ducklake",
        platform_version=None,
        benchmark="",
        query_id=None,
        phase=Phase.DDL_OPTIMIZE,
        mode="sql",
        dialect=None,
    )
    return REGISTRY.resolve_all(ctx)


class TestDuckLakeRuleStructure:
    """The single registered rule has the correct structure."""

    def test_exactly_one_rule_registered(self, ducklake_decisions):
        assert [d.rule_id for d in ducklake_decisions] == ["ddl_optimize.ducklake.all.strip_primary_keys"]

    def test_rule_payload_is_rewrite_ddl(self, ducklake_decisions):
        from benchbox.sql_compat.decision import RewriteDDLPayload

        (decision,) = ducklake_decisions
        assert isinstance(decision.payload, RewriteDDLPayload)

    def test_transformer_id_names_adapter_method(self, tmp_path: Path, ducklake_decisions):
        from benchbox.platforms.ducklake import DuckLakeAdapter

        (decision,) = ducklake_decisions
        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        assert decision.payload.transformer_id == "ducklake_strip_primary_keys"
        assert callable(getattr(adapter, decision.payload.transformer_id, None))

    def test_rewrite_routes_through_registered_transformer(self, tmp_path: Path):
        from benchbox.platforms.ducklake import DuckLakeAdapter

        adapter = DuckLakeAdapter(
            metadata_path=str(tmp_path / "catalog.ducklake"),
            data_path=str(tmp_path / "data"),
        )
        statement = "CREATE TABLE t (\n  id INTEGER PRIMARY KEY\n);"
        assert "PRIMARY KEY" not in adapter.ducklake_strip_primary_keys(statement)
        assert adapter._rewrite_schema_statement(statement) == adapter.ducklake_strip_primary_keys(statement)
