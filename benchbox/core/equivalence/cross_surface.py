# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from benchbox.core.equivalence.builders import (
    CrossSurfaceData,
    build_amplab_duckdb,
    build_clickbench_duckdb,
    build_coffeeshop_duckdb,
    build_datavault_duckdb,
    build_flightdata_duckdb,
    build_h2odb_duckdb,
    build_joinorder_synthetic_duckdb,
    build_nyctaxi_duckdb,
    build_read_primitives_duckdb,
    build_ssb_duckdb,
    build_tpcds_duckdb,
    build_tpch_duckdb,
    build_tpch_skew_duckdb,
    build_tsbs_devops_duckdb,
)
from benchbox.core.equivalence.dataframe_surface import (
    DATAFRAME_BACKENDS,
    SurfaceDivergence,
    fetch_reference_rows,
    find_surface_divergences,
    materialize_rows,
)

if TYPE_CHECKING:  # pragma: no cover
    from benchbox.core.tpchavoc.validation import ResultValidator


def _load_known_divergences_baseline() -> dict[str, dict[str, str]]:
    payload = yaml.safe_load(
        resources.files("benchbox.core.equivalence").joinpath("cross_surface_baseline.yaml").read_text(encoding="utf-8")
    )
    if not isinstance(payload, dict):
        raise RuntimeError("cross_surface_baseline.yaml must contain a top-level mapping")
    return payload


_KNOWN_DIVERGENCES_BASELINE: dict[str, dict[str, str]] = _load_known_divergences_baseline()

EQUIVALENCE_SCALE = 0.1

SURFACE_INDEPENDENCE_SHARED_SPEC = "shared-spec"
SURFACE_INDEPENDENCE_MIXED = "mixed-provenance"
SURFACE_INDEPENDENCE_SEPARATE = "separate-handwritten"

_DEFAULT_SURFACE_INDEPENDENCE_RATIONALE = (
    "SQL and DataFrame surfaces are maintained from a shared benchmark spec; the gate catches "
    "transcription drift between surfaces, not shared conceptual mistakes."
)

_TRAILING_LIMIT_RE = re.compile(r"(?is)(\blimit\s+)(\d+)(\s*(?:offset\s+\d+\s*)?;?\s*)$")
_TRAILING_COMMENT_RE = re.compile(r"\s*--[^\n]*$")


def _strip_trailing_comment(sql: str) -> str:
    return _TRAILING_COMMENT_RE.sub("", sql.strip())


def _is_truncated_top_n(sql: str) -> bool:
    return bool(_TRAILING_LIMIT_RE.search(_strip_trailing_comment(sql)))


def _bump_trailing_limit(sql: str) -> str | None:
    stripped = _strip_trailing_comment(sql)
    match = _TRAILING_LIMIT_RE.search(stripped)
    if match is None:
        return None
    bumped = int(match.group(2)) + 1
    return f"{stripped[: match.start()]}{match.group(1)}{bumped}{match.group(3)}"


def _final_key_tied_beyond_limit(
    connection: Any,
    sql: str,
    order_by: Sequence[int],
    reference: list[tuple[Any, ...]],
) -> bool:
    if not reference or not order_by:
        return False
    n = len(reference)
    width = len(reference[-1])
    if any(c < 0 or c >= width for c in order_by):
        return False
    final_key = tuple(reference[-1][c] for c in order_by)
    probe_sql = _bump_trailing_limit(sql)
    if probe_sql is None:
        return False
    try:
        probe = fetch_reference_rows(connection, probe_sql)
    except Exception:
        return False
    if len(probe) <= n or len(probe[n]) <= max(order_by):
        return False
    key_beyond = tuple(probe[n][c] for c in order_by)
    return final_key == key_beyond


def _is_star_projection(projection: Any) -> bool:
    from sqlglot import exp

    return isinstance(projection, exp.Star) or (
        isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star)
    )


def _order_by_result_key(sql: str) -> list[int] | None:
    import sqlglot
    from sqlglot import exp

    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except Exception:
        return None
    if tree is None:
        return None
    select = tree.find(exp.Select)
    if select is None:
        return None
    order = select.args.get("order")
    if order is None:
        return None

    projections = select.expressions
    if any(_is_star_projection(proj) for proj in projections):
        return None

    alias_to_index: dict[str, int] = {}
    expr_to_index: dict[str, int] = {}
    for index, proj in enumerate(projections):
        name = proj.alias_or_name
        if name:
            alias_to_index.setdefault(name.lower(), index)
        inner = proj.this if isinstance(proj, exp.Alias) else proj
        expr_to_index.setdefault(inner.sql(dialect="duckdb", normalize=True).lower(), index)

    resolved: list[int] = []
    for ordered in order.expressions:
        target = ordered.this
        index = _resolve_order_term(target, projections, alias_to_index, expr_to_index)
        if index is None:
            return None
        resolved.append(index)
    return resolved


def _resolve_order_term(
    target: Any,
    projections: Sequence[Any],
    alias_to_index: dict[str, int],
    expr_to_index: dict[str, int],
) -> int | None:
    from sqlglot import exp

    if isinstance(target, exp.Literal) and target.is_int:
        ordinal = int(target.name)
        return ordinal - 1 if 1 <= ordinal <= len(projections) else None
    if isinstance(target, exp.Column):
        index = alias_to_index.get(target.name.lower())
        if index is not None:
            return index
    return expr_to_index.get(target.sql(dialect="duckdb", normalize=True).lower())


@dataclass(frozen=True)
class ClassifiedDivergence:
    reason: str
    accepts: Callable[[SurfaceDivergence], bool]
    requires_live_divergence: bool = True
    review_by: date | None = None


@dataclass(frozen=True)
class CrossSurfaceGate:
    name: str
    build: Callable[[float, Path], CrossSurfaceData]
    known_divergences: dict[str, str | ClassifiedDivergence] = field(default_factory=dict)
    dtype_skip_keys: frozenset[str] = frozenset()
    legitimately_empty: dict[Any, str] = field(default_factory=dict)
    backends: tuple[str, ...] = DATAFRAME_BACKENDS
    tolerance: float = 1e-10
    surface_independence: str = SURFACE_INDEPENDENCE_SHARED_SPEC
    surface_independence_rationale: str = _DEFAULT_SURFACE_INDEPENDENCE_RATIONALE
    treat_nan_as_null: bool = False
    strip_strings: bool = False
    scale_factor: float = EQUIVALENCE_SCALE

    def build_validator(self) -> ResultValidator:
        from benchbox.core.tpchavoc.validation import ResultValidator

        return ResultValidator(
            tolerance=self.tolerance,
            treat_nan_as_null=self.treat_nan_as_null,
            strip_strings=self.strip_strings,
        )


