DataFrame Contexts and Tuning
==============================

Query implementations share table access and expression helpers through a context.
Pandas-family queries use string column access and Series operations; expression
queries use platform expression objects. See :doc:`dataframe-query` for query
metadata, execution and registry contracts, and :doc:`/platforms/dataframe` for
family architecture. These interfaces do not imply that every native DataFrame
implements every protocol operation, or that benchmark results are equivalent.

Contexts
--------

.. py:class:: benchbox.core.dataframe.context.DataFrameContext

   Runtime-checkable protocol for table access, expression construction and
   platform/family identity. ``get_table(name)``, ``list_tables()`` and
   ``table_exists(name)`` expose registered tables. ``col(name)`` and ``lit(value)``
   construct platform column references (strings in the Pandas family) and literal
   expressions. ``element()`` supplies a
   list-element expression where supported; Polars list evaluation uses
   ``element()`` rather than a named column reference inside ``eval()``.
   ``date_sub(column, days)`` and
   ``date_add(column, days)`` adjust date expressions; ``cast_date(column)`` and
   ``cast_string(column)`` request native date/string conversion. Query code can
   use these helpers without importing a native DataFrame library.

   ``window_rank``, ``window_row_number`` and ``window_dense_rank`` require
   ``order_by: list[tuple[str, bool]]`` and accept optional
   ``partition_by: list[str] | None = None``. The boolean is ascending order.
   Rank permits gaps after ties; dense rank has no gaps; row number assigns
   sequential positions. ``window_sum`` and ``window_avg`` accept a column,
   optional partitions and optional ordering: unordered operations aggregate a
   partition, while ordering requests cumulative results. ``window_count``
   additionally allows ``column=None`` for row counting. ``window_min`` and
   ``window_max`` accept a column and optional partitions. Native adapters
   determine concrete expression types and supported window behavior.

   ``union_all(*dataframes)`` concatenates rows including duplicates;
   ``rename_columns(df, mapping)`` maps old names to new names.
   ``scalar(df, column=None)`` expects a one-row result and selects the named
   column, or the first column when omitted. ``scalar_to_df(data)`` constructs
   one row from a dict of column names to scalar values, avoiding platform
   imports in query implementations. ``platform`` and ``family`` identify the
   adapter and its ``pandas`` or ``expression`` family.

.. py:class:: benchbox.core.dataframe.context.DataFrameContextImpl(platform: str, family: str)

   Abstract generic base with a fresh table registry. Identity strings are
   stored unchanged. ``register_table(name, df)`` lowercases the name and
   replaces any previous registration with that key. Table values are stored
   and returned by reference. Retrieval, membership and removal are
   case-insensitive; ``list_tables()`` returns sorted lowercase names.
   ``unregister_table(name)`` returns whether an entry was removed;
   ``clear_tables()`` removes all entries. Missing retrieval raises ``KeyError``
   and reports sorted available names.

   Expression, date/cast, window, union, rename and scalar methods are abstract
   extension points. Their existing implicit-``None`` method bodies carry no
   implementation guarantee. ``element()`` raises ``NotImplementedError`` by
   default. ``to_date(value)`` returns a date unchanged, extracts a datetime's
   date, or parses a string with ``%Y-%m-%d``; parsing errors propagate and other
   types raise ``TypeError``. ``days(n)`` returns ``timedelta(days=n)``.

.. py:function:: benchbox.core.dataframe.compat._to_list(values: Any) -> list

   Materialize an object exposing ``compute()`` first, then use ``tolist()`` if
   available, otherwise ``list(values)``. This supports Dask membership filters,
   whose right-hand operand must be a materialized collection. Conversion
   errors propagate; no SDK is imported by this helper.

Operation Protocols and Query Categories
----------------------------------------

