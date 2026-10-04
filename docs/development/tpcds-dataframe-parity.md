<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-DS DataFrame parity

```{tags} contributor, guide, tpcds, dataframe-platform
```

TPC-DS parity means that SQL and DataFrame implementations read the same generated tables, use the same substitution values, and return equivalent results. Registering 99 query implementations establishes execution support; it does not establish parity for every query, scale, draw, or DataFrame engine.

This guide complements [cross-platform result validation](result-validation.md) and the [DataFrame adapter guide](adding-dataframe-platform.md). It covers parameter binding, useful evidence, and contributor checks.

## Prerequisites

Use the bundled TPC-DS generator and templates, the optional dependencies for the engines being compared, and one shared generated data directory. Run through the production loaders so that each engine sees the data types used by a benchmark run.

Polars and DataFusion use the Expression implementation. Pandas uses the Pandas implementation. Passing an Expression query on Polars does not prove that DataFusion plans or executes it correctly. DataFusion needs its own native execution checks for operations such as aggregate expressions, decimal division, ranking, and ordered windows.

Record the source revision, generator binary hash, data scale, generation settings, query seed, dsqgen stream, backend and version, parameter values, query or variant ID, and comparison result. A result without this identity cannot be reproduced reliably.

## Two parameter bindings

### Seeded SQL and DataFrame comparison

Capture substitutions with `DSQGenBinary.generate_parameter_log` at the scale of the generated data and the chosen seed and stream. Pass those values to `ADAPTERS[query_number]`, then install the resulting DataFrame parameters with `parameter_overrides` while the implementation runs. Render SQL from the same logged values with `DSQGenBinary.generate_with_parameters`.

The adapter maps template names such as `YEAR.01` to implementation keys such as `year`. It also reproduces template arithmetic and lists. For example, Q39 uses the drawn month and its successor; binding only one month would change the query. Drawn column names, aggregate functions, output columns, and order positions matter as much as numeric filter values.

`default_parameters.yaml` contains representative parameters for direct implementation calls. Its values are not evidence that a SQL draw and a DataFrame call use the same parameters. Inspect the bound query or binding record when diagnosing a production run.

Production Power-stream binding uses `bind_power_stream_queries` to return query copies with scoped parameters. It uses the SQL Power test's parameter seed, `(seed or 1) + stream_id + 1000`, and captures dsqgen stream 0. The benchmark stream ID and dsqgen stream ID are distinct. Binding failures stop the run rather than silently using defaults; parameter overrides are active only while the bound implementation runs.

The data scale and parameter-rendering scale must agree. A small-data run with SF 1 substitution values answers a different query. dsqgen stream IDs also need care: `generate(..., stream_id=...)` does not select a nonzero dsqgen stream. Capture that stream with `generate_parameter_log` and render its exact values with `generate_with_parameters`.

Multipart templates Q14, Q23, Q24 and Q39 contain distinct statements. Exercise each selected variant under the same template binding. A missing variant implementation must be reported; running a base implementation under another variant ID cannot establish parity.

### Qualification values and official answers

Qualification uses the specification's substitution values, stored in `qualification_values.json`, rather than a random draw. Render SQL from those values and bind the DataFrame through the same adapters. The independent oracle is the official answer set for the qualification data and applicable NULL ordering.

A qualification-value or rendering test does not establish answer-value parity. Row counts alone are insufficient: a wrong aggregate can return the expected number of rows. Full qualification requires all intended answer files to parse, all intended value comparisons to execute, and parse failures or missing comparisons to fail the lane. This full oracle is a separate prerequisite; it must not be inferred from the seeded DuckDB comparison.

```bash
uv run -- python -m pytest tests/unit/core/tpcds/test_qualification_values.py -n 0 -q
```

This command checks the committed value inventory, sampled specification values, deterministic rendering, and available answer-row-count evidence. It does not run every DataFrame query against official answer values.

## Comparison commands and lane boundaries

The TPC-DS cross-surface gate is enforced. It builds SF 0.01 data on the default Power draw and compares all 103 statements on DuckDB with the Polars Expression, Pandas and native DataFusion implementations. CI runs it in two steps of the correctness-gate job:

