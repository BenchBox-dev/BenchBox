# ADR: Preserve read-primitives capabilities across cloud dialects

- Status: Accepted
- Date: 2026-09-24
- Constrains: `benchbox/core/read_primitives/catalog/queries.yaml`.

## Context

Read Primitives includes arrays, JSON, maps, structs, statistics, and
window frames. Several engines reject the catalog's generic SQL. A syntax
substitution can execute while changing the operation being measured or the
result type.

## Decision

Platform variants retain the base query's result columns and measured
capability. BigQuery uses exact window `PERCENTILE_CONT`, numeric date keys
for a date `RANGE` frame, and regression formulas with the same degenerate
case behavior as `REGR_R2`. Snowflake uses its array, JSON, and object access
functions where they preserve the result.

Skip a query when the available replacement changes its measured capability.
In particular, Snowflake `OBJECT_AGG` does not return the native map required
by the map result contracts. A flattened join cannot replace the correlated
scalar-subquery optimizer test. TPC-H comment fields are plain text, so the
simple JSON extraction test does not have valid input on these engines.

Catalog variants are final SQL for their target dialect. Static projection
contracts and offline tests guard their shape; live engine compilation and
result comparison remain necessary before treating a new engine as certified.

## Consequences

The catalog exposes fewer operations on engines that lack a comparable
native feature. A skipped operation does not appear as a successful timing.

## References

- [BigQuery window frames](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/window-function-calls)
- [BigQuery exact percentiles](https://docs.cloud.google.com/bigquery/docs/reference/standard-sql/navigation_functions)
- [Snowflake regression R-squared semantics](https://docs.snowflake.com/en/sql-reference/functions/regr_r2)
- [Snowflake OBJECT_AGG](https://docs.snowflake.com/en/sql-reference/functions/object_agg)
