DataFrame Query Registries
==========================

DataFrame benchmark modules store callable implementations and query metadata in
shared registries. Registration metadata is runtime data: descriptions,
category codes, SQL equivalents, expected counts and platform exclusions remain
part of the query surface rather than source documentation.

.. py:class:: benchbox.core.dataframe.query.DataFrameQuery(query_id: str, query_name: str, description: str, categories: list[QueryCategory] = ..., pandas_impl: Callable[[DataFrameContext], Any] | None = None, expression_impl: Callable[[DataFrameContext], Any] | None = None, sql_equivalent: str | None = None, expected_row_count: int | None = None, scale_factor_dependent: bool = False, timeout_seconds: float | None = None, skip_platforms: list[str] = ...)

   Mutable dataclass. Ellipses in the signature denote fresh-list factories:
   ``categories`` and ``skip_platforms`` each get a fresh empty list. ``pandas_impl``, ``expression_impl``, ``sql_equivalent``,
   ``expected_row_count`` and ``timeout_seconds`` default to ``None``;
   ``scale_factor_dependent`` defaults to ``False``. Timeout metadata is in
   seconds. Construction rejects a false query ID, false query name, or absence
   of both implementations with ``ValueError``. Other field values are not
   comprehensively validated.

   ``has_pandas_impl()``, ``has_expression_impl()`` and ``has_sql_equivalent()``
   test whether their corresponding fields are non-``None``.
   ``in_category(category)`` checks membership in ``categories``.
   ``get_impl_for_family(family)`` accepts case-insensitive ``pandas`` or
   ``expression``, returns the callable or ``None``, and raises ``ValueError``
   for another family name.

   ``execute(ctx, family)`` calls the selected implementation with ``ctx`` and
   returns its result unchanged. A missing implementation raises ``ValueError``;
   implementation exceptions propagate. This method does not enforce expected
   row counts, timeout metadata or platform exclusions.

   ``supports_platform(platform)`` first rejects a case-insensitive match in
   ``skip_platforms``. Pandas, cuDF, Vaex and Dask require ``pandas_impl``; Polars,
   PySpark, DataFusion and Spark require ``expression_impl``. Unrecognized
   platform names return ``False``.

   ``to_dict()`` returns query ID/name/description, category values,
   implementation-presence flags, SQL equivalent, expected row count,
   scale-factor dependence, timeout and platform exclusions. Callables are not
   serialized. The returned ``skip_platforms`` value is the original list.

.. py:class:: benchbox.core.dataframe.query.QueryRegistry(benchmark: str, loader: Callable[[], Iterable[DataFrameQuery]] | None = None)

   Store queries by their exact ID string. ``get(query_id)`` returns the stored
   query or ``None``; ``get_or_raise(query_id)`` raises ``KeyError`` when absent.
   ``get_all_queries()`` and ``get_query_ids()`` sort lexicographically by query
   ID; they do not interpret numeric portions of an ID. Queries are returned
   by reference, rather than copied. Iteration yields sorted IDs; membership
   and length consult the registry contents.

   ``register(query)`` rejects a duplicate ID with ``ValueError``.
   ``register_many(queries)`` registers in input order and can leave earlier
   items registered when a later item fails. These operations trigger any
   configured lazy loader before adding the supplied queries.

   ``get_queries_by_category(category)`` uses category membership;
   ``get_queries_for_platform(platform)`` uses ``supports_platform``.
   ``get_queries_for_family(family)`` selects non-``None`` implementations for
   case-insensitive ``pandas`` or ``expression`` and raises ``ValueError`` for
   another family name. ``list_queries(family=None, category=None)`` applies
   both optional filters while preserving sorted query order.

   ``set_loader(loader)`` is allowed only before the registry is loaded or
   contains queries; otherwise it raises ``RuntimeError``. With a loader,
   lookups and other content-dependent methods initialize it under a lock.
   Successful initialization runs once. Loader and duplicate-registration
   errors propagate; partial registrations are not rolled back, and a failed
   load does not set the loaded flag.

   ``load_info()`` returns lazy-load statistics. A registry without a loader
   does not accumulate load hits/misses, even when it contains manual entries.

