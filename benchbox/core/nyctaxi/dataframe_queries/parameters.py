"""NYC Taxi DataFrame query parameters.

Default parameter values for NYC Taxi queries. Uses static defaults
for DataFrame execution (date ranges and zone IDs).

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from csv import reader
from dataclasses import dataclass
from typing import Any

_PARAM_ROWS = """\
Q1|2019-01-01|2019-01-31|
Q2|2019-01-01|2019-12-31|
Q3|2019-01-01|2019-12-31|
Q4|2019-01-01|2019-03-31|
Q5|2019-01-01|2019-01-31|
Q6|2019-01-01|2019-01-31|
Q7|2019-01-01|2019-01-31|
Q8|2019-01-01|2019-03-31|
Q9|2019-01-01|2019-01-31|
Q10|2019-01-01|2019-01-31|
Q11|2019-01-01|2019-01-31|
Q12|2019-01-01|2019-12-31|
Q13|2019-01-01|2019-01-31|
Q14|2019-01-01|2019-01-31|
Q15|2019-01-01|2019-01-31|
Q16|2019-01-01|2019-03-31|
Q17|2019-01-01|2019-03-31|
Q18|2019-01-01|2019-01-31|
Q19|2019-01-01|2019-01-07|
Q20|2019-01-01|2019-01-31|
Q21|2019-01-01|2019-01-31|
Q22|2019-01-01|2019-12-31|
Q23|2019-06-15|2019-06-16|
Q24|2019-01-01|2019-01-31|zone_id=132
Q25|||
"""

NYCTAXI_DEFAULT_PARAMS: dict[str, dict[str, Any]] = {}
for _query_id, _start, _end, _extra in reader(_PARAM_ROWS.splitlines(), delimiter="|"):
    _params: dict[str, Any] = {}
    if _start:
        _params.update({"start_date": _start, "end_date": _end})
    if _extra:
        _key, _value = _extra.split("=", 1)
        _params[_key] = int(_value)
    NYCTAXI_DEFAULT_PARAMS[_query_id] = _params


@dataclass
class NYCTaxiParameters:
    """Parameter container for a NYC Taxi query."""

    query_id: str
    params: dict[str, Any]

    def get(self, key: str, default: Any = None) -> Any:
        """Get a parameter value with optional default."""
        return self.params.get(key, default)


def get_parameters(query_id: str) -> NYCTaxiParameters:
    """Get parameters for a NYC Taxi query.

    Args:
        query_id: Query identifier (e.g., "Q1", "Q25")

    Returns:
        NYCTaxiParameters with default values for the query.
    """
    params = NYCTAXI_DEFAULT_PARAMS.get(query_id, {}).copy()
    return NYCTaxiParameters(query_id=query_id, params=params)
