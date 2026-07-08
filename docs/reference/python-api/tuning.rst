Tuning Configuration API
========================

.. tags:: reference, python-api, tuning

Complete Python API reference for database tuning and optimization configuration.

Overview
--------

The tuning configuration API provides a comprehensive system for managing database table optimizations including partitioning, clustering, distribution, sorting, constraints, and platform-specific features. It supports serialization, validation, and platform compatibility checking.

**Key Features**:

- **Table-level tunings** - Partitioning, clustering, distribution, sorting
- **Schema constraints** - Primary keys, foreign keys, unique, check constraints
- **Platform-specific optimizations** - Z-ordering, auto-optimize, bloom filters
- **Validation** - Conflict detection and platform compatibility checks
- **Serialization** - JSON-based configuration persistence
- **Cross-platform support** - 9+ database platforms

Quick Start
-----------

.. code-block:: python

    from benchbox.core.tuning.interface import (
        UnifiedTuningConfiguration,
        TuningType
    )

    # Create tuning configuration
    config = UnifiedTuningConfiguration()

    # Configure constraints
    config.disable_foreign_keys()  # For faster data loading

    # Enable platform optimizations
    config.enable_platform_optimization(
        TuningType.Z_ORDERING,
        columns=["order_date", "customer_key"]
    )

    # Validate for target platform
    errors = config.validate_for_platform("databricks")
    if errors:
        print(f"Validation errors: {errors}")

API Reference
-------------

TuningType Enum
~~~~~~~~~~~~~~~

Enumeration of supported database tuning types.

.. code-block:: python

    class TuningType(Enum):
        # Table-level performance tunings
        PARTITIONING = "partitioning"
        CLUSTERING = "clustering"
        DISTRIBUTION = "distribution"
        SORTING = "sorting"

        # Schema constraint tunings
        PRIMARY_KEYS = "primary_keys"
        FOREIGN_KEYS = "foreign_keys"
        UNIQUE_CONSTRAINTS = "unique_constraints"
        CHECK_CONSTRAINTS = "check_constraints"

        # Platform-specific optimizations
        Z_ORDERING = "z_ordering"              # Databricks Delta Lake
        AUTO_OPTIMIZE = "auto_optimize"        # Databricks
        AUTO_COMPACT = "auto_compact"          # Databricks
        BLOOM_FILTERS = "bloom_filters"        # Various platforms
        MATERIALIZED_VIEWS = "materialized_views"  # Query acceleration

**Methods**:

- **from_string(value: str)**: Create TuningType from string
- **is_compatible_with_platform(platform: str)**: Check platform compatibility

**Platform Compatibility**:

.. code-block:: python

    from benchbox.core.tuning.interface import TuningType

    # Check if Z-ordering is supported on Databricks
    is_supported = TuningType.Z_ORDERING.is_compatible_with_platform("databricks")
    # Returns: True

    # Check if Z-ordering is supported on DuckDB
    is_supported = TuningType.Z_ORDERING.is_compatible_with_platform("duckdb")
    # Returns: False

TuningColumn Class
~~~~~~~~~~~~~~~~~~

Represents a column used in table tuning configurations.

.. code-block:: python

    @dataclass
    class TuningColumn:
        name: str       # Column name
        type: str       # SQL data type (e.g., 'DATE', 'INTEGER')
        order: int      # Column order in tuning (1-based)

**Methods**:

- **to_dict()**: Convert to dictionary
- **from_dict(data)**: Create from dictionary

**Example**:

.. code-block:: python

    from benchbox.core.tuning.interface import TuningColumn

    # Create tuning column
    col = TuningColumn(
        name="order_date",
        type="DATE",
        order=1
    )

    # Serialize
    col_dict = col.to_dict()
    # {'name': 'order_date', 'type': 'DATE', 'order': 1}

    # Deserialize
    col_restored = TuningColumn.from_dict(col_dict)

TableTuning Class
~~~~~~~~~~~~~~~~~

Represents the complete tuning configuration for a database table.

.. code-block:: python

    @dataclass
    class TableTuning:
        table_name: str
        partitioning: Optional[list[TuningColumn]] = None
        clustering: Optional[list[TuningColumn]] = None
        distribution: Optional[list[TuningColumn]] = None
        sorting: Optional[list[TuningColumn]] = None

**Methods**:

