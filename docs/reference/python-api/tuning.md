# Tuning Configuration API

```{tags} reference, python-api, tuning
```

Complete Python API reference for database tuning and optimization configuration.

## Overview

The tuning configuration API provides a comprehensive system for managing database table optimizations including partitioning, clustering, distribution, sorting, constraints, and platform-specific features. It supports serialization, validation, and platform compatibility checking.

**Key Features**:

- **Table-level tunings** - Partitioning, clustering, distribution, sorting
- **Schema constraints** - Primary keys, foreign keys, unique, check constraints
- **Platform-specific optimizations** - Z-ordering, auto-optimize, bloom filters
- **Validation** - Conflict detection and platform compatibility checks
- **Serialization** - JSON-based configuration persistence
- **Cross-platform support** - 9+ database platforms

## Quick Start

```python
from benchbox.core.tuning.interface import (
    UnifiedTuningConfiguration,
    TuningType
)

config = UnifiedTuningConfiguration()

config.disable_foreign_keys()

config.enable_platform_optimization(
    TuningType.Z_ORDERING,
    columns=["order_date", "customer_key"]
)

errors = config.validate_for_platform("databricks")
if errors:
    print(f"Validation errors: {errors}")
```

Disabling foreign keys speeds up data loading.

## API Reference

### TuningType Enum

Enumeration of supported database tuning types.

```python
class TuningType(Enum):
    PARTITIONING = "partitioning"
    CLUSTERING = "clustering"
    DISTRIBUTION = "distribution"
    SORTING = "sorting"

    PRIMARY_KEYS = "primary_keys"
    FOREIGN_KEYS = "foreign_keys"
    UNIQUE_CONSTRAINTS = "unique_constraints"
    CHECK_CONSTRAINTS = "check_constraints"

    Z_ORDERING = "z_ordering"
    AUTO_OPTIMIZE = "auto_optimize"
    AUTO_COMPACT = "auto_compact"
    BLOOM_FILTERS = "bloom_filters"
    MATERIALIZED_VIEWS = "materialized_views"
```

The values fall into three groups:

- `PARTITIONING`, `CLUSTERING`, `DISTRIBUTION` and `SORTING` are table-level performance tunings.
- `PRIMARY_KEYS`, `FOREIGN_KEYS`, `UNIQUE_CONSTRAINTS` and `CHECK_CONSTRAINTS` are schema constraint tunings.
- The rest are platform-specific optimizations: `Z_ORDERING` (Databricks Delta Lake), `AUTO_OPTIMIZE` and `AUTO_COMPACT` (Databricks), `BLOOM_FILTERS` (various platforms) and `MATERIALIZED_VIEWS` (query acceleration).

**Methods**:

- **from_string(value: str)**: Create TuningType from string
- **is_compatible_with_platform(platform: str)**: Check platform compatibility

**Platform Compatibility**:

```python
from benchbox.core.tuning.interface import TuningType

is_supported = TuningType.Z_ORDERING.is_compatible_with_platform("databricks")

is_supported = TuningType.Z_ORDERING.is_compatible_with_platform("duckdb")
```

The first call returns `True` because Databricks supports Z-ordering. The second returns `False` because DuckDB does not.

### TuningColumn Class

Represents a column used in table tuning configurations.

```python
@dataclass
class TuningColumn:
    name: str
    type: str
    order: int
```

`name` is the column name, `type` is the SQL data type (for example `'DATE'` or `'INTEGER'`), and `order` is the column's 1-based position in the tuning.

**Methods**:

- **to_dict()**: Convert to dictionary
- **from_dict(data)**: Create from dictionary

**Example**:

```python
from benchbox.core.tuning.interface import TuningColumn

col = TuningColumn(
    name="order_date",
    type="DATE",
    order=1
)

col_dict = col.to_dict()

col_restored = TuningColumn.from_dict(col_dict)
```

`to_dict()` returns `{'name': 'order_date', 'type': 'DATE', 'order': 1}`, which `from_dict` turns back into a `TuningColumn`.

### TableTuning Class

