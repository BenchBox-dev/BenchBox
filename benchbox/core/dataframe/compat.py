"""Cross-platform DataFrame compatibility utilities.

Helpers for writing query code that works across all Pandas-family backends
(pandas, Modin, cuDF, Dask) without platform-specific branches in query logic.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any


def _to_list(values: Any) -> list:
    """Materialize a lazy Series/Index to a Python list for .isin() compatibility.

    Dask's .isin() requires a plain Python list/set, not a Dask Series or Index.
    Safe for all Pandas-family platforms (pandas, Modin, cuDF, Dask).
    """
    if hasattr(values, "compute"):  # Dask lazy objects
        values = values.compute()
    if hasattr(values, "tolist"):
        return values.tolist()
    return list(values)