.. py:class:: benchbox.core.dataframe.query.QueryRegistryLoadInfo

   Named tuple with integer ``hits``, ``misses``, ``maxsize`` and ``currsize``.
   Hits count checks after successful lazy loading; misses count load attempts.
   ``maxsize`` is 1, and ``currsize`` is 1 only after a successful lazy load.

Benchmark Registry Helpers
--------------------------

The ``registry`` modules under ``benchbox.core.<benchmark>.dataframe_queries``
for AMPLab, ClickBench, CoffeeShop, DataVault, H2Odb, NYC Taxi, SSB, TPC-DS,
TPC-H Skew and TSBS DevOps expose ``get_<benchmark>_query(query_id)``,
``list_<benchmark>_queries(family=None, category=None)`` and
``register_query(query)``. Their names use the module spelling, such as
``get_tsbs_devops_query``. They delegate to the shared registry: retrieval can
return ``None``, filters and order follow the contract above, and duplicate
registration raises ``ValueError``. Importing their package installs the
benchmark's registrations or loader. TPC-DS uses
``configure_query_loader(loader)`` to install its generated-metadata loader;
loader replacement follows ``set_loader`` restrictions.

TPC-Havoc uses eager variant registration. Its
``get_dataframe_queries()`` returns the shared registry object,
``list_query_ids()`` returns sorted variant IDs, and ``get_query(query_id)``
raises ``KeyError`` for an unknown exact ID. IDs use ``Q<query>v<variant>``.
The registry imports the 22 query modules and registers their variant objects;
this is not a live SQL-equivalence certification.

TPC-Havoc Variant Factories
---------------------------

.. py:function:: benchbox.core.tpchavoc.dataframe_queries.loader.load_variant_specs(module_file: str, namespace: dict[str, Any]) -> tuple[list[tuple[VariantImpl, VariantImpl]], list[str]]

   Read UTF-8 YAML beside ``module_file`` using its path with suffix ``.yaml``.
   For each entry in ``variants``, resolve ``expression_impl`` and
   ``pandas_impl`` names from ``namespace`` and collect ``description`` in the
   same order. File, YAML, missing-key and namespace errors propagate; empty
   input lacks the required ``variants`` key.

.. py:function:: benchbox.core.tpchavoc.dataframe_queries.loader.build_variants(query_number: int, impl_pairs: Sequence[tuple[VariantImpl, VariantImpl]], descriptions: Sequence[str], categories: Sequence[QueryCategory], *, expected_row_count: int | None = None, scale_factor_dependent: bool = False, timeout_seconds: float | None = None, skip_platforms: Sequence[str] | None = None) -> list[DataFrameQuery]

   Enumerate implementation pairs from 1, forming ``Q<number>v<variant>`` IDs
   and the corresponding query names. Use the description at the same index;
   insufficient descriptions raise ``IndexError``. Copy categories into each
   object, and copy a truthy platform sequence into a new list; otherwise use
   an empty list. Forward row-count, scale-dependence and timeout metadata
   unchanged. The caller supplies canonical metadata; this factory does not
   validate a query-number range, execute queries or certify equivalence.

.. py:function:: benchbox.core.tpchavoc.dataframe_queries.loader.build_yaml_variants(module_file: str, namespace: dict[str, Any], query_number: int, categories: Sequence[QueryCategory]) -> list[DataFrameQuery]

   Load pairs/descriptions and delegate to ``build_variants`` with its metadata
   defaults. File, resolution and construction errors propagate.

.. py:function:: benchbox.core.tpchavoc.dataframe_queries._delegating_variants.make_variant_delegate(impl: VariantImpl, *, name: str, module: str) -> VariantImpl

   Return a wrapper that calls ``impl(ctx)`` and returns its value unchanged.
   Set the wrapper's ``__name__`` and ``__qualname__`` to ``name`` and its
   ``__module__`` to ``module``. Exceptions propagate. This does not transform
   results or assign a runtime docstring.

CSV and Schema Loading Helpers
------------------------------

.. py:function:: benchbox.core.dataframe.csv_dialect.dialect_preserves_empty_strings(null_marker: str | None) -> bool

   Return ``null_marker != ""``. An empty marker maps empty CSV fields to NULL;
   ``None`` disables that conversion, and a non-empty sentinel converts only
   that sentinel. DataFrame readers can restore empty text fields to match the
   SQL dialect when this predicate is true. The helper lives in core so loading
   code can share this policy without importing a platform adapter.

