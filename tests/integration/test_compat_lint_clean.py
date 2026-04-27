"""Integration smoke test: DDL drift check must report zero unregistered transforms.

Verifies that every platform adapter that performs DDL optimization
(via _optimize_table_definition or _transform_create_statement) has a
registered Phase.DDL_OPTIMIZE rule in the compatibility registry.

Uses check_ddl_drift() directly rather than the CLI so the test is
isolated from unrelated inventory validation failures.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]

_BENCHBOX_ROOT = Path(__file__).parent.parent.parent / "benchbox"


def test_ddl_drift_check_is_clean():
    """check_ddl_drift() must return zero findings for the current codebase."""
    from benchbox.sql_compat.inventory import check_ddl_drift

    drift = check_ddl_drift(_BENCHBOX_ROOT)

    if drift:
        lines = [
            f"  {d.file}:{d.line}  {d.func_name}()  [inferred platform key: {d.inferred_platform_key!r}]" for d in drift
        ]
        pytest.fail(
            f"{len(drift)} unregistered DDL-optimize transform(s) found:\n"
            + "\n".join(lines)
            + "\n\nRegister each in benchbox/sql_compat/rules/ddl_optimize/"
            "{platform}_ddl_rewrites.py — see benchbox/sql_compat/README.md."
        )


def test_singlestore_ddl_rules_resolve_via_base_optimizer():
    """SingleStore (the BaseDdlOptimizer canary) resolves all 4 DDL_OPTIMIZE rules."""
    import importlib
    import pkgutil

    import benchbox.sql_compat.rules.ddl_optimize as _ddl_pkg

    for _, mod_name, _ispkg in pkgutil.walk_packages(_ddl_pkg.__path__, _ddl_pkg.__name__ + "."):
        if not _ispkg:
            importlib.import_module(mod_name)

    from benchbox.sql_compat.context import CompatibilityContext, Phase
    from benchbox.sql_compat.decision import RewriteDDLPayload
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
    decisions = REGISTRY.resolve_all(ctx)

    assert len(decisions) == 4, f"Expected 4 SingleStore DDL rules, got {len(decisions)}"

    transformer_ids = [d.payload.transformer_id for d in decisions if isinstance(d.payload, RewriteDDLPayload)]
    assert transformer_ids == [
        "singlestore_strip_foreign_keys",
        "singlestore_reference_table",
        "singlestore_inject_shard_key",
        "singlestore_inject_sort_key",
    ], f"Unexpected transformer_id order: {transformer_ids}"

    for decision in decisions:
        assert isinstance(decision.payload, RewriteDDLPayload)
        assert decision.payload.transformer_id, "transformer_id must not be empty"
        assert decision.payload.description, "description must not be empty"


def test_base_ddl_optimizer_dispatches_correctly():
    """BaseDdlOptimizer dispatches SingleStore transforms and produces correct DDL."""
    from benchbox.platforms.singlestore import SingleStoreAdapter

    with patch("benchbox.platforms.singlestore._s2", MagicMock()):
        adapter = SingleStoreAdapter()

    lineitem_stmt = "CREATE TABLE `lineitem` (\n  l_orderkey BIGINT,\n  l_linenumber INT\n)"
    result = adapter._transform_create_statement(lineitem_stmt)
    assert "SHARD KEY (l_orderkey)" in result
    assert "SORT KEY (l_orderkey, l_linenumber)" in result
    assert "FOREIGN KEY" not in result

    nation_stmt = "CREATE TABLE nation (\n  n_nationkey INT\n)"
    result = adapter._transform_create_statement(nation_stmt)
    assert "CREATE REFERENCE TABLE" in result
    assert "SHARD KEY" not in result
    assert "SORT KEY" not in result


def test_every_rule_file_loads_via_base_optimizer():
    """For every {platform_key}_ddl_rewrites.py, _ensure_platform_rules_loaded must register rules.

    Locks the file-naming contract: BaseDdlOptimizer constructs the module name as
    f"benchbox.sql_compat.rules.ddl_optimize.{platform_key}_ddl_rewrites", so file stems
    that diverge from the registered platform_key would silently fail at runtime.
    """
    from benchbox.platforms.base.ddl_optimizer import _clear_load_cache, _ensure_platform_rules_loaded
    from benchbox.sql_compat.context import Phase
    from benchbox.sql_compat.registry import REGISTRY

    rules_dir = _BENCHBOX_ROOT / "sql_compat" / "rules" / "ddl_optimize"
    rule_files = sorted(p.stem for p in rules_dir.glob("*_ddl_rewrites.py"))
    assert rule_files, "No DDL rewrite rule files found"

    _clear_load_cache()
    for stem in rule_files:
        platform_key = stem.removesuffix("_ddl_rewrites")
        _ensure_platform_rules_loaded(platform_key)
        registered = {platform for (phase, platform, _, _), _ in REGISTRY.all_rules() if phase == Phase.DDL_OPTIMIZE}
        assert platform_key in registered, (
            f"Rule file {stem}.py loaded but registered no DDL_OPTIMIZE rule for "
            f"platform_key={platform_key!r}. File-stem and registered platform_key must match."
        )


# Adapter classes whose runtime DDL transforms are dispatched via BaseDdlOptimizer.
# Adapters not in this set must mark their rule(s) governance_only=True (the rewrite
# happens via a different code path; the rule exists only for compat_lint governance).
_DISPATCHED_ADAPTERS: dict[str, str] = {
    "singlestore": "benchbox.platforms.singlestore.SingleStoreAdapter",
}


def test_runtime_dispatch_or_governance_only():
    """Every DDL_OPTIMIZE rule must be governance_only=True OR name a callable adapter method.

    This is the structural analogue of the SingleStore-specific
    test_transformer_id_is_callable_on_adapter check, applied to every registered rule.
    Catches the failure mode where a platform migrates to BaseDdlOptimizer but its
    transformer_id points at a method that does not exist on the adapter class.
    """
    import importlib
    import pkgutil

    import benchbox.sql_compat.rules.ddl_optimize as _ddl_pkg

    for _, mod_name, _ispkg in pkgutil.walk_packages(_ddl_pkg.__path__, _ddl_pkg.__name__ + "."):
        if not _ispkg:
            importlib.import_module(mod_name)

    from benchbox.sql_compat.context import Phase
    from benchbox.sql_compat.decision import RewriteDDLPayload
    from benchbox.sql_compat.registry import REGISTRY

    failures: list[str] = []
    for (phase, platform, _, _), entry in REGISTRY.all_rules():
        if phase != Phase.DDL_OPTIMIZE:
            continue
        payload = entry.decision.payload
        if not isinstance(payload, RewriteDDLPayload):
            continue
        if payload.governance_only:
            continue
        adapter_path = _DISPATCHED_ADAPTERS.get(platform)
        if adapter_path is None:
            failures.append(
                f"{entry.rule_id}: platform={platform!r} has no entry in _DISPATCHED_ADAPTERS "
                f"and governance_only=False — either mark the rule governance_only=True or "
                f"register the adapter class here."
            )
            continue
        module_name, class_name = adapter_path.rsplit(".", 1)
        adapter_cls = getattr(importlib.import_module(module_name), class_name)
        if not callable(getattr(adapter_cls, payload.transformer_id, None)):
            failures.append(
                f"{entry.rule_id}: transformer_id={payload.transformer_id!r} is not a callable on {adapter_path}."
            )
    if failures:
        pytest.fail("Dispatch/governance contract violations:\n" + "\n".join(f"  {f}" for f in failures))
