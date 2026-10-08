# Implementation decisions behind the public contracts

Maintainer notes split out of `docs/reference/public-contracts.md`: where
behaviour lives in the code and how the SQL compatibility catalog is governed.

## SQL Compatibility Governance Decision

`sql_compat` is a hybrid
governance catalog plus optional runtime dispatcher. `BaseDdlOptimizer` is the
preferred dispatch path for ordered statement-to-statement DDL transforms, but
adapters may keep local CREATE TABLE rewrite paths when the rewrite depends on
adapter state, SDK-specific create/load loops, or platform deployment settings.

`governance_only=True` rules are allowed to represent real runtime behavior.
They are not dispatch targets; they are the auditable source of intent that the
drift checker requires before CI can call DDL governance clean. `compat_lint CLEAN`
means the source scanner found no unregistered or uninspectable adapter
CREATE TABLE rewrite behavior. It does not mean every DDL rewrite flows through
`BaseDdlOptimizer`.

## DataFrame Runner Lifecycle Decision

Production DataFrame execution is `run_benchmark_lifecycle()` ->
`adapter.run_benchmark()` -> `BenchmarkExecutionMixin.run_benchmark()`.
The helpers `dataframe_compliance_class` and `no_dataframe_queries_message`
live in `benchbox/platforms/dataframe/benchmark_mixin.py`, and the DataFrame
mode predicate lives in `benchbox.core.run_service` beside run-plan
resolution. New lifecycle behavior belongs in
`benchbox/platforms/dataframe/benchmark_mixin.py`.