.. py:class:: benchbox.core.dataframe.protocols.DataFrameOps

   Runtime-checkable generic structural protocol. ``select(*columns)`` projects
   columns; ``filter(condition)`` takes a boolean Series/string expression for
   the Pandas family or an expression object for the expression family.
   ``group_by(*columns)`` returns ``DataFrameGroupBy``. ``join(other, on=None,
   left_on=None, right_on=None, how=JoinType.INNER)`` supports shared or separate
   join keys. ``sort(*columns, ascending=True)`` accepts one boolean or an
   order sequence. ``with_column(name, expr)`` adds or replaces a column using
   a Series/scalar or expression. These operations return a chainable
   ``DataFrameOps`` type, as do ``distinct()`` and ``limit(n)``.

   ``collect()`` returns a native materialized result and may trigger lazy
   computation. ``count()`` returns row count; ``columns`` returns column names;
   ``shape`` is ``(rows, columns)``. Count and shape may compute lazy data.
   The protocol defines signatures and intended roles, without implementing
   native semantics or runtime value validation.

.. py:class:: benchbox.core.dataframe.protocols.DataFrameGroupBy

   Runtime-checkable generic grouped-operation protocol. ``agg(*aggregations,
   **named_aggregations)`` accommodates expression arguments, Pandas-style
   column/function mappings and named outputs. ``sum(*columns)`` and
   ``mean(*columns)`` target named columns, or numeric columns when omitted.
   ``count()`` counts group rows; ``min(*columns)``, ``max(*columns)`` and
   ``first(*columns)`` return the corresponding grouped values. All methods
   return the ``DataFrameOps`` protocol type.

.. py:class:: benchbox.core.dataframe.protocols.JoinType

   Values are ``inner``, ``left``, ``right``, ``outer``, ``cross``, ``semi`` and
   ``anti``. ``str(member)`` returns its value. ``from_string(value)`` lowercases
   input without stripping whitespace; an unknown value raises ``ValueError``.

.. py:class:: benchbox.core.dataframe.protocols.AggregateFunction

   Values are ``sum``, ``mean``, ``avg``, ``count``, ``min``, ``max``, ``first``,
   ``last``, ``std``, ``var``, ``median`` and ``count_distinct``. ``mean`` and
   ``avg`` are distinct enum members representing the same aggregation role;
   they are not Python enum aliases. String conversion and parsing follow
   ``JoinType`` rules.

.. py:class:: benchbox.core.dataframe.protocols.SortOrder

   Values ``asc`` and ``desc``; string conversion returns the value.
   ``ascending`` is true only for ``ASC``.

.. py:class:: benchbox.core.dataframe.query.QueryCategory

   Values are ``scan``, ``projection``, ``filter``, ``sort``, ``aggregate``,
   ``group_by``, ``join``, ``multi_join``, ``subquery``, ``window``, ``analytical``,
   ``tpch`` and ``tpcds``. These classify query workloads and benchmark families.
   ``str(member)`` returns the value.

Runtime Tuning Records
----------------------

Runtime tuning configures adapter execution and memory; physical write tuning
configures output layout. A configuration describes requested settings, rather
than proving their application by an adapter. The ``benchbox.core.dataframe``
package re-exports its query/context, capability, validation, loader, profiling,
maintenance and comparison APIs. Its ``tuning`` package re-exports the runtime,
write, profile/default, loader and validation APIs described here and in their
respective guides.

The following dataclasses are defined in
``benchbox.core.dataframe.tuning.interface``. Each ``to_dict()`` returns all
fields listed for that record. Each ``from_dict(data)`` reads those keys with
constructor defaults when absent, ignores unrelated keys, and invokes constructor
validation. The six runtime subconfigurations provide ``is_default()`` comparing their
listed defaults. Metadata has its separate behavior below. Type annotations do
not add general runtime type checking.

.. py:class:: benchbox.core.dataframe.tuning.interface.ParallelismConfiguration(thread_count: int | None = None, worker_count: int | None = None, threads_per_worker: int | None = None)

   Requested thread count, worker-process count and threads per worker.
   ``None`` leaves the setting to the platform. Each provided count must be at
   least 1 or construction raises ``ValueError``. DataFusion maps thread count
   to target partitions; Dask uses worker and per-worker thread settings.