.. py:function:: benchbox.core.dataframe.schema_utils.iter_schema_columns(table_schema: Any) -> list[Any]

   Normalize a dict's ``columns`` mapping into column dicts in mapping order,
   copying dict specifications and filling a missing ``name`` from the key.
   Non-dict specifications become ``{"type": spec}`` with that name. A list or
   tuple is copied to a list; unsupported dict column containers return an
   empty list. For object schemas, copy the ``columns`` attribute to a list,
   or return an empty list when it is absent or ``None``.

.. py:function:: benchbox.core.dataframe.schema_utils.column_name(column: Any) -> str | None

   Read ``name`` from a dict or object, or parse the first identifier of a DDL
   string. Truthy names become strings; absent or false-valued names return
   ``None``. DDL identifiers support double quotes, backticks and brackets,
   including doubled closing delimiters. Delimiters are removed because
   DataFrame column lookup uses the logical SQL name. An unterminated quoted
   identifier returns its remaining contents as the name and has no parsed type.

.. py:function:: benchbox.core.dataframe.schema_utils.column_sql_type(column: Any, default: str = "VARCHAR") -> str

   For DDL strings, preserve parenthesized precision/scale and supported
   multi-word types: ``DOUBLE PRECISION``, ``CHARACTER VARYING``, ``BIT VARYING``
   and time/timestamp zone modifiers. Stop before a column constraint or an
   unsupported continuation. An unbalanced parenthesis preserves the remaining
   text; this helper does not validate DDL syntax. Missing types use ``default``.

   Dicts use truthy ``type`` or ``data_type``. Objects try ``get_sql_type`` and
   ``sql_type`` (calling callable attributes), then ``data_type``. Return the
   first string candidate, or a candidate's string ``value`` attribute;
   otherwise return ``default``. Errors from these attributes or calls propagate.

.. py:function:: benchbox.core.dataframe.schema_utils.extract_schema_columns(schema: Any) -> dict[str, list[dict[str, str]]]

   Non-dicts return an empty dict. Normalize each table with the helpers above,
   omit unnamed columns and tables with no retained columns, and store table
   names as lowercase strings. Column order follows the input. Lowercase name
   collisions overwrite an earlier table entry.

.. py:function:: benchbox.core.dataframe.schema_utils.get_benchmark_schema_columns(benchmark: Any) -> dict[str, list[dict[str, str]]]

   Normalize ``benchmark.get_schema()``. Return an empty dict when the method
   is absent or when retrieval or normalization raises an exception.

Benchmark Query Resolution
---------------------------

.. py:function:: benchbox.core.dataframe.query_resolution.build_dataframe_query_filter(query_subset: Any) -> set[str] | None

   False-valued input means no filter and returns ``None``. Otherwise strip and
   uppercase each item's string representation, adding both its ``Q``-prefixed
   and unprefixed form. ``build_dataframe_query_filter_from_config(config)``
   applies this rule to the optional ``queries`` attribute.

.. py:function:: benchbox.core.dataframe.query_resolution.benchmark_defines_dataframe_hook(benchmark: Any | None, hook_name: str) -> bool

   Recognize a callable defined directly on the instance or its class, or an
   already configured mock child with a return value, side effect or wrapped
   callable. Inherited methods and unconfigured mock children do not suffice.
   ``benchmark_provides_dataframe_queries(benchmark)`` checks the
   ``get_dataframe_queries`` hook with this rule.

.. py:function:: benchbox.core.dataframe.query_resolution.get_dataframe_queries_for_benchmark(benchmark_config: Any, benchmark_instance: Any | None, stream_id: int | None = None) -> list[Any]

   Normalize the configuration's benchmark name. A missing ``stream_id`` uses
   its configured value, defaulting to zero. TPC-H, TPC-DS and ClickBench use
   their named resolvers before an instance hook is considered. Other benchmarks
   accept an explicit provider's list unchanged or its ``get_all_queries()``
   result. Unsupported containers log a warning and fall back to the registry.

