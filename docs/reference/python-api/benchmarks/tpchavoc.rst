TPC-Havoc Benchmark API
=======================

.. py:module:: benchbox.tpchavoc
.. py:class:: TPCHavoc(scale_factor: float = 1.0, output_dir: Optional[Union[str, Path]] = None, **kwargs)

   TPC-Havoc adds query variants to the TPC-H facade. Constructor validation,
   lifecycle methods, schema generation, and base query behavior follow the
   public TPC-H contract in :doc:`tpch` and the shared lifecycle contract in
   :doc:`../base`.

   .. py:method:: generate_data() -> list[Union[str, Path]]

      Generate TPC-Havoc data through the wrapped implementation and return the generated file paths.

   .. py:method:: get_platform_skip_queries(platform_name: str) -> list[str]

      Return query identifiers skipped by the compatibility policy for the supplied platform selector or display name.

   .. py:method:: get_queries(dialect: Optional[str] = None) -> dict[str, str]

      Return the base TPC-H query mapping, translating it when ``dialect`` is supplied.

   .. py:method:: get_query(query_id, *, seed: Optional[int] = None, scale_factor: Optional[float] = None, dialect: Optional[str] = None, base_dialect: Optional[str] = None, **kwargs) -> str

      Return a base query or a variant addressed by a ``<query>_v<variant>`` string. Integer IDs must be 1 through 22; ``scale_factor`` must be positive, and ``seed`` must be an integer when supplied. Invalid inputs raise ``TypeError`` or ``ValueError``.

   .. py:method:: get_query_variant(query_id: int, variant_id: int, params: Optional[dict[str, Any]] = None) -> str

      Return one variant query. Both IDs must be integers, with query IDs from 1 through 22 and variant IDs from 1 through 10; invalid values raise ``TypeError`` or ``ValueError``.

   .. py:method:: get_all_variants(query_id: int) -> dict[int, str]

      Return the variant SQL mapping for one integer query ID. IDs outside the 1 through 22 range raise ``ValueError``.

   .. py:method:: get_variant_description(query_id: int, variant_id: int) -> str

      Return the human-readable description for a validated query and variant ID; invalid IDs raise ``TypeError`` or ``ValueError``.

   .. py:method:: get_implemented_queries() -> list[int]

      Return the query IDs for which the variant catalog has implementations.

   .. py:method:: get_all_variants_info(query_id: int) -> dict[int, dict[str, str]]

      Return variant metadata for one integer query ID; invalid IDs raise ``TypeError`` or ``ValueError``.

   .. py:method:: get_schema() -> dict[str, dict[str, Any]]

      Return the TPC-H schema mapping used by the wrapped benchmark.

   .. py:method:: get_create_tables_sql(dialect: str = "standard", tuning_config=None) -> str

      Return CREATE TABLE SQL for the requested dialect and tuning settings.

   .. py:method:: get_benchmark_info() -> dict[str, Any]

      Return benchmark metadata from the wrapped TPC-Havoc implementation.

   .. py:method:: export_variant_queries(output_dir: Optional[Union[str, Path]] = None, format: str = "sql") -> dict[str, Path]

      Write variant queries as SQL or JSON files and return query identifiers mapped to their paths. Unsupported formats raise ``ValueError``.

   .. py:method:: load_data_to_database(connection_string: str, dialect: str = "standard", schema: Optional[str] = None, drop_existing: bool = False) -> None

      Load generated data through the TPC-H implementation. Missing generated data raises ``ValueError`` and an unavailable database driver raises ``ImportError``.

   .. py:method:: run_query(query_id: int, connection_string: str, params: Optional[dict[str, Any]] = None, dialect: str = "standard") -> dict[str, Any]

      Run one validated base query and return its result and timing mapping. The query ID must be an integer from 1 through 22 and the connection string must be non-empty.

   .. py:method:: run_benchmark(connection_string: str, queries: Optional[list[int]] = None, iterations: int = 1, dialect: str = "standard", schema: Optional[str] = None) -> dict[str, Any]

      Run selected base queries, or the implementation's default set, for the requested positive iteration count and return benchmark results. The connection string must be non-empty and query IDs must be integers from 1 through 22.

Source: ``benchbox/tpchavoc.py`` and ``benchbox/core/tpchavoc``.
