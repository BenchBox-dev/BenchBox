from __future__ import annotations

import dataclasses
import functools
from pathlib import Path
from typing import Any

from benchbox.core.equivalence.builders.base import CrossSurfaceData


def build_tpcds_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    from benchbox.core.tpcds.dataframe_queries.parameter_adapters import ADAPTERS, ParameterBinding, bind_parameters
    from benchbox.core.tpcds.dataframe_queries.parameters import parameter_overrides
    from benchbox.core.tpcds.schema.registry import TABLES
    from benchbox.tpcds import TPCDS

    bindings: dict[int, ParameterBinding] = {}

    def _bound(implementation: Any, number: int, parameters: dict[str, Any]) -> Any:
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
        if number not in bindings:
            bindings[number] = bind_parameters(number, scale_factor=scale_factor, seed=None, stream_id=0)
        parameters = dict(bindings[number].parameters)
        return dataclasses.replace(
            query,
            pandas_impl=_bound(query.pandas_impl, number, parameters),
            expression_impl=_bound(query.expression_impl, number, parameters),
        )

    _dataframe_query.bindings = bindings  # type: ignore[attr-defined]

    benchmark = TPCDS(scale_factor=scale_factor, output_dir=Path(output_dir))
    benchmark.generate_data()

    from benchbox.core.equivalence.builders.base import _load_duckdb_cell

    connection = _load_duckdb_cell(benchmark, Path(output_dir), [table.name for table in TABLES], label="TPC-DS")
    sql_queries = benchmark.get_queries(dialect="duckdb")
    return CrossSurfaceData(
        connection=connection,
        query_ids=list(sql_queries.keys()),
        reference_sql=lambda query_id: sql_queries[query_id],
        dataframe_query=_dataframe_query,
        benchmark=benchmark,
        data_dir=Path(output_dir),
    )
