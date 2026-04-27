"""TPC-DI (Data Integration) benchmark query management.

This module provides a comprehensive suite of validation and analytical queries
for the TPC-DI benchmark. TPC-DI is primarily an ETL benchmark, but includes
extensive queries to validate the data integration process and perform analytical
operations on the resulting data warehouse.

The complete query suite includes:
- 12 Data quality validation queries (VQ1-VQ12): Referential integrity, completeness,
  SCD Type 2 validation, consistency, business rules
- 10 Business intelligence analytical queries (AQ1-AQ10): Customer profitability,
  security performance, broker analysis, market trends, portfolio analysis
- 8 ETL validation queries (EQ1-EQ8): Batch processing, incremental loads,
  transformations, quality scores

This represents a complete expansion from the original 8 basic queries to 30
comprehensive queries covering all aspects of TPC-DI validation and analysis.

For more information see:
- http://www.tpc.org/tpcdi/

Copyright 2026 Joe Harris / BenchBox Project

TPC Benchmark™ DI (TPC-DI) - Copyright © Transaction Processing Performance Council
This implementation is based on the TPC-DI specification.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import Any, Optional

from benchbox.core.query_manager import ParameterizedQueryManager
from benchbox.utils.printing import emit

from .query_analytics import TPCDIAnalyticalQueries
from .query_etl import TPCDIETLQueries
from .query_validation import TPCDIValidationQueries


class TPCDIQueryManager(ParameterizedQueryManager):
    """Comprehensive manager for TPC-DI benchmark queries.

    This manager provides a unified interface to all TPC-DI queries including:
    - Original validation and analytical queries (V1-V3, A1-A5)
    - Extended validation queries (VQ1-VQ12)
    - Extended analytical queries (AQ1-AQ10)
    - ETL validation queries (EQ1-EQ8)

    Total query count: 30 queries (8 original + 22 extended)
    """

    def __init__(self) -> None:
        """Initialize the comprehensive TPC-DI query manager."""
        # Initialize specialized query managers
        self.validation_queries = TPCDIValidationQueries()
        self.analytical_queries = TPCDIAnalyticalQueries()
        self.etl_queries = TPCDIETLQueries()

        # Load base validation and analytical queries.
        self._base_queries = self._load_base_queries()
        self._queries = self._base_queries
        self._base_query_metadata = self._load_base_query_metadata()

        # Build comprehensive query catalog
        self._all_queries = self._build_comprehensive_catalog()
        self._all_metadata = self._build_comprehensive_metadata()

    def _load_base_queries(self) -> dict[str, str]:
        """Load all TPC-DI validation and analytical queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        queries = {}

        # Validation Query 1: Customer dimension validation
        queries["V1"] = """
SELECT
    COUNT(*) as total_customers,
    COUNT(DISTINCT CustomerID) as unique_customers,
    SUM(CASE WHEN IsCurrent = 1 THEN 1 ELSE 0 END) as current_customers
FROM DimCustomer;
"""

        # Validation Query 2: Account dimension validation
        queries["V2"] = """
SELECT
    Status,
    COUNT(*) as account_count,
    SUM(CASE WHEN IsCurrent = 1 THEN 1 ELSE 0 END) as current_accounts
FROM DimAccount
GROUP BY Status
ORDER BY Status;
"""

        # Validation Query 3: Trade fact validation
        queries["V3"] = """
SELECT
    Status,
    Type,
    COUNT(*) as trade_count,
    SUM(Quantity) as total_quantity,
    AVG(TradePrice) as avg_trade_price,
    SUM(Fee + Commission + Tax) as total_fees
FROM FactTrade
GROUP BY Status, Type
ORDER BY Status, Type;
"""

        # Analytical Query 1: Customer trading analysis
        queries["A1"] = """
SELECT
    c.Tier,
    COUNT(DISTINCT c.SK_CustomerID) as customer_count,
    COUNT(t.TradeID) as trade_count,
    SUM(t.Quantity * t.TradePrice) as total_value,
    AVG(t.TradePrice) as avg_trade_price
FROM DimCustomer c
LEFT JOIN FactTrade t ON c.SK_CustomerID = t.SK_CustomerID
WHERE c.IsCurrent = 1
GROUP BY c.Tier
ORDER BY c.Tier;
"""

        # Analytical Query 2: Company performance analysis
        queries["A2"] = """
SELECT
    comp.Industry,
    comp.SPrating,
    COUNT(DISTINCT comp.SK_CompanyID) as company_count,
    COUNT(t.TradeID) as trade_count,
    AVG(t.TradePrice) as avg_trade_price,
    SUM(t.Quantity * t.TradePrice) as total_trade_value
FROM DimCompany comp
LEFT JOIN FactTrade t ON comp.SK_CompanyID = t.SK_CompanyID
WHERE comp.IsCurrent = 1
GROUP BY comp.Industry, comp.SPrating
HAVING COUNT(t.TradeID) > {min_trades}
ORDER BY total_trade_value DESC
LIMIT {limit_rows};
"""

        # Analytical Query 3: Security trading analysis
        queries["A3"] = """
SELECT
    s.Symbol,
    s.Name,
    COUNT(t.TradeID) as trade_count,
    SUM(t.Quantity) as total_quantity,
    AVG(t.TradePrice) as avg_price,
    MIN(t.TradePrice) as min_price,
    MAX(t.TradePrice) as max_price,
    SUM(t.Quantity * t.TradePrice) as total_value
FROM DimSecurity s
JOIN FactTrade t ON s.SK_SecurityID = t.SK_SecurityID
WHERE s.IsCurrent = 1
  AND t.Status = 'Completed'
GROUP BY s.Symbol, s.Name
HAVING COUNT(t.TradeID) > {min_trades}
ORDER BY total_value DESC
LIMIT {limit_rows};
"""

        # Analytical Query 4: Time-based trading analysis
        queries["A4"] = """
SELECT
    d.CalendarYearID,
    d.CalendarQtrID,
    COUNT(t.TradeID) as trade_count,
    SUM(t.Quantity * t.TradePrice) as total_value,
    AVG(t.TradePrice) as avg_price,
    SUM(t.Fee + t.Commission + t.Tax) as total_fees
FROM DimDate d
JOIN FactTrade t ON d.SK_DateID = t.SK_CreateDateID
WHERE d.CalendarYearID >= {start_year}
  AND d.CalendarYearID <= {end_year}
GROUP BY d.CalendarYearID, d.CalendarQtrID
ORDER BY d.CalendarYearID, d.CalendarQtrID;
"""

        # Analytical Query 5: Customer geographic analysis
        queries["A5"] = """
SELECT
    c.Country,
    c.StateProv,
    COUNT(DISTINCT c.SK_CustomerID) as customer_count,
    COUNT(t.TradeID) as trade_count,
    SUM(t.Quantity * t.TradePrice) as total_trade_value,
    AVG(c.NetWorth) as avg_net_worth
FROM DimCustomer c
LEFT JOIN FactTrade t ON c.SK_CustomerID = t.SK_CustomerID
WHERE c.IsCurrent = 1
GROUP BY c.Country, c.StateProv
HAVING customer_count > {min_customers}
ORDER BY total_trade_value DESC
LIMIT {limit_rows};
"""

        return queries

    def _load_base_query_metadata(self) -> dict[str, dict[str, Any]]:
        """Load metadata for all TPC-DI queries including dependencies.

        Returns:
            Dictionary mapping query IDs to their metadata
        """
        metadata = {}

        # Validation Query 1: Customer dimension validation
        metadata["V1"] = {
            "relies_on": ["DimCustomer"],
            "query_type": "validation",
            "description": "Validates customer dimension data integrity and current status",
        }

        # Validation Query 2: Account dimension validation
        metadata["V2"] = {
            "relies_on": ["DimAccount"],
            "query_type": "validation",
            "description": "Validates account dimension data with status breakdown",
        }

        # Validation Query 3: Trade fact validation
        metadata["V3"] = {
            "relies_on": ["FactTrade"],
            "query_type": "validation",
            "description": "Validates trade fact table data quality and completeness",
        }

        # Analytical Query 1: Customer trading analysis
        metadata["A1"] = {
            "relies_on": ["DimCustomer", "FactTrade", "V1", "V3"],
            "query_type": "analytical",
            "description": "Analysis of customer trading patterns by tier",
        }

        # Analytical Query 2: Company performance analysis
        metadata["A2"] = {
            "relies_on": ["DimCompany", "FactTrade", "V3"],
            "query_type": "analytical",
            "description": "Company performance analysis by industry and rating",
        }

        # Analytical Query 3: Security trading analysis
        metadata["A3"] = {
            "relies_on": ["DimSecurity", "FactTrade", "V3"],
            "query_type": "analytical",
            "description": "Security trading volume and price analysis",
        }

        # Analytical Query 4: Time-based trading analysis
        metadata["A4"] = {
            "relies_on": ["DimDate", "FactTrade", "V3"],
            "query_type": "analytical",
            "description": "Time-based trading patterns by year and quarter",
        }

        # Analytical Query 5: Customer geographic analysis
        metadata["A5"] = {
            "relies_on": ["DimCustomer", "FactTrade", "V1", "V3"],
            "query_type": "analytical",
            "description": "Geographic distribution of customers and trading activity",
        }

        return metadata

    def _build_comprehensive_catalog(self) -> dict[str, str]:
        """Build comprehensive catalog combining all query types.

        Returns:
            Dictionary mapping all query IDs to SQL text
        """
        catalog = {}

        # Include base queries.
        catalog.update(self._base_queries)

        # Add extended validation queries
        catalog.update(self.validation_queries.get_all_queries())

        # Add extended analytical queries
        catalog.update(self.analytical_queries.get_all_queries())

        # Add ETL validation queries
        catalog.update(self.etl_queries.get_all_queries())

        return catalog

    def _build_comprehensive_metadata(self) -> dict[str, dict[str, Any]]:
        """Build comprehensive metadata combining all query types.

        Returns:
            Dictionary mapping all query IDs to their metadata
        """
        metadata = {}

        # Add base query metadata.
        metadata.update(self._base_query_metadata)

        # Add extended validation query metadata
        for query_id in self.validation_queries._queries:
            metadata[query_id] = self.validation_queries.get_query_metadata(query_id)

        # Add extended analytical query metadata
        for query_id in self.analytical_queries._queries:
            metadata[query_id] = self.analytical_queries.get_query_metadata(query_id)

        # Add ETL validation query metadata
        for query_id in self.etl_queries._queries:
            metadata[query_id] = self.etl_queries.get_query_metadata(query_id)

        return metadata

    def get_query(
        self,
        query_id: str,
        params: Optional[dict[str, Any]] = None,
        dialect: Optional[str] = None,
    ) -> str:
        """Get a TPC-DI query with parameters.

        Args:
            query_id: Query identifier (V1-V3, A1-A5, VQ1-VQ12, AQ1-AQ10, EQ1-EQ8)
            params: Optional parameter values. If None, uses defaults.
            dialect: Optional SQL dialect for query translation

        Returns:
            SQL query with parameters replaced

        Raises:
            ValueError: If query_id is invalid
        """
        # Route to appropriate query manager
        query = None
        if query_id in self._base_queries:
            query = super().get_query(query_id, params)
        elif query_id.startswith("VQ"):
            query = self.validation_queries.get_query(query_id, params)
        elif query_id.startswith("AQ"):
            query = self.analytical_queries.get_query(query_id, params)
        elif query_id.startswith("EQ"):
            query = self.etl_queries.get_query(query_id, params)
        else:
            available = ", ".join(sorted(self._all_queries.keys()))
            raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

        # Apply dialect translation if requested
        if dialect and dialect != "standard" and query:
            query = self.translate_query_text(query, dialect)

        return query

    def get_all_queries(self) -> dict[str, str]:
        """Get all TPC-DI queries with default parameters.

        Returns:
            Dictionary mapping query IDs to parameterized SQL (30 total queries)
        """
        return self._all_queries.copy()

    def _generate_default_params(self, query_id: str) -> dict[str, Any]:
        """Generate default parameters for a query.

        Args:
            query_id: Query identifier

        Returns:
            Dictionary of parameter names to default values
        """
        # Default parameters used in TPC-DI specification
        defaults = {
            # Thresholds
            "min_trades": 100,
            "min_customers": 10,
            # Years (TPC-DI typically covers 5 years)
            "start_year": 2015,
            "end_year": 2019,
            # Limits
            "limit_rows": 50,
        }

        return defaults

    def get_query_dependencies(self, query_id: str) -> list[str]:
        """Get the dependencies for a specific query.

        Args:
            query_id: Query identifier (V1-V3, A1-A5, VQ1-VQ12, AQ1-AQ10, EQ1-EQ8)

        Returns:
            List of dependencies (tables and other queries) this query relies on

        Raises:
            ValueError: If query_id is invalid
        """
        if query_id not in self._all_metadata:
            available = ", ".join(sorted(self._all_metadata.keys()))
            raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

        return self._all_metadata[query_id]["relies_on"].copy()

    def get_query_metadata(self, query_id: str) -> dict[str, Any]:
        """Get full metadata for a specific query.

        Args:
            query_id: Query identifier (V1-V3, A1-A5, VQ1-VQ12, AQ1-AQ10, EQ1-EQ8)

        Returns:
            Dictionary containing query metadata (relies_on, query_type, description, etc.)

        Raises:
            ValueError: If query_id is invalid
        """
        return self._get_query_metadata_copy(self._all_metadata, query_id, "query")

    def get_queries_by_type(self, query_type: str) -> list[str]:
        """Get all queries of a specific type.

        Args:
            query_type: Type of queries to retrieve ("validation", "analytical", "etl_validation")

        Returns:
            List of query IDs of the specified type

        Raises:
            ValueError: If query_type is invalid
        """
        valid_types = {"validation", "analytical", "etl_validation"}
        self._validate_selector_value(query_type, valid_types, "query type")
        return self._query_ids_by_metadata(self._all_metadata, "query_type", query_type)

    def resolve_query_order(self, query_ids: Optional[list[str]] = None) -> list[str]:
        """Resolve queries in dependency order using topological sort.

        Args:
            query_ids: Optional list of specific query IDs to order. If None, orders all queries.

        Returns:
            List of query IDs in dependency order (dependencies first)

        Raises:
            ValueError: If there's a circular dependency or invalid query ID
        """
        if query_ids is None:
            query_ids = list(self._all_queries.keys())

        # Validate all query IDs
        for query_id in query_ids:
            if query_id not in self._all_metadata:
                available = ", ".join(sorted(self._all_metadata.keys()))
                raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

        # Filter dependencies to only include queries (not tables)
        query_dependencies = {}
        for query_id in query_ids:
            deps = [
                dep
                for dep in self._all_metadata[query_id]["relies_on"]
                if dep in self._all_metadata  # Only include other queries, not tables
            ]
            query_dependencies[query_id] = deps

        # Topological sort using Kahn's algorithm
        # Count incoming edges for each query
        in_degree = dict.fromkeys(query_ids, 0)
        for query_id in query_ids:
            for dep in query_dependencies[query_id]:
                if dep in in_degree:  # Only count dependencies that are in our query set
                    in_degree[query_id] += 1

        # Queue of queries with no dependencies
        queue = [query_id for query_id in query_ids if in_degree[query_id] == 0]
        result = []

        while queue:
            # Sort queue for deterministic output
            queue.sort()
            current = queue.pop(0)
            result.append(current)

            # Reduce in-degree for queries that depend on current query
            for query_id in query_ids:
                if current in query_dependencies[query_id]:
                    in_degree[query_id] -= 1
                    if in_degree[query_id] == 0:
                        queue.append(query_id)

        # Check for circular dependencies
        if len(result) != len(query_ids):
            remaining = [q for q in query_ids if q not in result]
            raise ValueError(f"Circular dependency detected involving queries: {', '.join(remaining)}")

        return result

    def get_execution_plan(self) -> list[tuple[str, str, list[str]]]:
        """Get a complete execution plan with queries grouped by type and ordered by dependencies.

        Returns:
            List of tuples containing (query_id, query_type, dependencies) in execution order
        """
        # Get all queries in dependency order
        ordered_queries = self.resolve_query_order()

        execution_plan = []
        for query_id in ordered_queries:
            metadata = self._all_metadata[query_id]
            execution_plan.append((query_id, metadata["query_type"], metadata["relies_on"].copy()))

        return execution_plan

    # Extended methods for comprehensive query suite management

    def get_validation_queries(self) -> dict[str, str]:
        """Get all data quality validation queries.

        Returns:
            Dictionary mapping validation query IDs (VQ1-VQ12) to SQL text
        """
        return self.validation_queries.get_all_queries()

    def get_analytical_queries(self) -> dict[str, str]:
        """Get all business intelligence analytical queries.

        Returns:
            Dictionary mapping analytical query IDs (AQ1-AQ10) to SQL text
        """
        return self.analytical_queries.get_all_queries()

    def get_etl_queries(self) -> dict[str, str]:
        """Get all ETL validation queries.

        Returns:
            Dictionary mapping ETL query IDs (EQ1-EQ8) to SQL text
        """
        return self.etl_queries.get_all_queries()

    def get_queries_by_category(self, category: str) -> list[str]:
        """Get queries by detailed category (beyond basic type).

        Args:
            category: Detailed category (e.g. 'referential_integrity', 'customer_profitability',
                     'batch_processing', etc.)

        Returns:
            List of query IDs in the specified category
        """
        result = []

        # Check validation queries
        try:
            result.extend(self.validation_queries.get_queries_by_category(category))
        except ValueError:
            pass  # Category not found in validation queries

        # Check analytical queries
        try:
            result.extend(self.analytical_queries.get_queries_by_category(category))
        except ValueError:
            pass  # Category not found in analytical queries

        # Check ETL queries
        try:
            result.extend(self.etl_queries.get_queries_by_category(category))
        except ValueError:
            pass  # Category not found in ETL queries

        return result

    def get_query_statistics(self) -> dict[str, Any]:
        """Get comprehensive statistics about the query suite.

        Returns:
            Dictionary containing query suite statistics
        """
        all_queries = self._all_queries
        all_metadata = self._all_metadata

        # Count by type
        type_counts = {}
        for metadata in all_metadata.values():
            query_type = metadata.get("query_type", "unknown")
            type_counts[query_type] = type_counts.get(query_type, 0) + 1

        # Count by category (for extended queries)
        category_counts = {}
        for metadata in all_metadata.values():
            category = metadata.get("category", "uncategorized")
            category_counts[category] = category_counts.get(category, 0) + 1

        # Count by complexity/severity
        complexity_counts = {}
        severity_counts = {}
        for metadata in all_metadata.values():
            if "complexity" in metadata:
                complexity = metadata["complexity"]
                complexity_counts[complexity] = complexity_counts.get(complexity, 0) + 1
            if "severity" in metadata:
                severity = metadata["severity"]
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

        return {
            "total_queries": len(all_queries),
            "base_queries": len(self._base_queries),
            "extended_validation_queries": len(self.validation_queries._queries),
            "extended_analytical_queries": len(self.analytical_queries._queries),
            "etl_validation_queries": len(self.etl_queries._queries),
            "queries_by_type": type_counts,
            "queries_by_category": category_counts,
            "queries_by_complexity": complexity_counts,
            "queries_by_severity": severity_counts,
            "query_expansion_factor": len(all_queries) / len(self._base_queries),
        }

    def translate_query_text(self, query: str, dialect: str) -> str:
        """Translate a query string to a specific SQL dialect.

        Args:
            query: SQL query string to translate
            dialect: Target SQL dialect

        Returns:
            Translated SQL query string

        Raises:
            ImportError: If sqlglot is not available
            Exception: If translation fails
        """
        try:
            import sqlglot  # type: ignore[import-untyped]

            # TPC-DI queries are generated with ANSI SQL syntax, use 'ansi' as source
            translated = sqlglot.transpile(  # type: ignore[attr-defined]
                query, read="ansi", write=dialect
            )
            return translated[0] if translated else query
        except ImportError:
            raise ImportError(
                "sqlglot is required for SQL dialect translation. Install with: pip install sqlglot"
            ) from None
        except Exception as e:
            # If translation fails, return the original query with a warning
            emit(f"Warning: Failed to translate query to {dialect}: {e}")
            return query
