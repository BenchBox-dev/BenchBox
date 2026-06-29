"""Per-benchmark cross-surface gate builders."""

from benchbox.core.equivalence.builders.amplab import build_amplab_duckdb
from benchbox.core.equivalence.builders.base import CrossSurfaceData, _load_duckdb_cell
from benchbox.core.equivalence.builders.clickbench import build_clickbench_duckdb
from benchbox.core.equivalence.builders.coffeeshop import build_coffeeshop_duckdb
from benchbox.core.equivalence.builders.h2odb import build_h2odb_duckdb
from benchbox.core.equivalence.builders.joinorder_synthetic import build_joinorder_synthetic_duckdb
from benchbox.core.equivalence.builders.read_primitives import build_read_primitives_duckdb
from benchbox.core.equivalence.builders.ssb import build_ssb_duckdb

__all__ = [
    "CrossSurfaceData",
    "_load_duckdb_cell",
    "build_amplab_duckdb",
    "build_clickbench_duckdb",
    "build_coffeeshop_duckdb",
    "build_h2odb_duckdb",
    "build_joinorder_synthetic_duckdb",
    "build_read_primitives_duckdb",
    "build_ssb_duckdb",
]
