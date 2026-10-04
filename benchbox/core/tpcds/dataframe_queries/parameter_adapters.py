# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark(TM) DS (TPC-DS) - Copyright (c) Transaction Processing Performance Council

# Licensed under the MIT License. See LICENSE file in the project root for details.

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
    prefix = f"{name}."
    numbered = sorted((int(key[len(prefix) :]), value) for key, value in values.items() if key.startswith(prefix))
    return [value for number, value in numbered if number >= first and (last is None or number <= last)]


def _demographics(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "year": int(values["YEAR.01"]),
        "gender": values["GEN.01"],
        "marital_status": values["MS.01"],
        "education": values["ES.01"],
    }


def _dms(values: Mapping[str, str]) -> dict[str, Any]:
    return {"dms": int(values["DMS.01"])}


def _dms_value(values: Mapping[str, str]) -> int:
    return int(values["DMS.01"])


def _dms_window(values: Mapping[str, str]) -> dict[str, Any]:
    return {"dms": _dms_value(values)}


def _month_seq(values: Mapping[str, str]) -> dict[str, Any]:
    return {"dms": int(values["DMS.01"])}


def _q1(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "year": int(values["YEAR.01"]),
        "state": values["STATE.01"],
        "agg_field": values["AGG_FIELD.01"].lower(),
    }


def _q3(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "manufact_id": int(values["MANUFACT.01"]),
        "month": int(values["MONTH.01"]),
        "agg_column": values["AGGC.01"].lower(),
    }


def _q7(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "year": int(values["YEAR.01"]),
        "education": values["ES.01"],
        "gender": values["GEN.01"],
        "marital_status": values["MS.01"],
    }


def _q8(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "qoy": int(values["QOY.01"]), "zip_codes": _listed(values, "ZIP")}


def _q10(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "year": int(values["YEAR.01"]),
        "month": int(values["MONTH.01"]),
        "counties": _listed(values, "COUNTY", last=5),
    }


def _q12(values: Mapping[str, str]) -> dict[str, Any]:
    return {"item_categories": _listed(values, "CATEGORY"), "sales_date": values["SDATE.01"]}


def _q13(values: Mapping[str, str]) -> dict[str, Any]:
    marital, education, states = _listed(values, "MS"), _listed(values, "ES"), _listed(values, "STATE")
    parameters: dict[str, Any] = {"year": 2001}
    for group in range(3):
        parameters[f"demo{group + 1}_marital"] = marital[group]
        parameters[f"demo{group + 1}_education"] = education[group]
        parameters[f"states{group + 1}"] = states[group * 3 : group * 3 + 3]
    return parameters


