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


def _q32(values: Mapping[str, str]) -> dict[str, Any]:
    # The template's YEAR only feeds CSDATE, which is the first day of a 90-day window in the SQL.
    return {"manufact_id": int(values["IMID.01"]), "sales_date": values["CSDATE.01"]}


def _q33(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month, "gmt_offset": float(values["GMT.01"]), "category": values["CATEGORY.01"]}


def _q34(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL tests d_year in (YEAR, YEAR+1, YEAR+2); the implementation adds the offsets itself.
    return {
        "year": int(values["YEAR.01"]),
        "counties": [values[f"COUNTY_{letter}.01"] for letter in "ABCDEFGH"],
        "buy_potential_1": values["BPONE.01"],
        "buy_potential_2": values["BPTWO.01"],
    }


def _q35(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "year": int(values["YEAR.01"]),
        "aggone": values["AGGONE.01"],
        "aggtwo": values["AGGTWO.01"],
        "aggthree": values["AGGTHREE.01"],
    }


def _q36(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "states": [values[f"STATE_{letter}.01"] for letter in "ABCDEFGH"]}


def _q37(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL tests i_current_price between PRICE and PRICE+30.
    price = int(values["PRICE.01"])
    return {
        "current_price_min": price,
        "current_price_max": price + 30,
        "manufact_ids": [int(value) for value in _listed(values, "MANUFACT_ID")],
        "sales_date": values["INVDATE.01"],
    }


def _q38(values: Mapping[str, str]) -> dict[str, Any]:
    return {"dms": int(values["DMS.01"])}


def _q39(values: Mapping[str, str]) -> dict[str, Any]:
    # The SQL compares month MONTH with month MONTH+1; the log has only MONTH.
    year, month = _year_and_month(values)
    return {"year": year, "months": [month, month + 1]}


def _q44(values: Mapping[str, str]) -> dict[str, Any]:
    return {"store_sk": int(values["STORE.01"]), "null_col": values["NULLCOLSS.01"]}


def _q40(values: Mapping[str, str]) -> dict[str, Any]:
    return {"sales_date": values["SALES_DATE.01"]}


def _q45(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "qoy": int(values["QOY.01"]), "gbobc": values["GBOBC.01"]}


def _q49(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month}


def _q93(values: Mapping[str, str]) -> dict[str, Any]:
    return {"reason": values["REASON.01"]}


ADAPTERS: dict[int, Adapter] = {
    32: _q32,
    33: _q33,
    34: _q34,
    35: _q35,
    36: _q36,
    37: _q37,
    38: _q38,
    39: _q39,
    40: _q40,
    44: _q44,
    45: _q45,
    49: _q49,
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