def find_cross_surface_divergences(
    connection: Any,
    *,
    query_ids: Iterable[Any],
    reference_sql: Callable[[Any], str],
    dataframe_query: Callable[[Any], Any],
    contexts: dict[str, Any],
    validator: ResultValidator,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
    reference_row_counts: dict[Any, int] | None = None,
) -> list[SurfaceDivergence]:
    from benchbox.core.tpchavoc.validation import ValidationError

    def reference_rows(query_id: Any) -> list[tuple[Any, ...]]:
        rows = fetch_reference_rows(connection, reference_sql(query_id))
        if reference_row_counts is not None:
            if len(rows) == 1 and all(value is None for value in rows[0]):
                reference_row_counts[query_id] = 0
            else:
                reference_row_counts[query_id] = len(rows)
        return rows

    def candidate_cells(
        query_id: Any,
    ) -> Iterable[tuple[str, Callable[[list[tuple[Any, ...]]], None]]]:
        query = dataframe_query(query_id)
        sql = reference_sql(query_id)
        tie_aware = _is_truncated_top_n(sql)
        order_by = _order_by_result_key(sql)
        order_aware = order_by is not None
        probe_result: bool | None = None

        def final_key_tied(reference: list[tuple[Any, ...]]) -> bool:
            nonlocal probe_result
            if probe_result is None:
                probe_result = bool(
                    tie_aware
                    and order_by is not None
                    and _final_key_tied_beyond_limit(connection, sql, order_by, reference)
                )
            return probe_result

        for backend in backends:
            impl = query.get_impl_for_family(backend)
            if impl is None:
                continue

            def check(
                reference: list[tuple[Any, ...]],
                *,
                impl: Any = impl,
                backend: str = backend,
                query_id: Any = query_id,
                tie_aware: bool = tie_aware,
                order_aware: bool = order_aware,
                order_by: list[int] | None = order_by,
            ) -> None:
                candidate = materialize_rows(impl(contexts[backend]))
                validator.validate_results_exact(
                    reference,
                    candidate,
                    query_id,
                    0,
                    tie_aware=tie_aware,
                    order_aware=order_aware,
                    order_by=order_by,
                    final_key_tied_beyond_limit=final_key_tied(reference),
                )

            yield backend, check

    return find_surface_divergences(
        query_ids,
        reference_rows=reference_rows,
        candidate_cells=candidate_cells,
        validation_error=ValidationError,
        reference_failure_cell="reference",
    )


def count_executed_cells(
    query_ids: Iterable[Any],
    dataframe_query: Callable[[Any], Any],
    backends: tuple[str, ...],
) -> dict[str, int]:
    coverage = dict.fromkeys(backends, 0)
    for query_id in query_ids:
        query = dataframe_query(query_id)
        for backend in backends:
            if query.get_impl_for_family(backend) is not None:
                coverage[backend] += 1
    return coverage


def _dtype_category(dtype: Any) -> str:
    text = str(dtype).lower()
    if text.startswith(("int", "uint")):
        return "integer"
    if text.startswith(("float", "double", "halffloat")):
        return "float"
    if text.startswith("decimal"):
        return "decimal"
    if text in ("string", "large_string", "utf8", "large_utf8", "string_view", "utf8_view"):
        return "string"
    if text in ("bool", "boolean"):
        return "boolean"
    if text.startswith(("date", "timestamp", "datetime", "time", "duration", "interval", "month_day_nano")):
        return "temporal"
    if text.startswith(("list", "large_list", "fixed_size_list", "array", "struct", "map")):
        return "nested"
    if text == "null":
        return "null"
    if text.startswith(("binary", "large_binary")):
        return "binary"
    return f"other:{text}"


def _dtype_categories_equivalent(reference: str, candidate: str) -> bool:
    if reference == candidate:
        return True
    return reference == "decimal" and candidate == "float"


def _frame_polars_categories(result: Any) -> list[str] | None:
    native = getattr(result, "native", result)
    if hasattr(native, "collect"):
        native = native.collect()
    schema = getattr(native, "schema", None)
    if schema is None:
        return None
    values = schema.values() if hasattr(schema, "values") else schema
    return [_dtype_category(dtype) for dtype in values]


def find_cross_surface_dtype_divergences(
    connection: Any,
    *,
    query_ids: Iterable[Any],
    reference_sql: Callable[[Any], str],
    dataframe_query: Callable[[Any], Any],
    contexts: dict[str, Any],
    backends: tuple[str, ...] = ("expression",),
    skip_keys: frozenset[str] = frozenset(),
    skip_query_ids: frozenset[Any] = frozenset(),
) -> tuple[list[SurfaceDivergence], dict[str, int]]:
    divergences: list[SurfaceDivergence] = []
    compared = dict.fromkeys(backends, 0)
    for query_id in query_ids:
        if query_id in skip_query_ids:
            continue
        try:
            reference_schema = connection.execute(reference_sql(query_id)).fetch_arrow_table().schema
        except Exception as exc:
            divergences.append(SurfaceDivergence(query_id=query_id, cell="reference", detail=f"error: {exc}"))
            continue
        reference_categories = [_dtype_category(field.type) for field in reference_schema]
        query = dataframe_query(query_id)
        for backend in backends:
            key = f"{query_id}_{backend}"
            if key in skip_keys:
                continue
            impl = query.get_impl_for_family(backend)
            if impl is None:
                continue
            try:
                candidate_categories = _frame_polars_categories(impl(contexts[backend]))
            except Exception as exc:
                divergences.append(SurfaceDivergence(query_id=query_id, cell=backend, detail=f"error: {exc}"))
                continue
            if candidate_categories is None:
                divergences.append(
                    SurfaceDivergence(
                        query_id=query_id,
                        cell=backend,
                        detail="error: frame has no Polars-style schema to compare",
                    )
                )
                continue
            compared[backend] += 1
            if len(candidate_categories) != len(reference_categories):
                divergences.append(
                    SurfaceDivergence(
                        query_id=query_id,
                        cell=backend,
                        detail=(
                            "dtype width mismatch: reference has "
                            f"{len(reference_categories)} columns, frame has {len(candidate_categories)}"
                        ),
                    )
                )
                continue
            for index, (reference, candidate) in enumerate(zip(reference_categories, candidate_categories)):
                if not _dtype_categories_equivalent(reference, candidate):
                    divergences.append(
                        SurfaceDivergence(
                            query_id=query_id,
                            cell=backend,
                            detail=(f"dtype mismatch at column {index}: reference {reference}, frame {candidate}"),
                        )
                    )
    return divergences, compared


_PRODUCTION_ADAPTERS: dict[str, str] = {
    "expression": "benchbox.platforms.dataframe.polars_df:PolarsDataFrameAdapter",
    "pandas": "benchbox.platforms.dataframe.pandas_df:PandasDataFrameAdapter",
}


