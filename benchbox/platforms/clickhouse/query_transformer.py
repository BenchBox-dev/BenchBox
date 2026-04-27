"""Query transformation utilities for ClickHouse SQL compatibility.

This module provides transformations to adapt standard SQL (TPC-H, TPC-DS) to ClickHouse's
specific requirements, handling:
- Case sensitivity for identifiers
- Type system strictness (Decimal vs Float64)
- Subquery aliasing requirements
- Safe division operations
"""

from __future__ import annotations

import logging
import re

from benchbox.utils.sql_parsing import find_matching_parenthesis

logger = logging.getLogger(__name__)


class ClickHouseQueryTransformer:
    """Transform SQL queries for ClickHouse compatibility."""

    def __init__(self, verbose: bool = False):
        """Initialize query transformer.

        Args:
            verbose: Enable verbose logging of transformations
        """
        self.verbose = verbose
        self.transformations_applied = []

    def transform(self, query: str) -> str:
        """Apply all transformations to a query.

        Args:
            query: Original SQL query

        Returns:
            Transformed SQL query compatible with ClickHouse
        """
        self.transformations_applied = []

        # Apply transformations in order
        query = self.normalize_case(query)
        query = self.fix_type_casts(query)
        # NOTE: add_subquery_aliases is intentionally NOT called here.
        # It uses a simplistic regex that cannot correctly identify subquery
        # boundaries with nested parentheses, causing it to split GROUP BY clauses
        # out of their owning subquery (Q23) and insert aliases inside EXCEPT/INTERSECT
        # set operations (Q87). The joined_subquery_requires_alias = 0 session
        # setting handles the alias requirement without corrupting the SQL.
        query = self.safe_division(query)
        query = self.fix_decimal_division_by_zero(query)

        if self.verbose and self.transformations_applied:
            logger.debug(f"Applied transformations: {', '.join(self.transformations_applied)}")

        return query

    def normalize_case(self, query: str) -> str:
        """Normalize identifiers to lowercase for ClickHouse case-sensitive matching.

        ClickHouse is case-sensitive for unquoted identifiers, but TPC-DS queries
        often use uppercase column names while the schema uses lowercase.

        Args:
            query: SQL query with potentially uppercase identifiers

        Returns:
            Query with normalized lowercase identifiers
        """
        # Known TPC-DS/TPC-H columns that appear in uppercase
        uppercase_patterns = [
            # TPC-H
            r"\bSR_RETURN_AMT\b",
            r"\bSR_CUSTOMER_SK\b",
            r"\bSR_STORE_SK\b",
            r"\bSR_RETURNED_DATE_SK\b",
            # TPC-DS common patterns
            r"\b[A-Z][A-Z_]+_SK\b",  # Foreign keys like CUSTOMER_SK
            r"\b[A-Z][A-Z_]+_AMT\b",  # Amount columns
            r"\b[A-Z][A-Z_]+_QTY\b",  # Quantity columns
            r"\bD_YEAR\b",
            r"\bD_MOY\b",
            r"\bD_DATE_SK\b",
        ]

        original_query = query
        for pattern in uppercase_patterns:
            # Convert uppercase identifiers to lowercase, but preserve string literals
            # Only convert outside of string literals (single quotes)
            def replace_outside_strings(match):
                return match.group(0).lower()

            # Simple approach: convert uppercase identifiers to lowercase
            # This is a heuristic - more sophisticated parsing would use SQL parser
            query = re.sub(pattern, lambda m: m.group(0).lower(), query)

        if query != original_query:
            self.transformations_applied.append("case_normalization")

        return query

    def fix_type_casts(self, query: str) -> str:
        """Add explicit type casts to resolve Decimal/Float64 conflicts.

        ClickHouse's strict type system requires explicit casting when mixing
        Decimal and Float64 types in operations.

        Args:
            query: SQL query with potential type mismatches

        Returns:
            Query with explicit CAST operations added
        """
        original_query = query

        # Pattern 1: COALESCE with float literals (0., 0.0) used with Decimal columns
        # Replace: COALESCE(decimal_col, 0.) → COALESCE(decimal_col, CAST(0 AS Decimal(15,2)))
        query = re.sub(
            r"COALESCE\s*\(\s*([a-zA-Z_][a-zA-Z0-9_.]*)\s*,\s*(0\.0*)\s*\)",
            r"COALESCE(\1, CAST(0 AS Decimal(15,2)))",
            query,
            flags=re.IGNORECASE,
        )

        # Pattern 2: Arithmetic operations with float literals
        # Example: cs_ext_sales_price - 0. → cs_ext_sales_price - CAST(0 AS Decimal(15,2))
        # NOTE: (?![0-9\)]) prevents matching 0. in 0.06 - the regex (0\.0*)\b backtracks to
        # match just "0." when followed by a non-zero digit (word boundary between . and digit),
        # which would produce "CAST(0 AS Decimal(15,2))6" for 0.06. The lookahead ensures we
        # only match pure-zero floats (0., 0.0, 0.00) not non-zero decimals like 0.06.
        query = re.sub(
            r"([a-zA-Z_][a-zA-Z0-9_.]*)\s*([-+*/])\s*(0\.0*)(?![0-9\)])",
            r"\1 \2 CAST(0 AS Decimal(15,2))",
            query,
        )

        # Pattern 3: Float literals in CASE expressions with Decimal columns
        # NOTE: same (?![0-9]) guard as Pattern 2 - prevents matching 0. in 0.06 via \b backtrack.
        query = re.sub(
            r"\bTHEN\s+(0\.0*)(?![0-9])",
            r"THEN CAST(0 AS Decimal(15,2))",
            query,
            flags=re.IGNORECASE,
        )
        query = re.sub(
            r"\bELSE\s+(0\.0*)(?![0-9])",
            r"ELSE CAST(0 AS Decimal(15,2))",
            query,
            flags=re.IGNORECASE,
        )

        if query != original_query:
            self.transformations_applied.append("type_casting")

        return query

    def add_subquery_aliases(self, query: str) -> str:
        """Add aliases to subqueries that lack them.

        ClickHouse requires all subqueries in FROM clauses to have aliases.

        Args:
            query: SQL query with potentially unaliased subqueries

        Returns:
            Query with auto-generated aliases for subqueries
        """
        original_query = query

        # Pattern: Detect subqueries in FROM clause without aliases
        # Look for: FROM (...) followed by WHERE/JOIN/GROUP BY/ORDER BY/UNION/INTERSECT
        # but NOT followed by AS alias_name

        # Counter for generating unique aliases
        alias_counter = [0]

        def add_alias(match):
            """Add auto-generated alias to unaliased subquery."""
            alias_counter[0] += 1
            subquery = match.group(1)
            following = match.group(2)
            return f"FROM ({subquery}) AS subquery_{alias_counter[0]} {following}"

        # Match: FROM (...) followed by keyword (not AS)
        pattern = r"\bFROM\s*(\([^)]*(?:\([^)]*\))*[^)]*\))\s+(?!AS\s)(\b(?:WHERE|JOIN|GROUP|ORDER|UNION|INTERSECT|EXCEPT|LIMIT|;))"
        query = re.sub(pattern, add_alias, query, flags=re.IGNORECASE)

        if query != original_query:
            self.transformations_applied.append("subquery_aliasing")

        return query

    def safe_division(self, query: str) -> str:
        """Wrap division operations with nullif to prevent division by zero.

        Args:
            query: SQL query with division operations

        Returns:
            Query with safe division using nullif
        """
        original_query = query
        identifier_or_func = r"[a-zA-Z_][a-zA-Z0-9_.]*(?:\([^)]*\))?"
        paren_expr = r"\([^)]+\)"
        numerator_pattern = re.compile(rf"((?:{identifier_or_func}|{paren_expr}))\s*/\s*", re.IGNORECASE)

        transformed_segments: list[str] = []
        last_emitted = 0
        search_start = 0

        while match := numerator_pattern.search(query, search_start):
            # Skip matches that fall inside a single-quoted string literal.
            if self._inside_string_literal(query, match.start()):
                search_start = match.end()
                continue

            divisor_start = match.end()
            divisor_end = self._scan_sql_operand(query, divisor_start)
            if divisor_end is None:
                search_start = divisor_start
                continue

            numerator = match.group(1).strip()
            divisor = query[divisor_start:divisor_end].strip()
            replacement = self._wrap_divisor_with_nullif(numerator, divisor)

            transformed_segments.append(query[last_emitted : match.start()])
            transformed_segments.append(replacement)
            last_emitted = divisor_end
            search_start = divisor_end

        transformed_segments.append(query[last_emitted:])
        query = "".join(transformed_segments)

        if query != original_query:
            self.transformations_applied.append("safe_division")

        return query

    def _wrap_divisor_with_nullif(self, numerator: str, divisor: str) -> str:
        """Wrap a divisor unless it is already safe as-is."""
        normalized_divisor = self._strip_outer_parentheses(divisor).strip()

        if re.fullmatch(r"\d+(?:\.\d+)?", normalized_divisor):
            return f"{numerator} / {divisor}"

        if normalized_divisor.lower().startswith("nullif"):
            return f"{numerator} / {divisor}"

        return f"{numerator} / NULLIF({divisor}, 0)"

    @classmethod
    def _scan_sql_operand(cls, text: str, start_index: int) -> int | None:
        """Return the end index of a simple SQL operand starting at start_index."""
        index = start_index
        while index < len(text) and text[index].isspace():
            index += 1

        if index >= len(text):
            return None

        first = text[index]
        if first == "(":
            return cls._find_matching_parenthesis(text, index) + 1

        if first.isdigit():
            end = index + 1
            while end < len(text) and (text[end].isdigit() or text[end] == "."):
                end += 1
            return end

        if not (first.isalpha() or first == "_"):
            return None

        end = index + 1
        while end < len(text) and (text[end].isalnum() or text[end] in "._"):
            end += 1

        if end < len(text) and text[end] == "(":
            return cls._find_matching_parenthesis(text, end) + 1

        return end

    @classmethod
    def _strip_outer_parentheses(cls, expression: str) -> str:
        """Strip wrapping parentheses that enclose the entire expression."""
        stripped = expression.strip()
        while stripped.startswith("("):
            try:
                close_index = cls._find_matching_parenthesis(stripped, 0)
            except ValueError:
                break
            if close_index != len(stripped) - 1:
                break
            stripped = stripped[1:-1].strip()
        return stripped

    @staticmethod
    def _find_matching_parenthesis(text: str, open_index: int) -> int:
        """Return the closing parenthesis paired with open_index."""
        return find_matching_parenthesis(text, open_index)

    @staticmethod
    def _inside_string_literal(text: str, position: int) -> bool:
        """Return True if *position* falls inside a single-quoted SQL string literal."""
        in_quote = False
        index = 0
        while index < position:
            if text[index] == "'":
                if in_quote and index + 1 < len(text) and text[index + 1] == "'":
                    index += 2
                    continue
                in_quote = not in_quote
            index += 1
        return in_quote

    def fix_decimal_division_by_zero(self, query: str) -> str:
        """Wrap CAST(col AS Nullable(Decimal(...))) divisors with NULLIF to prevent division by zero.

        ClickHouse raises ILLEGAL_DIVISION when dividing by a Nullable(Decimal) expression
        that evaluates to zero (e.g. Q61's CAST-based ratio computation). This method keeps
        a narrow explicit fix for Nullable(Decimal) CAST divisors regardless of whether the
        generic safe_division() pass touches the surrounding expression.

        Args:
            query: SQL query with potential Nullable(Decimal) divisors

        Returns:
            Query with NULLIF-wrapped Nullable(Decimal) CAST divisors
        """
        original_query = query

        # Pattern: / CAST(expr AS Nullable(Decimal(P, S)))
        # Wraps the entire CAST expression in NULLIF(..., 0)
        pattern = r"/\s*(CAST\([^)]+\bAS\s+Nullable\s*\(\s*Decimal\s*\(\s*\d+\s*,\s*\d+\s*\)\s*\)\s*\))"
        query = re.sub(
            pattern,
            lambda m: f"/ NULLIF({m.group(1)}, 0)",
            query,
            flags=re.IGNORECASE,
        )

        if query != original_query:
            self.transformations_applied.append("decimal_division_fix")

        return query

    def get_transformations_applied(self) -> list[str]:
        """Return list of transformations applied to last query.

        Returns:
            List of transformation names
        """
        return self.transformations_applied

    def add_query_settings(self, query: str) -> str:
        """Append ClickHouse SETTINGS clause for TPC-DS/TPC-H SQL compatibility.

        Fixes for known ClickHouse incompatibilities with standard TPC SQL:
        - joined_subquery_requires_alias = 0:
            Allows unaliased subqueries in FROM/JOIN (Q14a INTERSECT subquery,
            Q23a/b unaliased inner subquery, Q87 EXCEPT set op subquery).

        Args:
            query: Transformed SQL query string

        Returns:
            Query with SETTINGS clause appended (only for SELECT statements)
        """
        stripped = query.strip()
        if not stripped.upper().startswith("SELECT") and not stripped.upper().startswith("WITH"):
            return query

        return f"{stripped} SETTINGS joined_subquery_requires_alias = 0"


def transform_query_for_clickhouse(query: str, verbose: bool = False) -> str:
    """Convenience function to transform a query for ClickHouse compatibility.

    Args:
        query: Original SQL query
        verbose: Enable verbose logging

    Returns:
        Transformed SQL query
    """
    transformer = ClickHouseQueryTransformer(verbose=verbose)
    return transformer.transform(query)


__all__ = ["ClickHouseQueryTransformer", "transform_query_for_clickhouse"]