def _q14(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"])}


def _q17(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "quarter": 1}


def _q18(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "year": int(values["YEAR.01"]),
        "cd_gender": values["GEN.01"],
        "cd_education_status": values["ES.01"],
        "birth_months": [int(month) for month in _listed(values, "MONTH")],
        "states": _listed(values, "STATE"),
    }


def _q20(values: Mapping[str, str]) -> dict[str, Any]:
    return {"item_categories": _listed(values, "CATEGORY"), "sales_date": values["SDATE.01"]}


def _q21(values: Mapping[str, str]) -> dict[str, Any]:
    return {"sales_date": values["SALES_DATE.01"]}


def _q22(values: Mapping[str, str]) -> dict[str, Any]:
    return {"dms": int(values["DMS.01"])}


def _q23(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month, "top_percent": int(values["TOPPERCENT.01"])}


def _q25(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "agg": values["AGG.01"]}


def _q26(values: Mapping[str, str]) -> dict[str, Any]:
    return _demographics(values)


def _q27(values: Mapping[str, str]) -> dict[str, Any]:
    states = [values[f"STATE_{letter}.01"] for letter in "ABCDEF"]
    return {**_demographics(values), "states": states}


def _q31(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "order_by": values["AGG.01"]}


def _q32(values: Mapping[str, str]) -> dict[str, Any]:
    return {"manufact_id": int(values["IMID.01"]), "sales_date": values["CSDATE.01"]}


def _q33(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month, "gmt_offset": float(values["GMT.01"]), "category": values["CATEGORY.01"]}


def _q34(values: Mapping[str, str]) -> dict[str, Any]:
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
    year, month = _year_and_month(values)
    return {"year": year, "months": [month, month + 1]}


def _q40(values: Mapping[str, str]) -> dict[str, Any]:
    return {"sales_date": values["SALES_DATE.01"]}


def _q44(values: Mapping[str, str]) -> dict[str, Any]:
    return {"store_sk": int(values["STORE.01"]), "null_col": values["NULLCOLSS.01"]}


def _q45(values: Mapping[str, str]) -> dict[str, Any]:
    return {"year": int(values["YEAR.01"]), "qoy": int(values["QOY.01"]), "gbobc": values["GBOBC.01"]}


def _q49(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month}


def _q50(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month}


def _q54(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month, "category": values["CATEGORY.01"], "class": values["CLASS.01"]}


def _q58(values: Mapping[str, str]) -> dict[str, Any]:
    return {"sales_date": values["SALES_DATE.01"]}


def _q59(values: Mapping[str, str]) -> dict[str, Any]:
    return {"d_month_seq": _dms_value(values)}


def _q60(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {"year": year, "month": month, "category": values["CATEGORY.01"], "gmt_offset": int(values["GMT.01"])}


def _q65(values: Mapping[str, str]) -> dict[str, Any]:
    return _dms(values)


def _q66(values: Mapping[str, str]) -> dict[str, Any]:
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
    return {
        "year": int(values["YEAR.01"]),
        "dep_count": int(values["DEPCNT.01"]),
        "vehicle_count": int(values["VEHCNT.01"]),
    }


def _q82(values: Mapping[str, str]) -> dict[str, Any]:
    price = int(values["PRICE.01"])
    return {
        "price_min": price,
        "price_max": price + 30,
        "sales_date": values["INVDATE.01"],
        "manufact_ids": [int(value) for value in _listed(values, "MANUFACT_ID")],
    }


def _q83(values: Mapping[str, str]) -> dict[str, Any]:
    return {"dates": [values["RETURNED_DATE_ONE.01"], values["RETURNED_DATE_TWO.01"], values["RETURNED_DATE_THREE.01"]]}


def _q84(values: Mapping[str, str]) -> dict[str, Any]:
    return {"city": values["CITY.01"], "income_band": int(values["INCOME.01"])}


def _q90(values: Mapping[str, str]) -> dict[str, Any]:
    return {
        "hour_am": int(values["HOUR_AM.01"]),
        "hour_pm": int(values["HOUR_PM.01"]),
        "dep_count": int(values["DEPCNT.01"]),
    }


def _q91(values: Mapping[str, str]) -> dict[str, Any]:
    year, month = _year_and_month(values)
    return {
        "year": year,
        "month": month,
        "buy_potential": values["BUY_POTENTIAL.01"],
        "gmt_offset": int(values["GMT.01"]),
    }


def _q92(values: Mapping[str, str]) -> dict[str, Any]:
    return {"manufact_id": int(values["IMID.01"]), "sales_date": values["WSDATE.01"]}


def _q93(values: Mapping[str, str]) -> dict[str, Any]:
    return {"reason": values["REASON.01"]}


def _q98(values: Mapping[str, str]) -> dict[str, Any]:
    return {"categories": _listed(values, "CATEGORY"), "sales_date": values["SDATE.01"]}


ADAPTERS: dict[int, Adapter] = {
    1: _q1,
    3: _q3,
    7: _q7,
    8: _q8,
    10: _q10,
    12: _q12,
    13: _q13,
    14: _q14,
    17: _q17,
    18: _q18,
    20: _q20,
    21: _q21,
    22: _q22,
    23: _q23,
    25: _q25,
    26: _q26,
    27: _q27,
    31: _q31,
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
    50: _q50,
    51: _dms_window,
    53: _dms_window,
    54: _q54,
    58: _q58,
    59: _q59,
    60: _q60,
    62: _dms_window,
    63: _dms_window,
    65: _q65,
    66: _q66,
    67: _q67,
    70: _q70,
    71: _q71,
    76: _q76,
    79: _q79,
    82: _q82,
    83: _q83,
    84: _q84,
    86: _month_seq,
    87: _month_seq,
    90: _q90,
    91: _q91,
    92: _q92,
    93: _q93,
    97: _month_seq,
    98: _q98,
    99: _month_seq,
}


def adapter_query_ids() -> tuple[int, ...]:
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