.. py:class:: benchbox.core.dataframe.tuning.interface.MemoryConfiguration(memory_limit: str | None = None, chunk_size: int | None = None, spill_to_disk: bool = False, spill_directory: str | None = None, rechunk_after_filter: bool = True)

   Memory limit per worker, rows per streaming/batch chunk, spill request and
   directory, and Polars rechunk preference. A provided chunk size must be at
   least 1. Memory limits accept non-negative decimal digits with optional
   fractional part/whitespace followed by a case-insensitive ``B``, ``KB``,
   ``MB``, ``GB``, ``TB``, ``KiB``, ``MiB``, ``GiB`` or ``TiB`` suffix; unsupported
   format raises ``ValueError``. This validates syntax without measuring memory.

.. py:class:: benchbox.core.dataframe.tuning.interface.ExecutionConfiguration(streaming_mode: bool = False, engine_affinity: str | None = None, lazy_evaluation: bool = True, collect_timeout: int | None = None)

   Streaming/lazy requests and optional preferred engine. ``collect_timeout``
   is in seconds; a provided value must be at least 1. Engine affinity is stored
   without enum validation. Platform consumers decide whether settings apply.

.. py:class:: benchbox.core.dataframe.tuning.interface.DataTypeConfiguration(dtype_backend: str = "numpy_nullable", enable_string_cache: bool = False, auto_categorize_strings: bool = False, categorical_threshold: float = 0.5)

   Backend must be ``numpy``, ``numpy_nullable`` or ``pyarrow``. The categorical
   threshold must lie inclusively between 0 and 1; it represents the unique
   value/row ratio for automatic string categorization. Backend or threshold
   violations raise ``ValueError``. String-cache and automatic categorization
   requests are separate fields.

.. py:class:: benchbox.core.dataframe.tuning.interface.IOConfiguration(memory_pool: str = "default", memory_map: bool = False, pre_buffer: bool = True, row_group_size: int | None = None)

   Arrow allocator, mapped-read/prebuffer requests and rows per Parquet group.
   Pool must be ``default``, ``jemalloc``, ``mimalloc`` or ``system``; a provided
   group size must be at least 1. Invalid values raise ``ValueError``.

.. py:class:: benchbox.core.dataframe.tuning.interface.GPUConfiguration(enabled: bool = False, device_id: int = 0, spill_to_host: bool = True, pool_type: str = "default")

   GPU request, zero-based device, host-spill request and RMM pool selection.
   Device IDs must be non-negative; pools must be ``default``, ``managed``,
   ``pool`` or ``cuda``. Violations raise ``ValueError``. A valid record does not
   establish GPU availability.

.. py:class:: benchbox.core.dataframe.tuning.interface.TuningMetadata(version: str = "1.0", format: str = "dataframe_tuning", platform: str | None = None, description: str | None = None, created: str | None = None, generated_by: str | None = None)

   Version/format and optional target, description, creation-date text and
   generating-tool text. No date or version validation occurs. ``to_dict()``
   always includes version/format and includes optional fields only when truthy;
   ``from_dict()`` supplies defaults for missing keys. This record has no
   ``is_default()`` method.

