# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.


class H2OQueryManager:
    def __init__(self) -> None:

        self._queries = self._load_queries()

    def _load_queries(self) -> dict[str, str]:

        queries = {}

        queries["Q1"] = """
SELECT COUNT(*) as count
FROM trips;
"""

        queries["Q2"] = """
SELECT
    SUM(fare_amount) as sum_fare_amount,
    AVG(fare_amount) as mean_fare_amount
FROM trips;
"""

        queries["Q3"] = """
SELECT
    passenger_count,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

        queries["Q4"] = """
SELECT
    passenger_count,
    SUM(fare_amount) as sum_fare_amount,
    AVG(fare_amount) as mean_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

        queries["Q5"] = """
SELECT
    passenger_count,
    vendor_id,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY passenger_count, vendor_id
ORDER BY passenger_count, vendor_id;
"""

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

        queries["Q7"] = """
SELECT
    EXTRACT(HOUR FROM pickup_datetime) as hour,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY EXTRACT(HOUR FROM pickup_datetime)
ORDER BY hour;
"""

        queries["Q8"] = """
SELECT
    EXTRACT(YEAR FROM pickup_datetime) as year,
    EXTRACT(HOUR FROM pickup_datetime) as hour,
    SUM(fare_amount) as sum_fare_amount
FROM trips
GROUP BY EXTRACT(YEAR FROM pickup_datetime), EXTRACT(HOUR FROM pickup_datetime)
ORDER BY year, hour;
"""

        queries["Q9"] = """
SELECT
    passenger_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY fare_amount) as median_fare_amount,
    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY fare_amount) as p90_fare_amount
FROM trips
GROUP BY passenger_count
ORDER BY passenger_count;
"""

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

        if query_id not in self._queries:
            available = ", ".join(sorted(self._queries.keys()))
            raise ValueError(f"Invalid query ID: {query_id}. Available: {available}")

        return self._queries[query_id]

    def get_all_queries(self) -> dict[str, str]:

        return self._queries.copy()
