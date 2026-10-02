"""TPC-DS cross-surface gate builder."""

from __future__ import annotations

from pathlib import Path

from benchbox.core.equivalence.builders.base import CrossSurfaceData


def build_tpcds_duckdb(scale_factor: float, output_dir: Path) -> CrossSurfaceData:
    """Generate TPC-DS data, load it into in-memory DuckDB, and wire both surfaces."""
    from benchbox.core.tpcds.dataframe_queries.parameter_adapters import ADAPTERS, ParameterBinding, bind_parameters
    from benchbox.core.tpcds.dataframe_queries.parameters import set_parameter_overrides
    from benchbox.core.tpcds.schema.registry import TABLES
    from benchbox.tpcds import TPCDS

    bindings: dict[int, ParameterBinding] = {}

    def _dataframe_query(query_id: str) -> object:
        from benchbox.core.tpcds.dataframe_queries import TPCDS_DATAFRAME_QUERIES

        # Run both families of an adapted query on the values dsqgen put in the SQL. The overrides are
        # process-wide and replaced for every query, so one query's values never reach the next.
        number = int(query_id) if str(query_id).isdigit() else None
        if number in ADAPTERS:
            if number not in bindings:
                bindings[number] = bind_parameters(number, scale_factor=scale_factor, seed=None, stream_id=0)
            set_parameter_overrides({number: dict(bindings[number].parameters)})
        else:
            set_parameter_overrides(None)
        return TPCDS_DATAFRAME_QUERIES.get_or_raise(f"Q{query_id}")

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
