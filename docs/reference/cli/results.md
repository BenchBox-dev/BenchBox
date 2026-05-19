# Results Commands

```{tags} reference, cli, validation
```

Commands for exporting, viewing, and comparing benchmark results.

(cli-export)=
## `export` - Export Results

Re-export existing benchmark results in different formats without re-running benchmarks. Useful for sharing results, generating reports, or converting to spreadsheet-friendly formats.

### Options

- `RESULT_FILE`: Path to result JSON file to export (optional argument)
- `--format [json|csv|html]`: Export format(s) - can specify multiple times (default: json)
- `--output-dir TEXT`: Output directory (default: benchmark_runs/results/)
- `--last`: Export most recent result file
- `--benchmark TEXT`: Filter by benchmark name when using --last
- `--platform TEXT`: Filter by platform name when using --last
- `--force`: Overwrite existing files without prompting

### Supported Export Formats

**JSON**, Complete benchmark results in canonical schema format
- Full metadata, metrics, and query results
- Suitable for programmatic analysis and archival
- Default format during benchmark runs

**CSV**, Flattened query results for spreadsheet analysis
- Query-level details: execution times, status, rows returned
- Compatible with Excel, Google Sheets, data analysis tools
- Ideal for performance analysis and charting

**HTML**, Standalone report with formatted tables
- Summary metrics and system information
- Color-coded query results table
- Ready to share with stakeholders

### Usage Examples

```bash
# Export most recent result to CSV
benchbox export --last --format csv

# Export specific result file to multiple formats
benchbox export results/tpch_sf1_duckdb.json --format csv --format html

# Export latest TPC-H result to all formats
benchbox export --last --benchmark tpc_h --format json --format csv --format html

# Export latest DuckDB result to HTML
benchbox export --last --platform duckdb --format html

# Export to custom directory
benchbox export --last --format csv --output-dir ./reports/

# Export with specific file and force overwrite
benchbox export benchmark_runs/results/tpcds_sf10.json --format html --force
```

### Common Workflows

**Share Results with Team:**
```bash
# Export recent result as HTML report
benchbox export --last --format html --output-dir ./team_reports/
# Share the HTML file via email or documentation
```

**Analyze in Spreadsheet:**
```bash
# Export to CSV for Excel/Sheets analysis
benchbox export --last --format csv --output-dir ~/Downloads/
# Open CSV in Excel for charting and analysis
```

**Archive Benchmarks:**
```bash
# Export all formats for comprehensive archival
benchbox export --last --format json --format csv --format html --output-dir ./archive/
```

### Notes

- The `export` command loads existing result files from `benchmark_runs/results/`
- Schema versions 2.0 and 2.1 are supported by current result tooling
- Export preserves all metrics and metadata from original results
- Large result files (TPC-DS at scale 100+) may take a few seconds to process
- The --force flag skips confirmation prompts when overwriting existing files
- Use `benchbox results` to see available result files before exporting

---

(cli-results)=
## `results` - Show Benchmark Results

Display exported benchmark results and execution history.

### Options

- `--limit INTEGER`: Number of results to show (default: 10)
- `--submitted`: Show hosted submission history sidecars instead of exported
  benchmark result files
- `--paths`: Print copyable primary result JSON paths for use with
  `benchbox submit`, `benchbox export`, or `benchbox results show-cli`

`--paths` writes one path per line to stdout (no Rich formatting, no preamble)
so the output is safe to pipe into `xargs` or save with `tee`. Hint text and
overflow notices are written to stderr. The list contains only primary
schema-v2 result JSON files — companion files such as `.plans.json`,
`.tuning.json`, and hosted `.submission.json` sidecars are excluded.

`--paths` and `--submitted` are mutually exclusive: hosted submission history
is a separate sidecar surface from local result discovery.

### Usage Examples

```bash
# Show recent results
benchbox results

# Show more results
benchbox results --limit 25

# Show exact result file paths accepted by submit/export (one per line, pipeable)
benchbox results --paths

# Pipe into submit to package each result in turn
benchbox results --paths --limit 100 | xargs -n1 -I{} benchbox submit {} --output ./submissions

# Show hosted submissions and public URLs
benchbox results --submitted
```

---

(cli-compare)=
## `compare` - Compare Benchmark Results

Compare two or more benchmark result files to analyze performance changes. Displays side-by-side query timing comparisons, geometric means, and regression detection suitable for CI/CD workflows.

### Basic Syntax

```bash
benchbox compare BASELINE.json CURRENT.json [OPTIONS]
```

### Options

- `RESULT_FILES`: Two or more result JSON files to compare (first file is baseline, required)
- `--fail-on-regression THRESHOLD`: Exit with code 1 if any regression exceeds threshold
  - Percentage format: `10%`, `5.5%`
  - Decimal format: `0.1`, `0.05`
- `--format [text|json|html]`: Output format (default: text)
- `--output FILE`: Save comparison output to file instead of stdout
- `--show-all-queries`: Show all query comparisons (default: only regressions/improvements)

