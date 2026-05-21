<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Result Integrity Validation

```{tags} contributor, validation, architecture
```

BenchBox includes a three-tier integrity validator for benchmark result JSON files. The validator checks structural correctness, completeness against benchmark specifications, and statistical believability of reported metrics.

## Overview

| Property | Value |
|----------|-------|
| Module | `benchbox.core.results.integrity_validator` |
| Specs | `benchbox.core.results.benchmark_specs` |
| CLI script | `_project/scripts/validate_results.py` |
| MCP tool | `validate_results` (in `benchbox.mcp.tools.analytics`) |
| Tests | `tests/unit/core/results/test_integrity_validator.py` |

### Design Principles

- **Never raises exceptions on validation failure** - always returns a structured `IntegrityReport`
- **Composes `SchemaV2Validator`** as the first structural gate - does not reimplement schema validation
- **Specs are hardcoded** from DuckDB SF1 reference runs, not dynamically imported from benchmark modules (avoids transitive import issues)
- **Two severity levels**: FAIL (mathematical impossibility / corruption) and WARN (suspicious but plausible)
- **Skipped checks emit PASS** with a "skipped" message so check counts remain consistent across benchmarks
- **Unchecked validation is not a pass**: `summary.validation` values of `not_run`, `not_validated`, `unknown`, or `uncertain` are non-clean publication/ranking states even when all queries succeeded

## Validation Status Semantics

`summary.validation` is a public correctness signal, not a generic run-success
flag. Query success and validation success are separate claims:

| Status | Meaning | Clean publication/ranking status |
|---|---|---|
| `passed` | Validation ran and did not find failures. | Yes |
| `warnings` | Validation ran but emitted warnings. | Consumer-specific; do not treat as stronger than the recorded warnings. |
| `failed`, `partial`, `interrupted`, `error` | Validation or execution found a non-clean condition. | No |
| `not_run`, `not_validated`, `unknown` | No validation evidence was recorded. | No |
| `uncertain` | A run completed, but translation fallback or equivalent uncertainty prevents a clean correctness claim. | No |

Lifecycle finalization converts default `PASSED` placeholders to `NOT_RUN` when
no validation records or validation details exist. SQL translation fallback is
recorded under `execution.translation`; if fallback occurred and the result
otherwise looked clean, the lifecycle marks `summary.validation` as `uncertain`.
Strict translation mode is available through benchmark or platform options
(`strict_translation=true`, `translation_strict=true`, or
`sql_translation_strict=true`) for CI, publishing, and compatibility gates that
should fail closed.

## Three-Tier Validation Model

### Tier 1: Structural (8 checks)

Validates that the result JSON is well-formed and internally consistent.

| Check | Severity | Description |
|-------|----------|-------------|
| `schema_v2` | FAIL | Delegates to `SchemaV2Validator` for schema compliance |
| `required_keys` | FAIL | Top-level keys present (`benchmark`, `platform`, `summary`, etc.) |
| `query_count_math` | FAIL | `passed + failed = total` in summary |
| `timing_non_negative` | FAIL | All timing fields >= 0 |
| `percentile_ordering` | FAIL | p90 <= p95 <= p99 |
| `phase_status_values` | WARN | Phase statuses are recognized values |
| `query_entry_fields` | FAIL | Each query has required fields (id, ms, status) |
| `query_ms_non_negative` | FAIL | Per-query millisecond values >= 0 |

### Tier 2: Completeness (5 checks)

Validates that the result contains expected content for its benchmark type.

| Check | Severity | Description |
|-------|----------|-------------|
| `expected_query_ids` | FAIL | Query IDs match benchmark spec (e.g., 22 for TPC-H) |
| `measurement_queries_present` | FAIL | At least one measurement query (run_type='measurement' or iter > 0) |
| `power_phase_completed` | WARN | Power test phase ran successfully |
| `tables_object` | WARN | Tables object present when spec requires it |
| `tpc_metrics` | WARN | TPC performance metrics present for TPC-H/DS/Havoc/Skew |

### Tier 3: Believability (7 checks)

Validates that reported metrics are statistically plausible.

| Check | Severity | Description |
|-------|----------|-------------|
| `avg_in_range` | WARN | Average timing is between min and max |
| `geomean_in_range` | WARN | Geometric mean is between min and max |
| `success_rate` | WARN | Success rate meets benchmark spec floor (e.g., 100% for TPC-H) |
| `sf1_row_counts` | WARN | Row counts within +/-1% of spec (SF1 only; warns on missing tables) |
| `timing_outliers` | WARN | No individual query exceeds 30 minutes |
| `no_duplicate_entries` | FAIL | No duplicate (id, iter, stream) tuples |
| `load_time_nonzero` | WARN | Data load time > 0 |

## BenchmarkSpec System

