# Specification: CLI Composite Parameters Module

## Overview

The Composite Parameters Module provides parsers for CLI parameters that combine multiple related options into single, concise specifications using colon-delimited syntax. These composite parameters reduce CLI verbosity while providing rich configuration capabilities.

## Location

**File**: `benchbox/cli/composite_params.py` | **Module**: `benchbox.cli.composite_params`

## Purpose

The module addresses the challenge of expressing complex, multi-faceted configurations through command-line interfaces by:

1. Consolidating related options into single parameters (e.g., `--compression zstd:9`)
2. Providing consistent colon-delimited syntax across all composite parameters
3. Validating parsed values against domain-specific constraints
4. Exposing typed configuration objects for downstream consumers

---

## Composite Parameter Syntax

All composite parameters follow a consistent pattern:

| Pattern | Description |
| ------- | ----------- |
| `type` | Simple type/mode specification |
| `type:value` | Type with a single option |
| `key:value,key:value,...` | Multiple key-value pairs |

---

## Configuration Types

### CompressionConfig

Represents data compression settings for benchmark outputs and data files.

#### Attributes

| Name | Type | Default | Description |
| ---- | ---- | ------- | ----------- |
| `type` | `str` | `"zstd"` | Compression algorithm identifier |
| `level` | `int | None` | `None` | Algorithm-specific compression level |
| `enabled` | `bool` | `True` | Whether compression is active |

#### Supported Compression Types

| Type | Level Range | Description |
| ---- | ----------- | ----------- |
| `zstd` | 1-22 | Zstandard compression |
| `gzip` | 1-9 | GNU zip compression |
| `none` | N/A | Compression disabled |

#### Input Formats

| Format | Interpretation |
| ------ | -------------- |
| `none` | Compression disabled |
| `zstd` | Zstd with platform default level |
| `zstd:9` | Zstd with level 9 |
| `gzip:6` | Gzip with level 6 |

#### Validation Rules

- Type must be one of: `zstd`, `gzip`, `none`
- Zstd level must be in range 1-22
- Gzip level must be in range 1-9
- Level must be a valid integer when provided

---

### PlanCaptureConfig

Controls query execution plan capture behavior during benchmark runs.

#### Attributes

| Name | Type | Default | Description |
| ---- | ---- | ------- | ----------- |
| `sample_rate` | `float | None` | `None` | Fraction of executions to capture (0.0-1.0) |
| `first_n` | `int | None` | `None` | Capture only first N iterations |
| `queries` | `list[str] | None` | `None` | Specific query IDs to capture |
| `strict` | `bool` | `False` | Fail if plan capture fails |

#### Input Formats

| Format | Interpretation |
| ------ | -------------- |
| `sample:0.1` | Capture 10% of executions |
| `first:5` | Capture first 5 iterations only |
| `queries:1,6,17` | Capture specific queries |
| `strict:true` | Enable strict mode |
| `sample:0.1,first:5` | Combined options |
| `queries:1,6,17,strict:true` | Queries with strict mode |

#### Validation Rules

- Sample rate must be in range 0.0-1.0
- First N must be a positive integer
- Query IDs are comma-separated strings
- Strict accepts: `true`, `1`, `yes` (case-insensitive)
- Unknown keys raise an error

#### Special Parsing

The `queries` key receives special handling because query IDs are comma-separated within the value. The parser detects `queries:` and collects subsequent comma-separated values until encountering another `key:` pattern.

---

### TableFormatConfig

Specifies data format conversion settings for output files.

#### Attributes

| Name | Type | Default | Description |
| ---- | ---- | ------- | ----------- |
| `format` | `str` | `"parquet"` | Target file format |
| `compression` | `str` | `"snappy"` | Compression for converted files |
| `partition_cols` | `list[str]` | `[]` | Columns for partitioned output |

#### Supported Formats

| Format | Description |
| ------ | ----------- |
| `parquet` | Apache Parquet columnar format |
| `delta` | Delta Lake table format |
| `iceberg` | Apache Iceberg table format |

#### Supported Compressions

| Compression | Description |
| ----------- | ----------- |
| `snappy` | Snappy compression (fast) |
| `gzip` | Gzip compression |
| `zstd` | Zstandard compression |
| `none` | No compression |

#### Input Formats

| Format | Interpretation |
| ------ | -------------- |
| `parquet` | Parquet with default (snappy) compression |
| `delta:zstd` | Delta with zstd compression |
| `iceberg:zstd,partition:year,month` | Iceberg with partitioning |

#### Parsing Rules

1. First segment is always format, optionally with compression (`format:compression`)
2. Subsequent comma-separated segments are partition specifications
3. Partition columns can be specified as `partition:col1,col2` or directly as column names

#### Validation Rules

- Format must be one of: `parquet`, `delta`, `iceberg`
- Compression must be one of: `snappy`, `gzip`, `zstd`, `none`
- Returns `None` when input is empty (no conversion)

---

### ValidationConfig

Controls result validation behavior and checkpoints.

#### Attributes

