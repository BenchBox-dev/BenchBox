(cli-metrics)=
# `metrics` - Performance Metrics

```{tags} reference, cli, metrics
```

Calculate official TPC performance metrics from benchmark results.

## Basic Syntax

```bash
benchbox metrics <subcommand> [OPTIONS]
```

## Subcommands

### `qphh` - TPC-H QphH@Size

Calculate the official TPC-H QphH@Size (Queries per Hour) composite metric from power test and throughput test results.

**Formula:**

```
QphH@Size = sqrt(Power@Size × Throughput@Size)

Where:
  Power@Size       = 3600 × SF / Power_Test_Time
  Throughput@Size  = Num_Streams × 3600 × SF / Throughput_Test_Time
```

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
- The command derives `Power@Size` and `Throughput@Size` from pre-computed TPC metrics in the result files when available, and falls back to calculating them from individual query times.

## Related

- [run](run.md) - Run benchmarks with power and throughput phases