def build_production_contexts(
    benchmark: Any,
    data_dir: Path,
    *,
    backends: tuple[str, ...] = DATAFRAME_BACKENDS,
    scale_factor: float = EQUIVALENCE_SCALE,
) -> dict[str, Any]:
    import importlib

    contexts: dict[str, Any] = {}
    for backend in backends:
        target = _PRODUCTION_ADAPTERS.get(backend)
        if target is None:
            raise ValueError(f"No production DataFrame adapter registered for backend {backend!r}")
        module_name, _, class_name = target.partition(":")
        adapter_cls = getattr(importlib.import_module(module_name), class_name)
        adapter = adapter_cls()
        contexts[backend] = adapter.load_benchmark_into_context(benchmark, Path(data_dir), scale_factor=scale_factor)
    return contexts


_CLICKBENCH_TIE_AMBIGUOUS_REASON = (
    "Q18 is LIMIT 10 with no ORDER BY over ~97k groups - an arbitrary, order-less top-N selection"
)


def _is_clickbench_q18_arbitrary_topn(divergence: SurfaceDivergence) -> bool:
    return "Value mismatch" in str(divergence.detail)


_CLICKBENCH_TIE_AMBIGUOUS = ClassifiedDivergence(
    reason=_CLICKBENCH_TIE_AMBIGUOUS_REASON,
    accepts=_is_clickbench_q18_arbitrary_topn,
    requires_live_divergence=False,
    review_by=date(2027, 1, 3),
)

_AMPLAB_VACUOUS_Q3 = (
    "0 reference rows at the bounded cell (still empty at SF=1.0): GROUP BY sourceIP "
    "HAVING COUNT(*)>10 over a 3-day visitDate window AND searchWord LIKE '%database%' "
    "- no source IP reaches >10 visits in that narrow slice; data density, not a bug."
)
_AMPLAB_VACUOUS_Q5 = (
    "0 reference rows at the bounded SF=0.1 cell: JOIN rankings ON pageRank>1000 "
    "(~111 qualifying rows) then GROUP BY countryCode HAVING COUNT(*)>10 - the join "
    "survivors do not reach 10 per country at the bounded cell; data density, not a bug."
)
_AMPLAB_LEGITIMATELY_EMPTY: dict[Any, str] = {"3": _AMPLAB_VACUOUS_Q3, "5": _AMPLAB_VACUOUS_Q5}

_CLICKBENCH_VACUOUS = (
    "0 reference rows at the bounded SF=0.1 (100k-row) cell: the canonical ClickBench "
    "query keeps an UPSTREAM literal/threshold (a specific UserID/RefererHash/URLHash, "
    "CounterID=62 + the July-2013 EventDate window, HAVING COUNT(*)>100000, or a "
    "LIMIT...OFFSET past the filtered slice) tuned for the ~100M-row upstream dataset; "
    "the synthetic 100k-row generator emits different ids/dates so the filter selects "
    "nothing on either surface. Data/literal artifact, not a load or logic bug. "
    "Tracked: a larger discriminating cell or upstream-faithful literals (do NOT change "
    "the canonical ClickBench query)."
)
_CLICKBENCH_LEGITIMATELY_EMPTY: dict[Any, str] = dict.fromkeys(
    ("Q20", "Q23", "Q28", "Q29", "Q39", "Q40", "Q41", "Q42"), _CLICKBENCH_VACUOUS
)

_DATAVAULT_Q17_VACUOUS = (
    "0 discriminating rows at the bounded gate cell: Q17 is a scalar SUM(...) with no "
    "GROUP BY over the small-quantity-order conjunction (brand + container literals "
    "against part/partsupp/lineitem). Verified 2026-09-26 by executing the reference "
    "SQL over every brand/container combination present in the built cell (25 brands x "
    "40 containers = 1000 combos): every combination returns the single all-NULL row, "
    "so neither surface can discriminate anything. Data/literal artifact of the bounded "
    "cell, not a load or logic bug. Tracked: plant a satisfying brand/container pair "
    "in the generator or gate a larger cell (do NOT change the canonical Q17 query)."
)
_DATAVAULT_LEGITIMATELY_EMPTY: dict[Any, str] = dict.fromkeys(("Q17",), _DATAVAULT_Q17_VACUOUS)

_TPCH_Q17_VACUOUS = (
    "0 discriminating rows at the bounded gate cell (SF=0.01): Q17 is a scalar SUM(...) with "
    "no GROUP BY whose default literals (Brand#23, MED BOX) match no qualifying part/lineitem "
    "rows in the small cell, so the reference returns the single all-NULL row and neither "
    "surface can discriminate anything: the gate asserts only that both surfaces also return "
    "NULL, so a defect in the join, the correlated subquery or the aggregate that still "
    "returns NULL would pass. Verified 2026-10-01 by executing the reference SQL over every "
    "brand/container combination present in the built cell (25 brands x 40 containers = "
    "1000 combos): 856 combinations return a non-NULL value and the other 144, including "
    "the default pair, return the all-NULL row. The all-NULL result is a literal artifact "
    "of the default parameters against the small cell, not a load or logic bug, and the "
    "query is not vacuous in general. Remediation: gate Q17 with a "
    "brand/container pair the cell satisfies on both surfaces (do NOT change the canonical "
    "Q17 query)."
)

_TPCH_SKEW_Q17_VACUOUS = (
    "0 discriminating rows at the bounded gate cell (SF=0.01, seed 42): Q17 is a scalar "
    "SUM(...) with no GROUP BY whose default literals (Brand#23, MED BOX) match no "
    "qualifying part/lineitem rows in the skewed data, so the reference returns the single "
    "all-NULL row and neither surface can discriminate anything: the gate asserts only that "
    "both surfaces also return NULL, so a defect in the join, the correlated subquery or the "
    "aggregate that still returns NULL would pass. Verified 2026-10-01 by executing the "
    "reference SQL over every brand/container combination present in the built cell (25 "
    "brands x 40 containers = 1000 combos): 496 combinations return a non-NULL value and "
    "the other 504, including the default pair, return the all-NULL row. The all-NULL "
    "result is a literal artifact of the default parameters against the skewed "
    "distribution, not a load or logic bug, and the query is not vacuous in general. "
    "Remediation: gate Q17 with a brand/container pair the cell satisfies on "
    "both surfaces (do NOT change the canonical Q17 query)."
)