Represents the complete tuning configuration for a database table.

```python
@dataclass
class TableTuning:
    table_name: str
    partitioning: Optional[list[TuningColumn]] = None
    clustering: Optional[list[TuningColumn]] = None
    distribution: Optional[list[TuningColumn]] = None
    sorting: Optional[list[TuningColumn]] = None
```

**Methods**:

- **validate()**: Validate configuration for conflicts
- **has_any_tuning()**: Check if any tuning is configured
- **get_columns_by_type(tuning_type)**: Get columns for specific tuning type
- **get_all_columns()**: Get all column names used in tuning
- **to_dict()**: Convert to dictionary
- **from_dict(data)**: Create from dictionary

**Example**:

```python
from benchbox.core.tuning.interface import TableTuning, TuningColumn

lineitem_tuning = TableTuning(
    table_name="lineitem",
    partitioning=[
        TuningColumn(name="l_shipdate", type="DATE", order=1)
    ],
    sorting=[
        TuningColumn(name="l_orderkey", type="BIGINT", order=1),
        TuningColumn(name="l_linenumber", type="INTEGER", order=2)
    ]
)

errors = lineitem_tuning.validate()
if errors:
    print(f"Validation errors: {errors}")

all_cols = lineitem_tuning.get_all_columns()
```

`get_all_columns()` returns every column used in the tuning, here `{'l_shipdate', 'l_orderkey', 'l_linenumber'}`.

### BenchmarkTunings Class

Manages tuning configurations for all tables in a benchmark.

```python
@dataclass
class BenchmarkTunings:
    benchmark_name: str
    table_tunings: dict[str, TableTuning] = field(default_factory=dict)
    enable_primary_keys: bool = True
    enable_foreign_keys: bool = True
```

**Methods**:

- **add_table_tuning(table_tuning)**: Add table tuning configuration
- **update_table_tuning(table_tuning)**: Update existing table tuning
- **get_table_tuning(table_name)**: Get tuning for specific table
- **remove_table_tuning(table_name)**: Remove table tuning
- **get_table_names()**: Get list of all table names
- **disable_primary_keys()**: Disable PK constraints
- **disable_foreign_keys()**: Disable FK constraints
- **enable_all_constraints()**: Enable all constraints
- **disable_all_constraints()**: Disable all constraints
- **validate_all()**: Validate all table tunings
- **has_valid_tunings()**: Check if all tunings are valid
- **get_configuration_hash()**: Generate SHA-256 hash of configuration
- **to_dict()**: Convert to dictionary
- **from_dict(data)**: Create from dictionary

**Example**:

```python
from benchbox.core.tuning.interface import BenchmarkTunings, TableTuning, TuningColumn

tunings = BenchmarkTunings(benchmark_name="tpch")

orders_tuning = TableTuning(
    table_name="orders",
    partitioning=[TuningColumn("o_orderdate", "DATE", 1)],
    sorting=[TuningColumn("o_orderkey", "BIGINT", 1)]
)
tunings.add_table_tuning(orders_tuning)

tunings.disable_foreign_keys()

validation_results = tunings.validate_all()
for table, errors in validation_results.items():
    if errors:
        print(f"{table}: {errors}")

config_hash = tunings.get_configuration_hash()
print(f"Configuration hash: {config_hash[:16]}...")
```

### UnifiedTuningConfiguration Class

Unified configuration that consolidates all tuning options.

```python
@dataclass
class UnifiedTuningConfiguration:
    primary_keys: PrimaryKeyConfiguration
    foreign_keys: ForeignKeyConfiguration
    unique_constraints: UniqueConstraintConfiguration
    check_constraints: CheckConstraintConfiguration

    platform_optimizations: PlatformOptimizationConfiguration

    table_tunings: dict[str, TableTuning]
```

**Methods**:

