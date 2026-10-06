(cli-metrics)=
# `metrics` - Performance Metrics

```{tags} reference, cli, metrics
```

Calculate TPC Power@Size and Throughput@Size from benchmark results.

## Basic Syntax

```bash
benchbox metrics <subcommand> [OPTIONS]
```

## Subcommands

### `qphh` - Power@Size and Throughput@Size

Calculate Power@Size and Throughput@Size from power test and throughput test results. The subcommand name is kept for compatibility, but it does not compute the composite QphH@Size or QphDS@Size: BenchBox does not yet run the TPC-H refresh functions or the TPC-DS data maintenance phases that the composite requires.

**Formula:**

```
Power@Size       = 3600 × SF / geometric_mean(final power iteration query times)
Throughput@Size  = Queries × 3600 × SF / Throughput_Phase_Wall_Time

Where Queries = 22 × streams for TPC-H and 99 × streams for TPC-DS.
```

The command exits non-zero when either file has suppressed TPC metrics, any failed query, or a failed throughput phase.

```bash
benchbox metrics qphh --power-results <path> --throughput-results <path> [OPTIONS]
```

**Required:**
- `--power-results PATH`: Path to power test results JSON file
- `--throughput-results PATH`: Path to throughput test results JSON file

**Optional:**
- `--scale-factor FLOAT`: Scale factor (auto-detected from results if not provided)
- `--format [text|json]`: Output format (default: `text`)
- `--output PATH`: Save output to file

## Usage Examples

```bash
benchbox metrics qphh \
  --power-results results/power/results.json \
  --throughput-results results/throughput/results.json

benchbox metrics qphh \
  --power-results power.json \
  --throughput-results throughput.json \
  --scale-factor 100

benchbox metrics qphh \
  --power-results power.json \
  --throughput-results throughput.json \
  --format json --output qphh.json
```

The first command calculates QphH from test results. The second specifies the scale factor explicitly, and the third exports to a JSON file.

## Notes

- Scale factor is auto-detected from the `environment.scale_factor` field in result files. If the power and throughput results have mismatched scale factors, an error is raised.
- The command uses `Power@Size` and `Throughput@Size` from the result files' `tpc_metrics` when present. Otherwise it derives Power@Size from the final power iteration and Throughput@Size from the throughput phase wall-clock duration, never from summed query time.

## Related

- [run](run.md) - Run benchmarks with power and throughput phases