_JOINORDER_SYNTHETIC_VACUOUS = (
    "Synthetic selectivity, not a bug: the query's multi-table conjunction needs coordinated "
    "real-world literals (specific keywords, notes, countries, ratings, link types) that the "
    "bounded synthetic cell does not plant on one entity set, so the reference join is empty on "
    "BOTH surfaces. Golden entities back the highest-traffic conjunctions (34 discriminating); "
    "this tail stays classified until its literals are planted too. Any query NOT listed here "
    "that goes vacuous fails the gate."
)
_JOINORDER_SYNTHETIC_LEGITIMATELY_EMPTY: dict[Any, str] = dict.fromkeys(
    (
        "1a",
        "1c",
        "2b",
        "2c",
        "3b",
        "5b",
        "7a",
        "7b",
        "7c",
        "8a",
        "8b",
        "9a",
        "9b",
        "9c",
        "9d",
        "11a",
        "11b",
        "11c",
        "12b",
        "13b",
        "13c",
        "14a",
        "14b",
        "14c",
        "15a",
        "15b",
        "15c",
        "15d",
        "17a",
        "17b",
        "17c",
        "17d",
        "18a",
        "18b",
        "18c",
        "19a",
        "19b",
        "19c",
        "19d",
        "20a",
        "20b",
        "20c",
        "21a",
        "21b",
        "21c",
        "22a",
        "22b",
        "22c",
        "22d",
        "23a",
        "23b",
        "23c",
        "24a",
        "24b",
        "25a",
        "25b",
        "25c",
        "26a",
        "26b",
        "26c",
        "27a",
        "27b",
        "27c",
        "28a",
        "28b",
        "28c",
        "29a",
        "29b",
        "29c",
        "30a",
        "30b",
        "30c",
        "31a",
        "31b",
        "31c",
        "32a",
        "33a",
        "33b",
        "33c",
    ),
    _JOINORDER_SYNTHETIC_VACUOUS,
)

_H2ODB_SCALE = 0.01

_H2ODB_PERCENTILE_DECIMAL = (
    "PERCENTILE_CONT over the DECIMAL(8,2) fare_amount column returns a DECIMAL(8,2) "
    "on the SQL surface (continuous percentile rounded to the column's 2-decimal "
    "scale), while the DataFrame surface computes the same linear-interpolated "
    "percentile over float64 (DECIMAL->float at load) and keeps full precision. Both "
    "DataFrame backends use linear interpolation and agree; casting the SQL to DOUBLE "
    "yields the DataFrame value, so the only difference is DuckDB's DECIMAL result "
    "scale - a deterministic, sub-cent presentational/dtype difference, not a logic bug."
)
_H2ODB_Q9_P90_COLUMN = 2
_H2ODB_Q9_RESIDUE_MAX = 0.005 + 1e-6
_VALUE_MISMATCH_RE = re.compile(
    r"Value mismatch at row \d+, column (?P<col>\d+)\. "
    r"Original:\s*(?P<orig>.+?),\s*Variant:\s*(?P<variant>.+?)"
    r"(?:; also columns \[(?P<also>[\d, ]*)\])?$"
)
_NUMBER_RE = re.compile(r"[-+]?\d*\.\d+|[-+]?\d+")


def _mismatched_columns(match: re.Match[str]) -> set[int]:
    columns = {int(match.group("col"))}
    also = match.group("also")
    if also:
        columns.update(int(token) for token in re.findall(r"\d+", also))
    return columns


def _first_number(text: str) -> float | None:
    match = _NUMBER_RE.search(text)
    return float(match.group()) if match else None


def _is_two_decimal_scale(value: str) -> bool:
    number = _NUMBER_RE.search(value)
    if number is None:
        return False
    _, _, frac = number.group().partition(".")
    return len(frac) <= 2


def _h2odb_q9_decimal_residue(divergence: SurfaceDivergence) -> bool:
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    if _mismatched_columns(match) != {_H2ODB_Q9_P90_COLUMN}:
        return False
    orig_text = match.group("orig")
    variant_text = match.group("variant")
    orig = _first_number(orig_text)
    variant = _first_number(variant_text)
    if orig is None or variant is None:
        return False
    if not _is_two_decimal_scale(orig_text):
        return False
    return abs(orig - variant) <= _H2ODB_Q9_RESIDUE_MAX


_H2ODB_KNOWN_DIVERGENCES: dict[str, str | ClassifiedDivergence] = {
    **_KNOWN_DIVERGENCES_BASELINE.get("h2odb", {}),
    **dict.fromkeys(
        ("Q9_expression", "Q9_pandas"),
        ClassifiedDivergence(_H2ODB_PERCENTILE_DECIMAL, _h2odb_q9_decimal_residue),
    ),
}


_READ_PRIMITIVES_APPROX = (
    "DuckDB APPROX_COUNT_DISTINCT (HyperLogLog) and APPROX_QUANTILE (T-Digest) are "
    "inherently approximate sketches; the DataFrame computes the exact distinct "
    "count / quantile, so the values differ by the sketch's error - approximate by "
    "construction, not a logic divergence."
)
_READ_PRIMITIVES_SKETCH_RELATIVE_ERROR_MAX = 0.15
_READ_PRIMITIVES_SKETCH_COLUMNS: dict[str, tuple[int, ...]] = {
    "approx_count_distinct_simple": (0,),
    "approx_count_distinct_groupby": (2, 3),
    "approx_quantile_groupby": (1,),
}


def _read_primitives_sketch_residue(divergence: SurfaceDivergence) -> bool:
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    query_id = str(divergence.query_id)
    allowed_columns = next(
        (columns for name, columns in _READ_PRIMITIVES_SKETCH_COLUMNS.items() if name in query_id),
        None,
    )
    if allowed_columns is None or not (_mismatched_columns(match) <= set(allowed_columns)):
        return False
    orig = _first_number(match.group("orig"))
    variant = _first_number(match.group("variant"))
    if orig is None or variant is None:
        return False
    denominator = abs(orig) if orig != 0 else abs(variant)
    if denominator == 0:
        return orig == variant
    return abs(orig - variant) / denominator <= _READ_PRIMITIVES_SKETCH_RELATIVE_ERROR_MAX


_READ_PRIMITIVES_DECIMAL_PERCENTILE = (
    "PERCENTILE_CONT over DECIMAL(15,2) returns a 2-decimal value on the SQL surface; "
    "the DataFrame interpolates in float64. Both use linear interpolation - only the "
    "DECIMAL result scale differs (sub-cent), the same presentational class as h2odb Q9."
)
_READ_PRIMITIVES_DECIMAL_ROUND = (
    "ROUND() of a DECIMAL revenue (DuckDB, exact) vs the same product computed in "
    "float64 (DataFrame) flips at a half-cent rounding boundary; a DECIMAL-vs-float "
    "presentational residue (every other column matches), not a logic divergence."
)
_READ_PRIMITIVES_PERCENTILE_P95_COLUMN = 6
_READ_PRIMITIVES_PERCENTILE_RESIDUE_MAX = 0.005 + 1e-6
_READ_PRIMITIVES_ROUND_COLUMN = 6
_READ_PRIMITIVES_ROUND_RESIDUE_MAX = 0.01 + 1e-6


