"""Shared per-query rendering for docs, MCP, and CLI surfaces.

Given a benchmark id and a query id, produce a *representative* rendering of the
query in both SQL and DataFrame form:

* :func:`get_sql_render` returns the query as SQL, translated to a target
  dialect when the benchmark supports translation (most do), otherwise in the
  benchmark's own default dialect.
* :func:`get_dataframe_render` returns the source of the registered DataFrame
  implementation for the matching query, when the benchmark has one.

"Representative" means default parameters and a single reference platform. It is
not the exact statement a specific run executes -- for that, callers substitute
their own ``scale_factor``/``seed``/``dialect`` into ``benchmark.get_query(...)``
directly (this is the call the power test itself makes,
``benchbox/core/tpch/power_test.py``).

Both ``benchbox.mcp.tools.benchmark`` (``get_query_details``) and the query-docs
generator (``scripts/generate_query_docs.py``) render through this module so the
two surfaces cannot drift.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import inspect
import logging
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from benchbox.core.benchmark_registry import (
    get_benchmark_default_scale,
    get_public_benchmark_class,
)

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Reference platform for representative renderings. DataFusion has both a SQL
#: dialect and a DataFrame surface (the "expression" family), so a single
#: reference platform covers both forms.
REFERENCE_DIALECT = "datafusion"
REFERENCE_DATAFRAME_FAMILY = "expression"

#: Substitution tokens that mean a render is still a raw template rather than a
#: runnable statement: qgen-style ``:1`` / ``:x`` / ``:o`` / ``:n`` and
#: ``str.format`` style ``{param}``. Anchored so date/time literals such as
#: ``'2016-01-01 00:00:00'`` do not trigger it.
_TEMPLATE_TOKEN_RE = re.compile(r"(?<![\w'])(:[0-9]+\b|:[xon]\b|\{[a-zA-Z_]\w*\})")


@dataclass(frozen=True)
class SqlRender:
    """A representative SQL rendering of one benchmark query."""

    sql: str
    #: Dialect the SQL is expressed in. ``"default"`` when the benchmark does
    #: not support dialect translation and returned its own native SQL.
    dialect: str
    #: True when ``sql`` still contains unsubstituted parameter tokens.
    is_template: bool


@dataclass(frozen=True)
class DataFrameRender:
    """A representative DataFrame rendering of one benchmark query."""

    source: str
    #: ``"expression"`` or ``"pandas"`` -- which family implementation this is.
    family: str
    query_name: str | None
    description: str | None


@cache
def _benchmark_instance(benchmark_id: str) -> Any | None:
    """Instantiate a benchmark at its default scale, or ``None`` if unavailable.

    Cached: instantiation is cheap but the doc generator asks for the same
    benchmark once per query.
    """
    cls = get_public_benchmark_class(benchmark_id)
    if cls is None:
        return None
    try:
        return cls(scale_factor=get_benchmark_default_scale(benchmark_id))
    except Exception:  # pragma: no cover - benchmark needs optional deps
        logger.debug("query_catalog: cannot instantiate benchmark %r", benchmark_id, exc_info=True)
        return None


def _all_queries(bm: Any, *, dialect: str | None = None) -> dict[str, str]:
    """Return ``bm.get_queries()`` keyed by ``str``.

    With ``dialect`` set, returns the translated set only if the benchmark
    actually accepts and applies ``dialect``; otherwise returns ``{}`` so the
    caller does not mistake an untranslated set for a translated one.
    """
    if dialect is not None:
        try:
            queries = bm.get_queries(dialect=dialect)
        except TypeError:
            return {}
        except Exception:
            logger.debug("query_catalog: get_queries(dialect=%r) failed", dialect, exc_info=True)
            return {}
        return {str(k): v for k, v in (queries or {}).items()}
    try:
        queries = bm.get_queries()
    except Exception:
        return {}
    return {str(k): v for k, v in (queries or {}).items()}


def _normalize_query_key(query_id: str) -> str:
    """Fold ``"Q1"``/``"1"`` and ``"Q1.1"``/``"1.1"`` to a common key."""
    match = re.fullmatch(r"[Qq](\d.*)", query_id)
    return match.group(1) if match else query_id.lower()


def _get_query_accepts_dialect(bm: Any) -> bool:
    """True when ``bm.get_query`` names ``dialect`` explicitly (not via ``**kwargs``).

    Benchmarks that only absorb ``dialect`` into ``**kwargs`` silently ignore it
    and return untranslated SQL, so the render must not be labelled with the
    requested dialect in that case.
    """
    try:
        params = inspect.signature(bm.get_query).parameters
    except (TypeError, ValueError):
        return False
    return "dialect" in params


def _get_query_single(bm: Any, query_id: str, dialect: str | None) -> str | None:
    """Try ``bm.get_query`` with the id shapes benchmarks variously expect."""
    candidates: list[Any] = [query_id]
    if query_id.isdigit():
        candidates.append(int(query_id))
    stripped = query_id[1:] if query_id[:1] in {"Q", "q"} else f"Q{query_id}"
    candidates.append(stripped)
    kwargs = {"dialect": dialect} if dialect else {}
    for candidate in candidates:
        try:
            sql = bm.get_query(candidate, **kwargs)
        except (KeyError, ValueError, TypeError):
            continue
        except Exception:
            logger.debug("query_catalog: get_query(%r) failed", candidate, exc_info=True)
            continue
        if sql:
            return sql
    return None


def list_query_ids(benchmark_id: str) -> list[str]:
    """Return the benchmark's query ids in canonical (definition) order."""
    bm = _benchmark_instance(benchmark_id)
    if bm is None:
        return []
    return list(_all_queries(bm).keys())


