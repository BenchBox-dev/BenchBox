---
orphan: true
---

<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Usage Overview

```{tags} beginner, quickstart
```

BenchBox keeps everyday workflows concise. Use this page as the jumping-off point for the tasks you perform most often.

## Essentials

- [Getting started in 5 minutes](getting-started.md), install the tool, profile your system, and execute a reproducible first run.
- [CLI quick reference](cli-quick-start.md), most-used commands and flags for interactive and unattended runs.
- [Configuration handbook](configuration.md), YAML layouts, environment overrides, and precedence rules.
- [Examples & automation snippets](examples.md), copyable scripts for Python and shell automation.
- [Python API reference](../reference/api-reference.md), when you need to orchestrate runs programmatically.

## Extended Topics

- [Dry-run previews](dry-run.md), validate queries, seeds, and artifacts without executing them.
- [Data generation & compression](data-generation.md), storage footprint guidance and compression toggles.
- [Intelligent guidance](intelligent-guidance.md), how the CLI adapts recommendations to your hardware profile.
- [Platform selection guide](../platforms/platform-selection-guide.md), compare adapter capabilities before running at scale.
- [Troubleshooting](troubleshooting.md), fix common environment and dependency issues fast.

## Next Steps

1. Run `uv run -- benchbox profile` to capture a baseline system profile.
2. Pick a platform with `uv run -- benchbox platforms list` and enable it if required.
3. Execute a benchmark with `uv run -- benchbox run --platform duckdb --benchmark tpch --scale 0.01`.
4. Inspect results via `uv run -- benchbox results --limit 1` or export JSON for CI with `uv run -- benchbox export`.

Bookmark this page to keep the most relevant references a single click away.