### Output Formats

**Text** (default), Human-readable comparison report
- Color-coded indicators for performance changes
- Geometric mean calculation across all queries
- Per-query breakdown sorted by severity
- Suitable for terminal viewing and logs

**JSON**, Machine-readable comparison data
- Full comparison metrics and query-level details
- Suitable for programmatic analysis and dashboards
- Includes `performance_changes`, `query_comparisons`, and `summary` sections

**HTML**, Standalone comparison report
- Formatted tables with color-coded severity
- Summary statistics and per-query breakdown
- Ready to share with stakeholders or archive

### Usage Examples

**Basic Comparison:**
```bash
# Compare two result files
benchbox compare baseline.json current.json

# Compare with all queries shown (not just changes)
benchbox compare baseline.json current.json --show-all-queries
```

**CI/CD Integration:**
```bash
# Fail pipeline if any query regresses more than 10%
benchbox compare baseline.json current.json --fail-on-regression 10%

# Stricter threshold for critical paths
benchbox compare baseline.json current.json --fail-on-regression 5%

# Using decimal notation
benchbox compare baseline.json current.json --fail-on-regression 0.1
```

**Export Comparison Reports:**
```bash
# Export as JSON for dashboards
benchbox compare baseline.json current.json --format json --output comparison.json

# Generate HTML report for stakeholders
benchbox compare baseline.json current.json --format html --output report.html

# Save text report to file
benchbox compare baseline.json current.json --output comparison.txt
```

### Comparison Output

The comparison report includes:

**Summary Section:**
- Total queries compared
- Count of improved, regressed, and unchanged queries
- Overall assessment (improved/regressed/mixed)

**Performance Metrics:**
- Average query time change
- Total execution time change
- Per-metric improvement indicators

**Geometric Mean:**
- Baseline and current geometric means (standard benchmark metric)
- Percentage change with severity indicator

**Per-Query Breakdown:**
- Query ID, baseline time, current time, percentage change
- Severity classification:
  - `CRITICAL`: >50% regression
  - `MAJOR`: >25% regression
  - `MINOR`: >10% regression
  - `SLIGHT`: >1% regression
  - `FASTER`: Any improvement

### Severity Indicators

| Indicator | Meaning | Threshold |
|-----------|---------|-----------|
| `🟢` | Improved (faster) | Any negative change |
| `⚪` | Unchanged | <1% change |
| `🟡` | Minor regression | 1-10% slower |
| `🔴` | Major regression | >10% slower |

### Common Workflows

**Regression Testing in CI/CD:**
```bash
# 1. Run baseline benchmark (e.g., main branch)
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --output ./baseline-results

# 2. Run current benchmark (e.g., feature branch)
benchbox run --platform duckdb --benchmark tpch --scale 0.1 \
  --output ./current-results

# 3. Compare and fail on regression
benchbox compare \
  baseline-results/results/*.json \
  current-results/results/*.json \
  --fail-on-regression 10%
```

**Before/After Optimization Analysis:**
```bash
# Run without tuning
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning notuning --output ./baseline

# Run with tuning
benchbox run --platform snowflake --benchmark tpch --scale 1 \
  --tuning tuned --output ./optimized

# Compare results
benchbox compare \
  baseline/results/tpch_*.json \
  optimized/results/tpch_*.json \
  --format html --output tuning-analysis.html
```

**Cross-Platform Comparison:**
```bash
# Compare DuckDB vs ClickHouse performance
benchbox compare \
  duckdb-results/results/tpch_sf1.json \
  clickhouse-results/results/tpch_sf1.json \
  --show-all-queries
```

### Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Comparison completed successfully (no regression above threshold) |
| `1` | Regression detected above `--fail-on-regression` threshold, or error occurred |

### Notes

- The first result file is always treated as the baseline
- Both result files must use schema version 1.0
- Results should be from the same benchmark and scale factor for meaningful comparison
- Multi-file comparison (>2 files) is planned for a future release
- Use `benchbox results` to find available result files for comparison

### Python API

For programmatic comparison, use the `ResultExporter` class:

```python
from pathlib import Path
from benchbox.core.results.exporter import ResultExporter

exporter = ResultExporter()

# Compare two result files
comparison = exporter.compare_results(
    Path("baseline.json"),
    Path("current.json")
)

# Check overall performance
perf = comparison['performance_changes']['average_query_time']
print(f"Average query time: {perf['change_percent']:.2f}% change")

if perf['improved']:
    print("Performance improved!")

# Export as HTML report
report_path = exporter.export_comparison_report(comparison)
print(f"Report saved to: {report_path}")
```

See [Result Analysis API](../python-api/result-analysis.rst) for complete API documentation.

## Related

- [Workflows](workflows.md) - Common usage patterns including performance analysis
- [Result Schema](../result-schema-v1.md) - JSON schema specification for result files