- **enable_all_constraints()**: Enable all schema constraints
- **disable_all_constraints()**: Disable all schema constraints
- **enable_primary_keys()**: Enable primary key constraints
- **disable_primary_keys()**: Disable primary key constraints
- **enable_foreign_keys()**: Enable foreign key constraints
- **disable_foreign_keys()**: Disable foreign key constraints
- **enable_platform_optimization(optimization_type, \\*\\*kwargs)**: Enable platform optimization
- **disable_platform_optimization(optimization_type)**: Disable platform optimization
- **get_enabled_tuning_types()**: Get all enabled tuning types
- **validate_for_platform(platform)**: Validate against platform capabilities
- **to_dict()**: Convert to dictionary
- **from_dict(data)**: Create from dictionary
- **merge_with_legacy_config(benchmark_tunings)**: Merge with legacy config
- **to_legacy_config(benchmark_name)**: Convert to legacy format

**Example**:

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

config = UnifiedTuningConfiguration()

config.disable_foreign_keys()
config.primary_keys.enforce_uniqueness = True

config.enable_platform_optimization(
    TuningType.Z_ORDERING,
    columns=["order_date", "customer_key"]
)
config.enable_platform_optimization(TuningType.AUTO_OPTIMIZE)

errors = config.validate_for_platform("databricks")
if not errors:
    print("Configuration valid for Databricks")

enabled = config.get_enabled_tuning_types()
print(f"Enabled tunings: {[t.value for t in enabled]}")
```

### Constraint Configurations

#### PrimaryKeyConfiguration

```python
@dataclass
class PrimaryKeyConfiguration:
    enabled: bool = True
    enforce_uniqueness: bool = True
    nullable: bool = False
```

#### ForeignKeyConfiguration

```python
@dataclass
class ForeignKeyConfiguration:
    enabled: bool = True
    enforce_referential_integrity: bool = True
    on_delete_action: str = "RESTRICT"
    on_update_action: str = "RESTRICT"
```

`on_delete_action` accepts `RESTRICT`, `CASCADE`, `SET NULL` or `SET DEFAULT`.

#### UniqueConstraintConfiguration

```python
@dataclass
class UniqueConstraintConfiguration:
    enabled: bool = True
    ignore_nulls: bool = False
```

#### CheckConstraintConfiguration

```python
@dataclass
class CheckConstraintConfiguration:
    enabled: bool = True
    enforce_on_insert: bool = True
    enforce_on_update: bool = True
```

### Platform Optimization Configuration

```python
@dataclass
class PlatformOptimizationConfiguration:
    z_ordering_enabled: bool = False
    z_ordering_columns: list[str] = field(default_factory=list)
    auto_optimize_enabled: bool = False
    auto_compact_enabled: bool = False
    bloom_filters_enabled: bool = False
    bloom_filter_columns: list[str] = field(default_factory=list)
    materialized_views_enabled: bool = False
```

## Usage Examples

### Basic Tuning Configuration

```python
from benchbox.core.tuning.interface import (
    UnifiedTuningConfiguration,
    TuningType
)
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter

benchmark = TPCH(scale_factor=1.0)

config = UnifiedTuningConfiguration()

config.disable_foreign_keys()

schema_sql = benchmark.get_create_tables_sql(
    dialect="duckdb",
    tuning_config=config
)

adapter = DuckDBAdapter()
conn = adapter.create_connection()
conn.execute(schema_sql)
```

### Table-Specific Tuning

```python
from benchbox.core.tuning.interface import TableTuning, TuningColumn

lineitem_tuning = TableTuning(
    table_name="lineitem",
    partitioning=[
        TuningColumn("l_shipdate", "DATE", 1)
    ],
    sorting=[
        TuningColumn("l_orderkey", "BIGINT", 1),
        TuningColumn("l_linenumber", "INTEGER", 2)
    ]
)

orders_tuning = TableTuning(
    table_name="orders",
    partitioning=[
        TuningColumn("o_orderdate", "DATE", 1)
    ],
    sorting=[
        TuningColumn("o_orderkey", "BIGINT", 1)
    ]
)

config = UnifiedTuningConfiguration()
config.table_tunings["lineitem"] = lineitem_tuning
config.table_tunings["orders"] = orders_tuning

