# Adapter Factory Specification

## Overview

The Adapter Factory provides a unified entry point for obtaining platform adapters, abstracting the difference between SQL and DataFrame execution modes. It implements mode resolution, platform normalization, and dependency validation to ensure seamless adapter instantiation regardless of execution paradigm.

## Design Philosophy

### Unified Entry Point

The factory centralizes adapter acquisition by:

1. **Normalizing platform names** - Handling naming conventions like the `-df` suffix for DataFrame mode
2. **Resolving execution modes** - Determining whether SQL or DataFrame execution applies
3. **Validating mode support** - Ensuring the platform supports the requested mode
4. **Routing to adapters** - Dispatching to the appropriate adapter factory

### Mode Priority Resolution

Execution mode is resolved through a priority chain:

1. **Explicit mode** - User-specified `sql` or `dataframe` takes highest priority
2. **Name-implied mode** - Platform names ending in `-df` imply DataFrame mode
3. **Platform default** - Falls back to the platform's registered default mode

---

## Component Specifications

### 1. Platform Name Normalization

#### Behavior

Normalizes platform name input and detects implied execution mode from naming conventions.

| Input Pattern | Base Name | DataFrame Implied |
|---------------|-----------|-------------------|
| `<platform>-df` | `<platform>` | Yes |
| `<platform>` | `<platform>` | No |

#### Requirements

- Platform names are case-insensitive
- The `-df` suffix is stripped when detected
- Returns both normalized name and mode-implied flag

---

### 2. Primary Adapter Acquisition

#### Signature

```
get_adapter(platform, mode?, **config) -> Adapter
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `platform` | string | Yes | Platform identifier (may include `-df` suffix) |
| `mode` | "sql" or "dataframe" or null | No | Explicit execution mode override |
| `config` | key-value pairs | No | Platform-specific configuration |

#### Return Value

Returns a platform adapter instance appropriate for the resolved execution mode:
- SQL mode: Returns a `PlatformAdapter` implementation
- DataFrame mode: Returns a DataFrame adapter implementation

#### Error Conditions

| Condition | Error Type | Description |
|-----------|------------|-------------|
| Unknown platform | ValueError | Platform not registered in registry |
| Unsupported mode | ValueError | Platform does not support requested mode |
| Missing dependencies | ImportError | Required libraries not installed |

#### Mode Resolution Algorithm

1. Normalize platform name, extract base name and implied mode
2. Query platform registry for capabilities
3. Resolve mode by priority: explicit > implied > default
4. Validate that platform supports resolved mode
5. Dispatch to appropriate adapter factory

---

### 3. SQL Adapter Factory (Internal)

#### Purpose

Retrieves SQL-mode adapters through the platform registry.

#### Behavior

- Delegates to the main platform adapter factory
- Resolves adapter class from platform registry
- Instantiates with provided configuration

---

### 4. DataFrame Adapter Factory (Internal)

#### Purpose

Retrieves DataFrame-mode adapters for supported platforms.

#### Supported Platforms

| Platform | Adapter | Availability Check | Installation Command |
|----------|---------|-------------------|---------------------|
| polars | PolarsDataFrameAdapter | POLARS_AVAILABLE | `uv add polars` |
| pandas | PandasDataFrameAdapter | PANDAS_AVAILABLE | `uv add pandas` |
| modin | ModinDataFrameAdapter | MODIN_AVAILABLE | `uv add modin[ray]` |
| cudf | CuDFDataFrameAdapter | CUDF_AVAILABLE | `pip install cudf-cu12` |
| dask | DaskDataFrameAdapter | DASK_AVAILABLE | `uv add dask[distributed]` |
| pyspark | PySparkDataFrameAdapter | PYSPARK_AVAILABLE | Extra: `pyspark` |
| datafusion | DataFusionDataFrameAdapter | DATAFUSION_DF_AVAILABLE | `uv add datafusion` |

#### Error Conditions

| Condition | Error Type | Description |
|-----------|------------|-------------|
| Unknown DataFrame platform | ValueError | Platform not in adapter mapping |
| Unavailable platform | ImportError | Dependencies not installed |

---

### 5. Mode Detection Utility

#### Signature

```
is_dataframe_mode(platform, mode?) -> boolean
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `platform` | string | Yes | Platform identifier |
| `mode` | string or null | No | Explicit mode if specified |

#### Behavior

Determines if the effective execution mode is DataFrame by:

1. Returning true if explicit mode is "dataframe"
2. Returning true if platform name has `-df` suffix
3. Consulting platform registry for default mode

---

### 6. Available Modes Query

#### Signature

```
get_available_modes(platform) -> list[string]
```

#### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `platform` | string | Yes | Platform identifier |

#### Return Value

List of supported execution modes for the platform:
- Empty list if platform unknown
- Contains "sql" if SQL mode supported
- Contains "dataframe" if DataFrame mode supported

---

## Integration Points

### With Platform Registry

The factory depends on the platform registry for:

- Platform capability information (supports_sql, supports_dataframe, default_mode)
- Platform name alias resolution
- Mode support validation

### With SQL Platform Adapters

For SQL mode, the factory delegates to the existing `get_platform_adapter()` function which:

- Resolves platform names to adapter classes
- Handles configuration mapping
- Instantiates SQL adapters

### With DataFrame Adapters

For DataFrame mode, the factory directly manages:

- Adapter class mapping per platform
- Dependency availability checking
- Adapter instantiation with configuration

---

## Error Handling

### ValueError Scenarios

1. **Unknown Platform**: Platform name not found in registry
   - Message includes the unrecognized platform name

2. **Unsupported Mode**: Platform does not support requested execution mode
   - Message includes platform name, requested mode, and list of supported modes

### ImportError Scenarios

1. **Missing Dependencies**: DataFrame platform dependencies not installed
   - Message includes platform name and installation command

---

## Usage Patterns

### Explicit SQL Mode

```
adapter = get_adapter("duckdb", mode="sql", database_path=":memory:")
```

### DataFrame via Suffix

```
adapter = get_adapter("polars-df")  # DataFrame mode implied
```

### Explicit DataFrame Override

```
adapter = get_adapter("datafusion", mode="dataframe")  # Override default
```

### Mode Detection for Branching

```
if is_dataframe_mode(platform, mode):
    # Execute DataFrame-style benchmark
else:
    # Execute SQL-style benchmark
```

### Capability Discovery

```
modes = get_available_modes("polars")  # ["sql", "dataframe"]
modes = get_available_modes("pandas")  # ["dataframe"]
modes = get_available_modes("duckdb")  # ["sql"]
```

---

## Configuration Passthrough

Configuration parameters are passed through to the underlying adapter without modification. Each adapter type defines its own configuration schema:

- SQL adapters receive connection parameters, tuning options
- DataFrame adapters receive parallelism, memory, and execution settings

The factory does not validate configuration; validation is the responsibility of the adapter.

---

## Thread Safety

The factory functions are stateless and thread-safe. They depend on:

- Platform registry (uses class-level caching, thread-safe for reads)
- Module-level imports (protected by Python's import lock)

Concurrent adapter acquisition for different platforms is safe. Concurrent configuration of the same adapter instance requires external synchronization.
