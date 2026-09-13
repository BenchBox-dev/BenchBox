# Schema-aware frozen-model challenge

This extension evaluates the existing selected CodeT5 checkpoints without training,
checkpoint selection, output repair, or execution-feedback retries. It is a new
post-training challenge, not a revision of the original locked test set.

## Prior art and implementation boundary

Extend the deterministic seed/replay pattern in
`_project/sqlglot-upstream/repros/generator.py` and reuse this experiment's bounded
execution comparator, model prompt, span validator, and selected-checkpoint hash
checks. Reuse TPC-H type and key metadata from
`benchbox/core/tpch/schema.py`. The supported package and its default dependencies
are unchanged. All added functionality remains in this isolated research project.

The generator uses typed, source-native SQL construction rather than SQLGlot
translation to decide which source queries are allowed. SQLGlot still parses
sources for safety and structure tagging; native-engine execution establishes
source eligibility. Therefore this is not independent of SQLGlot's parsing limits.

Coverage-guided construction follows the separation of generation and oracles in
[SQLancer](https://github.com/sqlancer/sqlancer) and the grammar-coverage motivation
of [ParserFuzz](https://arxiv.org/abs/2503.03893). It does not import their code or
claim their engine-internal coverage. A learned generator is unnecessary for the
current bounded requirement; revisit it only if measured valid structural coverage
plateaus under a comparable generation/execution budget.

## Coverage contract

All eight TPC-H tables are represented. The finite inventory combines eight
expression categories with nine relational forms, subject to actual column types.
The default two variants produce 1,872 directional generated cases across 468
applicable table/expression/form targets. Another 108 targets are explicitly
unavailable because their tables lack DATE columns. The scheduler visits every
applicable target; a seed controls compatible columns, constants and output aliases.
The second variant adds multiline formatting. Related variants and reverse
directions remain identified by the same family.

This is constrained random generation, not arbitrary grammar synthesis. The
capability inventory is intentionally incomplete relative to either engine. It
does not claim all syntax, arbitrary nesting, every feature interaction, or
engine-internal branch coverage. `source-validation.json` retains failed sources;
`summary.json` reports attempted, source-valid and nonempty-witness coverage for
every target. A nonempty result still does not prove every expression branch ran.

`independent_queries.py` contains 12 schema-only, independently authored challenges,
each evaluated in both directions. The author did not inspect generator templates
or model outcomes. These include nested CTEs, correlated subqueries, grouping,
ordering, windows, set operations, NULLs, multiline SQL and longer queries. They
are a separate small suite, not a statistically representative random sample.

Five small seeded fixtures preserve declared non-null columns and foreign-key
references. They include repeated non-key values, NULL comments, negative and zero
numeric values, Unicode and whitespace, boundary dates, unmatched outer joins,
and an empty lineitem table. DECIMAL fixture values are integral to avoid an
implicit tolerance masking SQLite/DuckDB numeric differences. These are not
compliant TPC-H data distributions or performance benchmarks.

## Replay

Use an absolute new output directory outside Git. Replace the example paths with
the retained original training directory and a fresh challenge directory.

```sh
uv run --project _project/sql-translation-ml -- python _project/sql-translation-ml/schema_evaluate.py prepare \
  --training-dir /absolute/original-training-run --run-dir /absolute/new-challenge-run
uv run --project _project/sql-translation-ml -- python _project/sql-translation-ml/schema_evaluate.py evaluate \
  --run-dir /absolute/new-challenge-run --system sqlglot
uv run --project _project/sql-translation-ml -- python _project/sql-translation-ml/schema_evaluate.py evaluate \
  --run-dir /absolute/new-challenge-run --system benchbox
uv run --project _project/sql-translation-ml -- python _project/sql-translation-ml/schema_evaluate.py evaluate \
  --run-dir /absolute/new-challenge-run --system full
uv run --project _project/sql-translation-ml -- python _project/sql-translation-ml/schema_evaluate.py evaluate \
  --run-dir /absolute/new-challenge-run --system edit
uv run --project _project/sql-translation-ml -- python _project/sql-translation-ml/schema_evaluate.py report \
  --run-dir /absolute/new-challenge-run
```

Run the systems sequentially for comparable CPU conditions. Each evaluation has
a one-hour budget; individual source/target queries have a two-second execution
timeout and a 10,000-row limit. Model decoding uses the existing single-candidate,
30-second generation setting and rejects outputs without EOS. A stopped or failed
run retains its partial output but cannot produce a complete report. Use a fresh
directory to repeat; do not overwrite or silently resume a partial locked run.

The preparation contract freezes all attempted sources, fixture values, source
validation, implementation hashes, schema and checkpoint identities before model
evaluation. Reported full-population outcomes include over-budget model failures;
the report also gives the same source-prompt-at-most-1024-token subset for all
systems. Hybrid candidate-expanded prompts may exceed that limit even when the
source-only prompt fits; those failures are retained, not silently truncated.
No confidence claim of general SQL accuracy is made from these finite families.

## Verification

```sh
uv run --project _project/sql-translation-ml -- pytest -c _project/sql-translation-ml/pytest.ini _project/sql-translation-ml -q
```

Tests cover deterministic replay, scheduled target coverage, source execution,
independent query agreement over all five fixtures, key relationships, exact
numeric comparison, and preservation of the original safety allowlist.