errors = lineitem_tuning.validate()
if errors:
    print(f"Lineitem tuning errors: {errors}")
```

### Databricks Delta Lake Optimization

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType
from benchbox.tpch import TPCH
from benchbox.platforms.databricks import DatabricksAdapter

benchmark = TPCH(scale_factor=10.0)

config = UnifiedTuningConfiguration()

config.enable_platform_optimization(
    TuningType.Z_ORDERING,
    columns=["l_shipdate", "l_orderkey"]
)

config.enable_platform_optimization(TuningType.AUTO_OPTIMIZE)
config.enable_platform_optimization(TuningType.AUTO_COMPACT)

config.enable_platform_optimization(
    TuningType.BLOOM_FILTERS,
    columns=["l_orderkey", "l_partkey"]
)

errors = config.validate_for_platform("databricks")
if errors:
    print(f"Configuration errors: {errors}")
else:
    print("Configuration valid for Databricks")

adapter = DatabricksAdapter(...)
schema_sql = benchmark.get_create_tables_sql(
    dialect="databricks",
    tuning_config=config
)
```

### Snowflake Clustering Configuration

```python
from benchbox.core.tuning.interface import TableTuning, TuningColumn
from benchbox.tpch import TPCH
from benchbox.platforms.snowflake import SnowflakeAdapter

benchmark = TPCH(scale_factor=10.0)

lineitem_tuning = TableTuning(
    table_name="lineitem",
    clustering=[
        TuningColumn("l_shipdate", "DATE", 1),
        TuningColumn("l_orderkey", "BIGINT", 2)
    ]
)

orders_tuning = TableTuning(
    table_name="orders",
    clustering=[
        TuningColumn("o_orderdate", "DATE", 1),
        TuningColumn("o_custkey", "BIGINT", 2)
    ]
)

config = UnifiedTuningConfiguration()
config.table_tunings["lineitem"] = lineitem_tuning
config.table_tunings["orders"] = orders_tuning

errors = config.validate_for_platform("snowflake")
if not errors:
    adapter = SnowflakeAdapter(...)
    schema_sql = benchmark.get_create_tables_sql(
        dialect="snowflake",
        tuning_config=config
    )
```

### Redshift Distribution and Sort Keys

```python
from benchbox.core.tuning.interface import TableTuning, TuningColumn
from benchbox.tpch import TPCH

lineitem_tuning = TableTuning(
    table_name="lineitem",
    distribution=[
        TuningColumn("l_orderkey", "BIGINT", 1)
    ],
    sorting=[
        TuningColumn("l_shipdate", "DATE", 1),
        TuningColumn("l_orderkey", "BIGINT", 2)
    ]
)

orders_tuning = TableTuning(
    table_name="orders",
    distribution=[
        TuningColumn("o_orderkey", "BIGINT", 1)
    ],
    sorting=[
        TuningColumn("o_orderdate", "DATE", 1)
    ]
)

config = UnifiedTuningConfiguration()
config.table_tunings["lineitem"] = lineitem_tuning
config.table_tunings["orders"] = orders_tuning

errors = config.validate_for_platform("redshift")
if not errors:
    benchmark = TPCH(scale_factor=10.0)
    schema_sql = benchmark.get_create_tables_sql(
        dialect="redshift",
        tuning_config=config
    )
```

### Constraint Management

```python
from benchbox.core.tuning.interface import (
    UnifiedTuningConfiguration,
    PrimaryKeyConfiguration,
    ForeignKeyConfiguration
)

config = UnifiedTuningConfiguration()

config.primary_keys = PrimaryKeyConfiguration(
    enabled=True,
    enforce_uniqueness=True,
    nullable=False
)

config.foreign_keys = ForeignKeyConfiguration(
    enabled=True,
    enforce_referential_integrity=True,
    on_delete_action="CASCADE",
    on_update_action="CASCADE"
)

config.disable_all_constraints()

print(f"Primary keys enabled: {config.primary_keys.enabled}")
print(f"Foreign keys enabled: {config.foreign_keys.enabled}")
```