```bash
make tpcds-cross-surface-equivalence-report
make tpcds-pandas-cross-surface-equivalence-report
```

Each of the two CI steps has a 45 s budget on hosted Ubuntu runners, including the data build and parameter binding (about 10 s). That figure was set from hosted runs, where the pandas step took 26-39 s and the Polars and DataFusion step 14-16 s.

The direct entry point is equivalent:

```bash
uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark tpcds
```

The CLI accepts `--seed`, `--power-stream`, repeated `--backend` options, and `--repeats`. The defaults compare all three backends at SF 0.01 with one repeat and Power stream 0. DataFusion uses the production loader:

```bash
uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark tpcds \
  --backend expression --backend pandas --backend datafusion \
  --seed 42 --power-stream 1 --repeats 3
```

All 99 base queries and the four `b` statements are required. Missing statements, adapters, implementations, or captured bindings fail before comparison. Both statements of each multipart query use the same captured dsqgen substitution log. The report records all canonical bindings, the requested seed and Power stream, effective RNG seed, native dsqgen stream, scale, binary digest, and all 103 SQL digests.

The Power draw uses an effective RNG seed of `(seed or 1) + power_stream + 1000` and native dsqgen stream 0. A repeat reruns comparison against the same generated files and captured draw; it does not draw new parameters. To test another draw, run another command with a different seed or Power stream. Seed and Power stream options are rejected for other benchmarks. The CLI does not expose a scale option; use a programmatic comparison for other scales and record its binding and data identity.

The gate fails on any unclassified divergence, on a vacuous statement without a classification, and on a classification whose statement now returns rows. The classifications describe the default draw only. A run with `--seed` or a nonzero `--power-stream` still fails on divergences and on cells whose outcome changes between repeats, but lists vacuous statements without failing on them. Explicit baseline maintenance retains its refusal rules and rejects combinations with explicit backend or draw overrides.

After each merge to `develop`, the trunk workflow runs every backend twice on three other draws:

```bash
make tpcds-cross-surface-draws-report
```

Native DataFusion wrapper regressions can be checked with:

```bash
uv run -- python -m pytest tests/unit/platforms/dataframe/test_unified_frame_datafusion_real.py -n 0 -q
```

Those regressions cover wrapper behavior; they do not certify the complete TPC-DS workload.

The pull-request gate, the post-merge draw job and the scheduled SF 1 qualification diagnostic are separate lanes. A passing local command does not show that the hosted lanes are installed or passing; check the workflow runs.

## Empty results and coverage

An empty SQL result matched by a DataFrame result is useful evidence about that particular cell. It provides little evidence about projection, aggregation, join multiplicity, ranking, or ordering after rows pass the filters. Report it as an empty match, separately from non-empty coverage.

A single all-NULL aggregate row is not a zero-row result. Report that case separately too; preserving the aggregate row and its NULL values is observable behavior.

Before classifying a query as legitimately empty at a gate scale:

1. Verify identical table data and parameter values, and zero rows from SQL and every backend being claimed.
2. Name the table and filter that eliminate the rows at that scale.
3. Seek a discriminating seed, dsqgen stream, or scale within the run budget, and record unsuccessful attempts as well as hits.
4. Establish template validity from qualification answer evidence, and exercise the query on non-empty data in the independent qualification lane.
5. Record any divergence at another scale as uncovered work and exclude it from coverage counts.

Keep classifications scoped to the scale and draw. Empty results are not monotonic in scale. A SQL-only search that finds a non-empty draw is a candidate for further testing; rerun every DataFrame backend under that exact binding before claiming parity. A one-row hit may still need a stronger fixture that distinguishes the operation being changed.

Classified empty matches never count as non-empty query coverage. Report registered queries, attempted comparisons, non-empty matches, empty matches, all-NULL matches, missing implementations, errors, and divergences separately.

## Adding or changing a query