- **validate()**: Validate configuration for conflicts
- **has_any_tuning()**: Check if any tuning is configured
- **get_columns_by_type(tuning_type)**: Get columns for specific tuning type
- **get_all_columns()**: Get all column names used in tuning
- **to_dict()**: Convert to dictionary
- **from_dict(data)**: Create from dictionary

**Example**:

.. code-block:: python

    from benchbox.core.tuning.interface import TableTuning, TuningColumn

    # Create table tuning
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

    # Validate
    errors = lineitem_tuning.validate()
    if errors:
        print(f"Validation errors: {errors}")

    # Get all columns used in tuning
    all_cols = lineitem_tuning.get_all_columns()
    # {'l_shipdate', 'l_orderkey', 'l_linenumber'}

BenchmarkTunings Class
~~~~~~~~~~~~~~~~~~~~~~

Manages tuning configurations for all tables in a benchmark.

.. code-block:: python

    @dataclass
    class BenchmarkTunings:
        benchmark_name: str
        table_tunings: dict[str, TableTuning] = field(default_factory=dict)
        enable_primary_keys: bool = True
        enable_foreign_keys: bool = True

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

.. code-block:: python

    from benchbox.core.tuning.interface import BenchmarkTunings, TableTuning, TuningColumn

    # Create benchmark tunings
    tunings = BenchmarkTunings(benchmark_name="tpch")

    # Add table tuning
    orders_tuning = TableTuning(
        table_name="orders",
        partitioning=[TuningColumn("o_orderdate", "DATE", 1)],
        sorting=[TuningColumn("o_orderkey", "BIGINT", 1)]
    )
    tunings.add_table_tuning(orders_tuning)

    # Disable foreign keys for faster loading
    tunings.disable_foreign_keys()

    # Validate all tunings
    validation_results = tunings.validate_all()
    for table, errors in validation_results.items():
        if errors:
            print(f"{table}: {errors}")

    # Get configuration hash
    config_hash = tunings.get_configuration_hash()
    print(f"Configuration hash: {config_hash[:16]}...")

UnifiedTuningConfiguration Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Unified configuration that consolidates all tuning options.

.. code-block:: python

    @dataclass
    class UnifiedTuningConfiguration:
        # Schema constraints
        primary_keys: PrimaryKeyConfiguration
        foreign_keys: ForeignKeyConfiguration
        unique_constraints: UniqueConstraintConfiguration
        check_constraints: CheckConstraintConfiguration

        # Platform-specific optimizations
        platform_optimizations: PlatformOptimizationConfiguration

        # Legacy table tunings
        table_tunings: dict[str, TableTuning]

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

.. code-block:: python

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

    # Create unified configuration
    config = UnifiedTuningConfiguration()

    # Configure constraints
    config.disable_foreign_keys()  # Faster data loading
    config.primary_keys.enforce_uniqueness = True

    # Enable Databricks optimizations
    config.enable_platform_optimization(
        TuningType.Z_ORDERING,
        columns=["order_date", "customer_key"]
    )
    config.enable_platform_optimization(TuningType.AUTO_OPTIMIZE)

    # Validate for target platform
    errors = config.validate_for_platform("databricks")
    if not errors:
        print("Configuration valid for Databricks")

    # Get enabled tuning types
    enabled = config.get_enabled_tuning_types()
    print(f"Enabled tunings: {[t.value for t in enabled]}")

Constraint Configurations
~~~~~~~~~~~~~~~~~~~~~~~~~

PrimaryKeyConfiguration
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    @dataclass
    class PrimaryKeyConfiguration:
        enabled: bool = True
        enforce_uniqueness: bool = True
        nullable: bool = False

ForeignKeyConfiguration
^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    @dataclass
    class ForeignKeyConfiguration:
        enabled: bool = True
        enforce_referential_integrity: bool = True
        on_delete_action: str = "RESTRICT"  # RESTRICT, CASCADE, SET NULL, SET DEFAULT
        on_update_action: str = "RESTRICT"

UniqueConstraintConfiguration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    @dataclass
    class UniqueConstraintConfiguration:
        enabled: bool = True
        ignore_nulls: bool = False

CheckConstraintConfiguration
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: python

    @dataclass
    class CheckConstraintConfiguration:
        enabled: bool = True
        enforce_on_insert: bool = True
        enforce_on_update: bool = True