`disable_all_constraints()` is the alternative to configuring each constraint when loading in bulk.

### Configuration Serialization

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType
import json

config = UnifiedTuningConfiguration()
config.disable_foreign_keys()
config.enable_platform_optimization(
    TuningType.Z_ORDERING,
    columns=["order_date", "customer_key"]
)

config_dict = config.to_dict()
config_json = json.dumps(config_dict, indent=2)

with open("tuning_config.json", "w") as f:
    f.write(config_json)

with open("tuning_config.json", "r") as f:
    loaded_dict = json.load(f)

restored_config = UnifiedTuningConfiguration.from_dict(loaded_dict)

assert restored_config.foreign_keys.enabled == config.foreign_keys.enabled
assert restored_config.platform_optimizations.z_ordering_enabled == config.platform_optimizations.z_ordering_enabled
```

### Platform Compatibility Validation

```python
from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

config = UnifiedTuningConfiguration()
config.enable_platform_optimization(TuningType.Z_ORDERING, columns=["date_col"])
config.enable_platform_optimization(TuningType.AUTO_OPTIMIZE)
config.enable_platform_optimization(TuningType.BLOOM_FILTERS, columns=["id_col"])

platforms = ["duckdb", "databricks", "snowflake", "bigquery", "redshift"]

print("Platform Compatibility:")
print("=" * 60)

for platform in platforms:
    errors = config.validate_for_platform(platform)

    if errors:
        print(f"\n{platform.upper()}:")
        print("  Status: ✗ NOT COMPATIBLE")
        print("  Errors:")
        for error in errors:
            print(f"    - {error}")
    else:
        print(f"\n{platform.upper()}:")
        print("  Status: ✓ COMPATIBLE")

        enabled = config.get_enabled_tuning_types()
        print(f"  Supported features: {', '.join(t.value for t in enabled)}")
```

## Best Practices

1. **Disable foreign keys for bulk loading**: Improves load performance significantly. Load the data after disabling them and re-enable them afterwards if needed

   ```python
   config = UnifiedTuningConfiguration()
   config.disable_foreign_keys()
   ```

2. **Validate before applying**: Always validate configuration for target platform

   ```python
   errors = config.validate_for_platform("databricks")
   if errors:
       print(f"Fix these issues before applying: {errors}")
       return
   ```

3. **Use platform-specific optimizations**: Take advantage of platform strengths, such as Z-ordering on Databricks for selective queries, clustering on Snowflake for large tables and distribution keys on Redshift for joins

   ```python
   config.enable_platform_optimization(
       TuningType.Z_ORDERING,
       columns=["date", "customer_id"]
   )

   ```

4. **Partition large tables by date**: Improves query performance and maintenance

   ```python
   tuning = TableTuning(
       table_name="fact_sales",
       partitioning=[TuningColumn("sale_date", "DATE", 1)]
   )
   ```

5. **Sort by frequently filtered columns**: Enables zone maps and skip scanning

   ```python
   tuning = TableTuning(
       table_name="lineitem",
       sorting=[
           TuningColumn("l_shipdate", "DATE", 1),
           TuningColumn("l_orderkey", "BIGINT", 2)
       ]
   )
   ```

## See Also

- {doc}`base` - Base benchmark interface
- {doc}`platforms/databricks` - Databricks platform adapter (Z-ordering)
- {doc}`platforms/snowflake` - Snowflake platform adapter (clustering)
- {doc}`platforms/redshift` - Redshift platform adapter (distribution, sort keys)
- {doc}`/usage/configuration` - Configuration guide
- {doc}`/advanced/performance` - Performance optimization guide

### External Resources

- [Databricks Delta Lake Optimization](https://docs.databricks.com/aws/en/optimizations)
- [Snowflake Clustering](https://docs.snowflake.com/en/user-guide/tables-clustering-keys)
- [Redshift Distribution Styles](https://docs.aws.amazon.com/redshift/latest/dg/c_choosing_dist_sort.html)
- [BigQuery Partitioning](https://docs.cloud.google.com/bigquery/docs/partitioned-tables)
