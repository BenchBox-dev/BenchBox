CoffeeShop Benchmark API
=========================

.. tags:: reference, python-api, coffeeshop

.. py:module:: benchbox.coffeeshop

CoffeeShop models sales activity through ``dim_locations``, ``dim_products``, and the exploded ``order_lines`` fact table. It provides eleven analytical queries: ``SA1``-``SA5`` for sales analysis, ``PR1``-``PR2`` for product mix, ``TR1`` and ``TM1`` for trends, and ``QC1``-``QC2`` for quality checks.

Class
-----

.. py:class:: CoffeeShop(scale_factor: float = 1.0, output_dir: Optional[Union[str, Path]] = None, **kwargs: Any)

   Create a CoffeeShop benchmark. ``scale_factor`` and ``output_dir`` follow :doc:`../base`; additional keyword arguments are passed to the underlying generator.

   .. py:method:: generate_data() -> list[Union[str, Path]]

      Generate the benchmark data and return paths to the generated files.

   .. py:method:: get_schema() -> dict[str, dict]

      Return a mapping for ``dim_locations``, ``dim_products``, and ``order_lines`` keyed by table name.

   .. py:method:: get_create_tables_sql(dialect: str = "standard", tuning_config=None) -> str

      Return CREATE TABLE SQL for the selected dialect. ``tuning_config`` supplies constraint settings.

   .. py:method:: get_queries(dialect: Optional[str] = None) -> dict[str, str]

      Return the complete query mapping. With no dialect, it returns the canonical SQL. A dialect requests translated SQL, including maintained Spark-family and ClickHouse variants where needed.

   .. py:method:: get_query(query_id: str, *, params: Optional[dict[str, Any]] = None) -> str

      Return one query after applying its defaults and any supplied parameter overrides. Invalid query IDs and missing required parameter values raise ``ValueError``.

Example
-------

.. code-block:: python

    from benchbox.coffeeshop import CoffeeShop

    benchmark = CoffeeShop(scale_factor=0.1)
    data_files = benchmark.generate_data()
    regional_sales = benchmark.get_query(
        "SA1", params={"start_date": "2023-01-01", "end_date": "2023-01-31"}
    )

See also
--------

- :doc:`../base` for the shared benchmark lifecycle.