1. Read the SQL template and identify every substitution that reaches its predicates, expressions, projection, aggregation, or ordering. Preserve fixed template constants as fixed constants.
2. Add or update the adapter, including derived values and ordered lists. Keep the default parameter inventory consistent with the implementation keys.
3. Update both implementation families and every affected statement variant. Preserve SQL NULL behavior and the explicit order direction and NULL placement.
4. Add a non-empty fixture with enough rows to distinguish the changed operation. Include NULLs, duplicate matches, or ties when they affect the query.
5. Run binding checks and compare SQL and each affected DataFrame engine using identical values. Test a different draw and relevant scales when the changed predicate can disappear in the smallest cell.

Run the adapter and implementation-key checks:

```bash
uv run -- python -m pytest tests/unit/core/tpcds/test_parameter_adapters.py tests/unit/core/tpcds/test_parameter_binding_coverage.py tests/unit/core/tpcds/test_parameter_consumption_inventory.py -n 0 -q
```

Run the literal-fallback and drawn-name completeness checks:

```bash
uv run -- python -m pytest tests/unit/core/tpcds/test_literal_fallback_lint.py tests/unit/core/tpcds/test_parameter_name_completeness.py -n 0 -q
```

The literal-fallback check follows parameter reads through implementation helpers and YAML specs, and checks that the adapter supplies the keys. The name-completeness check verifies that logged values reaching the SQL are read by the adapter. Neither test proves result equivalence. Production binding behavior is covered separately by `tests/unit/core/tpcds/test_production_binding.py`. A literal default must not conceal an unbound drawn value; fix the adapter and implementation instead of adding an exemption to make a check pass.

The official qualification diagnostic runner uses SF1 and the full Appendix B
substitution maps, including Q75's year 2002. Reproduce the complete parameter
reconciliation with:

```bash
uv run --with pypdf==6.0.0 -- python scripts/audit_tpcds_qualification.py \
  --pdf _sources/tpc-ds/specification/specification_4.0.0.pdf \
  --parameters benchbox/core/tpcds/dataframe_queries/qualification_values.json \
  --output /tmp/tpcds-parameter-audit.json
```

Run the diagnostic with a fresh output directory:

```bash
uv run -- python -m benchbox.core.tpcds.qualification.runner \
  --output-dir /tmp/tpcds-qualification --query-seconds 120 --overall-seconds 1200
```

`--preflight-only` verifies the frozen specification, parameter, template and
answer inventories and renders all 103 statements without generating SF1 data.
Q14, Q23, Q24 and Q39 each map to two statements. Q98's repeated page header
produces two extracted pages that concatenate in file order into one statement.
The official pack has 104 extracted blocks and 103 mapped statements per NULL
order. Both official NULL-order variants are reported independently against
unchanged reference SQL; file selection does not alter its ordering or membership.

The runner converts printed cells using the DuckDB reference column types and
file-specific NULL spellings recorded in the frozen manifest. Numeric-looking
strings remain strings. It preserves the existing validator's numeric tolerance,
NULL/NaN distinction and order checks, with its existing string-padding option.
Official files contain rounded display values: a strict mismatch remains a
reported mismatch. When a strict comparison fails, the runner also records
`sql_to_printed_display` or `dataframe_to_printed_display`. That comparison
replaces each numeric cell with the printed value only when rounding the cell
to the printed decimal places gives exactly the printed text, with rows paired
by position. A match there classifies the mismatch as display precision; it
does not change the statement's status. These diagnostics do not certify
compliance with the TPC specification's aggregate precision allowances.

When an `ORDER BY` term does not map to a result column, such as a `CASE` key,
an arithmetic key or an outer `SELECT *`, the runner and the cross-surface gate
evaluate the query's own sort terms over the returned rows. Rows that tie on
every sort term may appear in any order.

Each engine runs in a separate process with a private cache. The runner bounds
the whole report to 20 minutes, each query to 120 seconds and each worker's
resident memory to 6 GiB. Artifacts record all substitution values and hashes,
source and dependency versions, binary and data hashes, chosen answer files,
SQL text, column types, comparison failures and resource receipts. The weekly
workflow is advisory and retains failures in artifacts and its job summary.