Platform Optimization Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    @dataclass
    class PlatformOptimizationConfiguration:
        z_ordering_enabled: bool = False
        z_ordering_columns: list[str] = field(default_factory=list)
        auto_optimize_enabled: bool = False
        auto_compact_enabled: bool = False
        bloom_filters_enabled: bool = False
        bloom_filter_columns: list[str] = field(default_factory=list)
        materialized_views_enabled: bool = False

Usage Examples
--------------

Basic Tuning Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import (
        UnifiedTuningConfiguration,
        TuningType
    )
    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark
    benchmark = TPCH(scale_factor=1.0)

    # Create tuning configuration
    config = UnifiedTuningConfiguration()

    # Disable foreign keys for faster data loading
    config.disable_foreign_keys()

    # Generate schema SQL with tuning
    schema_sql = benchmark.get_create_tables_sql(
        dialect="duckdb",
        tuning_config=config
    )

    # Load data with optimized schema
    adapter = DuckDBAdapter()
    conn = adapter.create_connection()
    conn.execute(schema_sql)

Table-Specific Tuning
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import TableTuning, TuningColumn

    # Configure lineitem table tuning
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

    # Configure orders table tuning
    orders_tuning = TableTuning(
        table_name="orders",
        partitioning=[
            TuningColumn("o_orderdate", "DATE", 1)
        ],
        sorting=[
            TuningColumn("o_orderkey", "BIGINT", 1)
        ]
    )

    # Add to unified configuration
    config = UnifiedTuningConfiguration()
    config.table_tunings["lineitem"] = lineitem_tuning
    config.table_tunings["orders"] = orders_tuning

    # Validate configuration
    errors = lineitem_tuning.validate()
    if errors:
        print(f"Lineitem tuning errors: {errors}")

Databricks Delta Lake Optimization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType
    from benchbox.tpch import TPCH
    from benchbox.platforms.databricks import DatabricksAdapter

    # Create benchmark
    benchmark = TPCH(scale_factor=10.0)

    # Create Databricks-optimized configuration
    config = UnifiedTuningConfiguration()

    # Enable Z-ordering for fact tables
    config.enable_platform_optimization(
        TuningType.Z_ORDERING,
        columns=["l_shipdate", "l_orderkey"]
    )

    # Enable auto-optimize and auto-compact
    config.enable_platform_optimization(TuningType.AUTO_OPTIMIZE)
    config.enable_platform_optimization(TuningType.AUTO_COMPACT)

    # Enable bloom filters for selective columns
    config.enable_platform_optimization(
        TuningType.BLOOM_FILTERS,
        columns=["l_orderkey", "l_partkey"]
    )

    # Validate for Databricks
    errors = config.validate_for_platform("databricks")
    if errors:
        print(f"Configuration errors: {errors}")
    else:
        print("Configuration valid for Databricks")

    # Apply configuration
    adapter = DatabricksAdapter(...)
    schema_sql = benchmark.get_create_tables_sql(
        dialect="databricks",
        tuning_config=config
    )

Snowflake Clustering Configuration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import TableTuning, TuningColumn
    from benchbox.tpch import TPCH
    from benchbox.platforms.snowflake import SnowflakeAdapter

    # Create benchmark
    benchmark = TPCH(scale_factor=10.0)

    # Configure clustering for large tables
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

    # Create unified configuration
    config = UnifiedTuningConfiguration()
    config.table_tunings["lineitem"] = lineitem_tuning
    config.table_tunings["orders"] = orders_tuning

    # Validate for Snowflake
    errors = config.validate_for_platform("snowflake")
    if not errors:
        adapter = SnowflakeAdapter(...)
        schema_sql = benchmark.get_create_tables_sql(
            dialect="snowflake",
            tuning_config=config
        )

Redshift Distribution and Sort Keys
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import TableTuning, TuningColumn
    from benchbox.tpch import TPCH

    # Configure Redshift-specific tuning
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

    # Create configuration
    config = UnifiedTuningConfiguration()
    config.table_tunings["lineitem"] = lineitem_tuning
    config.table_tunings["orders"] = orders_tuning

    # Validate for Redshift
    errors = config.validate_for_platform("redshift")
    if not errors:
        benchmark = TPCH(scale_factor=10.0)
        schema_sql = benchmark.get_create_tables_sql(
            dialect="redshift",
            tuning_config=config
        )