def _read_primitives_decimal_scale_residue(divergence: SurfaceDivergence, *, column: int, max_residue: float) -> bool:
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    if _mismatched_columns(match) != {column}:
        return False
    orig_text = match.group("orig")
    orig = _first_number(orig_text)
    variant = _first_number(match.group("variant"))
    if orig is None or variant is None:
        return False
    if not _is_two_decimal_scale(orig_text):
        return False
    return abs(orig - variant) <= max_residue


def _read_primitives_percentile_decimal_residue(divergence: SurfaceDivergence) -> bool:
    return _read_primitives_decimal_scale_residue(
        divergence,
        column=_READ_PRIMITIVES_PERCENTILE_P95_COLUMN,
        max_residue=_READ_PRIMITIVES_PERCENTILE_RESIDUE_MAX,
    )


def _read_primitives_round_decimal_residue(divergence: SurfaceDivergence) -> bool:
    return _read_primitives_decimal_scale_residue(
        divergence,
        column=_READ_PRIMITIVES_ROUND_COLUMN,
        max_residue=_READ_PRIMITIVES_ROUND_RESIDUE_MAX,
    )


_READ_PRIMITIVES_ARGMIN_TIE = (
    "ARG_MIN(p_name, p_retailprice) is non-deterministic when several parts in a brand "
    "share the minimum retail price; DuckDB's tie pick is engine-defined and not "
    "reproducible by a fixed DataFrame tie-break (the min_price value matches exactly)."
)
_READ_PRIMITIVES_ARGMIN_TIE_COLUMNS = (1, 2)


def _read_primitives_argmin_tie(divergence: SurfaceDivergence) -> bool:
    match = _VALUE_MISMATCH_RE.search(str(divergence.detail))
    if match is None:
        return False
    return _mismatched_columns(match) <= set(_READ_PRIMITIVES_ARGMIN_TIE_COLUMNS)


_READ_PRIMITIVES_JSON_TEXT = (
    "JSON_GROUP_ARRAY/JSON_GROUP_OBJECT return JSON *text* with engine-defined element/"
    "key order and number formatting; the DataFrame produces native list/dict "
    "containers. Representational difference, not a logic divergence."
)
_READ_PRIMITIVES_BRAND_DOMAIN = frozenset(f"Brand#{m}{n}" for m in range(1, 6) for n in range(1, 6))
_ORDER_KEY_MISMATCH_RE = re.compile(
    r"Original key:\s*\('(?P<orig>[^']*)',\),\s*Variant key:\s*\('(?P<variant>[^']*)',\)"
)


def _read_primitives_json_parse(text: str) -> Any:
    import ast
    import json

    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return ast.literal_eval(text)


def _read_primitives_json_equivalent(original: str, variant: str) -> bool:

    def normalize(value: Any) -> Any:
        if isinstance(value, dict):
            return {str(key): normalize(item) for key, item in value.items()}
        if isinstance(value, list):
            return sorted((normalize(item) for item in value), key=str)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return round(float(value), 2)
        return value

    try:
        return normalize(_read_primitives_json_parse(original)) == normalize(_read_primitives_json_parse(variant))
    except (ValueError, SyntaxError):
        return False


def _read_primitives_json_agg_accepts(divergence: SurfaceDivergence) -> bool:
    detail = str(divergence.detail)
    order_match = _ORDER_KEY_MISMATCH_RE.search(detail)
    if order_match is not None:
        return (
            order_match.group("orig") in _READ_PRIMITIVES_BRAND_DOMAIN
            and order_match.group("variant") in _READ_PRIMITIVES_BRAND_DOMAIN
        )
    value_match = _VALUE_MISMATCH_RE.search(detail)
    if value_match is None:
        return False
    if not (_mismatched_columns(value_match) <= {1, 2}):
        return False
    return _read_primitives_json_equivalent(value_match.group("orig"), value_match.group("variant"))


_READ_PRIMITIVES_POLARS_MAP = (
    "Polars (the expression backend) has no native Map dtype, so MAP_FROM_ENTRIES is "
    "unsupported (the query is in the benchmark's SKIP_FOR_POLARS set); there is no "
    "expression-surface result to compare. The pandas surface matches its SQL."
)
_READ_PRIMITIVES_POLARS_MAP_ERROR_SIGNATURE = "not supported on Polars (no native Map dtype)"


def _read_primitives_polars_map_gap(divergence: SurfaceDivergence) -> bool:
    detail = str(divergence.detail)
    return detail.startswith("error: ") and detail.endswith(_READ_PRIMITIVES_POLARS_MAP_ERROR_SIGNATURE)


_READ_PRIMITIVES_SCALE = 0.05