def _lookup(queries: dict[str, str], query_id: str) -> str | None:
    """Find ``query_id`` in a query dict, tolerating ``Q``-prefix differences."""
    if query_id in queries:
        return queries[query_id]
    wanted = _normalize_query_key(query_id)
    for key, sql in queries.items():
        if _normalize_query_key(key) == wanted:
            return sql
    return None


def get_sql_render(
    benchmark_id: str,
    query_id: str,
    *,
    dialect: str | None = REFERENCE_DIALECT,
) -> SqlRender | None:
    """Return a representative SQL rendering of ``query_id``.

    With ``dialect`` set: benchmarks whose ``get_query`` names ``dialect`` are
    translated one query at a time (cheap -- avoids regenerating a whole
    qgen/dsqgen query set for one row); the rest go through
    ``get_queries(dialect=...)``. Either translated hit reports that dialect.
    Falls back to ``get_queries()`` / ``get_query(id)`` reporting
    ``dialect="default"``. With ``dialect=None`` no translation is attempted.
    """
    bm = _benchmark_instance(benchmark_id)
    if bm is None:
        return None

    if dialect is not None:
        if _get_query_accepts_dialect(bm):
            sql = _get_query_single(bm, query_id, dialect)
            if sql:
                return _make_sql_render(sql, dialect)
        else:
            sql = _lookup(_all_queries(bm, dialect=dialect), query_id)
            if sql:
                return _make_sql_render(sql, dialect)

    sql = _lookup(_all_queries(bm), query_id)
    if sql:
        return _make_sql_render(sql, "default")

    sql = _get_query_single(bm, query_id, None)
    if sql:
        return _make_sql_render(sql, "default")

    return None


def _make_sql_render(sql: str, dialect: str) -> SqlRender:
    text = sql.strip()
    return SqlRender(sql=text, dialect=dialect, is_template=bool(_TEMPLATE_TOKEN_RE.search(text)))


def _dataframe_registry(benchmark_id: str) -> list[Any]:
    # ``benchbox.core.dataframe`` must import before any
    # ``benchbox.core.<id>.dataframe_queries`` module to avoid a partial-init
    # circular import (benchmark_suite imports the tpch df queries at module load).
    import benchbox.core.dataframe  # noqa: F401
    from benchbox.core.dataframe.query_resolution import registry_dataframe_queries

    try:
        return registry_dataframe_queries(benchmark_id)
    except Exception:
        logger.debug("query_catalog: no DataFrame registry for %r", benchmark_id, exc_info=True)
        return []


def get_dataframe_query(benchmark_id: str, query_id: str) -> Any | None:
    """Return the registered ``DataFrameQuery`` matching ``query_id``, or ``None``."""
    wanted = _normalize_query_key(query_id)
    for query in _dataframe_registry(benchmark_id):
        if _normalize_query_key(str(query.query_id)) == wanted:
            return query
    return None


def get_dataframe_render(
    benchmark_id: str,
    query_id: str,
    *,
    family: str = REFERENCE_DATAFRAME_FAMILY,
) -> DataFrameRender | None:
    """Return the source of the DataFrame implementation for ``query_id``.

    Prefers the requested ``family`` ("expression" or "pandas"), falling back to
    whichever implementation the query defines. ``None`` when the benchmark has
    no DataFrame query for this id.
    """
    query = get_dataframe_query(benchmark_id, query_id)
    if query is None:
        return None

    impl, resolved_family = _resolve_impl(query, family)
    if impl is None:
        return None
    try:
        source = inspect.getsource(impl).strip()
    except (OSError, TypeError):
        return None

    return DataFrameRender(
        source=source,
        family=resolved_family,
        query_name=getattr(query, "query_name", None),
        description=getattr(query, "description", None),
    )