| Name | Type | Default | Description |
| ---- | ---- | ------- | ----------- |
| `mode` | `str` | `"exact"` | Row count validation tolerance mode |
| `preflight` | `bool` | `False` | Validate before execution |
| `postgen` | `bool` | `False` | Validate after data generation |
| `postload` | `bool` | `False` | Validate after data loading |
| `check_platforms` | `bool` | `False` | Validate platform compatibility |

#### Validation Modes

| Mode | Description |
| ---- | ----------- |
| `exact` | Exact row count matching |
| `loose` | Allows +/- 50% tolerance |
| `range` | Min/max bounds validation |
| `disabled` | No validation performed |

#### Input Formats

| Format | Interpretation |
| ------ | -------------- |
| `exact` | Exact mode only |
| `loose` | Loose mode only |
| `disabled` | Validation disabled |
| `full` | All checkpoints enabled with exact mode |
| `postgen` | Post-generation checkpoint only |
| `preflight` | Pre-execution checkpoint only |
| `postload` | Post-load checkpoint only |
| `check-platforms` | Platform compatibility check only |

#### Validation Rules

- Mode must be one of: `exact`, `loose`, `range`, `disabled`
- Special values (`full`, `postgen`, `preflight`, `postload`, `check-platforms`) enable specific checkpoints

---

### ForceConfig

Controls forced regeneration and re-upload behavior.

#### Attributes

| Name | Type | Default | Description |
| ---- | ---- | ------- | ----------- |
| `datagen` | `bool` | `False` | Force data regeneration |
| `upload` | `bool` | `False` | Force data re-upload |

#### Computed Properties

| Property | Type | Description |
| -------- | ---- | ----------- |
| `any` | `bool` | True if any force option is enabled |

#### Input Formats

| Format | Interpretation |
| ------ | -------------- |
| `all` | Force both datagen and upload |
| `true` / `1` / `yes` | Force both datagen and upload |
| `datagen` | Force data regeneration only |
| `upload` | Force re-upload only |
| `datagen,upload` | Explicitly enable both |

#### Validation Rules

- Options must be one of: `datagen`, `upload`, `all`
- Multiple options can be comma-separated
- Boolean flag usage (without value) forces all

---

## Parameter Type Adapters

Each configuration type has a corresponding CLI parameter type adapter that integrates with the Click framework.

### Common Adapter Behavior

| Behavior | Description |
| -------- | ----------- |
| Passthrough | If value is already the target type, return as-is |
| Null handling | Return default configuration for null/missing values |
| Boolean handling | Handle flag usage (true boolean) where applicable |
| String parsing | Delegate to configuration type's parse method |
| Error propagation | Convert parse errors to CLI-appropriate errors |

### Provided Adapters

| Adapter | Target Type | CLI Name |
| ------- | ----------- | -------- |
| `CompressionParamType` | `CompressionConfig` | `compression` |
| `PlanConfigParamType` | `PlanCaptureConfig` | `plan-config` |
| `TableFormatParamType` | `TableFormatConfig` | `table-format` |
| `ValidationParamType` | `ValidationConfig` | `validation` |
| `ForceParamType` | `ForceConfig` | `force` |

### Singleton Instances

Pre-instantiated adapter instances for use in Click decorators:

| Instance | Type |
| -------- | ---- |
| `COMPRESSION` | `CompressionParamType` |
| `PLAN_CONFIG` | `PlanConfigParamType` |
| `TABLE_FORMAT` | `TableFormatParamType` |
| `VALIDATION` | `ValidationParamType` |
| `FORCE` | `ForceParamType` |

---

## Error Handling

All configuration parsers raise descriptive errors when input is invalid:

| Error Condition | Behavior |
| --------------- | -------- |
| Invalid type/mode | Error listing valid options |
| Out-of-range value | Error specifying valid range |
| Non-numeric value | Error indicating expected type |
| Unknown key | Error listing valid keys |

Errors are surfaced through the CLI framework's parameter error mechanism.

---

## Usage Patterns

### CLI Declaration

Configuration types are used with Click option decorators:

```python
@click.option("--compression", type=COMPRESSION, help="Compression settings")
@click.option("--validation", type=VALIDATION, help="Validation mode")
@click.option("--force", type=FORCE, is_flag=True, flag_value="all", help="Force regeneration")
```

### Consumer Access

Parsed configurations provide typed attribute access:

```python
def execute(compression: CompressionConfig, validation: ValidationConfig):
    if compression.enabled and compression.type == "zstd":
        # Apply zstd compression with specified level
        pass

    if validation.mode == "exact" and validation.postload:
        # Perform exact validation after load
        pass
```

---

## Design Principles

1. **Colon Syntax Consistency**: All composite parameters use colon as the primary delimiter between type and value
2. **Comma Separation**: Multiple options within a parameter are comma-separated
3. **Sensible Defaults**: Each configuration provides meaningful defaults when no value is specified
4. **Case Insensitivity**: Type names and option keys are normalized to lowercase
5. **Graceful Degradation**: Missing optional components use defaults rather than failing

---

## Extension Points

New composite parameters can be added by:

1. Defining a dataclass with a `parse(cls, value: str)` class method
2. Creating a corresponding Click `ParamType` subclass
3. Exporting a singleton instance for use in decorators
