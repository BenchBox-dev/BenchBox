"""Utilities for converting TPC-DS query templates to the OBT schema."""

from __future__ import annotations

import random
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import sqlglot
from sqlglot import exp

from benchbox.core.tpcds_obt.schema import OBT_TABLE_NAME, get_column_lineage

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "_sources" / "tpc-ds" / "query_templates"
# Queries that cannot be converted to OBT:
# - Inventory fact table: Q21, Q22, Q37, Q39, Q72, Q82 (separate fact domain)
# - Require external dimension tables: Q46, Q64, Q68, Q84 (customer's CURRENT address/demographics)
BLOCKED_QUERY_IDS = {21, 22, 37, 39, 46, 64, 68, 72, 82, 84}

# Column prefix → source table mapping (multi-char prefixes before single-char to avoid shadowing).
_PREFIX_TO_TABLE: dict[str, str] = {
    "ss_": "store_sales",
    "sr_": "store_returns",
    "ws_": "web_sales",
    "wr_": "web_returns",
    "cs_": "catalog_sales",
    "cr_": "catalog_returns",
    "sm_": "ship_mode",
    "ca_": "customer_address",
    "hd_": "household_demographics",
    "cd_": "customer_demographics",
    "d_": "date_dim",
    "t_": "time_dim",
    "i_": "item",
    "s_": "store",
    "p_": "promotion",
    "r_": "reason",
    "w_": "warehouse",
}

# Dimension table → static role prefix (for tables whose role doesn't depend on the fact column).
_DIM_STATIC_ROLE: dict[str, str] = {
    "item": "item_",
    "store": "store_",
    "promotion": "promo_",
    "reason": "reason_",
    "web_site": "web_site_",
    "web_page": "web_page_",
    "call_center": "call_center_",
    "catalog_page": "catalog_page_",
    "ship_mode": "ship_mode_",
    "warehouse": "warehouse_",
}
_IDENTIFIER_DEFAULT_FACT_TABLES = {
    "ss_": "store_sales",
    "sr_": "store_returns",
    "ws_": "web_sales",
    "wr_": "web_returns",
    "cs_": "catalog_sales",
    "cr_": "catalog_returns",
}
_CHANNEL_FACT_TABLES = {
    "store": "store_sales",
    "web": "web_sales",
    "catalog": "catalog_sales",
}


@dataclass(frozen=True)
class TemplateParameter:
    """Parameter metadata extracted from a TPC-DS template."""

    name: str
    default: str | int | float
    kind: str  # numeric | string | identifier
    token: str

    def token_expression(self) -> str:
        """Return a parse-friendly token replacement."""
        if self.kind == "numeric":
            return str(self.numeric_token)
        if self.kind == "string":
            return self.token
        return self.token

    @property
    def numeric_token(self) -> int:
        import zlib

        return 9_000_000 + int(zlib.crc32(self.token.encode()) % 1_000_000)

    def render(self, value: Any | None = None) -> str:
        """Render the parameter value as SQL literal or identifier."""
        val = self.default if value is None else value
        if isinstance(val, (int, float)):
            return str(val)
        return str(val)


@dataclass(frozen=True)
class ConvertedQuery:
    """Container for converted query text and metadata."""

    query_id: int
    template_sql: str
    default_sql: str
    parameters: dict[str, TemplateParameter]
    channels: tuple[str, ...]


class ColumnMapper:
    """Maps source TPC-DS column names to OBT equivalents using schema lineage."""

    def __init__(self) -> None:
        lineage = get_column_lineage()
        self.fact_map: dict[tuple[str, str], str] = {}
        self.dimension_map: dict[tuple[str, str, str], str] = {}
        self._role_prefix_map = {
            "promotion": "promo_",
            "reason": "reason_",
            "store": "store_",
            "item": "item_",
            "call_center": "call_center_",
            "catalog_page": "catalog_page_",
            "ship_mode": "ship_mode_",
            "warehouse": "warehouse_",
            "web_site": "web_site_",
            "web_page": "web_page_",
            "sold_date": "sold_date_",
            "sold_time": "sold_time_",
            "ship_date": "ship_date_",
            "ship_time": "ship_time_",
            "return_date": "return_date_",
            "return_time": "return_time_",
            "bill_customer": "bill_customer_",
            "bill_cdemo": "bill_cdemo_",
            "bill_hdemo": "bill_hdemo_",
            "bill_address": "bill_addr_",
            "ship_customer": "ship_customer_",
            "ship_cdemo": "ship_cdemo_",
            "ship_hdemo": "ship_hdemo_",
            "ship_address": "ship_addr_",
            "returning_customer": "returning_customer_",
            "returning_cdemo": "returning_cdemo_",
            "returning_hdemo": "returning_hdemo_",
            "returning_address": "returning_addr_",
            "refunded_customer": "refunded_customer_",
            "refunded_cdemo": "refunded_cdemo_",
            "refunded_hdemo": "refunded_hdemo_",
            "refunded_address": "refunded_addr_",
        }
        self.obt_columns = set(lineage.keys())

        for obt_name, meta in lineage.items():
            source_table = (meta.get("source_table") or "").lower()
            source_column = (meta.get("source_column") or "").lower()
            role = (meta.get("role") or "").lower()
            if not source_table or not source_column:
                continue

            tables = [tbl.strip() for tbl in source_table.split("|")]
            columns = [col.strip() for col in source_column.split("|")]

            if role == "fact":
                for tbl, col in zip(tables, columns):
                    self.fact_map[(tbl, col)] = obt_name
                continue
            prefix = self._prefix_for_role(role, obt_name, source_column)
            if not prefix:
                prefix = self._extract_prefix(obt_name, source_column)
            if prefix:
                self.dimension_map[(tables[0], columns[0], prefix)] = obt_name

    @staticmethod
    def _extract_prefix(obt_name: str, source_col: str) -> str | None:
        if not obt_name.endswith(source_col):
            return None
        return obt_name[: -len(source_col)]

    def _prefix_for_role(self, role: str, obt_name: str, source_column: str) -> str | None:
        if not role:
            return None
        if role in self._role_prefix_map:
            return self._role_prefix_map[role]
        if obt_name.startswith(f"{role}_"):
            return f"{role}_"
        if role.endswith("_dim") and obt_name.startswith(role.replace("_dim", "_")):
            return role.replace("_dim", "_")
        if role in {"date", "time"}:
            return f"{role}_"
        if role == "customer":
            return "bill_customer_"
        if role == "cdemo":
            return "bill_cdemo_"
        if role == "hdemo":
            return "bill_hdemo_"
        return None

    def map_fact(self, table: str, column: str) -> str | None:
        return self.fact_map.get((table.lower(), column.lower()))

    def map_dimension(self, table: str, column: str, role_prefix: str) -> str | None:
        return self.dimension_map.get((table.lower(), column.lower(), role_prefix))


