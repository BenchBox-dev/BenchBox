# TPC-Havoc DataFrame Variants

TPC-Havoc DataFrame support exposes a flat `QueryRegistry` with 220 entries:
`Q1v1` through `Q22v10`. The runner already knows how to execute a registry of
`DataFrameQuery` objects, so TPC-Havoc uses the same dispatch path as FlightData
and JoinOrder rather than adding a benchmark-specific runner branch.

## Design Decision

Use a flat registry in `benchbox.core.tpchavoc.dataframe_queries.registry`.
Every per-query module exports `Q{n}_VARIANTS`, and `registry.py` imports those
modules into a single `TPCHAVOC_DATAFRAME_QUERIES` registry.

| Option | Fit | Decision |
| --- | --- | --- |
| Flat `QueryRegistry` with IDs like `Q1v7` | Matches existing runner and dry-run extraction contracts | Chosen |
| Nested variant registry around `QueryRegistry` | More explicit variant grouping, but requires runner and CLI changes | Rejected |
| Hard-coded dispatch in `dataframe_runner.py` | Useful only for TPC-H/TPC-DS stream permutation | Rejected |
| Reuse TPC-H baseline implementation for `v1` | Preserves parameter behavior and avoids modifying TPC-H | Chosen |

## Implementation Pattern

Queries Q1-Q15 have hand-written variant modules. They vary DataFrame call
sequences around filter timing, column pruning, intermediate DataFrames, join
order, and aggregation formulation while preserving the canonical TPC-H output.

Queries Q16-Q22 are complex correlated-subquery and anti-join workloads. Their
initial variants delegate the core canonical TPC-H implementation, then replay
final result projection and ordering steps in different sequences. This keeps
the registration and execution surface complete while preserving equivalence for
the highest-risk query shapes.

The benchmark class exposes `get_dataframe_queries()` as a lazy import and marks
`supports_dataframe_mode()` true. This follows the FlightData and JoinOrder
integration pattern and keeps SQL TPC-Havoc variant generation unchanged.

## Compatibility

- TPC-Havoc does not modify `benchbox.core.tpch.dataframe_queries`.
- TPC-H parameter defaults and overrides remain owned by the TPC-H module.
- SQL mode continues to use `TPCHavocQueryManager`, `VariantGenerator`, and
  `StaticSQLVariant`.
- DataFrame query IDs are string IDs (`Q{query}v{variant}`) and do not affect SQL
  variant IDs such as `1_v1`.

## Future Work

The Q16-Q22 result-replay variants should be replaced with deeper structural
variants after Q1-Q15 have established equivalence coverage across both
families. The next useful targets are Q19 union-of-conditions, Q20 semi-join
ordering, Q21 anti-join alternatives, and Q22 average-balance materialization.