_READ_PRIMITIVES_KNOWN_DIVERGENCES: dict[str, str | ClassifiedDivergence] = {
    **_KNOWN_DIVERGENCES_BASELINE.get("read_primitives", {}),
    **dict.fromkeys(
        (
            "approx_count_distinct_simple_expression",
            "approx_count_distinct_simple_pandas",
            "approx_count_distinct_groupby_expression",
            "approx_count_distinct_groupby_pandas",
            "approx_quantile_groupby_expression",
            "approx_quantile_groupby_pandas",
        ),
        ClassifiedDivergence(_READ_PRIMITIVES_APPROX, _read_primitives_sketch_residue),
    ),
    **dict.fromkeys(
        ("statistical_percentiles_expression", "statistical_percentiles_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_DECIMAL_PERCENTILE, _read_primitives_percentile_decimal_residue),
    ),
    **dict.fromkeys(
        ("optimizer_common_subexpression_expression", "optimizer_common_subexpression_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_DECIMAL_ROUND, _read_primitives_round_decimal_residue),
    ),
    **dict.fromkeys(
        ("min_by_complex_expression", "min_by_complex_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_ARGMIN_TIE, _read_primitives_argmin_tie),
    ),
    **dict.fromkeys(
        ("json_aggregates_expression", "json_aggregates_pandas"),
        ClassifiedDivergence(_READ_PRIMITIVES_JSON_TEXT, _read_primitives_json_agg_accepts),
    ),
    **dict.fromkeys(
        ("map_access_expression", "map_construction_expression", "map_keys_values_expression"),
        ClassifiedDivergence(_READ_PRIMITIVES_POLARS_MAP, _read_primitives_polars_map_gap),
    ),
}
_READ_PRIMITIVES_LEGITIMATELY_EMPTY: dict[Any, str] = {
    **dict.fromkeys(
        ("filter_bigint_selective", "filter_decimal_selective", "filter_decimal_in_list_selective"),
        "Highly selective exact-match filter whose literal does not occur in the bounded "
        "SF=0.05 cell (an orderkey outside the generated range, or an exact DECIMAL price "
        "that the generator never produces), so the SQL reference is empty.",
    ),
    "json_extract_nested": (
        "TPC-H c_comment is free natural-language text, never valid JSON, so "
        "WHERE JSON_VALID(c_comment) matches nothing at any scale - the benchmark has no "
        "JSON source data. The DataFrame surface mirrors the empty result."
    ),
}

_TPCDS_LEGITIMATELY_EMPTY: dict[Any, str] = {
    "3": (
        "The bounded SF=0.01 cell has no December sales for manufacturer 436, so the exact "
        "manufacturing and month predicates produce an empty SQL result mirrored by both DataFrame families."
    ),
    "4": (
        "The bounded cell has no customer with qualifying year-over-year sales in all required channels; "
        "the empty SQL result is mirrored by both DataFrame families."
    ),
    "6": (
        "The bounded cell has no state with at least ten February 2000 sales for items above the category-price "
        "threshold; the empty SQL result is mirrored by both DataFrame families."
    ),
    "8": (
        "The bounded cell has no store sales matching the preferred-customer ZIP cohort for Q1 2002; "
        "the empty SQL result is mirrored by both DataFrame families."
    ),
    "10": (
        "The bounded cell has no customer county and year combination satisfying the required store and web "
        "channel overlap; the empty SQL result is mirrored by both DataFrame families."
    ),
    "11": (
        "The bounded cell has no customer with qualifying store and web revenue growth across the required "
        "years; the empty SQL result is mirrored by both DataFrame families."
    ),
    "24": (
        "The bounded cell has no qualifying store-return rows for the configured item color and market filters; "
        "the empty SQL result is mirrored by both DataFrame families."
    ),
    "31": (
        "The bounded cell has no customer satisfying the six-channel quarterly sales comparison; the empty SQL "
        "result is mirrored by both DataFrame families."
    ),
    "37": (
        "The bounded cell has no inventory and sales combination satisfying the date, manufacturer, and quantity "
        "filters; the empty SQL result is mirrored by both DataFrame families."
    ),
    "39": (
        "The bounded cell has no inventory month pair whose standard-deviation to mean ratio exceeds one; "
        "the empty SQL result is mirrored by both DataFrame families."
    ),
    "41": (
        "The bounded item dimension contains no product satisfying the manufacturer range and correlated attribute "
        "conditions; the empty SQL result is mirrored by both DataFrame families."
    ),
    "49": (
        "The bounded cell has no web, catalog, and store return combination satisfying the December 2000 and "
        "profit thresholds; the empty SQL result is mirrored by both DataFrame families."
    ),
    "53": (
        "The bounded cell has no manager and item combination satisfying the twelve-month sequence and brand or "
        "category filters; the empty SQL result is mirrored by both DataFrame families."
    ),
    "54": (
        "The bounded cell has no jewelry or consignment customer revenue segment for March 1999; the empty SQL "
        "result is mirrored by both DataFrame families."
    ),
    "55": (
        "The bounded cell has no item brand with store sales for manager 36 in December 2001; the empty SQL result "
        "is mirrored by both DataFrame families."
    ),
    "58": (
        "The bounded cell has no item with comparable revenue in all three channels during the week containing the "
        "configured February 1998 date; the empty SQL result is mirrored by both DataFrame families."
    ),
    "63": (
        "The bounded cell has no manager whose twelve-month sales deviation exceeds ten percent for the configured "
        "item filters; the empty SQL result is mirrored by both DataFrame families."
    ),
    "64": (
        "The bounded cell has no cross-year store-sale and catalog-return pair satisfying the refund, demographic, "
        "and price filters; the empty SQL result is mirrored by both DataFrame families."
    ),
    "65": (
        "The bounded cell has no store and item revenue below ten percent of the store average across the configured "
        "month sequence; the empty SQL result is mirrored by both DataFrame families."
    ),
    "73": (
        "The bounded cell has no store ticket in Williamson County satisfying the day-of-month and household "
        "vehicle or dependent filters; the empty SQL result is mirrored by both DataFrame families."
    ),
    "82": (
        "The bounded cell has no item and inventory combination satisfying the May 2002 date window, manufacturer, "
        "price, and quantity filters; the empty SQL result is mirrored by both DataFrame families."
    ),
    "83": (
        "The bounded cell has no item returned in all three channels during the weeks containing the configured "
        "1998 return dates; the empty SQL result is mirrored by both DataFrame families."
    ),
    "85": (
        "The bounded cell has no web return satisfying the 1998 date, customer-demographic, state, and profit "
        "conditions; the empty SQL result is mirrored by both DataFrame families."
    ),
    "91": (
        "The bounded cell has no call-center return satisfying the November 1999 demographic and GMT-offset filters; "
        "the empty SQL result is mirrored by both DataFrame families."
    ),
    "93": (
        "The bounded cell has no store sale joined to a return reason of 'Did not like the warranty'; the empty SQL "
        "result is mirrored by both DataFrame families."
    ),
}


_FLIGHTDATA_SCALE = 0.01
_DATAVAULT_SCALE = 0.01
_TPCH_SCALE = 0.01
_TPCDS_SCALE = 0.01
_NYCTAXI_SCALE = 0.01
_TSBS_DEVOPS_SCALE = 0.01
_TPCH_SKEW_SCALE = 0.01

GATES: dict[str, CrossSurfaceGate] = {
    "ssb": CrossSurfaceGate(
        name="ssb",
        build=build_ssb_duckdb,
        surface_independence=SURFACE_INDEPENDENCE_SHARED_SPEC,
        surface_independence_rationale=(
            "Both DataFrame backends are generated from compact SSB query metadata; the independent "
            "signal is SQL text versus the shared generated DataFrame spec."
        ),
    ),
    "amplab": CrossSurfaceGate(
        name="amplab",
        build=build_amplab_duckdb,
        legitimately_empty=_AMPLAB_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "Expression and pandas DataFrame implementations are separately handwritten for each query, "
            "so the gate has stronger cross-implementation signal than shared-spec generators."
        ),
    ),
    "coffeeshop": CrossSurfaceGate(
        name="coffeeshop",
        build=build_coffeeshop_duckdb,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "Expression and pandas DataFrame implementations are separately handwritten for each query, "
            "so the gate has stronger cross-implementation signal than shared-spec generators."
        ),
    ),
    "clickbench": CrossSurfaceGate(
        name="clickbench",
        build=build_clickbench_duckdb,
        known_divergences={
            **_KNOWN_DIVERGENCES_BASELINE.get("clickbench", {}),
            "Q18_expression": _CLICKBENCH_TIE_AMBIGUOUS,
            "Q18_pandas": _CLICKBENCH_TIE_AMBIGUOUS,
        },
        legitimately_empty=_CLICKBENCH_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_MIXED,
        surface_independence_rationale=(
            "Most ClickBench DataFrame cells are generated from shared compact specs, with a small set "
            "of bespoke implementations; read as mixed provenance, not fully independent implementations."
        ),
    ),
    "joinorder_synthetic": CrossSurfaceGate(
        name="joinorder_synthetic",
        build=build_joinorder_synthetic_duckdb,
        legitimately_empty=_JOINORDER_SYNTHETIC_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_SHARED_SPEC,
        surface_independence_rationale=(
            "Both DataFrame families are generated through shared JoinOrder translation helpers, so the "
            "gate primarily catches SQL-vs-generated-DataFrame transcription drift."
        ),
    ),
    "h2odb": CrossSurfaceGate(
        name="h2odb",
        build=build_h2odb_duckdb,
        known_divergences=_H2ODB_KNOWN_DIVERGENCES,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "H2O-DB expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_H2ODB_SCALE,
    ),
    "read_primitives": CrossSurfaceGate(
        name="read_primitives",
        build=build_read_primitives_duckdb,
        known_divergences=_READ_PRIMITIVES_KNOWN_DIVERGENCES,
        dtype_skip_keys=frozenset(
            {
                "approx_quantile_groupby_expression",
                "json_aggregates_expression",
                "map_access_expression",
                "map_construction_expression",
                "map_keys_values_expression",
            }
        ),
        legitimately_empty=_READ_PRIMITIVES_LEGITIMATELY_EMPTY,
        treat_nan_as_null=True,
        surface_independence=SURFACE_INDEPENDENCE_MIXED,
        surface_independence_rationale=(
            "Read Primitives combines explicit family implementations with factory-built/query-catalog "
            "implementations, so provenance is mixed rather than wholly independent."
        ),
        scale_factor=_READ_PRIMITIVES_SCALE,
    ),
    "flightdata": CrossSurfaceGate(
        name="flightdata",
        build=build_flightdata_duckdb,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "FlightData expression and pandas DataFrame implementations are separately handwritten for each "
            "query (expression helpers plus a compact pandas metadata DSL), so the gate has stronger "
            "cross-implementation signal than shared-spec generators."
        ),
        scale_factor=_FLIGHTDATA_SCALE,
    ),
    "datavault": CrossSurfaceGate(
        name="datavault",
        build=build_datavault_duckdb,
        legitimately_empty=_DATAVAULT_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "Data Vault expression and pandas DataFrame implementations are separately handwritten for each "
            "query, so the gate has stronger cross-implementation signal than shared-spec generators."
        ),
        scale_factor=_DATAVAULT_SCALE,
    ),
    "tpch": CrossSurfaceGate(
        name="tpch",
        build=build_tpch_duckdb,
        legitimately_empty={"17": _TPCH_Q17_VACUOUS},
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "TPC-H expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_TPCH_SCALE,
    ),
    "nyctaxi": CrossSurfaceGate(
        name="nyctaxi",
        build=build_nyctaxi_duckdb,
        legitimately_empty={
            "airport-trips": "Synthetic generator hardcodes rate_code_id=1; query filters rate_code_id IN (2, 3), so the reference returns 0 rows.",
        },
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "NYC Taxi expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_NYCTAXI_SCALE,
    ),
    "tsbs_devops": CrossSurfaceGate(
        name="tsbs_devops",
        build=build_tsbs_devops_duckdb,
        legitimately_empty={
            "high-cpu-1-hr": "Generator caps usage_user at ~55; usage_user > 90 never fires at SF 0.01-0.1.",
            "high-cpu-12-hr": "Generator caps usage_user at ~55; HAVING COUNT(*) > 10 over usage_user > 90 never fires.",
            "low-memory-hosts": "Generator floor for available_percent is ~17; MIN(available_percent) < 10 never fires.",
        },
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "TSBS DevOps expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_TSBS_DEVOPS_SCALE,
    ),
    "tpch_skew": CrossSurfaceGate(
        name="tpch_skew",
        build=build_tpch_skew_duckdb,
        legitimately_empty={
            "8": "Skewed generator emits zero 'ECONOMY ANODIZED STEEL' part rows at SF 0.01-0.1; reference returns 0 rows.",
            "17": _TPCH_SKEW_Q17_VACUOUS,
        },
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "TPC-H Skew expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_TPCH_SKEW_SCALE,
    ),
}


