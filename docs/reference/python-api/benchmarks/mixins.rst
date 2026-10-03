Shared Benchmark Facade Mixins
==============================

These maintained contracts document public methods inherited by benchmark
facades. Concrete benchmark pages describe only their own behavior and link
here instead of repeating the same inherited member list.

.. py:module:: benchbox.core.benchmark_mixins

DataGenerationMixin
-------------------

.. py:class:: DataGenerationMixin

   Shared table generation and loading flow. Consumers provide a table schema,
   a data generator, and the benchmark's CREATE TABLE SQL method.

   .. py:method:: generate_data(tables: Optional[list[str]] = None, output_format: str = "csv") -> dict[str, Any]

      Generate the selected tables, defaulting to every table in the schema,
      and return the benchmark's table-to-path mapping. Only ``csv`` output is
      accepted; another format raises ``ValueError``. Unknown table names also
      raise ``ValueError``.

   .. py:method:: load_data_to_database(connection: Any, tables: Optional[list[str]] = None) -> None

      Create the schema, load the selected generated tables, and commit when
      the connection exposes ``commit``. Calling this before data generation
      raises ``ValueError``; names absent from the generated mapping or schema
      are skipped.

QueryFacadeMixin
-----------------

.. py:class:: QueryFacadeMixin

   Delegates query listing and retrieval to a benchmark implementation while
   preserving optional parameters and keyword compatibility.

   .. py:method:: get_queries(dialect: Optional[str] = None) -> dict[str, str]

      Return the implementation's query mapping, optionally translated to the
      requested dialect.

   .. py:method:: get_query(query_id: Union[int, str], *, params: Optional[dict[str, Any]] = None, **kwargs: Any) -> str

      Return one implementation query, forwarding ``params`` and additional
      keyword options when supplied.

QueryCategoryFacadeMixin
------------------------

.. py:class:: QueryCategoryFacadeMixin

   Delegates category-oriented query accessors to the benchmark implementation.

   .. py:method:: get_queries_by_category(category: str) -> dict[str, str]

      Return the implementation's query mapping for one category.

   .. py:method:: get_query_categories() -> list[str]

      Return the implementation's available query category names.

OperationCategoryFacadeMixin
----------------------------

.. py:class:: OperationCategoryFacadeMixin

   Delegates category-oriented operation accessors to the benchmark implementation.

   .. py:method:: get_operations_by_category(category: str) -> dict[str, Any]

      Return the implementation's operation mapping for one category.

   .. py:method:: get_operation_categories() -> list[str]

      Return the implementation's available operation category names.

Source: ``benchbox/core/benchmark_mixins.py``.
