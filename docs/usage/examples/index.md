# BenchBox Examples

```{tags} beginner, guide
```

This section provides detailed documentation for all examples in the `examples/` directory.

## Overview

The BenchBox examples are organized into six categories to help you learn progressively and find the right pattern for your needs.

## Example Categories

### 1. [Getting Started Examples](../../../examples/getting_started/README.md)
**5 examples** | **Beginner-friendly** | **5-10 minutes each**

Zero to working benchmark in minutes. Includes local (DuckDB) and cloud (Databricks, BigQuery) examples with clear progression.

**Start here if:** You're new to BenchBox

### 2. [Feature Examples](../../../examples/features/README.md)
**8 examples** | **Intermediate** | **10-15 minutes each**

Learn specific BenchBox capabilities in isolation: test types, query subsetting, tuning, multi-platform execution, and more.

**Start here if:** You know the basics and want to learn specific features

### 3. [Use Case Patterns](../../../examples/use_cases/README.md)
**4 examples** | **Advanced** | **20-30 minutes each**

Real-world solutions for common problems: CI/CD testing, platform evaluation, incremental tuning, and cost optimization.

**Start here if:** You're building production workflows

### 4. [Notebook Examples](../../../examples/notebooks/README.md)
**11 notebooks** | **All levels** | **Interactive**

Interactive Jupyter notebooks for each platform plus analysis patterns. Perfect for exploration and presentation.

**Start here if:** You prefer interactive development

### 5. [Configuration Templates](../../../examples/tunings/README.md)
**49 files** | **Reference** | **Copy-paste ready**

Platform configurations (15 files) and benchmark tuning configs (34 files) for all supported platforms.

**Start here if:** You need platform setup or tuning references

### 6. [Workflow Patterns](../../../examples/programmatic/README.md)
**8 patterns** | **All levels** | **Production-ready**

Complete, tested workflow patterns for common scenarios. Each pattern includes context, code, and usage guidance.

**Start here if:** You want proven patterns for your workflow

## Quick Links

- **Complete directory structure:** [Examples Directory Guide](../examples-directory.md)
- **Examples repository location:** `examples/` in the BenchBox repository
- **Detailed navigation:** [`examples/INDEX.md`](../../../examples/INDEX.md)
- **Pattern reference:** [`examples/PATTERNS.md`](../../../examples/PATTERNS.md)

## How to Use These Guides

Each guide in this section:

1. **Lists all examples** in that category with descriptions
2. **Provides code snippets** and usage examples
3. **Links to source files** in the `examples/` directory
4. **Explains when to use** each example
5. **Shows expected output** where applicable

## Running the Examples

All examples are in the `examples/` directory of the BenchBox repository:

```bash
# Clone the repository (if not already cloned)
git clone https://github.com/BenchBox-dev/benchbox.git
cd benchbox/examples

# Install BenchBox
uv add benchbox

# Run a local example (no configuration needed)
cd getting_started/local
python duckdb_tpch_power.py

# Run a feature example
cd ../../features
python query_subset.py
```

For cloud examples, see the [Configuration Guide](../../../examples/tunings/README.md) for platform setup instructions.

## See Also

- [Getting Started Guide](../getting-started.md) - BenchBox fundamentals
- [Configuration Guide](../configuration.md) - Platform configuration
- [CLI Reference](../../reference/cli-reference.md) - Command-line interface
- [API Reference](../../reference/api-reference.md) - Python API
