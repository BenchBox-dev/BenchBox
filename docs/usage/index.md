<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# User Guide

```{tags} beginner
```

Your daily reference for using BenchBox. This section covers configuration, running benchmarks, and understanding results.

## Quick Links

| Task | Guide |
|------|-------|
| Configure BenchBox | [Configuration](configuration.md) |
| Generate test data | [Data Generation](data-generation.md) |
| Preview before running | [Dry Run](dry-run.md) |
| Find example scripts | [Examples Directory](examples-directory.md) |
| Understand your results | [Understanding Results](../tutorials/understanding-results.md) |
| Fix common issues | [Troubleshooting](troubleshooting.md) |

## Configuration

- [Configuration Guide](configuration.md) - YAML layouts, environment overrides, and precedence rules
- [Intelligent Guidance](intelligent-guidance.md) - How the CLI adapts to your hardware profile

## Running Benchmarks

- [Data Generation](data-generation.md) - Generating benchmark datasets at various scales
- [Dry Run](dry-run.md) - Preview queries and configuration without executing
- [Dialect Translation](dialect-translation.md) - SQL dialect translation vs platform adapters
- [Cloud Sorted Ingestion](cloud-sorted-ingestion.md) - Opt-in deep sorting strategy for cloud DW comparisons
- [TPC Logical Tuning Profiles](tpc-tuning-profiles.md) - Tuned-template profile coverage and comparison semantics
- [Databricks Liquid Clustering](databricks-liquid-clustering.md) - Strategy control and migration from Z-ORDER

## Examples

- [Examples Directory](examples-directory.md) - **40+ runnable examples organized by difficulty**
- [Code Snippets](examples.md) - Inline Python and shell examples
- [Example Scripts](examples/index.md) - Categorized example scripts

## Help & Support

- [FAQ](faq.md) - Frequently asked questions
- [Troubleshooting](troubleshooting.md) - Common issues and solutions

## Concepts

Core concepts for understanding BenchBox:

- [Concepts Overview](../concepts/index.md) - Architecture, workflow, and terminology
- [Glossary](../concepts/glossary.md) - Terms and definitions
- [Data Model](../concepts/data-model.md) - Data structures and relationships

## Next Steps

1. Run `benchbox profile` to capture a baseline system profile
2. Pick a platform with `benchbox platforms list`
3. Execute a benchmark: `benchbox run --platform duckdb --benchmark tpch --scale 0.01`
4. View results: `benchbox results --limit 1`

## Related Documentation

- [Getting Started](getting-started.md) - First-time setup
- [CLI Reference](../reference/cli/index.md) - Complete command documentation
- [Guides](../guides/index.md) - Task-oriented how-to guides

```{toctree}
:maxdepth: 1

installation
getting-started
cli-quick-start
configuration
examples
examples-directory
examples/index
dry-run
data-generation
dialect-translation
cloud-sorted-ingestion
tpc-tuning-profiles
databricks-liquid-clustering
intelligent-guidance
faq
troubleshooting
README
```
