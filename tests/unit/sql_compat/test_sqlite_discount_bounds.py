import importlib

import pytest

from benchbox.sql_compat import (
    REGISTRY,
    CompatAction,
    CompatibilityContext,
    FailureMode,
    Phase,
    RewriteQueryPayload,
    SupportLevel,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.mark.parametrize(
    "platform, benchmark_name, query_id",
    [("sqlite", "tpch", "6"), ("duckdb", "tpch", "6"), ("sqlite", "tpch", "5"), ("sqlite", "ssb", "6")],
)
def test_exact_discount_rule_scope_and_transformer(platform, benchmark_name, query_id):
    importlib.import_module("benchbox.sql_compat.rules.query_compile.sqlite_tpch_discount_bounds")
    context = CompatibilityContext(
        platform=platform,
        platform_version=None,
        benchmark=benchmark_name,
        query_id=query_id,
        phase=Phase.QUERY_COMPILE,
        mode="sql",
        dialect=platform,
    )
    decision = REGISTRY.resolve(context)
    if (platform, benchmark_name, query_id) != ("sqlite", "tpch", "6"):
        assert decision is None
        return
    assert decision.rule_id == "query_compile.sqlite.tpch.q6_exact_discount_bounds"
    assert decision.action == CompatAction.REWRITE_QUERY
    assert decision.support_level == SupportLevel.REWRITTEN
    assert decision.failure_mode == FailureMode.SILENT_CORRUPTION
    assert isinstance(decision.payload, RewriteQueryPayload)
    module_name, name = decision.payload.transformer_id.rsplit(".", 1)
    transformer = getattr(importlib.import_module(module_name), name)
    query = "SELECT * FROM lineitem WHERE l_discount BETWEEN 0.06 - 0.01 AND 0.06 + 0.01"
    assert transformer(query) == "SELECT * FROM lineitem WHERE l_discount BETWEEN 0.05 AND 0.07"
