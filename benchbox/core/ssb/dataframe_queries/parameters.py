"""SSB DataFrame query parameters.

Default parameter values for SSB queries, matching the SSB specification defaults.
SSB does not use seed-derived parameter substitution (unlike TPC-H/TPC-DS),
so these are static defaults only.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _value(value: str) -> Any:
    """Coerce plain decimal strings to integers for compact parameters."""
    return int(value) if value.isdecimal() else value


_PARAM_ROWS = """\
Q1.1|year=1993,discount_min=1,discount_max=3,quantity=25
Q1.2|year_month=199401,discount_min=1,discount_max=3,quantity_min=26,quantity_max=35
Q1.3|week=6,year=1993,discount_min=1,discount_max=3,quantity_min=26,quantity_max=35
Q2.1|category=MFGR#12,region=AMERICA
Q2.2|brand_min=MFGR#2221,brand_max=MFGR#2228,region=AMERICA
Q2.3|brand=MFGR#2221,region=AMERICA
Q3.1|c_region=ASIA,s_region=ASIA,year_min=1992,year_max=1997
Q3.2|c_nation=UNITED STATES,s_nation=UNITED STATES,year_min=1992,year_max=1997
Q3.3|c_city1=UNITED KI1,c_city2=UNITED KI5,s_city1=UNITED KI1,s_city2=UNITED KI5,year_min=1992,year_max=1997
Q3.4|c_city1=UNITED KI1,c_city2=UNITED KI5,s_city1=UNITED KI1,s_city2=UNITED KI5,year_month=Dec1997
Q4.1|region=AMERICA,mfgr1=MFGR#1,mfgr2=MFGR#2
Q4.2|region=AMERICA,year1=1997,year2=1998,mfgr1=MFGR#1,mfgr2=MFGR#2
Q4.3|region=AMERICA,year1=1997,year2=1998,category=MFGR#12
"""

SSB_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {
    query_id: {key: _value(value) for key, value in (item.split("=", 1) for item in params.split(","))}
    for query_id, params in (line.split("|", 1) for line in _PARAM_ROWS.splitlines())
}


@dataclass
class SSBParameters:
    """Parameter container for an SSB query."""

    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(key, default)


def get_parameters(query_id: str) -> SSBParameters:
    """Get parameters for an SSB query.

    Args:
        query_id: Query identifier (e.g., "Q1.1", "Q3.2")

    Returns:
        SSBParameters with default values for the query.
    """
    params = SSB_DEFAULT_PARAMS.get(query_id, {}).copy()
    return SSBParameters(query_id=query_id, params=params)
