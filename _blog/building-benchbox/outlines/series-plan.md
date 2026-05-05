# "Building BenchBox" Content Plan

**Concept**: Engineering decisions behind BenchBox: the trade-offs, evaluations, and design choices that shaped the tool. Not how to use BenchBox, but why it works the way it does.

**Audience**: Developers building CLI tools, open-source maintainers making build-vs-buy decisions, and BenchBox users curious about what's under the hood.

**Tone**: Exploratory, evidence-based, technically honest. We share what we tried, what worked, what didn't, and why we chose our path.

**Length**: 1,500-2,500 words per post (Architecture/Design Post type)

**Cadence**: As-needed; tied to significant engineering decisions

---

## Post Template

1. **The Problem** (200-300 words): What we needed, why existing options fell short
2. **What We Tried** (300-500 words): Libraries evaluated, approaches considered, evidence gathered
3. **What We Built** (400-600 words): The implementation, key design choices, trade-offs accepted
4. **What We Learned** (200-400 words): Takeaways, things we'd do differently, open questions
5. **Try It Yourself** (100-200 words): How readers can reproduce or explore the feature

---

## Planned Posts

| #   | Title | Status | Key Insight |
| --- | ----- | ------ | ----------- |
| 1   | Why we deleted Plotly and wrote our own ASCII charts | PLANNING | LLM-native tools need inline content, not file paths; zero-dep custom charting beat 10+ libraries |
| 2   | BenchBox v0.1.2 changes summary | PUBLISHED | Concise release summary of visualization, DataFrame coverage, platform expansion, and reliability updates |
| 3   | BenchBox v0.1.3 release summary | PLANNING | ASCII charts complete (new types, no-color fallbacks, auto-run), driver pinning/optional extras, bulk loading |
| 3   | TPC binary wrangling: shipping prebuilt dsdgen across platforms | IDEA | Cross-platform binary distribution for TPC data generation |
| 4   | DataFrame benchmarking: translating SQL to Polars/Pandas | IDEA | The challenges of faithful TPC-H translation to DataFrame APIs |
| 5   | DuckDB tpch extension vs BenchBox TPCH: same benchmark, different goals | OUTLINED | Extension mode is ideal for quick in-engine checks, while BenchBox adds reproducibility controls and cross-platform workflow |
| 6   | Extracting textcharts from BenchBox | PUBLISHED | Extraction forced API improvements we wouldn't have made otherwise; the process revealed hidden coupling |
| 7   | BenchBox v0.1.5 release summary | PUBLISHED | Textcharts extraction ships, table format loading lands, coverage theater replaced with mutation testing |
| 8   | BenchBox v0.2.0: Alpha to Beta | PUBLISHED | Beta promotion: cloud platform hardening, on-demand answer downloads, 80% coverage, Redshift reliability |
| 9   | BenchBox v0.2.1: MPP wave, vector search, and harmonized scale factors | OUTLINED | 6 new platforms (Doris, CedarDB, StarRocks, SingleStore, QuestDB, Gluten+Velox), Vector Search and FlightData benchmarks, NYC Taxi expansion, ClickHouse split into 3 deployment modes |
| 10  | One SF, one gigabyte: harmonizing scale factors across BenchBox | OUTLINED | Backwards-incompatible by intent: 7 adjustable benchmarks now target ~1 GB at SF=1; spec-locked benchmarks unchanged; covers second-order constraints (TSBS quadratic growth, NYC Taxi/FlightData corpus ceilings) |
| 11  | What we built on top of SQLGlot (and why transpilation isn't enough) | OUTLINED | SQLGlot does the transpilation 80%; the other ~2,500 lines (dialect normalization, DataFusion semantic rewrites, QuestDB syntax fixups, 19-platform DDL registry, hand-written query overrides, SQL-to-DataFrame layer) are what production cross-engine work looks like |
| 12  | Two benchmarks for one announcement: covering Databricks' new sketch functions in BenchBox | DRAFTED | The Databricks sketch announcement's headline claim is persist+merge+requery, not aggregate latency. Single-query catalogs can't exercise that loop, so coverage needed `read_primitives` (5 approx queries) and a new `write_primitives` sketch category (8 ops), with Tuple sketches deferred and verification claims separated from catalog support, DuckDB extension drift, and deferred cloud credentials |

---

## Key Themes

1. **Build vs. Buy with Evidence**: We don't build custom when a library works. But we evaluate thoroughly before deciding, and sometimes the evidence says "build."
2. **CLI-First, LLM-Friendly**: Design decisions that serve both terminal users and AI tool integrations (MCP).
3. **Zero-Dependency Where Possible**: Every dependency is a maintenance burden; we justify each one.
4. **Benchmarking Tools Need to Be Fast**: A benchmarking framework that's slow or bloated undermines its own credibility.

---

*Series created: 2026-02-13*
