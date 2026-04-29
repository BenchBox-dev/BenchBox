# Configuration Handbook

```{tags} intermediate, guide, configuration
```

BenchBox reads configuration from three layers, highest precedence first:

1. **CLI options** - flags supplied to `benchbox run`, `benchbox export`, etc.
2. **Environment variables** - primarily tuning overrides (see below).
3. **Configuration files** - `benchbox.yaml` in the working directory or `~/.benchbox/config.yaml`.

If no file is present, BenchBox uses sensible defaults. You can generate a tuning template with `uv run -- benchbox tuning init --platform duckdb`.

## Minimal Example

```yaml
# benchbox.yaml
benchmarks:
  default_scale: 0.1
  continue_on_error: false

database:
  preferred: duckdb
  connection_timeout: 30

output:
  directory: ./benchmark_runs/results
  formats: [json, console]

execution:
  power_run:
    iterations: 3
    warm_up_iterations: 1
  concurrent_queries:
    enabled: false
```

Save the file next to your project and run:

```bash
uv run -- benchbox run --benchmark tpch --platform duckdb
```

CLI flags still win. For example `--scale 1` overrides `benchmarks.default_scale` for that invocation only.

## File Locations & Schema

BenchBox searches in this order:

1. `./benchbox.yaml`
2. `~/.benchbox/config.yaml`

Files are parsed as YAML and merged with built-in defaults defined in `benchbox.cli.config.ConfigManager`. Unknown keys are preserved so you can store project metadata alongside official sections (`system`, `database`, `benchmarks`, `output`, `execution`, `tuning`).

Use these helpers when you need to inspect or persist configuration programmatically:

```python
from benchbox.cli.config import ConfigManager

config = ConfigManager()             # auto-detects benchbox.yaml
scale = config.get("benchmarks.default_scale")
config.set("execution.power_run.iterations", 5)
config.save_config()
```

## Execution Profiles

`benchbox.utils.ExecutionConfigHelper` wraps common tuning operations. It works with or without an existing config file.

```python
from benchbox.utils import ExecutionConfigHelper

helper = ExecutionConfigHelper()

# Enable a quick power run profile
helper.enable_power_run_iterations(iterations=3, warm_up_iterations=1)

# Turn on concurrent streams and optimise for hardware
helper.enable_concurrent_queries(max_concurrent=4)
helper.optimize_for_system(cpu_cores=16, memory_gb=64)
```

The helper updates the active configuration provider, so CLI runs pick up the changes once you call `config.save_config()` or invoke the helper with an explicit `ConfigManager` instance.

## Environment Overrides

Some tuning settings can be toggled at deploy time without editing files. The default mapping is stored under `tuning.environment_overrides`:

| Environment variable | Maps to | Typical values |
| --- | --- | --- |
| `BENCHBOX_TUNING_ENABLED` | `tuning.enabled` | `true`, `false` |
| `BENCHBOX_TUNING_CONFIG` | `tuning.default_config_file` | Path to a YAML file |

Set `BENCHBOX_TUNING_ENABLED=true` to activate tuned runs in CI, or point `BENCHBOX_TUNING_CONFIG` at a configuration checked into your repo.

## Validating Configuration

Before running large jobs, dry-run the plan and validate dependencies:

```bash
# Render the execution plan without running anything
uv run -- benchbox run --dry-run ./plan --platform duckdb --benchmark tpch

# Check platform requirements declared in the config
uv run -- benchbox check-deps --matrix
```

`benchbox run` respects values from `benchbox.yaml`, so you can set project defaults once and execute repeatable runs with only a few flags.

## Related Commands

- `uv run -- benchbox tuning init` - scaffold a tuning YAML file for a specific platform.
- `uv run -- benchbox validate --config benchbox.yaml` - ensure configuration syntax and schema are valid.
- `uv run -- benchbox platforms setup` - interactively enable adapters defined in your config.

See the [CLI reference](../reference/cli-reference.md) for detailed command usage and the [examples library](examples.md) for advanced automation patterns.
