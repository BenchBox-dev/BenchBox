"""TPC-DS cross-surface gate builder."""

from __future__ import annotations

import dataclasses
import functools
from pathlib import Path
from typing import Any

from benchbox.core.equivalence.builders.base import CrossSurfaceData


def build_tpcds_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-DS data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpcds.dataframe_queries.parameter_adapters import ADAPTERS, ParameterBinding, bind_parameters
    from benchbox.core.tpcds.dataframe_queries.parameters import parameter_overrides
    from benchbox.core.tpcds.schema.registry import TABLES
    from benchbox.tpcds import TPCDS

    bindings: dict[int, ParameterBinding] = {}

    def _bound(implementation: Any, number: int, parameters: dict[str, Any]) -> Any:
        """Wrap one implementation so the binding is installed only while it runs."""
        if implementation is None:
            return None

        @functools.wraps(implementation)
        def run(ctx: Any) -> Any:
            with parameter_overrides({number: dict(parameters)}):
                return implementation(ctx)

        return run

    def _dataframe_query(query_id: str) -> object:
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        query = TPCDS_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")
        number = int(query_id) if str(query_id).isdigit() else None
        if number not in ADAPTERS:
            return query
        # Run both families of an adapted query on the values dsqgen put in the SQL. The binding travels with
        # the returned copy of the query (the shared registry object is untouched), so it does not matter
        # what else is looked up or run between this call and the query's execution.
        if number not in bindings:
            bindings[number] = bind_parameters(number, scale_factor=scale_factor, seed=None, stream_id=0)
        parameters = dict(bindings[number].parameters)
        return dataclasses.replace(
            query,
            pandas_impl=_bound(query.pandas_impl, number, parameters),
            expression_impl=_bound(query.expression_impl, number, parameters),
        )

    # Where each adapted query's parameters came from (dsqgen binary, seed, scale, stream).
    _dataframe_query.bindings = bindings  # type: ignore[attr-defined]

    benchmark = TPCDS(scale_factor=scale_factor, output_dir=Path(output_dir))
    benchmark.generate_data()

    from benchbox.core.equivalence.builders.base import _load_duckdb_cell

    connection = _load_duckdb_cell(benchmark, Path(output_dir), [table.name for table in TABLES], label="TPC-DS")
    # The reference SQL executes directly on DuckDB: request the DuckDB
    # rendering so dialect-sensitive aliases (for example Q90's unquoted
    # ``AS at`` in the default Netezza form) parse.
    sql_queries = benchmark.get_queries(dialect="duckdb")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=_dataframe_query,
        benchmark=benchmark,
        data_dir=Path(output_dir),
    )
