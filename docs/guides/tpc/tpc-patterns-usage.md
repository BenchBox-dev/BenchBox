<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC Patterns Usage Guide

```{tags} intermediate, guide, tpc-h, tpc-ds, data-generation
```

`benchbox.core.tpc_patterns` used to ship a generic concurrent-stream execution
framework (`StreamExecutor`, `QueryPermutator`, `ParameterManager`,
`TransactionManager`, `ErrorHandler`, `ProgressTracker`, `ResultAggregator`,
`BenchmarkTestRunner`, and related dataclasses/utilities). It was never wired
into the TPC-H or TPC-DS execution paths -- the only external consumers of the
module imported `generate_official_benchmark_audit_trail`, and the framework
duplicated (without ever running) the same stream-execution concept that
`benchbox.core.throughput.runner.StreamRunner` implements for real. The
framework has been removed; `tpc_patterns` now contains only
`generate_official_benchmark_audit_trail`.

## What to use instead

- **Power Test**: `TPCHBenchmark.run_power_test(...)` /
  `TPCDSBenchmark.run_power_test(...)` execute all queries sequentially
  against a real connection and compute Power@Size.
- **Throughput Test**: `benchbox.core.tpch.throughput_test.TPCHThroughputTest`
  and `benchbox.core.tpcds.throughput_test.TPCDSThroughputTest` execute
  multiple concurrent query streams for real, via the shared
  `benchbox.core.throughput.runner.StreamRunner` executor, and compute
  Throughput@Size.
- **Official benchmark audit trail**: `generate_official_benchmark_audit_trail`
  in `benchbox.core.tpc_patterns` is unchanged and still used by
  `benchbox.core.tpch.official_benchmark` and
  `benchbox.core.tpcds.official_benchmark` to write the shared audit-trail
  report format.

```python
from benchbox.core.tpc_patterns import generate_official_benchmark_audit_trail

generate_official_benchmark_audit_trail(
    result=official_result,
    benchmark_title="TPC-H",
    benchmark_slug="tpch",
    qph_label="QphH@Size",
    qph_attr="qphh_at_size",
)
```
