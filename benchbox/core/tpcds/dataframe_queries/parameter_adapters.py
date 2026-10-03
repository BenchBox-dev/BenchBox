"""Bind TPC-DS DataFrame query parameters to the values dsqgen substitutes into the SQL.

The SQL surface takes its substitution values from dsqgen. The DataFrame surface reads its own
parameter keys (``year``, ``months``, ``store_sk``) from ``default_parameters.yaml``, which holds
representative values valid for scale factor 1 and does not follow dsqgen's seed or scale. An adapter
maps what ``dsqgen -LOG`` reports for a query to the DataFrame keys for that query, so both surfaces
can be run on the same parameters.

A flat name map is not enough. Q39's SQL uses ``[MONTH]`` and ``[MONTH]+1``, ``-LOG`` records only
``MONTH.01``, and the DataFrame implementation takes ``months: [m, m + 1]``, so an adapter reproduces
the template's arithmetic. One adapter is written per query, and only for queries whose implementation
reads every value the SQL varies: Q41 has none, because its implementation hard-codes colors and
reads ``manufact_start`` with a literal fallback, so binding it would hide that gap.

Each binding records where its values came from (the dsqgen binary, seed, scale factor and stream), so
a result can be tied to the parameters that produced it. ``stream_id`` is dsqgen's ``-STREAMS``
stream; ``DSQGenBinary.generate`` does not select a stream, so SQL for a stream above 0 has to be
rendered from the same values (``DSQGenBinary.generate_with_parameters``).

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

Adapter = Callable[[Mapping[str, str]], dict[str, Any]]


@dataclass(frozen=True)
class ParameterBinding:
    """DataFrame parameters for one query, with the dsqgen run they were derived from."""

    query_id: int
    scale_factor: float
    seed: int | None
    stream_id: int
    dsqgen_sha256: str
    logged: Mapping[str, str]
    parameters: Mapping[str, Any]


def _year_and_month(values: Mapping[str, str]) -> tuple[int, int]:
    return int(values["YEAR.01"]), int(values["MONTH.01"])


def _listed(values: Mapping[str, str], name: str, first: int = 1, last: int | None = None) -> list[str]:
    """The values logged as ``NAME.nn`` for ``first`` through ``last`` (every one when ``last`` is omitted)."""
    prefix = f"{name}."
    numbered = sorted((int(key[len(prefix) :]), value) for key, value in values.items() if key.startswith(prefix))
    return [value for number, value in numbered if number >= first and (last is None or number <= last)]


def _q39(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL compares month MONTH with month MONTH+1; the log has only MONTH.
    year, month = _year_and_month(values)
    return {"year": year, "months": [month, month + 1]}


def _q44(values: Mapping[str, str]) -> dict[str, Any]:
    return {"store_sk": int(values["STORE.01"]), "null_col": values["NULLCOLSS.01"]}


def _q49(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month}


def _dms(values: Mapping[str, str]) -> dict[str, Any]:
    # Q65, Q67 and Q70 all test d_month_seq between DMS and DMS+11; the implementations add the 11.
    return {"dms": int(values["DMS.01"])}


def _q65(values: Mapping[str, str]) -> dict[str, Any]:
    return _dms(values)


def _q66(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL window is TIMEONE through TIMEONE+28800; the implementations add the 28800. The carrier
    # order matters because the query reports it as ship_carriers.
    return {
        "year": int(values["YEAR.01"]),
        "time_start": int(values["TIMEONE.01"]),
        "ship_carriers": [values["SMC.01"], values["SMC.02"]],
        "web_sales_col": values["SALESONE.01"],
        "web_net_col": values["NETONE.01"],
        "catalog_sales_col": values["SALESTWO.01"],
        "catalog_net_col": values["NETTWO.01"],
    }


def _q67(values: Mapping[str, str]) -> dict[str, Any]:
    return _dms(values)


def _q70(values: Mapping[str, str]) -> dict[str, Any]:
    return _dms(values)


def _q71(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month}


def _q76(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "null_col_ss": values["NULLCOLSS.01"],
        "null_col_ws": values["NULLCOLWS.01"],
        "null_col_cs": values["NULLCOLCS.01"],
    }


def _q79(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL tests d_year in (YEAR, YEAR+1, YEAR+2); the implementations add the offsets.
    return {
        "year": int(values["YEAR.01"]),
        "dep_count": int(values["DEPCNT.01"]),
        "vehicle_count": int(values["VEHCNT.01"]),
    }


def _q82(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL tests i_current_price between PRICE and PRICE+30 and a 60-day window from INVDATE. YEAR only
    # constrains how INVDATE was drawn, so it does not reach the SQL.
    price = int(values["PRICE.01"])
    return {
        "price_min": price,
        "price_max": price + 30,
        "sales_date": values["INVDATE.01"],
        "manufact_ids": [int(value) for value in _listed(values, "MANUFACT_ID")],
    }


def _q83(values: Mapping[str, str]) -> dict[str, Any]:
    # Three dates, in the order the template lists them.
    return {"dates": [values["RETURNED_DATE_ONE.01"], values["RETURNED_DATE_TWO.01"], values["RETURNED_DATE_THREE.01"]]}


def _q93(values: Mapping[str, str]) -> dict[str, Any]:
    return {"reason": values["REASON.01"]}


ADAPTERS: dict[int, Adapter] = {
    39: _q39,
    44: _q44,
    49: _q49,
    65: _q65,
    66: _q66,
    67: _q67,
    70: _q70,
    71: _q71,
    76: _q76,
    79: _q79,
    82: _q82,
    83: _q83,
    93: _q93,
}


def adapter_query_ids() -> tuple[int, ...]:
    """Queries that have an adapter, in ascending order."""
    return tuple(sorted(ADAPTERS))


@lru_cache(maxsize=8)
def _file_sha256(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def bind_parameters(
    query_id: int,
    *,
    scale_factor: float,
    seed: int | None = None,
    stream_id: int = 0,
    dsqgen: Any | None = None,
) -> ParameterBinding:
    """The DataFrame parameters for ``query_id`` that match dsqgen's SQL for the same seed, scale and stream.

    Raises:
        KeyError: If the query has no adapter (it must not silently fall back to the defaults).
        ValueError: If dsqgen did not log a value the adapter needs.
    """
    if query_id not in ADAPTERS:
        raise KeyError(f"Q{query_id} has no parameter adapter; adapters exist for {list(adapter_query_ids())}")
    if dsqgen is None:
        from benchbox.core.tpcds.c_tools import DSQGenBinary

        dsqgen = DSQGenBinary()
    logged = dict(
        dsqgen.generate_parameter_log(query_id, seed=seed, scale_factor=scale_factor, stream_id=stream_id).substitutions
    )
    try:
        parameters = ADAPTERS[query_id](logged)
    except KeyError as exc:
        raise ValueError(f"dsqgen did not log {exc.args[0]!r} for Q{query_id} (logged: {sorted(logged)})") from exc
    return ParameterBinding(
        query_id=query_id,
        scale_factor=scale_factor,
        seed=seed,
        stream_id=stream_id,
        dsqgen_sha256=_file_sha256(str(dsqgen.dsqgen_path)),
        logged=logged,
        parameters=parameters,
    )
