---
name: benchbox-workflow
description: Use when the user asks to "test TPC-H", "check compliance", "review architecture", "run quality checks", "check binaries", "test dialect translation", "compare implementations", "run live platform tests", or "plan and execute" a benchmark feature.
version: 0.2.0
tools: Bash, Read, Write, Edit, Glob, Grep, Task
---

# BenchBox Workflow

BenchBox-specific benchmark, platform, quality, and architecture workflows. Auto-detect runner, honor non-interactive mode, and produce human plus JSON/file artifacts when the called workflow supports them.

## Actions

| Action | Aliases | Contract |
|---|---|---|
| `test` | `benchmark-test` | Run benchmark-specific tests |
| `quality` | `quality-check`, `qa` | Run pre-commit quality checks |
| `compliance` | `tpc-compliance` | Validate TPC/spec coverage |
| `dialect` | `dialect-translation`, `sql` | Test SQL translation |
| `binary` | `binary-check`, `binaries` | Verify TPC binary integration |
| `compare` | `compare-impl` | Compare benchmark implementations |
| `live` | `live-test`, `platform-test` | Run approved cloud/platform tests |
| `architecture` | `arch`, `arch-review` | Review platform/benchmark architecture |
| `plan` | `plan-execute`, `implement` | Research, plan, implement, verify benchmark feature |

## Hard Rules

- Use `uv run --` for Python commands; `make` wrappers are fine.
- Respect BenchBox phases (`generate`, `load`, `power`, `throughput`, `maintenance`) and propagate `--phases`.
- Default smoke scale is 0.01; scale >=1 must be whole integers.
- Do not run live cloud tests without explicit approval and required credentials.
- Timing uses `benchbox.utils.clock.mono_time()` / `elapsed_seconds()` for durations.
- Adapter DDL rewrites must be registered under `benchbox/sql_compat/rules/ddl_optimize/`.

## Commands And References

- `test`: TPC-H/TPC-DS/SSB/ClickBench/DataFrame smoke and standards checks. See `references/test.md`.
- `quality`: lint, format, typecheck, fast tests. See `references/quality.md`.
- `compliance`: query count/correctness, data generation, binary integration, tests. See `references/compliance.md`.
- `dialect`: sqlglot translation across supported platforms. See `references/dialect.md`.
- `binary`: locations, executability, wrappers, query/data generation. See `references/binary.md`.
- `compare`: structural parity and harmonization opportunities. See `references/compare.md`.
- `live`: cloud/platform smoke with approval gate. See `references/live.md`.
- `architecture`: patterns, boundaries, duplication, extensibility. See `references/architecture.md`.
- `plan`: research -> implementation slices -> verification -> summary. See `references/plan.md`.
- UAT/long-run sweeps: see AGENTS.md "Long-Running UAT" and `docs/operations/uat-framework.md`.

## Output

For every action report command(s), pass/fail status, artifacts, key findings, and next steps. For failures include root-cause hypothesis and the narrowest next verification command.