class TemplateLoader:
    """Loads and normalizes raw TPC-DS template text."""

    DEFINE_PATTERN = re.compile(r"^define\s+(\w+)\s*=\s*(.*?);\s*$", re.IGNORECASE)
    PARAM_PATTERN = re.compile(r"\[(\w+)\]")

    def __init__(self, query_id: int, template_dir: Path | None = None) -> None:
        self.query_id = query_id
        self.template_dir = template_dir or TEMPLATE_DIR
        self.path = self.template_dir / f"query{query_id}.tpl"
        if not self.path.exists():
            raise FileNotFoundError(f"Template for query {query_id} not found at {self.path}")

        self.raw_text = self.path.read_text()
        self.definitions: dict[str, str] = {}
        self.body_sql: str = ""
        self.parameters: dict[str, TemplateParameter] = {}
        self.limit_value: int | None = None

        self._parse()

    def _parse(self) -> None:
        lines: list[str] = []
        define_buffer: list[str] = []
        in_define = False

        for line in self.raw_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or not stripped:
                continue

            if in_define:
                define_buffer.append(stripped)
                if stripped.endswith(";"):
                    self._store_definition(" ".join(define_buffer))
                    define_buffer = []
                    in_define = False
                continue

            if stripped.lower().startswith("define"):
                define_buffer.append(stripped)
                if stripped.endswith(";"):
                    self._store_definition(" ".join(define_buffer))
                    define_buffer = []
                    in_define = False
                else:
                    in_define = True
                continue

            lines.append(line)

        self.body_sql = "\n".join(lines).strip()
        self.limit_value = self._parse_limit()
        self._expand_ulist_defaults()
        self.parameters = self._parse_parameters()

    def _store_definition(self, line: str) -> None:
        match = self.DEFINE_PATTERN.match(line)
        if match:
            name, expr = match.groups()
            self.definitions[name] = expr

    def _parse_limit(self) -> int | None:
        raw = self.definitions.get("_LIMIT")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _expand_ulist_defaults(self) -> None:
        """Expand ulist() parameters by replacing indexed [NAME.N] placeholders with generated values."""
        expanded_names: list[str] = []
        for name, expr in self.definitions.items():
            if name.startswith("_"):
                continue
            if not expr.lower().startswith("ulist("):
                continue
            values = self._generate_ulist_values(name, expr)
            if values is None:
                continue  # Unsupported generator — fall back to scalar default
            for i, val in enumerate(values, 1):
                self.body_sql = self.body_sql.replace(f"[{name}.{i}]", str(val))
            # Also replace bare [NAME] with first value (if present)
            self.body_sql = self.body_sql.replace(f"[{name}]", str(values[0]))
            expanded_names.append(name)
        for name in expanded_names:
            del self.definitions[name]

    def _generate_ulist_values(self, name: str, expr: str) -> list[int] | None:
        """Generate distinct values for a ulist() expression. Returns None for unsupported generators."""
        match = re.match(r"ulist\(random\((\d+),(\d+)", expr, re.IGNORECASE)
        if not match:
            return None  # dist() or rowcount() — not yet supported
        lo, hi = int(match.group(1)), int(match.group(2))
        count_match = re.search(r",\s*(\d+)\)\s*$", expr)
        if not count_match:
            return None
        count = int(count_match.group(1))
        rng = random.Random(self.query_id * 1000 + hash(name) % 10000)
        if hi - lo + 1 < count:
            return None  # Range too small for unique values
        return rng.sample(range(lo, hi + 1), count)

    def _parse_parameters(self) -> dict[str, TemplateParameter]:
        params: dict[str, TemplateParameter] = {}
        for name, expr in self.definitions.items():
            if name.startswith("_"):
                continue
            default, kind = self._default_value(expr)
            token = f"__BB_PARAM_{name}__"
            params[name] = TemplateParameter(name=name, default=default, kind=kind, token=token)
        return params

    def _default_value(self, expr: str) -> tuple[str | int | float, str]:
        expr_lower = expr.lower()
        if expr_lower.startswith("random("):
            numbers = re.findall(r"-?\d+", expr)
            if numbers:
                return int(numbers[0]), "numeric"
            return 0, "numeric"

        if expr_lower.startswith("text("):
            match = re.search(r'\{"([^"]+)"', expr)
            if match:
                value = match.group(1)
                kind = "numeric" if value.isdigit() else "identifier"
                return value, kind
            return "value", "string"

        if expr_lower.startswith("date("):
            return "1998-01-01", "string"

        if expr_lower.startswith("ulist("):
            numbers = re.findall(r"-?\d+", expr)
            if numbers:
                return int(numbers[0]), "numeric"
            return 0, "numeric"

        if expr_lower.startswith("dist") or expr_lower.startswith("sub"):
            return 0, "numeric"

        # Fallback to literal expression
        raw = expr.strip('"')
        return raw, "numeric" if raw.isdigit() else "string"

    def substitute_tokens(self, text: str) -> tuple[str, dict[str, TemplateParameter]]:
        """Replace parameter placeholders with parse-friendly tokens."""
        result = text
        for name, param in self.parameters.items():
            replacement = param.token_expression()
            result = result.replace(f"[{name}]", replacement)
        return result, self.parameters

    def substitute_defaults(self, text: str) -> str:
        """Replace placeholders with default literal values."""
        result = text
        for name, param in self.parameters.items():
            result = result.replace(f"[{name}]", param.render())
        return result


def _gather_aliases(select: exp.Select) -> dict[str, str]:
    aliases: dict[str, str] = {}
    # sqlglot 28+ uses "from_" instead of "from"
    from_expr = select.args.get("from") or select.args.get("from_")

    def _record(target: exp.Expression | None) -> None:
        if isinstance(target, exp.Table):
            alias = target.alias or target.name
            aliases[alias] = target.name
        elif isinstance(target, exp.Subquery):
            if target.alias:
                aliases[target.alias] = target.alias

    if isinstance(from_expr, exp.From):
        _record(from_expr.this)

    for join in select.args.get("joins", []) or []:
        if isinstance(join, exp.Join):
            _record(join.this)
    return aliases


def _infer_date_role(fact_column: str) -> str | None:
    if "sold_date" in fact_column:
        return "sold_date_"
    if "sold_time" in fact_column:
        return "sold_time_"
    if "ship_date" in fact_column:
        return "ship_date_"
    if "returned_date" in fact_column or "return_date" in fact_column:
        return "return_date_"
    if "return_time" in fact_column or "returned_time" in fact_column:
        return "return_time_"
    return None


def _infer_customer_role(fact_column: str, fact_table: str) -> str | None:
    if "bill_customer" in fact_column:
        return "bill_customer_"
    if "ship_customer" in fact_column:
        return "ship_customer_"
    if "returning_customer" in fact_column or fact_table.endswith("returns"):
        return "returning_customer_"
    if "refunded_customer" in fact_column:
        return "refunded_customer_"
    if fact_table == "store_sales" and fact_column.endswith("customer_sk"):
        return "bill_customer_"
    return None


def _infer_cdemo_role(fact_column: str, fact_table: str) -> str | None:
    if "bill_cdemo" in fact_column:
        return "bill_cdemo_"
    if "ship_cdemo" in fact_column:
        return "ship_cdemo_"
    if "returning_cdemo" in fact_column or fact_table.endswith("returns"):
        return "returning_cdemo_"
    if "refunded_cdemo" in fact_column:
        return "refunded_cdemo_"
    if fact_table == "store_sales" and fact_column.endswith("cdemo_sk"):
        return "bill_cdemo_"
    return None


def _infer_hdemo_role(fact_column: str, fact_table: str) -> str | None:
    if "bill_hdemo" in fact_column:
        return "bill_hdemo_"
    if "ship_hdemo" in fact_column:
        return "ship_hdemo_"
    if "returning_hdemo" in fact_column or fact_table.endswith("returns"):
        return "returning_hdemo_"
    if "refunded_hdemo" in fact_column:
        return "refunded_hdemo_"
    if fact_table == "store_sales" and fact_column.endswith("hdemo_sk"):
        return "bill_hdemo_"
    return None


def _infer_address_role(fact_column: str, fact_table: str) -> str | None:
    if "bill_addr" in fact_column:
        return "bill_addr_"
    if "ship_addr" in fact_column:
        return "ship_addr_"
    if "returning_addr" in fact_column or fact_table.endswith("returns"):
        return "returning_addr_"
    if "refunded_addr" in fact_column:
        return "refunded_addr_"
    if fact_table == "store_sales" and fact_column.endswith("addr_sk"):
        return "bill_addr_"
    return None


