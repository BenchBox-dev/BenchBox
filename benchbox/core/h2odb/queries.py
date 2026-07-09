"""H2O DB benchmark query management.

Provides standard H2O DB benchmark queries that test various aspects of analytical database performance using taxi trip data.

The queries cover:
- Basic aggregations (sum, count, mean)
- Grouping operations
- Advanced analytics (percentiles, rolling operations)
- String operations
- Complex analytical queries

For more information see:
- https://h2oai.github.io/db-benchmark/

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""


class H2OQueryManager:
    """Manager for H2O DB benchmark queries."""

    def __init__(self) -> None:
        """Initialize H2O DB query manager."""
        self._queries = self._load_queries()

    def _load_queries(self) -> dict[str, str]:
        """Load all H2O DB benchmark queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        queries = {}

        # Q1: Basic count
        queries["Q1"] = """
SELECT COUNT(*) as count
FROM trips;
"""

        # Q2: Sum and mean of fare_amount
        queries["Q2"] = """
SELECT
    SUM(fare_amount) as sum_fare_amount,
    AVG(fare_amount) as mean_fare_amount
FROM trips;
"""

        # Q3: Sum by passenger_count
        queries["Q3"] = """
SELECT
    passenger_count,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

        # Q4: Sum and mean by passenger_count
        queries["Q4"] = """
SELECT
    passenger_count,
    SUM(fare_amount) as sum_fare_amount,
    AVG(fare_amount) as mean_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

        # Q5: Sum by passenger_count and vendor_id
        queries["Q5"] = """
SELECT
    passenger_count,
    vendor_id,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY passenger_count, vendor_id
ORDER BY passenger_count, vendor_id;
"""

        # Q6: Sum and mean by passenger_count and vendor_id
        queries["Q6"] = """
SELECT
    passenger_count,
    vendor_id,
    SUM(fare_amount) as sum_fare_amount,
    AVG(fare_amount) as mean_fare_amount
FROM trips
GROUP BY passenger_count, vendor_id
ORDER BY passenger_count, vendor_id;
"""

        # Q7: Sum by hour of pickup_datetime
        queries["Q7"] = """
SELECT
    EXTRACT(HOUR FROM pickup_datetime) as hour,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY EXTRACT(HOUR FROM pickup_datetime)
ORDER BY hour;
"""

        # Q8: Sum by year and hour of pickup_datetime
        queries["Q8"] = """
SELECT
    EXTRACT(YEAR FROM pickup_datetime) as year,
    EXTRACT(HOUR FROM pickup_datetime) as hour,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY EXTRACT(YEAR FROM pickup_datetime), EXTRACT(HOUR FROM pickup_datetime)
ORDER BY year, hour;
"""

        # Q9: Percentiles by passenger_count
        queries["Q9"] = """
SELECT
    passenger_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fare_amount) as median_fare_amount,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY fare_amount) as p90_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

        # Q10: Top 10 pickup locations by trip count. The secondary
        # `pickup_location_id` sort key makes the top-N a total order: trip counts
        # tie across locations (near-uniform assignment), and a bare `ORDER BY
        # trip_count DESC LIMIT 10` would otherwise pick an arbitrary, engine- and
        # run-dependent member at the tied cutoff (non-reproducible results).
        queries["Q10"] = """
SELECT
    pickup_location_id,
    COUNT(*) as trip_count
FROM trips
WHERE pickup_location_id IS NOT NULL
GROUP BY pickup_location_id
ORDER BY trip_count DESC, pickup_location_id
LIMIT 10;
"""

        return queries

    def get_query(self, query_id: str) -> str:
        """Get an H2O DB benchmark query.

        Args:
            query_id: Query identifier (Q1, Q2, etc.)

        Returns:
            SQL query text

        Raises:
            ValueError: If query_id is invalid
        """
        if query_id not in self._queries:
            available = ", ".join(sorted(self._queries.keys()))
            raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

        return self._queries[query_id]

    def get_all_queries(self) -> dict[str, str]:
        """Get all H2O DB benchmark queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        return self._queries.copy()
