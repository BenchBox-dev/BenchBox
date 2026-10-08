(cli-query-plans)=
# `show-plan` / `plan-history` - Query Plans

```{tags} reference, cli, query-plans
```

Inspect and track query execution plans from benchmark runs.

## `show-plan` - Display Query Plan

Display the query plan for a specific query from a benchmark result file as an ASCII tree, summary, or JSON.

### Basic Syntax

```bash
benchbox show-plan --run <results.json> --query-id <id> [OPTIONS]
```

### Options

**Required:**
- `--run PATH`: Path to benchmark results JSON file
- `--query-id TEXT`: Query ID to show plan for (e.g., `q05`, `1`)

**Optional:**
- `--format [tree|summary|json]`: Output format (default: `tree`)
- `--no-properties`: Hide operator properties in tree view
- `--compact`: Use compact tree format
- `--max-depth INT`: Maximum tree depth to display

### Examples

```bash
benchbox show-plan --run results.json --query-id q05

benchbox show-plan --run results.json --query-id 1 --format summary

benchbox show-plan --run results.json --query-id q05 --format json

benchbox show-plan --run results.json --query-id q05 --compact --no-properties

benchbox show-plan --run results.json --query-id q05 --max-depth 3
```

### Notes

- Plans must be captured during the benchmark run using `--capture-plans`. Without this flag, no plan data is available.
- The result loader automatically checks for a companion `.plans.json` file alongside the result file.

---

## `plan-history` - Plan Evolution

Show how a query's execution plan has changed across benchmark runs. Useful for identifying plan regressions and optimizer instability.

### Basic Syntax

```bash
benchbox plan-history --query-id <id> --history-dir <path> [OPTIONS]
```

### Options

**Required:**
- `--query-id TEXT`: Query ID to show history for (e.g., `q05`, `1`)
- `--history-dir PATH`: Directory containing plan history files

**Optional:**
- `--limit INT`: Maximum number of entries to show (default: 20)
- `--check-flapping`: Detect plan flapping (plans that change frequently between runs)

### Examples

```bash
benchbox plan-history --query-id q05 --history-dir ./plan_history

benchbox plan-history --query-id q05 --history-dir ./plan_history --check-flapping

benchbox plan-history --query-id q05 --history-dir ./plan_history --limit 50
```

### Output

The history table shows:

| Column | Description |
|--------|-------------|
| Run ID | Benchmark run identifier |
| Timestamp | When the run occurred |
| Fingerprint | Plan structure hash (changes highlighted in yellow) |
| Time (ms) | Query execution time |
| Version | Plan version number (increments on each plan change) |

A summary section shows the total number of unique plans and plan changes. With `--check-flapping`, the command reports whether the plan exhibits instability.

## Related

- [run](run.md) - Run benchmarks with `--capture-plans` to record query plans