.. py:class:: benchbox.core.dataframe.tuning.interface.DataFrameTuningConfiguration

   Fields ``parallelism``, ``memory``, ``execution``, ``data_types``, ``io``,
   ``gpu`` and ``write`` each receive fresh default records. ``metadata`` defaults
   to ``None``. ``to_dict()`` includes only non-default sections and truthy
   metadata under ``_metadata``. ``to_full_dict()`` includes all seven sections,
   and metadata when present. Write serialization remains sparse in either form.
   ``from_dict()`` builds each section from its mapping, defaults absent sections,
   and creates metadata only if the ``_metadata`` key is present; malformed
   section values and constructor validation errors propagate.

   ``is_default()`` ignores metadata. ``get_enabled_settings()`` returns runtime
   tuning enum values selected by the settings table: non-``None`` counts,
   memory limit/chunk size and engine affinity, enabled spill/streaming/string cache, disabled
   rechunk/lazy/prebuffer, non-default backend/allocator, mapped reads and
   non-``None`` row group size. GPU device is enabled when ``gpu.enabled``;
   host-spill and pool changes count only when GPU is enabled. It omits write
   options and does not enumerate every configurable field.
   ``get_summary()`` reports enum-value lists/count, default/GPU/streaming/write
   flags, selected thread/worker/memory fields and write type/name/compression
   summaries. Enum sets do not promise list order.

.. py:class:: benchbox.core.dataframe.tuning.types.DataFrameTuningType

   String-valued runtime-setting enum. ``str(member)`` returns its value;
   ``from_string(value)`` lowercases without stripping whitespace and raises
   ``ValueError`` for unknown values. Compatibility checks lowercase platform
   names and remove a trailing ``-df``. Unknown platforms support no types.
   ``get_platform_supported_types(platform)`` returns a copy of its set;
   ``is_compatible_with_platform(platform)`` tests membership. This policy
   matrix is separate from physical write capabilities.

   DataFusion supports ``thread_count`` and ``chunk_size``; Polars supports
   thread/chunk, rechunk, streaming/engine/lazy, string cache, memory pool and
   row group settings. Pandas supports chunk, dtype backend, string cache,
   memory pool, mapped reads, prebuffer and row groups. Dask supports workers,
   threads per worker, memory limit/chunk/spill/lazy/backend/mapping/prebuffer.
   cuDF supports string cache, GPU device/spill/pool and row groups. Arrow-backed
   allocators and categorical-string conversion are implementation paths, rather
   than promises of native APIs with identical names.

.. py:function:: benchbox.core.dataframe.tuning.types.get_all_platforms() -> list[str]

   Return matrix keys in insertion order: DataFusion, Polars, Pandas, Dask and
   cuDF, using lowercase slugs.

.. py:function:: benchbox.core.dataframe.tuning.profiles.create_profile_config(platform: str, profile: str) -> DataFrameTuningConfiguration

   Construct fresh default records; names are compared exactly without case or
   suffix normalization. DataFusion rejects profiles other than ``default`` or
   ``optimized``. Other platforms leave unknown profiles at defaults.
   ``optimized`` enables lazy evaluation, selects Polars ``in-memory`` affinity,
   DataFusion thread count 4, Dask 4 workers/2 threads, or cuDF GPU/pool mode.
   ``streaming`` enables streaming and chunk size 100,000, with Polars streaming
   affinity. ``memory-constrained`` enables streaming, chunk size 50,000 and
   disk spill; Dask adds ``2GB`` memory limit. ``gpu`` enables GPU and pool mode
   even on a non-cuDF platform; caller presentation handles mismatch warnings.
   These are requested presets, not executed performance measurements.

``DATAFRAME_PLATFORMS`` in ``tuning.profiles`` contains the five runtime-policy
slugs. ``DATAFRAME_CAPABILITY_ROWS`` supplies CLI display rows from core so
presentation does not maintain a second policy table. The rows are descriptive
metadata, distinct from the setting-compatibility and write-capability matrices.

Physical Write Configuration
-----------------------------

The following types are defined in ``benchbox.core.dataframe.tuning.write_config``.
Write options affect Parquet directory/file layout, sorting, grouping and encoding,
which can affect compression and later scans. Consumers determine which options
are applied; configuration validation alone is not proof of emitted layout.

.. py:class:: benchbox.core.dataframe.tuning.write_config.SortColumn(name: str, order: SortOrder = "asc")

   Name must be truthy and order exactly ``asc`` or ``desc``, otherwise construction
   raises ``ValueError``. ``to_dict()`` returns name/order; ``from_dict()`` requires
   name and defaults missing order to ``asc``. ``SortOrder`` is a literal type
   alias, separate from the operation-protocol enum above.