.. py:function:: benchbox.core.dataframe.query_resolution.registry_dataframe_queries(benchmark_id: str) -> list[Any]

   Import ``benchbox.core.<benchmark_id>.dataframe_queries`` and find distinct
   ``QueryRegistry`` objects by identity. Aliases to one object are allowed;
   multiple distinct registries raise ``RuntimeError``. No registry, or a
   missing target module or parent package, yields an empty list. A missing
   dependency within an existing module propagates. Return the registry's
   sorted query list, triggering its lazy loader. Registry fallback prevents
   registered benchmark families from silently running zero queries merely
   because they lack an explicit instance provider.

The stream-specific helpers preserve these ordering boundaries:

* ``get_tpch_dataframe_queries(stream_id)`` selects the permutation matrix row
  modulo its length, logs missing query IDs and omits those entries.
* ``resolve_tpcds_query_manager(instance)`` checks the instance, then its
  ``_impl`` wrapper. Without a manager, ``get_tpcds_legacy_queries(ids, stream_id)``
  warns and generates legacy ordering using seed ``42 + stream_id``.
* ``get_tpcds_dataframe_queries(config, instance, stream_id)`` gathers numeric
  base IDs, creates one standard stream over query range 1 through 99 with that
  seed, and resolves variants. ``tpcds_dataframe_variant_fallback`` defaults to
  true and is interpreted with ``bool``.
* ``resolve_tpcds_stream_queries(queries, allow_variant_fallback)`` logs and
  skips missing base queries, resolves variant IDs with lower/upper/capitalized
  suffix spellings, and retains stream order. With fallback enabled, a missing
  variant uses a dataclass copy of the base implementation with the variant ID;
  this does not certify SQL parity. With fallback disabled, missing variants
  raise ``RuntimeError`` after collection.
* ``get_clickbench_dataframe_queries(config, instance, stream_id)`` returns
  the registry's sorted list; its configuration, instance and stream arguments
  do not alter the order.

DataFrame Row-count Evidence
-----------------------------

.. py:class:: benchbox.core.dataframe.query_validation.DataFrameQueryValidationSummary(status: str, details: dict[str, Any])

   Frozen dataclass containing a run-level status and mutable evidence dict.

.. py:function:: benchbox.core.dataframe.query_validation.validate_dataframe_query_results(query_results: list[dict[str, Any]], *, benchmark_name: str, scale_factor: float, validation_mode: str | None = None, seed: int | None = None) -> DataFrameQueryValidationSummary

   Mutate successful measurement rows with ``row_count_validation`` evidence,
   then return aggregate counts and status. Absent run types mean measurement;
   run types other than measurement are excluded from oracle evidence. Execution failures and
   selected non-warmup skips affect the aggregate status. False-valued mode
   defaults to ``exact``; mode and benchmark names are normalized.

   Only TPC-H at scale factor 1 with an absent seed or the reference seed can
   produce supported expected-row-count evidence. TPC-DS lacks seed-aligned
   counts for this path; its successful rows receive skipped evidence. Other
   benchmarks have no registered provider and return ``NOT_RUN``, or ``PARTIAL``
   when execution failed. Disabled validation uses the same two statuses.
   Unsupported modes mark successful rows skipped and yield ``UNCERTAIN``
   when evidence was unavailable, or ``PARTIAL`` when execution failed.

   DataFrame ``stream_id`` denotes a repeated measurement here, whereas the
   oracle uses it to select distinct answer streams. It is deliberately omitted
   from the oracle call. A valid actual count is a non-negative integer excluding
   booleans. An invalid count clears ``rows_returned`` and marks the row failed.
   An oracle mismatch also marks the row failed; skipped results retain their
   execution status. Oracle initialization or query errors produce error
   evidence rather than a fabricated candidate-result mismatch. Messages are
   truncated to 500 characters, including an ellipsis.

   Aggregate precedence is ``FAILED`` for a candidate mismatch or invalid count,
   then ``PARTIAL`` for execution failures, ``UNCERTAIN`` for skips or oracle
   errors, ``PASSED`` when every successful measurement was checked, otherwise
   ``NOT_RUN``. Initialization failure uses the unavailable-evidence status
   instead. Row-count agreement alone does not validate result contents or
   certify benchmark compliance.
