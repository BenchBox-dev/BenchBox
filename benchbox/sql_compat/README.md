# sql_compat — Phase-Aware SQL Compatibility Registry

## Overview

`sql_compat` is the governance layer for every SQL-text or DDL transformation
BenchBox performs on behalf of a specific platform.  Instead of silently
rewriting queries and DDL in adapter code, each intentional transformation is
**registered** in the registry with a `rule_id`, an action type, and a reason.
`compat_lint` walks the rule files at CI time and fails if any transformation
is found in adapter code that has no matching registry entry.

## Design: "register intent, implement locally"

The registry **documents** what an adapter does; `BaseDdlOptimizer` uses
`transformer_id` as an adapter method name to dispatch calls.  Adapter methods
remain in `benchbox/platforms/<platform>.py` because transformations are
platform-specific (SHARD KEY syntax, DUPLICATE KEY injection, schema prefixes,
etc.) and are tested alongside the adapter.  The registry makes those decisions
discoverable, auditable, and enforceable without moving code.

```
Registry rule     →  declares transformer_id "myplatform_strip_fk"
Adapter method    →  implements def myplatform_strip_fk(self, stmt): ...
BaseDdlOptimizer  →  dispatches each rule to getattr(self, transformer_id)(stmt)
compat_lint       →  verifies every regex/DDL-text branch in adapter code
                     maps to a registered rule_id
```

> **Note:** Pre-W6 rule files in `rules/ddl_optimize/` contain the comment
> "transformer_id is documentary only — no runtime dispatch."  That was true
> before `BaseDdlOptimizer` existed.  When an adapter inherits
> `BaseDdlOptimizer`, `transformer_id` *is* used for runtime dispatch.  The
> comment in legacy rule files refers to the old direct-call pattern and can
> be ignored for adapters that use the mixin.

## Phase.DDL_OPTIMIZE — adding a new platform

1. **Register** a `CompatibilityDecision` in
   `benchbox/sql_compat/rules/ddl_optimize/<platform>_ddl_rewrites.py`:

   ```python
   from benchbox.sql_compat.registry import REGISTRY
   from benchbox.sql_compat.context import Phase
   from benchbox.sql_compat.decision import (
       CompatibilityDecision, CompatAction, SupportLevel, FailureMode,
       RewriteDDLPayload,
   )

   REGISTRY.register(
       CompatibilityDecision(
           rule_id="ddl_optimize.myplatform.all.strip_foreign_keys",
           action=CompatAction.REWRITE_DDL,
           support_level=SupportLevel.REWRITTEN,
           failure_mode=FailureMode.SYNTAX_ERROR,
           payload=RewriteDDLPayload(
               transformer_id="myplatform_strip_foreign_keys",
               description="Remove FK clauses unsupported by MyPlatform.",
           ),
           reason="MyPlatform raises error XYZ on FOREIGN KEY clauses.",
       ),
       Phase.DDL_OPTIMIZE,
       "myplatform",
   )
   ```

2. **Implement** the method in your adapter (inherit `BaseDdlOptimizer`):

   ```python
   from typing import ClassVar
   from benchbox.platforms.base.ddl_helpers import strip_foreign_keys
   from benchbox.platforms.base.ddl_optimizer import BaseDdlOptimizer

   class MyPlatformAdapter(BaseDdlOptimizer, PlatformAdapter):
       _platform_key: ClassVar[str] = "myplatform"

       def myplatform_strip_foreign_keys(self, stmt: str) -> str:
           return strip_foreign_keys(stmt)

       # optimize_table_definition() is inherited; transformers are dispatched
       # automatically in registration order — no manual wiring needed.
   ```

3. **Confirm** `compat_lint` runs clean:

   ```bash
   uv run -- python -m benchbox.sql_compat.inventory --platform myplatform
   ```

## BaseDdlOptimizer — automatic dispatch

`BaseDdlOptimizer` (in `benchbox/platforms/base/ddl_optimizer.py`) is a mixin
that adapters can inherit to get automatic dispatch.  On the first call to
`optimize_table_definition(stmt, table_name)` it:

1. Lazily imports `benchbox.sql_compat.rules.ddl_optimize.<platform_key>_ddl_rewrites`
   to ensure rules are registered (the registry is idempotent on re-import).
2. Calls `REGISTRY.resolve_all(ctx)` to get all registered rules in
   registration order.
3. For each rule's `RewriteDDLPayload.transformer_id`, calls
   `getattr(self, transformer_id)(stmt)` and passes the result to the
   next transformer.

**Registration order is application order.**  If one transform depends on
another (e.g., `SHARD KEY` skip-guard needs `REFERENCE TABLE` to already be
in the stmt), register the prerequisite rule first.

## Canonical example: SingleStore

SingleStore has four DDL_OPTIMIZE rules applied in this order:

| # | rule_id suffix                    | transformer_id                    | What it does |
|---|-----------------------------------|-----------------------------------|--------------|
| 1 | `strip_foreign_keys`              | `singlestore_strip_foreign_keys`  | Removes FK clauses (error 2752) |
| 2 | `reference_table_for_dimensions`  | `singlestore_reference_table`     | `CREATE TABLE` → `CREATE REFERENCE TABLE` for nation/region |
| 3 | `inject_shard_key`                | `singlestore_inject_shard_key`    | Injects `SHARD KEY` (skips `REFERENCE TABLE`) |
| 4 | `inject_sort_key`                 | `singlestore_inject_sort_key`     | Injects `SORT KEY` (skips `REFERENCE TABLE`) |

Rule file: `benchbox/sql_compat/rules/ddl_optimize/singlestore_ddl_rewrites.py`
Adapter:   `benchbox/platforms/singlestore.py` — `SingleStoreAdapter` inherits `BaseDdlOptimizer`

## Multi-rule platforms and resolve() vs resolve_all()

Platforms with **multiple** rules at the same `(phase, platform)` key (like
SingleStore) will cause `REGISTRY.resolve()` to raise
`CompatibilityRegistryConflict`.  Use `REGISTRY.resolve_all(ctx)` for
governance queries on these platforms.

`BaseDdlOptimizer` uses `resolve_all()` internally and is safe for any number
of rules.

## compat_lint enforcement

`benchbox/sql_compat/inventory.py` walks platform source files and flags every
dialect branch or DDL regex that lacks a matching registry rule.  Add the
`--check-ddl-drift` flag to fail CI on any unregistered transform.