class QueryConverter:
    """Convert a single TPC-DS template into an OBT-ready query."""

    FACT_TABLES = {"store_sales", "web_sales", "catalog_sales", "store_returns", "web_returns", "catalog_returns"}
    DIMENSION_TABLES = {
        "date_dim",
        "time_dim",
        "item",
        "store",
        "promotion",
        "reason",
        "web_site",
        "web_page",
        "call_center",
        "catalog_page",
        "ship_mode",
        "warehouse",
        "customer",
        "customer_demographics",
        "household_demographics",
        "customer_address",
    }

    CHANNEL_BY_TABLE = {
        "store_sales": "store",
        "store_returns": "store",
        "web_sales": "web",
        "web_returns": "web",
        "catalog_sales": "catalog",
        "catalog_returns": "catalog",
    }

    def __init__(self, mapper: ColumnMapper | None = None) -> None:
        self.mapper = mapper or ColumnMapper()
        self._default_dimension_prefix = {
            "date_dim": "sold_date_",
            "time_dim": "sold_time_",
            "item": "item_",
            "promotion": "promo_",
            "reason": "reason_",
            "store": "store_",
            "web_site": "web_site_",
            "web_page": "web_page_",
            "call_center": "call_center_",
            "catalog_page": "catalog_page_",
            "ship_mode": "ship_mode_",
            "warehouse": "warehouse_",
            "customer": "bill_customer_",
            "customer_demographics": "bill_cdemo_",
            "household_demographics": "bill_hdemo_",
            "customer_address": "bill_addr_",
        }
        self._fact_column_names = set(self.mapper.fact_map.values())

    def convert(self, query_id: int) -> ConvertedQuery:
        if query_id in BLOCKED_QUERY_IDS:
            raise ValueError(f"Query {query_id} cannot be converted due to missing source tables.")

        template = TemplateLoader(query_id)
        channels = self._detect_channels(template.body_sql)
        channel = next(iter(channels)) if len(channels) == 1 else None

        params = self._normalize_identifier_defaults(template.parameters, channel)
        normalized_sql = self._apply_limit_macros(template.body_sql, template.limit_value)
        tokenized_sql = self._apply_param_tokens(normalized_sql, params)

        converted = self._rewrite_sql(tokenized_sql, channels)
        template_sql = self._restore_placeholders(converted, params.values())
        default_sql = self._apply_defaults(template_sql, params.values())
        template_sql = self._normalize_intervals(template_sql)
        default_sql = self._normalize_intervals(default_sql)
        template_sql = self._post_process(query_id, template_sql)
        default_sql = self._post_process(query_id, default_sql)

        return ConvertedQuery(
            query_id=query_id,
            template_sql=template_sql,
            default_sql=default_sql,
            parameters=params,
            channels=tuple(sorted(channels)),
        )

    def _detect_channels(self, sql_text: str) -> set[str]:
        channels: set[str] = set()
        lowered = sql_text.lower()
        for table, channel in self.CHANNEL_BY_TABLE.items():
            if table in lowered:
                channels.add(channel)
        return channels

    def _apply_limit_macros(self, sql_text: str, limit_value: int | None) -> str:
        sql = sql_text.replace("[_LIMITA]", "").replace("[_LIMITB]", "")
        if "[_LIMITC]" in sql:
            limit_clause = f"LIMIT {limit_value}" if limit_value is not None else ""
            sql = sql.replace("[_LIMITC]", limit_clause)
        return sql

    def _apply_param_tokens(self, sql_text: str, params: dict[str, TemplateParameter]) -> str:
        result = sql_text
        for param in params.values():
            pattern = self._param_pattern(param.name)
            result = pattern.sub(param.token_expression(), result)
        return result

    def _rewrite_sql(self, sql_text: str, channels: set[str]) -> str:
        parsed = sqlglot.parse_one(sql_text, read="postgres")
        rewritten = self._rewrite_expression(parsed, channels)
        return rewritten.sql(dialect="duckdb", pretty=True)

    def _rewrite_expression(self, expression: exp.Expression, channels: set[str]) -> exp.Expression:
        if isinstance(expression, exp.Select):
            self._rewrite_select(expression, channels)

        for arg in expression.args.values():
            if isinstance(arg, exp.Expression):
                self._rewrite_expression(arg, channels)
            elif isinstance(arg, list):
                for item in arg:
                    if isinstance(item, exp.Expression):
                        self._rewrite_expression(item, channels)
        return expression

    def _rewrite_select(self, select: exp.Select, channels: set[str]) -> None:
        aliases = _gather_aliases(select)
        select_channels = self._channels_for_aliases(aliases) or channels
        subquery_aliases: dict[str, exp.Subquery] = {}
        joins_arg = select.args.get("joins", [])
        # sqlglot 28+ uses "from_" instead of "from"
        from_expr = select.args.get("from") or select.args.get("from_")
        if isinstance(from_expr, exp.From) and isinstance(from_expr.this, exp.Subquery) and from_expr.this.alias:
            subquery_aliases[from_expr.this.alias] = from_expr.this
        for join in joins_arg:
            if isinstance(join, exp.Join) and isinstance(join.this, exp.Subquery) and join.this.alias:
                subquery_aliases[join.this.alias] = join.this
        base_aliases = [
            alias for alias, table in aliases.items() if table in self.FACT_TABLES or table in self.DIMENSION_TABLES
        ]
        extra_aliases = [
            alias
            for alias, table in aliases.items()
            if table not in self.FACT_TABLES and table not in self.DIMENSION_TABLES
        ]
        role_map = self._infer_roles(select, aliases)
        self._rewrite_columns(select, aliases, role_map, has_obt=bool(base_aliases))
        if "wscs" in extra_aliases:
            extra_aliases = [alias for alias in extra_aliases if alias != "wscs"]

        join_conditions = [join.args["on"] for join in joins_arg if join.args.get("on")]

        where_clauses: list[exp.Expression] = []
        if select.args.get("where"):
            where_clauses.append(select.args["where"].this)
        where_clauses.extend(join_conditions)
        if select_channels and base_aliases:
            channel_predicate = self._build_channel_predicate(select_channels)
            if channel_predicate is not None:
                where_clauses.append(channel_predicate)

        if where_clauses:
            combined = where_clauses[0]
            for clause in where_clauses[1:]:
                combined = exp.and_(combined, clause)
            select.set("where", exp.Where(this=combined))

        if not base_aliases:
            return

        if base_aliases:
            table_expr = exp.table_(OBT_TABLE_NAME, alias="obt")
            select.set("joins", [])
            # sqlglot 28+ uses "from_" instead of "from"
            select.set("from_", exp.From(this=table_expr))
            joins: list[exp.Join] = []
            for alias in extra_aliases:
                subquery = subquery_aliases.get(alias)
                if subquery:
                    joins.append(exp.Join(this=subquery, kind="cross"))
                    continue
                table_name = aliases.get(alias, alias)
                joins.append(
                    exp.Join(
                        this=exp.Table(
                            this=exp.to_identifier(table_name),
                            alias=exp.TableAlias(this=exp.to_identifier(alias)),
                        ),
                        kind="cross",
                    )
                )
        if joins:
            select.set("joins", joins)
        elif extra_aliases:
            first = extra_aliases[0]
            table_name = aliases.get(first, first)
            table_expr = exp.Table(
                this=exp.to_identifier(table_name),
                alias=exp.TableAlias(this=exp.to_identifier(first)),
            )
            # sqlglot 28+ uses "from_" instead of "from"
            select.set("from_", exp.From(this=table_expr))
            joins = []
            for alias in extra_aliases[1:]:
                table_name = aliases.get(alias, alias)
                joins.append(
                    exp.Join(
                        this=exp.Table(
                            this=exp.to_identifier(table_name),
                            alias=exp.TableAlias(this=exp.to_identifier(alias)),
                        ),
                        kind="cross",
                    )
                )
            if joins:
                select.set("joins", joins)

    @staticmethod
    def _build_channel_predicate(channels: set[str]) -> exp.Expression | None:
        """Return a predicate that constrains the canonical channel column."""
        if not channels:
            return None
        column = exp.column("channel")
        if len(channels) == 1:
            return exp.EQ(this=column, expression=exp.Literal.string(next(iter(channels))))
        values = [exp.Literal.string(channel) for channel in sorted(channels)]
        return exp.In(this=column, expressions=values)

    def _channels_for_aliases(self, aliases: dict[str, str]) -> set[str]:
        """Return channels implied by the fact table aliases in this select."""
        return {self.CHANNEL_BY_TABLE[table] for table in aliases.values() if table in self.CHANNEL_BY_TABLE}

    def _rewrite_columns(
        self, select: exp.Select, aliases: dict[str, str], role_map: dict[str, str], *, has_obt: bool
    ) -> None:
        for column in select.find_all(exp.Column):
            table_alias = column.table
            name = column.name
            source_table: str | None = None
            if not table_alias:
                new_name = self._map_unqualified_column(name, aliases, role_map)
            else:
                source_table = aliases.get(table_alias)
                new_name = None
                if source_table:
                    role_prefix = role_map.get(table_alias)
                    if source_table in self.DIMENSION_TABLES:
                        prefix = role_prefix or self._default_dimension_prefix.get(source_table)
                        if prefix:
                            new_name = self.mapper.map_dimension(source_table, name, prefix)
                    elif source_table in self.FACT_TABLES:
                        new_name = self.mapper.map_fact(
                            source_table, f"{table_alias}_{name}" if "_" not in name else name
                        )
                        if new_name is None:
                            new_name = self.mapper.map_fact(source_table, name)
            if not new_name and name in getattr(self.mapper, "obt_columns", set()):
                new_name = name
                source_table = source_table or "fact"
            if not new_name and name in self._fact_column_names:
                new_name = name
                source_table = source_table or "fact"
            if new_name:
                column.set("this", exp.to_identifier(new_name))
                if has_obt and source_table and (source_table in self.FACT_TABLES or source_table == "fact"):
                    column.set("table", "obt")
                else:
                    column.set("table", None)

    # Mapping from column prefix to (dimension_table, default_role_prefix) for simple dimension lookups.
    # IMPORTANT: Iteration order matters — "w_" must precede "web_" because both match "web_*" columns,
    # and warehouse columns (w_warehouse_*) should match "w_" first. Do not reorder these entries.
    _SIMPLE_DIMENSION_PREFIX_MAP: dict[str, tuple[str, str]] = {
        "p_": ("promotion", "promo_"),
        "r_": ("reason", "reason_"),
        "cp_": ("catalog_page", "catalog_page_"),
        "cc_": ("call_center", "call_center_"),
        "sm_": ("ship_mode", "ship_mode_"),
        "w_": ("warehouse", "warehouse_"),
        "wp_": ("web_page", "web_page_"),
        "web_": ("web_site", "web_site_"),
    }

    # Mapping from column prefix to (dimension_table, default_role_prefix) for alias-aware dimension lookups.
    _ALIASED_DIMENSION_PREFIX_MAP: dict[str, tuple[str, str]] = {
        "c_": ("customer", "bill_customer_"),
        "cd_": ("customer_demographics", "bill_cdemo_"),
        "hd_": ("household_demographics", "bill_hdemo_"),
        "ca_": ("customer_address", "bill_addr_"),
        "s_": ("store", "store_"),
    }

    # Mapping from return column prefix to channel for return reference lookups.
    _RETURN_PREFIX_CHANNEL_MAP: dict[str, str] = {
        "sr_": "store",
        "wr_": "web",
        "cr_": "catalog",
    }

    def _map_unqualified_column(self, name: str, aliases: dict[str, str], role_map: dict[str, str]) -> str | None:
        lowered = name.lower()

        # Try fact table prefixes first
        mapped = self._map_fact_column(lowered)
        if mapped:
            return mapped

        # Item dimension
        if lowered.startswith("i_"):
            alias_for_item = self._alias_for_table(aliases, "item")
            role_prefix = role_map.get(alias_for_item or "", "item_")
            return self.mapper.map_dimension("item", lowered, role_prefix)

        # Date dimension (fall through if not found — column may match later prefixes)
        if lowered.startswith("d_"):
            mapped = self._map_date_dimension_column(lowered, aliases, role_map)
            if mapped:
                return mapped

        # Return reference columns
        mapped = self._map_return_prefix_column(lowered, role_map, aliases)
        if mapped:
            return mapped

        # Store with numeric suffix (s_store_name1 etc.) — checked before s_ prefix
        if lowered.startswith("s_store_"):
            return self._map_store_numeric_suffix(lowered, aliases, role_map)

        # Alias-aware dimension columns (customer, demographics, address, store)
        mapped = self._map_aliased_dimension_column(lowered, aliases, role_map)
        if mapped:
            return mapped

        # Simple dimension columns (no alias resolution needed)
        return self._map_simple_dimension_column(lowered)

    def _map_fact_column(self, lowered: str) -> str | None:
        """Map a column to a fact table based on its prefix."""
        fact_prefix_map = {
            "ss_": "store_sales",
            "sr_": "store_returns",
            "ws_": "web_sales",
            "wr_": "web_returns",
            "cs_": "catalog_sales",
            "cr_": "catalog_returns",
        }
        for prefix, table in fact_prefix_map.items():
            if lowered.startswith(prefix):
                mapped = self.mapper.map_fact(table, lowered)
                if mapped:
                    return mapped
        return None

    def _map_date_dimension_column(self, lowered: str, aliases: dict[str, str], role_map: dict[str, str]) -> str | None:
        """Map a date dimension column with alias-aware role prefix."""
        alias_for_date = self._alias_for_table(aliases, "date_dim")
        role_prefix = role_map.get(alias_for_date or "", "sold_date_")
        return self.mapper.map_dimension("date_dim", lowered, role_prefix)

    def _map_return_prefix_column(self, lowered: str, role_map: dict[str, str], aliases: dict[str, str]) -> str | None:
        """Map return-prefixed columns (sr_, wr_, cr_) via return reference lookup."""
        for prefix, channel in self._RETURN_PREFIX_CHANNEL_MAP.items():
            if lowered.startswith(prefix):
                mapped = self._map_return_reference(lowered, role_map, aliases, channel=channel)
                if mapped:
                    return mapped
        return None

    def _map_aliased_dimension_column(
        self, lowered: str, aliases: dict[str, str], role_map: dict[str, str]
    ) -> str | None:
        """Map dimension columns that require alias resolution for role prefix."""
        for prefix, (dim_table, default_role) in self._ALIASED_DIMENSION_PREFIX_MAP.items():
            if lowered.startswith(prefix):
                alias = self._alias_for_table(aliases, dim_table)
                role_prefix = role_map.get(alias or "", default_role)
                return self.mapper.map_dimension(dim_table, lowered, role_prefix)
        return None

    def _map_store_numeric_suffix(self, lowered: str, aliases: dict[str, str], role_map: dict[str, str]) -> str | None:
        """Map store columns with numeric suffix (e.g., s_store_name1)."""
        base = re.sub(r"\d+$", "", lowered)
        alias_for_store = self._alias_for_table(aliases, "store")
        role_prefix = role_map.get(alias_for_store or "", "store_")
        return self.mapper.map_dimension("store", base, role_prefix)

    def _map_simple_dimension_column(self, lowered: str) -> str | None:
        """Map dimension columns that use a fixed role prefix (no alias resolution)."""
        for prefix, (dim_table, role_prefix) in self._SIMPLE_DIMENSION_PREFIX_MAP.items():
            if lowered.startswith(prefix):
                return self.mapper.map_dimension(dim_table, lowered, role_prefix)
        return None

    @staticmethod
    def _alias_for_table(aliases: dict[str, str], table_name: str) -> str | None:
        for alias, table in aliases.items():
            if table == table_name:
                return alias
        return None

    def _map_return_reference(
        self, name: str, role_map: dict[str, str], aliases: dict[str, str], channel: str
    ) -> str | None:
        role_prefix = "returning_"
        if "refunded" in name:
            role_prefix = "refunded_"

        role_prefix_map = {
            "customer_sk": f"{role_prefix}customer_",
            "cdemo_sk": f"{role_prefix}cdemo_",
            "hdemo_sk": f"{role_prefix}hdemo_",
            "addr_sk": f"{role_prefix}addr_",
        }

        for suffix, prefix in role_prefix_map.items():
            if name.endswith(suffix):
                table_name = (
                    "customer"
                    if "customer" in suffix
                    else "customer_demographics"
                    if "cdemo" in suffix
                    else "household_demographics"
                    if "hdemo" in suffix
                    else "customer_address"
                )
                source_column = {
                    "customer": "c_customer_sk",
                    "customer_demographics": "cd_demo_sk",
                    "household_demographics": "hd_demo_sk",
                    "customer_address": "ca_address_sk",
                }[table_name]
                alias = self._alias_for_table(aliases, table_name) or ""
                role = role_map.get(alias, prefix)
                return self.mapper.map_dimension(table_name, source_column, role)

        if name.endswith("reason_sk"):
            return self.mapper.map_dimension("reason", "r_reason_sk", "reason_") or self.mapper.map_fact(
                f"{channel}_returns", name
            )

        if name.endswith("ticket_number") or name.endswith("order_number"):
            return "sale_id"

        if name.endswith("item_sk"):
            return "item_sk"

        return None

    @staticmethod
    def _table_from_prefix(column_name: str) -> str | None:
        lowered = column_name.lower()
        for prefix, table in _PREFIX_TO_TABLE.items():
            if lowered.startswith(prefix):
                return table
        return None

    def _infer_roles(self, select: exp.Select, aliases: dict[str, str]) -> dict[str, str]:
        role_map: dict[str, str] = {}

        conditions: list[exp.Expression] = []
        for join in select.args.get("joins", []):
            condition = join.args.get("on")
            if condition:
                conditions.append(condition)

        where_expr = select.args.get("where")
        if where_expr:
            conditions.append(where_expr.this)

        for condition in conditions:
            for left, right in self._extract_column_pairs(condition):
                left_alias = left.table or self._table_from_prefix(left.name)
                right_alias = right.table or self._table_from_prefix(right.name)

                left_alias = left_alias or self._alias_for_table(aliases, self._table_from_prefix(left.name) or "")
                right_alias = right_alias or self._alias_for_table(aliases, self._table_from_prefix(right.name) or "")

                left_table = aliases.get(left_alias, self._table_from_prefix(left.name) or "")
                right_table = aliases.get(right_alias, self._table_from_prefix(right.name) or "")
                self._update_role_map(role_map, left_table, right_table, left.name, right.name, left_alias, right_alias)
                self._update_role_map(role_map, right_table, left_table, right.name, left.name, right_alias, left_alias)

        return role_map

    def _update_role_map(
        self,
        role_map: dict[str, str],
        dim_table: str,
        fact_table: str,
        _dim_col: str,
        fact_col: str,
        dim_alias: str | None,
        fact_alias: str | None,
    ) -> None:
        if not dim_alias or not fact_alias:
            return
        if dim_table not in self.DIMENSION_TABLES or fact_table not in self.FACT_TABLES:
            return

        dim_table_lower = dim_table.lower()
        fact_col_lower = fact_col.lower()
        fact_table_lower = fact_table.lower()

        if dim_table_lower in ("date_dim", "time_dim"):
            role = _infer_date_role(fact_col_lower)
        elif dim_table_lower in _DIM_STATIC_ROLE:
            role = _DIM_STATIC_ROLE[dim_table_lower]
        elif dim_table_lower == "customer":
            role = _infer_customer_role(fact_col_lower, fact_table_lower)
        elif dim_table_lower == "customer_demographics":
            role = _infer_cdemo_role(fact_col_lower, fact_table_lower)
        elif dim_table_lower == "household_demographics":
            role = _infer_hdemo_role(fact_col_lower, fact_table_lower)
        elif dim_table_lower == "customer_address":
            role = _infer_address_role(fact_col_lower, fact_table_lower)
        else:
            role = None

        if role:
            role_map[dim_alias] = role

    def _extract_column_pairs(self, condition: exp.Expression) -> Iterable[tuple[exp.Column, exp.Column]]:
        pairs: list[tuple[exp.Column, exp.Column]] = []
        for comparison in condition.find_all(exp.EQ):
            left = comparison.left
            right = comparison.right
            if isinstance(left, exp.Column) and isinstance(right, exp.Column):
                pairs.append((left, right))
        return pairs

    def _restore_placeholders(self, sql_text: str, params: Iterable[TemplateParameter]) -> str:
        restored = sql_text
        for param in params:
            placeholder = f"[{param.name}]"
            pattern = self._param_pattern(param.name)
            restored = restored.replace(param.token_expression(), placeholder)
            restored = restored.replace(param.token, placeholder)
            restored = pattern.sub(placeholder, restored)
        return restored

    def _apply_defaults(self, template_sql: str, params: Iterable[TemplateParameter]) -> str:
        rendered = template_sql
        for param in params:
            pattern = self._param_pattern(param.name)
            rendered = pattern.sub(param.render(), rendered)
        return rendered

    def _normalize_identifier_defaults(
        self, params: dict[str, TemplateParameter], channel: str | None
    ) -> dict[str, TemplateParameter]:
        normalized: dict[str, TemplateParameter] = {}
        for name, param in params.items():
            default = param.default
            if param.kind == "identifier":
                mapped = self._map_identifier_default(str(default), channel)
                default = mapped or default
            normalized[name] = TemplateParameter(name=name, default=default, kind=param.kind, token=param.token)
        return normalized

    def _map_identifier_default(self, value: str, channel: str | None) -> str | None:
        lowered = value.lower()
        table_hint = next(
            (table for prefix, table in _IDENTIFIER_DEFAULT_FACT_TABLES.items() if lowered.startswith(prefix)), None
        )
        if table_hint:
            mapped = self.mapper.map_fact(table_hint, lowered)
            if mapped:
                return mapped

        if channel:
            table_hint = _CHANNEL_FACT_TABLES.get(channel)
            if table_hint:
                mapped = self.mapper.map_fact(table_hint, lowered)
                if mapped:
                    return mapped
        return None

    @staticmethod
    def _normalize_intervals(sql_text: str) -> str:
        normalized = re.sub(r"\+\s*([0-9]+)\s+as\s+days", r"+ INTERVAL \1 DAY", sql_text, flags=re.IGNORECASE)
        normalized = re.sub(r"\+\s*([0-9]+)\s+days", r"+ INTERVAL \1 DAY", normalized, flags=re.IGNORECASE)
        return normalized

    def _post_process(self, query_id: int, sql_text: str) -> str:
        """Apply query-specific fixes after AST rewriting."""
        # Q2: Fix CTE column references for week sequence comparison
        if query_id == 2:
            # The wswscs CTE needs d_week_seq alias - it comes from joining with date_dim
            sql_text = sql_text.replace(
                "obt.sold_date_d_week_seq,\n    SUM(",
                "obt.sold_date_d_week_seq AS d_week_seq,\n    SUM(",
            )
            # Also need to alias in GROUP BY
            sql_text = sql_text.replace(
                "GROUP BY\n  obt.sold_date_d_week_seq",
                "GROUP BY\n  d_week_seq",
            )
            sql_text = sql_text.replace(
                "GROUP BY\n    obt.sold_date_d_week_seq",
                "GROUP BY\n    d_week_seq",
            )
            # Include year information in the wswscs CTE so we can filter without rejoining
            sql_text = sql_text.replace(
                "  SELECT\n    obt.sold_date_d_week_seq AS d_week_seq,\n    SUM(",
                "  SELECT\n    obt.sold_date_d_week_seq AS d_week_seq,\n    obt.sold_date_d_year AS d_year,\n    SUM(",
            )
            sql_text = sql_text.replace(
                "GROUP BY\n  d_week_seq",
                "GROUP BY\n  d_week_seq,\n  d_year",
            )
            sql_text = sql_text.replace(
                "GROUP BY\n    d_week_seq",
                "GROUP BY\n    d_week_seq,\n    d_year",
            )
            # Replace the expensive joins in the y/z subqueries with direct filtering on d_year
            wswscs_block = re.compile(
                r"  FROM tpcds_sales_returns_obt AS obt\n"
                r"  CROSS JOIN wswscs AS wswscs\n"
                r"  WHERE\n"
                r"    \(\n"
                r"      sold_date_d_week_seq = wswscs.d_week_seq AND obt.sold_date_d_year = ([^\n]+)\n"
                r"    \)\n"
                r"    AND channel IN \('catalog', 'web'\)\n"
            )

            def _wswscs_replacement(match: re.Match[str]) -> str:
                year_expr = match.group(1)
                return f"  FROM wswscs AS wswscs\n  WHERE\n    (\n      d_year = {year_expr}\n    )\n"

            sql_text = wswscs_block.sub(_wswscs_replacement, sql_text, count=1)
            sql_text = wswscs_block.sub(_wswscs_replacement, sql_text, count=1)

        # Q8: Value list V1 needs ca_zip column preserved - rewrite the subquery structure
        if query_id == 8:
            # The subquery structure needs to expose ca_zip properly
            sql_text = sql_text.replace(
                "SELECT\n    bill_addr_ca_zip\n  FROM (",
                "SELECT\n    ca_zip\n  FROM (",
            )
            sql_text = sql_text.replace(
                "SUBSTRING(obt.bill_addr_ca_zip, 1, 5) AS ca_zip",
                "SUBSTRING(bill_addr_ca_zip, 1, 5) AS ca_zip",
            )

        # Q14: Fix cross_items CTE - need to add columns and qualify references
        if query_id == 14:
            # First fix the cross_items CTE to include needed columns
            sql_text = sql_text.replace(
                "SELECT\n    obt.item_i_item_sk AS ss_item_sk\n  FROM tpcds_sales_returns_obt AS obt",
                "SELECT\n    obt.item_i_item_sk AS ss_item_sk,\n    obt.item_i_brand_id AS brand_id,\n    obt.item_i_class_id AS class_id,\n    obt.item_i_category_id AS category_id\n  FROM tpcds_sales_returns_obt AS obt",
            )
            # Then fix the references to use the CTE
            sql_text = sql_text.replace("= brand_id", "= cross_items.brand_id")
            sql_text = sql_text.replace("= class_id", "= cross_items.class_id")
            sql_text = sql_text.replace("= category_id", "= cross_items.category_id")

        # Q16: NOT EXISTS with return tables - convert to OBT with has_return check
        if query_id == 16:
            sql_text = sql_text.replace(
                "obt.sale_id = cr1.cr_order_number AND channel = 'catalog'",
                "obt.sale_id = obt.sale_id AND obt.has_return = 'Y' AND obt.channel = 'catalog'",
            )

        # Q31: Fix CTE references - CTEs produce columns with obt. prefix but are referenced without
        if query_id == 31:
            # Fix ss CTE output column aliases
            sql_text = sql_text.replace(
                "obt.bill_addr_ca_county,\n    obt.sold_date_d_qoy,\n    obt.sold_date_d_year,\n    SUM(obt.ext_sales_price) AS store_sales",
                "obt.bill_addr_ca_county AS ca_county,\n    obt.sold_date_d_qoy AS d_qoy,\n    obt.sold_date_d_year AS d_year,\n    SUM(obt.ext_sales_price) AS store_sales",
            )
            # Fix ws CTE output column aliases
            sql_text = sql_text.replace(
                "obt.bill_addr_ca_county,\n    obt.sold_date_d_qoy,\n    obt.sold_date_d_year,\n    SUM(obt.ext_sales_price) AS web_sales",
                "obt.bill_addr_ca_county AS ca_county,\n    obt.sold_date_d_qoy AS d_qoy,\n    obt.sold_date_d_year AS d_year,\n    SUM(obt.ext_sales_price) AS web_sales",
            )
            # Update GROUP BY to use original column names
            sql_text = sql_text.replace(
                "GROUP BY\n    obt.bill_addr_ca_county,\n    obt.sold_date_d_qoy,\n    obt.sold_date_d_year",
                "GROUP BY\n    ca_county,\n    d_qoy,\n    d_year",
            )

        # Q34, Q46, Q68: Ambiguous columns between obt (main) and subquery (also named obt)
        # Solution: Rename the inner subquery's obt to sub_obt
        if query_id in {34, 46, 68}:
            # Rename the inner subquery's obt alias to avoid conflict
            sql_text = sql_text.replace(
                "CROSS JOIN (\n  SELECT\n    obt.sale_id,\n    obt.ship_customer_sk",
                "CROSS JOIN (\n  SELECT\n    sub_obt.sale_id AS dn_sale_id,\n    sub_obt.ship_customer_sk AS dn_ship_customer_sk",
            )
            sql_text = sql_text.replace(
                "FROM tpcds_sales_returns_obt AS obt\n  WHERE\n    (\n      obt.sold_date_sk",
                "FROM tpcds_sales_returns_obt AS sub_obt\n  WHERE\n    (\n      sub_obt.sold_date_sk",
            )
            # Fix references inside the subquery
            sql_text = sql_text.replace("obt.store_sk = store_s_store_sk", "sub_obt.store_sk = store_s_store_sk")
            sql_text = sql_text.replace("obt.ship_hdemo_sk", "sub_obt.ship_hdemo_sk")
            sql_text = sql_text.replace("obt.bill_hdemo_sk", "sub_obt.bill_hdemo_sk")
            # Fix the GROUP BY and HAVING clauses
            sql_text = sql_text.replace(
                "GROUP BY\n    obt.sale_id,\n    obt.ship_customer_sk",
                "GROUP BY\n    sub_obt.sale_id,\n    sub_obt.ship_customer_sk",
            )
            # Add alias for the subquery result
            sql_text = sql_text.replace(
                ") AS dn\nWHERE",
                ") AS dn\nWHERE\n  obt.sale_id = dn.dn_sale_id AND obt.ship_customer_sk = dn.dn_ship_customer_sk AND",
            )
            if query_id == 68:
                sql_text = sql_text.replace("  extended", "  obt.list_price AS extended")
            if query_id == 46:
                sql_text = sql_text.replace("  amt", "  obt.ext_sales_price AS amt")

        # Q79: Same CROSS JOIN → filtered join fix as Q34/Q46/Q68.
        # The subquery (aliased ms) must be joined on sale_id + ship_customer_sk,
        # and the inner obt alias must be renamed to avoid ambiguity.
        if query_id == 79:
            # Rename inner subquery's SELECT columns to avoid ambiguity
            sql_text = sql_text.replace(
                "CROSS JOIN (\n  SELECT\n    obt.sale_id,\n    obt.ship_customer_sk",
                "CROSS JOIN (\n  SELECT\n    sub_obt.sale_id AS ms_sale_id,\n    sub_obt.ship_customer_sk AS ms_ship_customer_sk",
            )
            # Rename inner FROM alias
            sql_text = sql_text.replace(
                "FROM tpcds_sales_returns_obt AS obt\n  WHERE\n    (\n      obt.sold_date_sk",
                "FROM tpcds_sales_returns_obt AS sub_obt\n  WHERE\n    (\n      sub_obt.sold_date_sk",
            )
            # Fix inner subquery column references
            sql_text = sql_text.replace("obt.store_sk = store_s_store_sk", "sub_obt.store_sk = store_s_store_sk")
            sql_text = sql_text.replace("obt.ship_hdemo_sk", "sub_obt.ship_hdemo_sk")
            sql_text = sql_text.replace("obt.coupon_amt", "sub_obt.coupon_amt")
            sql_text = sql_text.replace("obt.net_profit", "sub_obt.net_profit")
            # Fix inner GROUP BY
            sql_text = sql_text.replace(
                "GROUP BY\n    obt.sale_id,\n    obt.ship_customer_sk,\n    obt.ship_addr_sk",
                "GROUP BY\n    sub_obt.sale_id,\n    sub_obt.ship_customer_sk,\n    sub_obt.ship_addr_sk",
            )
            # Add join condition between outer obt and subquery ms
            sql_text = sql_text.replace(
                ") AS ms\nWHERE",
                ") AS ms\nWHERE\n  obt.sale_id = ms.ms_sale_id AND obt.ship_customer_sk = ms.ms_ship_customer_sk AND",
            )
            # Disambiguate outer SELECT/ORDER BY references
            sql_text = sql_text.replace("  sale_id,\n  amt", "  obt.sale_id,\n  amt")
            sql_text = sql_text.replace("SUBSTRING(store_s_city", "SUBSTRING(obt.store_s_city")
            sql_text = re.sub(r"(?<![a-z_\.])bill_customer_c_", "obt.bill_customer_c_", sql_text)
            sql_text = sql_text.replace("obt.obt.bill_customer_c_", "obt.bill_customer_c_")
            # Disambiguate bare ship_customer_sk in outer WHERE
            sql_text = sql_text.replace(
                "ship_customer_sk = obt.bill_customer_c_customer_sk",
                "obt.ship_customer_sk = obt.bill_customer_c_customer_sk",
            )

        # Q40: Interval syntax - fix "- 30 AS days"
        if query_id == 40:
            sql_text = re.sub(
                r"CAST\('(\d{4}-\d{2}-\d{2})' AS DATE\) - (\d+) AS days",
                r"CAST('\1' AS DATE) - INTERVAL \2 DAY",
                sql_text,
            )
            sql_text = re.sub(
                r"CAST\('(\d{4}-\d{2}-\d{2})' AS DATE\) \+ (\d+) AS days",
                r"CAST('\1' AS DATE) + INTERVAL \2 DAY",
                sql_text,
            )

        # Q44: Special handling for ranking subqueries
        if query_id == 44:
            sql_text = sql_text.replace(
                "FROM (\n  SELECT", "FROM tpcds_sales_returns_obt AS obt CROSS JOIN (\n  SELECT", 1
            )
            sql_text = sql_text.replace("AND item_i_item_sk = item_sk", "AND obt.item_sk = asceding.item_sk", 1)
            sql_text = sql_text.replace("AND item_i_item_sk = item_sk", "AND obt.item_sk = descending.item_sk", 1)

        # Q45: Missing ca_city - should be bill_addr_ca_city
        if query_id == 45:
            sql_text = sql_text.replace("ca_city", "bill_addr_ca_city")

        # Q47, Q57: Parameter placeholder creates empty alias "AS ," and CTE column references
        if query_id in {47, 57}:
            sql_text = re.sub(r"\[SELECTONE\]\s*AS\s*,", "[SELECTONE],", sql_text)
            sql_text = re.sub(r"AS\s*,\s*v1\.", ", v1.", sql_text)
            # For Q47 - fix v1 CTE output columns - add aliases in SELECT only, not GROUP BY
            if query_id == 47:
                # The v1 CTE SELECT columns need aliases - add all missing ones
                sql_text = sql_text.replace(
                    "obt.item_i_category,\n    obt.item_i_brand,\n    obt.store_s_store_name,\n    obt.store_s_company_name,\n    obt.sold_date_d_year,\n    obt.sold_date_d_moy,",
                    "obt.item_i_category AS i_category,\n    obt.item_i_brand AS i_brand,\n    obt.store_s_store_name AS s_store_name,\n    obt.store_s_company_name AS s_company_name,\n    obt.sold_date_d_year AS d_year,\n    obt.sold_date_d_moy AS d_moy,",
                )
                # Fix GROUP BY - remove aliases (AS not allowed in GROUP BY)
                sql_text = sql_text.replace(
                    "GROUP BY\n    obt.item_i_category AS i_category,\n    obt.item_i_brand AS i_brand,\n    obt.store_s_store_name AS s_store_name,\n    obt.store_s_company_name AS s_company_name,\n    obt.sold_date_d_year AS d_year,\n    obt.sold_date_d_moy AS d_moy",
                    "GROUP BY\n    obt.item_i_category,\n    obt.item_i_brand,\n    obt.store_s_store_name,\n    obt.store_s_company_name,\n    obt.sold_date_d_year,\n    obt.sold_date_d_moy",
                )
                # Also fix the WHERE clause in the outer query - same issue as Q57
                sql_text = sql_text.replace(
                    "WHERE\n  sold_date_d_year = 1999",
                    "WHERE\n  d_year = 1999",
                )
            if query_id == 57:
                # Similar fix for Q57 with call_center instead of store
                sql_text = sql_text.replace(
                    "SELECT\n    obt.item_i_category,\n    obt.item_i_brand,\n    obt.call_center_cc_name,\n    obt.sold_date_d_year,\n    obt.sold_date_d_moy,",
                    "SELECT\n    obt.item_i_category AS i_category,\n    obt.item_i_brand AS i_brand,\n    obt.call_center_cc_name AS cc_name,\n    obt.sold_date_d_year AS d_year,\n    obt.sold_date_d_moy AS d_moy,",
                )
                # Fix GROUP BY
                sql_text = sql_text.replace(
                    "GROUP BY\n    obt.item_i_category AS i_category,",
                    "GROUP BY\n    obt.item_i_category,",
                )
                # Fix WHERE clause - v2 CTE outputs d_year not sold_date_d_year
                sql_text = sql_text.replace(
                    "WHERE\n  sold_date_d_year = 1999",
                    "WHERE\n  d_year = 1999",
                )

        # Q49: Missing tables wr and cr - convert to OBT
        if query_id == 49:
            sql_text = sql_text.replace("wr.wr_order_number", "obt.sale_id")
            sql_text = sql_text.replace("wr.wr_item_sk", "obt.item_sk")
            sql_text = sql_text.replace("cr.cr_order_number", "obt.sale_id")
            sql_text = sql_text.replace("cr.cr_item_sk", "obt.item_sk")

        # Q51: Ambiguous item_sk between web and store CTEs - qualify all references
        if query_id == 51:
            # Fix the CASE expression that tries to coalesce item_sk from both CTEs
            sql_text = sql_text.replace(
                "CASE WHEN NOT item_sk IS NULL THEN item_sk ELSE item_sk END AS item_sk",
                "COALESCE(web.item_sk, store.item_sk) AS item_sk",
            )
            # Fix the JOIN ON clause
            sql_text = sql_text.replace(
                "item_sk = item_sk AND web.d_date = store.d_date",
                "web.item_sk = store.item_sk AND web.d_date = store.d_date",
            )
            # Fix sold_date_d_date alias needed for outer reference
            sql_text = sql_text.replace(
                "obt.sold_date_d_date,\n    SUM(SUM(",
                "obt.sold_date_d_date AS d_date,\n    SUM(SUM(",
            )
            # Fix outer query references to use d_date instead of sold_date_d_date
            # The outer SELECT needs to output d_date consistently
            sql_text = sql_text.replace(
                "SELECT\n    item_sk,\n    sold_date_d_date,",
                "SELECT\n    item_sk,\n    d_date,",
            )
            # Fix window function ORDER BY clauses that still reference sold_date_d_date
            sql_text = sql_text.replace(
                "ORDER BY sold_date_d_date\n      rows",
                "ORDER BY d_date\n      rows",
            )
            # Fix final ORDER BY
            sql_text = sql_text.replace(
                "ORDER BY\n  item_sk,\n  sold_date_d_date",
                "ORDER BY\n  item_sk,\n  d_date",
            )

        # Q58: Fix scalar subquery to use DISTINCT (OBT has multiple rows per date)
        if query_id == 58:
            # The innermost subquery returns week_seq for a date, but OBT has many rows per date.
            # Use MAX() to ensure only one value is returned (all rows have same week_seq for same date)
            sql_text = sql_text.replace(
                "obt.sold_date_d_week_seq = (\n            SELECT\n              obt.sold_date_d_week_seq\n            FROM tpcds_sales_returns_obt AS obt\n            WHERE\n              obt.sold_date_d_date =",
                "obt.sold_date_d_week_seq = (\n            SELECT\n              MAX(obt.sold_date_d_week_seq)\n            FROM tpcds_sales_returns_obt AS obt\n            WHERE\n              obt.sold_date_d_date =",
            )
            # Fix WHERE clause references - need both comparisons
            sql_text = sql_text.replace(
                "ss_items.item_id = ws_items.item_id\n  AND ss_items.item_id = ws_items.item_id",
                "ss_items.item_id = cs_items.item_id\n  AND ss_items.item_id = ws_items.item_id",
            )
            # Fix unqualified item_id in ORDER BY
            sql_text = sql_text.replace(
                "ORDER BY\n  item_id,",
                "ORDER BY\n  ss_items.item_id,",
            )

        # Q59: Restructure to avoid cartesian product - query wss CTE directly with store dimension join
        if query_id == 59:
            # The query creates a massive cartesian product by CROSS JOINing OBT with wss.
            # Instead, we need to join wss with store dimension info from OBT.
            # Add store info to the wss CTE and filter by month_seq there.

            # First, add store dimension columns and month_seq to wss CTE
            sql_text = sql_text.replace(
                "  SELECT\n    obt.sold_date_d_week_seq,\n    obt.store_sk,",
                "  SELECT\n    obt.sold_date_d_week_seq,\n    obt.store_sk,\n    obt.store_s_store_name,\n    obt.store_s_store_id,\n    obt.sold_date_d_month_seq,",
            )
            sql_text = sql_text.replace(
                "  GROUP BY\n    obt.sold_date_d_week_seq,\n    obt.store_sk",
                "  GROUP BY\n    obt.sold_date_d_week_seq,\n    obt.store_sk,\n    obt.store_s_store_name,\n    obt.store_s_store_id,\n    obt.sold_date_d_month_seq",
            )

            # Now rewrite the y subquery to just query wss directly
            sql_text = sql_text.replace(
                """FROM (
  SELECT
    obt.store_s_store_name AS s_store_name1,
    wss.d_week_seq AS d_week_seq1,
    obt.store_s_store_id AS s_store_id1,
    sun_sales AS sun_sales1,
    mon_sales AS mon_sales1,
    tue_sales AS tue_sales1,
    wed_sales AS wed_sales1,
    thu_sales AS thu_sales1,
    fri_sales AS fri_sales1,
    sat_sales AS sat_sales1
  FROM tpcds_sales_returns_obt AS obt
  CROSS JOIN wss AS wss
  WHERE
    (
      sold_date_d_week_seq = wss.d_week_seq
      AND obt.store_sk = obt.store_s_store_sk
      AND obt.sold_date_d_month_seq BETWEEN 1176 AND 1176 + 11
    )
    AND channel = 'store'
) AS y, (""",
                """FROM (
  SELECT
    wss.store_s_store_name AS s_store_name1,
    wss.sold_date_d_week_seq AS d_week_seq1,
    wss.store_s_store_id AS s_store_id1,
    sun_sales AS sun_sales1,
    mon_sales AS mon_sales1,
    tue_sales AS tue_sales1,
    wed_sales AS wed_sales1,
    thu_sales AS thu_sales1,
    fri_sales AS fri_sales1,
    sat_sales AS sat_sales1
  FROM wss
  WHERE
    wss.sold_date_d_month_seq BETWEEN 1176 AND 1176 + 11
) AS y, (""",
            )

            # Now rewrite the x subquery similarly
            sql_text = sql_text.replace(
                """  SELECT
    obt.store_s_store_name AS s_store_name2,
    wss.d_week_seq AS d_week_seq2,
    obt.store_s_store_id AS s_store_id2,
    sun_sales AS sun_sales2,
    mon_sales AS mon_sales2,
    tue_sales AS tue_sales2,
    wed_sales AS wed_sales2,
    thu_sales AS thu_sales2,
    fri_sales AS fri_sales2,
    sat_sales AS sat_sales2
  FROM tpcds_sales_returns_obt AS obt
  CROSS JOIN wss AS wss
  WHERE
    (
      sold_date_d_week_seq = wss.d_week_seq
      AND obt.store_sk = obt.store_s_store_sk
      AND obt.sold_date_d_month_seq BETWEEN 1176 + 12 AND 1176 + 23
    )
    AND channel = 'store'
) AS x""",
                """  SELECT
    wss.store_s_store_name AS s_store_name2,
    wss.sold_date_d_week_seq AS d_week_seq2,
    wss.store_s_store_id AS s_store_id2,
    sun_sales AS sun_sales2,
    mon_sales AS mon_sales2,
    tue_sales AS tue_sales2,
    wed_sales AS wed_sales2,
    thu_sales AS thu_sales2,
    fri_sales AS fri_sales2,
    sat_sales AS sat_sales2
  FROM wss
  WHERE
    wss.sold_date_d_month_seq BETWEEN 1176 + 12 AND 1176 + 23
) AS x""",
            )
            sql_text = sql_text.replace(
                "SELECT\n  store_s_store_name,\n  store_s_store_id,",
                "SELECT\n  s_store_name1 AS store_s_store_name,\n  s_store_id1 AS store_s_store_id,",
            )
            sql_text = sql_text.replace(
                "WHERE\n  store_s_store_id = store_s_store_id AND d_week_seq1 = d_week_seq2 - 52",
                "WHERE\n  s_store_id1 = s_store_id2 AND d_week_seq1 = d_week_seq2 - 52",
            )

        # Q65: CTE sc and sb need proper column names
        if query_id == 65:
            # Fix the CTE output columns
            sql_text = sql_text.replace("sb.ss_store_sk", "sb.store_sk")
            sql_text = sql_text.replace("sc.ss_store_sk", "sc.store_sk")
            sql_text = sql_text.replace("sc.ss_item_sk", "sc.item_sk")
            # Add aliases to CTE outputs
            sql_text = sql_text.replace(
                "obt.store_sk,\n    obt.item_sk,",
                "obt.store_sk AS store_sk,\n    obt.item_sk AS item_sk,",
            )

        # Q73: Ambiguous sale_id and ship_customer_sk between obt and dj subquery
        if query_id == 73:
            # The subquery dj outputs sale_id and ship_customer_sk which conflict with obt columns
            # Fix the outer SELECT to use the subquery's column
            sql_text = sql_text.replace(
                "SELECT\n  bill_customer_c_last_name,\n  bill_customer_c_first_name,\n  bill_customer_c_salutation,\n  bill_customer_c_preferred_cust_flag,\n  sale_id,\n  cnt",
                "SELECT\n  bill_customer_c_last_name,\n  bill_customer_c_first_name,\n  bill_customer_c_salutation,\n  bill_customer_c_preferred_cust_flag,\n  dj.sale_id,\n  cnt",
            )
            # Fix WHERE clause - ship_customer_sk is also ambiguous
            sql_text = sql_text.replace(
                "ship_customer_sk = bill_customer_c_customer_sk",
                "dj.ship_customer_sk = obt.bill_customer_c_customer_sk",
            )

        # Q66, Q71: Missing time dimension column references
        if query_id == 66:
            sql_text = sql_text.replace("t_time_sk", "sold_time_t_time_sk")
            sql_text = sql_text.replace("sold_time_sold_time_t_time_sk", "sold_time_t_time_sk")
            sql_text = sql_text.replace("t_time", "sold_time_t_time")
            sql_text = sql_text.replace("sold_time_sold_time_t_time", "sold_time_t_time")

        if query_id == 71:
            sql_text = sql_text.replace("t_time_sk", "sold_time_t_time_sk")
            sql_text = sql_text.replace("sold_time_sold_time_t_time_sk", "sold_time_t_time_sk")
            sql_text = sql_text.replace("t_meal_time", "sold_time_t_meal_time")
            sql_text = sql_text.replace("t_hour", "sold_time_t_hour")
            sql_text = sql_text.replace("sold_time_sold_time_t_hour", "sold_time_t_hour")
            sql_text = sql_text.replace("t_minute", "sold_time_t_minute")
            sql_text = sql_text.replace("sold_time_sold_time_t_minute", "sold_time_t_minute")

        # Q75: CTE all_sales needs proper column output aliases
        if query_id == 75:
            # The outer CTE SELECT columns need aliases to match what's expected (d_year, i_brand_id, etc.)
            sql_text = sql_text.replace(
                "WITH all_sales AS (\n  SELECT\n    sold_date_d_year,\n    item_i_brand_id,\n    item_i_class_id,\n    item_i_category_id,\n    item_i_manufact_id,",
                "WITH all_sales AS (\n  SELECT\n    sold_date_d_year AS d_year,\n    item_i_brand_id AS i_brand_id,\n    item_i_class_id AS i_class_id,\n    item_i_category_id AS i_category_id,\n    item_i_manufact_id AS i_manufact_id,",
            )
            # Also fix the GROUP BY to use aliases
            sql_text = sql_text.replace(
                "GROUP BY\n    sold_date_d_year,\n    item_i_brand_id,\n    item_i_class_id,\n    item_i_category_id,\n    item_i_manufact_id",
                "GROUP BY\n    d_year,\n    i_brand_id,\n    i_class_id,\n    i_category_id,\n    i_manufact_id",
            )

        # Q77: CTE ss and sr need s_store_sk aliases, ws and wr need wp_web_page_sk aliases
        if query_id == 77:
            # Fix ss CTE - add s_store_sk alias (matches what main query expects)
            sql_text = sql_text.replace(
                "WITH ss AS (\n  SELECT\n    obt.store_s_store_sk,",
                "WITH ss AS (\n  SELECT\n    obt.store_s_store_sk AS s_store_sk,",
            )
            # Fix sr CTE - add s_store_sk alias
            sql_text = sql_text.replace(
                "), sr AS (\n  SELECT\n    obt.store_s_store_sk,",
                "), sr AS (\n  SELECT\n    obt.store_s_store_sk AS s_store_sk,",
            )
            # The fix that was adding AS store_sk needs to be undone for sr
            sql_text = sql_text.replace(
                "obt.store_s_store_sk AS store_sk,\n    SUM(obt.return_amount)",
                "obt.store_s_store_sk AS s_store_sk,\n    SUM(obt.return_amount)",
            )
            # Fix ws CTE - add wp_web_page_sk alias
            sql_text = sql_text.replace(
                "), ws AS (\n  SELECT\n    obt.web_page_wp_web_page_sk,",
                "), ws AS (\n  SELECT\n    obt.web_page_wp_web_page_sk AS wp_web_page_sk,",
            )
            # Fix wr CTE - add wp_web_page_sk alias
            sql_text = sql_text.replace(
                "), wr AS (\n  SELECT\n    obt.web_page_wp_web_page_sk,",
                "), wr AS (\n  SELECT\n    obt.web_page_wp_web_page_sk AS wp_web_page_sk,",
            )
            # Fix ambiguous call_center_sk in catalog channel SELECT
            sql_text = sql_text.replace(
                "'catalog channel' AS channel,\n    call_center_sk AS id,",
                "'catalog channel' AS channel,\n    cs.call_center_sk AS id,",
            )

        # Q78: Ambiguous item_sk - the CTEs (ws, cs, ss) need proper column references
        if query_id == 78:
            # Fix all unqualified item_sk = item_sk patterns
            # ws JOIN ON clause (line 80)
            sql_text = sql_text.replace(
                "ws_sold_year = ss_sold_year\n    AND item_sk = item_sk\n    AND ws_customer_sk",
                "ws_sold_year = ss_sold_year\n    AND ws.item_sk = ss.item_sk\n    AND ws_customer_sk",
            )
            # cs JOIN ON clause (line 86)
            sql_text = sql_text.replace(
                "cs_sold_year = ss_sold_year\n    AND item_sk = item_sk\n    AND cs_customer_sk",
                "cs_sold_year = ss_sold_year\n    AND ss.item_sk = cs.item_sk\n    AND cs_customer_sk",
            )
            # WHERE clause - ws section
            sql_text = sql_text.replace(
                "ws_sold_year = ss_sold_year\n      AND item_sk = item_sk\n      AND ws_customer_sk",
                "ws_sold_year = ss_sold_year\n      AND ws.item_sk = ss.item_sk\n      AND ws_customer_sk",
            )
            # WHERE clause - cs section
            sql_text = sql_text.replace(
                "cs_sold_year = ss_sold_year\n    AND item_sk = item_sk\n    AND cs_customer_sk",
                "cs_sold_year = ss_sold_year\n    AND cs.item_sk = ss.item_sk\n    AND cs_customer_sk",
            )

        # Q90: Reserved word 'at' as alias
        if query_id == 90:
            sql_text = sql_text.replace(") AS at,", ") AS am_count,")
            sql_text = sql_text.replace("at.", "am_count.")

        # Q94: Missing table wr1
        if query_id == 94:
            sql_text = sql_text.replace(
                "obt.sale_id = wr1.wr_order_number AND channel = 'web'",
                "obt.sale_id = obt.sale_id AND obt.has_return = 'Y' AND obt.channel = 'web'",
            )

        # Q95: Missing table ws_wh
        if query_id == 95:
            sql_text = sql_text.replace(
                "obt.sale_id = ws_wh.ws_order_number AND channel = 'web'",
                "obt.sale_id = obt.sale_id AND obt.has_return = 'Y' AND obt.channel = 'web'",
            )

        # Q97: Ambiguous item_sk between ssci and csci CTEs
        if query_id == 97:
            # Fix the ambiguous item_sk = item_sk in ON and WHERE clauses
            sql_text = sql_text.replace(
                "ssci.customer_sk = csci.customer_sk AND item_sk = item_sk",
                "ssci.customer_sk = csci.customer_sk AND ssci.item_sk = csci.item_sk",
            )

        return sql_text

    @staticmethod
    def _param_pattern(name: str) -> re.Pattern[str]:
        return re.compile(rf"\[{re.escape(name)}(?:\.\d+)?\]")


__all__ = [
    "BLOCKED_QUERY_IDS",
    "ColumnMapper",
    "ConvertedQuery",
    "QueryConverter",
    "TemplateLoader",
    "TemplateParameter",
]