def _resolve_impl(query: Any, family: str) -> tuple[Any | None, str]:
    expr = getattr(query, "expression_impl", None)
    pandas = getattr(query, "pandas_impl", None)
    if family == "pandas" and pandas is not None:
        return pandas, "pandas"
    if family == "expression" and expr is not None:
        return expr, "expression"
    if expr is not None:
        return expr, "expression"
    if pandas is not None:
        return pandas, "pandas"
    return None, family


def _query_info(benchmark_id: str, query_id: str) -> dict[str, Any] | None:
    """Return ``benchmark.get_query_info(id)`` when the benchmark exposes it."""
    bm = _benchmark_instance(benchmark_id)
    if bm is None or not hasattr(bm, "get_query_info"):
        return None
    for candidate in (query_id, f"Q{query_id}", query_id.lstrip("Qq")):
        try:
            info = bm.get_query_info(candidate)
        except Exception:
            continue
        if isinstance(info, dict):
            return info
    return None


def query_display_name(benchmark_id: str, query_id: str) -> str | None:
    """Human name for a query, or ``None`` (caller falls back to the bare id).

    Priority: the benchmark's own ``get_query_info`` -> the DataFrame registry
    entry's ``query_name``.
    """
    info = _query_info(benchmark_id, query_id)
    if info and info.get("name"):
        return str(info["name"])
    query = get_dataframe_query(benchmark_id, query_id)
    if query is not None and getattr(query, "query_name", None):
        return str(query.query_name)
    return None


def query_description(benchmark_id: str, query_id: str) -> str | None:
    """One-line description of a query, or ``None``."""
    info = _query_info(benchmark_id, query_id)
    if info and info.get("description"):
        return str(info["description"])
    query = get_dataframe_query(benchmark_id, query_id)
    if query is not None and getattr(query, "description", None):
        return str(query.description)
    return None


def query_groups(benchmark_id: str) -> dict[str, list[str]] | None:
    """Group a benchmark's query ids by category, or ``None`` if it has no scheme.

    Sources, in order: ``get_query_categories()`` returning a ``{category:
    [ids]}`` map; ``get_query_categories()`` returning category names plus
    ``get_queries_by_category(name)``; a ``category`` field on
    ``get_query_info(id)``. Returned lists are filtered to ids the catalog
    actually lists, in catalog order; ids matched by no group are collected
    under ``"other"``.
    """
    ids = list_query_ids(benchmark_id)
    if not ids:
        return None
    known = set(ids)
    bm = _benchmark_instance(benchmark_id)
    raw: dict[str, list[str]] = {}

    categories = None
    if bm is not None and hasattr(bm, "get_query_categories"):
        try:
            categories = bm.get_query_categories()
        except Exception:
            categories = None

    if isinstance(categories, dict) and categories:
        raw = {str(name): [str(q) for q in members] for name, members in categories.items()}
    elif isinstance(categories, (list, tuple)) and categories and hasattr(bm, "get_queries_by_category"):
        for name in categories:
            try:
                members = bm.get_queries_by_category(name)
            except Exception:
                continue
            keys = list(members.keys()) if isinstance(members, dict) else list(members)
            if keys:
                raw[str(name)] = [str(q) for q in keys]
    else:
        by_info: dict[str, list[str]] = {}
        for query_id in ids:
            info = _query_info(benchmark_id, query_id)
            category = info.get("category") if info else None
            if category:
                by_info.setdefault(str(category), []).append(query_id)
        raw = by_info

    if not raw:
        return None

    grouped: dict[str, list[str]] = {}
    seen: set[str] = set()
    for name, members in raw.items():
        kept = [q for q in ids if q in members and q in known]
        if kept:
            grouped[name] = kept
            seen.update(kept)
    leftover = [q for q in ids if q not in seen]
    if leftover:
        grouped["other"] = leftover
    return grouped or None


def query_source_path(benchmark_id: str, query_id: str) -> str | None:
    """Repo-relative path of the file a query's text comes from, or ``None``."""
    candidates: list[str] = []
    if benchmark_id in {"tpch", "tpch_skew"} and query_id.isdigit():
        candidates.append(f"benchbox/_binaries/tpc-h/templates/queries/{query_id}.sql")
    if benchmark_id == "tpcds" and query_id.isdigit():
        candidates.append(f"_sources/tpc-ds/query_templates/query{query_id}.tpl")
    candidates.append(f"benchbox/core/{benchmark_id}/queries.py")
    candidates.append(f"benchbox/core/{benchmark_id}/operations.py")
    for rel in candidates:
        if (_REPO_ROOT / rel).exists():
            return rel
    return None
