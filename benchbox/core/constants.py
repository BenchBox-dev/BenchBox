"""Benchmark-specific constants and defaults.

Contains specification-defined defaults for TPC benchmarks and other
configuration values that should be consistent across the codebase.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root for details.
"""

# TPC-H Power Test Defaults (TPC-H Specification Section 4.2)
# The Power Test measures query execution performance with a single stream
# Specification requires: 1 qualification run (warmup) + measured runs
TPCH_POWER_DEFAULT_WARMUP_ITERATIONS = 1
TPCH_POWER_DEFAULT_MEASUREMENT_ITERATIONS = 3

# TPC-DS Power Test Defaults (TPC-DS Specification Section 4.2.2)
# TPC-DS uses different defaults than TPC-H
TPCDS_POWER_DEFAULT_WARMUP_ITERATIONS = 1
TPCDS_POWER_DEFAULT_MEASUREMENT_ITERATIONS = 3

# TPC-H Throughput Test Defaults (TPC-H Specification Section 4.3)
TPCH_THROUGHPUT_DEFAULT_STREAMS = 2

# TPC-DS Throughput Test Defaults (TPC-DS Specification Section 4.3)
TPCDS_THROUGHPUT_DEFAULT_STREAMS = 2

# Generic Power Test Defaults (for non-TPC benchmarks)
# Based on TPC-H best practices: warmup to prime caches, multiple measurements for statistical validity
GENERIC_POWER_DEFAULT_WARMUP_ITERATIONS = 1
GENERIC_POWER_DEFAULT_MEASUREMENT_ITERATIONS = 3

# Generic Throughput Test Defaults (for non-TPC benchmarks)
GENERIC_THROUGHPUT_DEFAULT_STREAMS = 2


# --- Surface vocabulary -----------------------------------------------------
# The value sets below are shared by the CLI, MCP, and core. Each was previously
# written as a literal in two or more places and had already drifted; see
# `one-engine-unify-constants` and the ADR on scoped surfaces.

# Platform execution modes. This answers "how does the platform run queries",
# and it is a platform CAPABILITY -- PlatformRegistry.supports_mode() validates
# a request against it. It deliberately excludes `data_only`, which is not a way
# of running queries but a request not to run them at all; see EXECUTION_TYPES.
RUN_MODES = ("sql", "dataframe")

# Benchmark phases, in canonical execution order. `benchbox run --phases` and
# MCP `run_benchmark(phases=...)` both validate against this list.
VALID_PHASES = (
    "generate",
    "load",
    "statistics",
    "warmup",
    "power",
    "throughput",
    "maintenance",
)

# Phases that execute queries. Used to derive the execution type from a phase
# selection, and to reject phase combinations that cannot be measured.
QUERY_PHASES = ("power", "throughput", "maintenance")

# Execution types derived from a phase selection. `data_only` lives here rather
# than in RUN_MODES because it describes what work runs, not how the platform
# runs it.
EXECUTION_TYPES = (
    "standard",
    "power",
    "throughput",
    "maintenance",
    "combined",
    "load_only",
    "data_only",
)

# Formats a result bundle can be exported AS. `benchbox export --format` and the
# MCP `get_results` export path share this set.
EXPORT_FORMATS = ("json", "csv", "html")

# Everything MCP `get_results(format=...)` accepts: the export formats plus its
# read/preview modes. `list` and `details` select a response shape rather than
# an export, and `text`/`markdown` are rendered summaries, so this is a superset
# of EXPORT_FORMATS rather than a competing definition of it.
MCP_RESULT_FORMATS = ("list", "details", *EXPORT_FORMATS, "text", "markdown")

# MCP additionally accepts `data_only` on its `mode` parameter as a shortcut for
# "generate data, run no queries". The CLI reaches the same behavior through
# `--phases generate`. This asymmetry is deliberate and documented in
# docs/reference/mcp.md: MCP has no phase-selection surface rich enough to
# derive the execution type, so it names it directly.
MCP_MODE_CHOICES = (*RUN_MODES, "data_only")

# Spellings MCP accepts for `data_only` on its `mode` parameter.
MCP_DATA_ONLY_ALIASES = ("datagen", "generate")