.. py:class:: benchbox.core.dataframe.tuning.write_config.PartitionColumn(name: str, strategy: PartitionStrategy = PartitionStrategy.VALUE)

   Truthy name is required. Strategy is not checked in direct construction;
   ``to_dict()`` reads its ``value``. ``from_dict()`` requires name, defaults
   strategy to ``value``, converts string values through ``PartitionStrategy``
   and passes non-string values through. Invalid strings raise ``ValueError``.

.. py:class:: benchbox.core.dataframe.tuning.write_config.PartitionStrategy

   Values are ``value`` (direct Hive-style value directories), ``date_year``,
   ``date_month`` and ``date_day`` (date extraction directory strategies).

.. py:class:: benchbox.core.dataframe.tuning.write_config.DataFrameWriteTuningType

   Values ``partition_by``, ``sort_by``, ``row_group_size``, ``repartition``,
   ``compression``, ``dictionary_encoding`` and ``data_page_version`` classify
   non-default write settings.

.. py:class:: benchbox.core.dataframe.tuning.write_config.DataFrameWriteConfiguration

   ``partition_by`` and ``sort_by`` are fresh empty lists of column records.
   ``row_group_size`` (rows), ``target_file_size_mb`` (target megabytes),
   ``repartition_count`` and ``compression_level`` default to ``None``.
   ``compression`` defaults to ``zstd``. ``dictionary_columns`` and
   ``skip_dictionary_columns`` each receive a fresh empty list;
   ``data_page_version`` defaults to ``None``. Row group size has no fixed
   one-million-row default in this record. Compression codecs are annotated
   as ``none``, ``snappy``, ``gzip``, ``zstd``, ``lz4`` or ``brotli``;
   data page versions are annotated as ``1.0`` or ``2.0``. These annotations
   do not independently validate arbitrary direct-constructor values.

   Provided row-group/file-size/repartition values must be at least 1.
   Compression levels are bounded for zstd 1–22, gzip 1–9, brotli 0–11 and
   lz4 0–16. Unsupported-level codecs log a warning; the field remains stored.
   Other violations raise ``ValueError``. Dictionary selection requests control
   encoding of low/high-cardinality columns; page versions describe Parquet
   serialization choices rather than an adapter support guarantee.

   ``to_dict()`` includes non-default fields, serializes column records and
   returns the original dictionary-column lists when included. ``from_dict()``
   accepts partition names as strings or mappings; sort entries may be strings,
   mappings or already constructed objects. It builds new partition/sort lists,
   passes supplied dictionary-column lists through and uses field defaults when
   keys are absent. Errors from malformed entries propagate. ``is_default()``
   checks the listed defaults. ``get_enabled_types()`` reports partition/sort,
   row groups, repartition, compression changes or explicit levels, dictionary
   selection and page-version changes; target file size has no corresponding
   enabled-type enum entry.

.. py:function:: benchbox.core.dataframe.tuning.write_config.get_platform_write_capabilities(platform: str) -> dict[str, bool]

   Lowercase the name without stripping a ``-df`` suffix. Known platforms return
   their shared matrix dict by reference. Unknown names return a fresh basic
   capability dict. All five known platforms support row groups, compression
   and dictionary encoding in this policy. Dask and PySpark support partitioning
   and repartitioning; Dask does not declare sorting, while the other four do.

.. py:function:: benchbox.core.dataframe.tuning.write_config.validate_write_config_for_platform(config: DataFrameWriteConfiguration, platform: str) -> list[str]

   Return warnings for requested unsupported partitioning, sorting or
   repartitioning. Do not mutate the configuration, reject it, or validate every
   write field. In particular, a capability warning does not itself ensure that
   a downstream writer ignores the option.