Constraint Management
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import (
        UnifiedTuningConfiguration,
        PrimaryKeyConfiguration,
        ForeignKeyConfiguration
    )

    # Create configuration
    config = UnifiedTuningConfiguration()

    # Configure primary keys
    config.primary_keys = PrimaryKeyConfiguration(
        enabled=True,
        enforce_uniqueness=True,
        nullable=False
    )

    # Configure foreign keys with CASCADE
    config.foreign_keys = ForeignKeyConfiguration(
        enabled=True,
        enforce_referential_integrity=True,
        on_delete_action="CASCADE",
        on_update_action="CASCADE"
    )

    # Or disable all constraints for bulk loading
    config.disable_all_constraints()

    print(f"Primary keys enabled: {config.primary_keys.enabled}")
    print(f"Foreign keys enabled: {config.foreign_keys.enabled}")

Configuration Serialization
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType
    import json

    # Create and configure
    config = UnifiedTuningConfiguration()
    config.disable_foreign_keys()
    config.enable_platform_optimization(
        TuningType.Z_ORDERING,
        columns=["order_date", "customer_key"]
    )

    # Serialize to JSON
    config_dict = config.to_dict()
    config_json = json.dumps(config_dict, indent=2)

    # Save to file
    with open("tuning_config.json", "w") as f:
        f.write(config_json)

    # Load from file
    with open("tuning_config.json", "r") as f:
        loaded_dict = json.load(f)

    # Deserialize
    restored_config = UnifiedTuningConfiguration.from_dict(loaded_dict)

    # Verify
    assert restored_config.foreign_keys.enabled == config.foreign_keys.enabled
    assert restored_config.platform_optimizations.z_ordering_enabled == config.platform_optimizations.z_ordering_enabled

Platform Compatibility Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.core.tuning.interface import UnifiedTuningConfiguration, TuningType

    # Create configuration with various optimizations
    config = UnifiedTuningConfiguration()
    config.enable_platform_optimization(TuningType.Z_ORDERING, columns=["date_col"])
    config.enable_platform_optimization(TuningType.AUTO_OPTIMIZE)
    config.enable_platform_optimization(TuningType.BLOOM_FILTERS, columns=["id_col"])

    # Validate for different platforms
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

Best Practices
--------------

1. **Disable foreign keys for bulk loading**: Improves load performance significantly

   .. code-block:: python

       config = UnifiedTuningConfiguration()
       config.disable_foreign_keys()
       # Load data...
       # Re-enable after loading if needed

2. **Validate before applying**: Always validate configuration for target platform

   .. code-block:: python

       errors = config.validate_for_platform("databricks")
       if errors:
           print(f"Fix these issues before applying: {errors}")
           return

3. **Use platform-specific optimizations**: Take advantage of platform strengths

   .. code-block:: python

       # Databricks: Z-ordering for selective queries
       config.enable_platform_optimization(
           TuningType.Z_ORDERING,
           columns=["date", "customer_id"]
       )

       # Snowflake: Clustering for large tables
       # Redshift: Distribution keys for joins

4. **Partition large tables by date**: Improves query performance and maintenance

   .. code-block:: python

       tuning = TableTuning(
           table_name="fact_sales",
           partitioning=[TuningColumn("sale_date", "DATE", 1)]
       )

5. **Sort by frequently filtered columns**: Enables zone maps and skip scanning

   .. code-block:: python

       tuning = TableTuning(
           table_name="lineitem",
           sorting=[
               TuningColumn("l_shipdate", "DATE", 1),
               TuningColumn("l_orderkey", "BIGINT", 2)
           ]
       )

See Also
--------

- :doc:`base` - Base benchmark interface
- :doc:`platforms/databricks` - Databricks platform adapter (Z-ordering)
- :doc:`platforms/snowflake` - Snowflake platform adapter (clustering)
- :doc:`platforms/redshift` - Redshift platform adapter (distribution, sort keys)
- :doc:`/usage/configuration` - Configuration guide
- :doc:`/advanced/performance` - Performance optimization guide

External Resources
~~~~~~~~~~~~~~~~~~

- `Databricks Delta Lake Optimization <https://docs.databricks.com/aws/en/optimizations>`_
- `Snowflake Clustering <https://docs.snowflake.com/en/user-guide/tables-clustering-keys>`_
- `Redshift Distribution Styles <https://docs.aws.amazon.com/redshift/latest/dg/c_choosing_dist_sort.html>`_
- `BigQuery Partitioning <https://docs.cloud.google.com/bigquery/docs/partitioned-tables>`_