STAGED_GATES: dict[str, CrossSurfaceGate] = {
    "tpcds": CrossSurfaceGate(
        name="tpcds",
        build=build_tpcds_duckdb,
        legitimately_empty=_TPCDS_LEGITIMATELY_EMPTY,
        surface_independence=SURFACE_INDEPENDENCE_SEPARATE,
        surface_independence_rationale=(
            "TPC-DS expression and pandas DataFrame implementations are separately handwritten for each query."
        ),
        scale_factor=_TPCDS_SCALE,
    ),
}


def get_gate(name: str) -> CrossSurfaceGate:
    if name in GATES:
        return GATES[name]
    return STAGED_GATES[name]


_BASELINE_YAML_PATH = Path(__file__).parent / "cross_surface_baseline.yaml"


def _resolved_baseline_keys(
    known: dict[str, str | ClassifiedDivergence], divergences: list[SurfaceDivergence]
) -> list[str]:
    found = {d.key for d in divergences}
    return sorted(key for key, entry in known.items() if key not in found and _requires_live_divergence(entry))


def _apply_baseline_update(
    gate: CrossSurfaceGate,
    divergences: list[SurfaceDivergence],
    total: int,
    coverage: dict[str, int],
    reference_row_counts: dict[Any, int],
    vacuous_cells: int,
) -> int:
    from benchbox.core.equivalence.known_divergences_baseline import update_baseline_file

    resolved = _resolved_baseline_keys(gate.known_divergences, divergences)
    known_after_update = {key: entry for key, entry in gate.known_divergences.items() if key not in resolved}
    exit_code = _report(
        divergences,
        total,
        coverage,
        known_after_update,
        benchmark=gate.name,
        reference_row_counts=reference_row_counts,
        legitimately_empty=gate.legitimately_empty,
        scale_factor=gate.scale_factor,
        vacuous_cells=vacuous_cells,
    )

    if exit_code != 0:
        print(f"{gate.name}: refusing to update baseline - gate reported other failure(s) above; nothing written.")
        return exit_code

    if not resolved:
        print(f"{gate.name}: no resolved known-divergence entries; baseline unchanged.")
        return exit_code

    removed = update_baseline_file(_BASELINE_YAML_PATH, resolved, gate.name)
    if removed:
        print(f"{gate.name}: removed resolved known-divergence baseline entries: {removed}")
    code_only = sorted(set(resolved) - set(removed))
    if code_only:
        print(
            f"{gate.name}: resolved entries {code_only} are code-only (ClassifiedDivergence) and cannot be "
            "auto-pruned; remove them manually from cross_surface.py in a reviewed change."
        )
        return 1
    return exit_code