Each benchmark has a `BenchmarkSpec` frozen dataclass defining its expected characteristics:

```python
@dataclass(frozen=True)
class BenchmarkSpec:
    benchmark_id: str
    unique_query_ids: frozenset[str]
    min_unique_queries: int = 0
    min_success_rate: float = 1.0
    high_failure_expected: bool = False
    requires_tables_object: bool = True
    sf1_row_counts: dict[str, int] | None = None
    sf1_power_at_size_range: tuple[float, float] | None = None
```

### Key fields

- **`unique_query_ids`**: The complete set of expected query IDs for the benchmark
- **`min_success_rate`**: Floor for success rate checks (e.g., 1.0 for TPC-H, 0.95 for TPC-DS)
- **`high_failure_expected`**: When `True`, bypasses success rate floor (used by `transaction_primitives`)
- **`requires_tables_object`**: When `False`, skips the tables object check (used by `metadata_primitives`)
- **`sf1_row_counts`**: Expected table row counts at scale factor 1, used for believability checks

### Coverage

Specs exist for 20 of 22 registered benchmarks: `tpch`, `tpcds`, `tpchavoc`, `tpch_skew`, `ssb`, `clickbench`, `nyctaxi`, `h2odb`, `amplab`, `joinorder`, `flightdata`, `datavault`, `coffeeshop`, `tpcdi`, `tsbs_devops`, `tpcds_obt`, `read_primitives`, `write_primitives`, `metadata_primitives`, `transaction_primitives`. `ai_primitives` and `vector_search` do not yet have integrity specs.

8 legacy aliases are mapped automatically (e.g., `star_schema` -> `ssb`, `amplab_big_data` -> `amplab`).

### Adding a spec for a new benchmark

1. Run the benchmark at SF1 on DuckDB to produce a reference result file
2. Add a new entry to the `BENCHMARK_SPECS` dict in `benchmark_specs.py`:

```python
BENCHMARK_SPECS["my_benchmark"] = BenchmarkSpec(
    benchmark_id="my_benchmark",
    unique_query_ids=frozenset(["q1", "q2", "q3"]),
    min_success_rate=1.0,
    requires_tables_object=True,
    sf1_row_counts={
        "table_a": 100_000,
        "table_b": 50_000,
    },
)
```

3. If the benchmark has legacy aliases, add them to `LEGACY_ALIASES`
4. Run the test suite: `uv run -- python -m pytest tests/unit/core/results/test_integrity_validator.py`

## IntegrityReport

The validator returns an `IntegrityReport` dataclass:

```python
@dataclass
class IntegrityReport:
    file: str                           # File path validated
    benchmark_id: str                   # Benchmark identifier
    platform: str                       # Platform name
    scale_factor: float                 # Scale factor
    overall_status: CheckStatus         # Worst status across all checks
    checks: list[CheckResult]           # Individual check results
    summary: dict[str, int]             # Counts by status (PASS, WARN, FAIL)
```

**Helper methods:**
- `report.passed()` - Returns `True` if overall status is PASS
- `report.has_warnings()` - Returns `True` if any check has WARN status

Each `CheckResult` contains:

```python
@dataclass
class CheckResult:
    category: CheckCategory   # STRUCTURAL, COMPLETENESS, or BELIEVABILITY
    name: str                 # Check identifier (e.g., "query_count_math")
    status: CheckStatus       # PASS, WARN, or FAIL
    message: str              # Human-readable description
    details: dict | None      # Optional structured details
```

## Convenience Functions

The module provides two convenience functions for common use cases:

```python
from benchbox.core.results.integrity_validator import validate_file, validate_directory

# Single file
report = validate_file(Path("results/tpch_duckdb_sf1.json"))

# Directory (returns list of reports)
reports = validate_directory(Path("results/"), pattern="*.json")
```

Both functions handle invalid JSON gracefully - returning a FAIL report rather than raising exceptions.

## Access Points

| Interface | Usage |
|-----------|-------|
| **CLI script** | `uv run _project/scripts/validate_results.py <path> [options]` |
| **MCP tool** | `validate_results(result_file="...", verbose=True)` |
| **Python API** | `from benchbox.core.results.integrity_validator import validate_file` |

See the [CLI reference](../reference/cli/utilities.md#cli-validate-results) and [MCP reference](../reference/mcp.md) for usage details.

## Special Cases

- **`metadata_primitives`**: Has `requires_tables_object=False` and is excluded from load-time checks (no data loading phase)
- **`transaction_primitives`**: Has `high_failure_expected=True` - bypasses the success rate floor since failures are an expected part of transaction testing
- **Non-SF1 results**: Row count checks are skipped (emitted as PASS with "skipped" message)
- **Non-TPC benchmarks**: TPC metric checks are skipped similarly