def run_gate(gate: CrossSurfaceGate, *, update_baseline: bool = False) -> int:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        data = gate.build(gate.scale_factor, Path(tmp))
        connection = data.connection
        reference_row_counts: dict[Any, int] = {}
        try:
            contexts = build_production_contexts(
                data.benchmark, data.data_dir, backends=gate.backends, scale_factor=gate.scale_factor
            )
            divergences = find_cross_surface_divergences(
                connection,
                query_ids=data.query_ids,
                reference_sql=data.reference_sql,
                dataframe_query=data.dataframe_query,
                contexts=contexts,
                validator=gate.build_validator(),
                backends=gate.backends,
                reference_row_counts=reference_row_counts,
            )
            coverage = count_executed_cells(data.query_ids, data.dataframe_query, gate.backends)
            vacuous_cells = count_executed_cells(
                [qid for qid, n in reference_row_counts.items() if n == 0],
                data.dataframe_query,
                gate.backends,
            )
        finally:
            connection.close()

    total = len(data.query_ids) * len(gate.backends)
    vacuous_cells_total = sum(vacuous_cells.values())

    if update_baseline:
        return _apply_baseline_update(gate, divergences, total, coverage, reference_row_counts, vacuous_cells_total)

    return _report(
        divergences,
        total,
        coverage,
        gate.known_divergences,
        benchmark=gate.name,
        reference_row_counts=reference_row_counts,
        legitimately_empty=gate.legitimately_empty,
        scale_factor=gate.scale_factor,
        vacuous_cells=vacuous_cells_total,
    )


def _classification(known: dict[str, str | ClassifiedDivergence], divergence: SurfaceDivergence) -> str | None:
    entry = known.get(divergence.key)
    if entry is None:
        return None
    if isinstance(entry, ClassifiedDivergence):
        return entry.reason if entry.accepts(divergence) else None
    return entry


def _requires_live_divergence(entry: str | ClassifiedDivergence) -> bool:
    return entry.requires_live_divergence if isinstance(entry, ClassifiedDivergence) else True


def _report(
    divergences: list[SurfaceDivergence],
    total: int,
    coverage: dict[str, int],
    known: dict[str, str | ClassifiedDivergence],
    *,
    benchmark: str,
    reference_row_counts: dict[Any, int] | None = None,
    legitimately_empty: dict[Any, str] | None = None,
    scale_factor: float = EQUIVALENCE_SCALE,
    vacuous_cells: int | None = None,
) -> int:
    legitimately_empty = legitimately_empty or {}
    reference_row_counts = reference_row_counts or {}

    found = {d.key for d in divergences}
    new = sorted({d.key for d in divergences if _classification(known, d) is None})
    resolved = sorted(key for key, entry in known.items() if key not in found and _requires_live_divergence(entry))
    missing_backends = sorted(backend for backend, count in coverage.items() if count == 0)
    executed = sum(coverage.values())

    review_due = sorted(
        key
        for key, entry in known.items()
        if isinstance(entry, ClassifiedDivergence) and entry.review_by is not None and entry.review_by < date.today()
    )

    vacuous = sorted(qid for qid, count in reference_row_counts.items() if count == 0)
    classified_empty = [qid for qid in vacuous if qid in legitimately_empty]
    unclassified_empty = [qid for qid in vacuous if qid not in legitimately_empty]

    if vacuous_cells is not None:
        vacuous_executed = vacuous_cells
    else:
        implemented_backends = sum(1 for count in coverage.values() if count)
        vacuous_executed = len(vacuous) * implemented_backends if reference_row_counts else 0
    discriminating = max(executed - vacuous_executed, 0)

    print(f"{benchmark} cross-surface SQL<->DataFrame equivalence @ SF={scale_factor} (DuckDB-backed)")
    print(
        f"  compared {discriminating} of {total} query-backend cells "
        f"({total - executed} not implemented by the DataFrame surface, "
        f"{vacuous_executed} vacuous empty-vs-empty) - {len(divergences)} divergent\n"
    )

    by_class: dict[str, list[SurfaceDivergence]] = {}
    for divergence in sorted(divergences, key=lambda d: d.key):
        klass = _classification(known, divergence) or "UNCLASSIFIED"
        by_class.setdefault(klass, []).append(divergence)
    for klass in sorted(by_class):
        print(f"  [{klass}]")
        for divergence in by_class[klass]:
            print(f"    {divergence.key}: {divergence.detail}")
        print()

    if classified_empty:
        print("  [legitimately-empty - classified, NON-discriminating]")
        for qid in classified_empty:
            print(f"    {qid}: {legitimately_empty[qid]}")
        print()

    if missing_backends:
        print(f"GATE FAILURE - gated backend(s) implement no queries (nothing compared): {missing_backends}")
    if new:
        print(f"GATE FAILURE - unclassified cross-surface divergences: {new}")
    if unclassified_empty:
        print(
            "GATE FAILURE - vacuous empty-vs-empty queries (0 reference rows) not classified "
            f"legitimately_empty: {unclassified_empty} - make them discriminating or classify them with a rationale"
        )
    if resolved:
        print(
            "GATE FAILURE - previously-known divergences now equivalent: "
            f"{resolved} - remove the stale baseline entry in a reviewed change"
        )
    if review_due:
        for key in review_due:
            entry = known[key]
            assert isinstance(entry, ClassifiedDivergence)
            print(f"WAIVER REVIEW DUE - {key}: review_by {entry.review_by} has passed - {entry.reason}")
    if not new and not resolved and not missing_backends and not unclassified_empty:
        suffix = " (modulo classified exceptions)" if (known or classified_empty) else ""
        print(f"SQL and DataFrame surfaces are equivalent{suffix}.")
    return 1 if (new or resolved or missing_backends or unclassified_empty) else 0


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Cross-surface SQL<->DataFrame equivalence gate.")
    parser.add_argument(
        "--benchmark",
        choices=sorted({**GATES, **STAGED_GATES}),
        default="ssb",
        help="Benchmark to gate (default: ssb). Staged gates run in report mode but may diverge.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Explicit maintenance writer: drop any known-divergence entries that no longer "
            "reproduce from this benchmark's YAML baseline (cross_surface_baseline.yaml). "
            "Only writes when the run is otherwise completely clean - any other gate failure "
            "(unclassified divergences, vacuous queries, missing backends) leaves the baseline "
            "untouched and still fails the command (non-zero exit). Idempotent on a second run."
        ),
    )
    args = parser.parse_args(argv)
    return run_gate(get_gate(args.benchmark), update_baseline=args.update_baseline)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
