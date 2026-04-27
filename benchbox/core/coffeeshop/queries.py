"""CoffeeShop query manager for the reference-aligned schema.

The query set has been rewritten to operate solely on the canonical
``dim_locations``, ``dim_products``, and ``order_lines`` tables emitted by the
new generator. Queries emphasise sales performance, regional trends, product
mix, and pricing behaviour - mirroring typical analytics performed on the
reference dataset.
"""

from __future__ import annotations

from typing import Any


class CoffeeShopQueryManager:
    """Manage CoffeeShop analytical queries and parameter defaults."""

    def __init__(self) -> None:
        self._queries = self._load_queries()

    def _load_queries(self) -> dict[str, dict[str, Any]]:
        queries: dict[str, dict[str, Any]] = {}

        queries["SA1"] = {
            "description": "Daily revenue and order volume by region.",
            "defaults": {"start_date": "2023-01-01", "end_date": "2023-01-31"},
            "sql": """
SELECT
    ol.order_date,
    dl.region,
    COUNT(DISTINCT ol.order_id) AS order_count,
    SUM(ol.total_price) AS gross_revenue,
    SUM(ol.total_price) / NULLIF(COUNT(DISTINCT ol.order_id), 0) AS avg_order_value
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
GROUP BY ol.order_date, dl.region
ORDER BY ol.order_date, dl.region;
""",
        }

        queries["SA2"] = {
            "description": "Top products by revenue for a given year.",
            "defaults": {"year": 2023, "limit": 15},
            "sql": """
SELECT
    dp.subcategory,
    dp.name AS product_name,
    SUM(ol.quantity) AS total_quantity,
    SUM(ol.total_price) AS total_revenue
FROM order_lines ol
JOIN dim_products dp ON ol.product_record_id = dp.record_id
WHERE EXTRACT(YEAR FROM ol.order_date) = {year}
GROUP BY dp.subcategory, dp.name
ORDER BY total_revenue DESC
LIMIT {limit};
""",
        }

        queries["SA3"] = {
            "description": "Monthly performance metrics for a selected year.",
            "defaults": {"year": 2023},
            "sql": """
SELECT
    EXTRACT(YEAR FROM ol.order_date) AS year,
    EXTRACT(MONTH FROM ol.order_date) AS month,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.quantity) AS items_sold,
    SUM(ol.total_price) AS revenue,
    SUM(ol.total_price) / NULLIF(COUNT(DISTINCT ol.order_id), 0) AS avg_order_value,
    SUM(ol.quantity) / NULLIF(COUNT(DISTINCT ol.order_id), 0) AS avg_items_per_order
FROM order_lines ol
WHERE EXTRACT(YEAR FROM ol.order_date) = {year}
GROUP BY year, month
ORDER BY year, month;
""",
        }

        queries["SA4"] = {
            "description": "Revenue share by region across a date window.",
            "defaults": {"start_date": "2023-01-01", "end_date": "2024-12-31"},
            "sql": """
SELECT
    dl.region,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.total_price) AS revenue,
    SUM(ol.total_price) / SUM(SUM(ol.total_price)) OVER () AS revenue_share
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
GROUP BY dl.region
ORDER BY revenue DESC;
""",
        }

        queries["SA5"] = {
            "description": "Top-performing locations by revenue.",
            "defaults": {"start_date": "2023-01-01", "end_date": "2024-12-31", "limit": 20},
            "sql": """
SELECT
    dl.location_id,
    dl.city,
    dl.state,
    dl.region,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.total_price) AS revenue,
    AVG(ol.total_price) AS avg_line_value
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
GROUP BY dl.location_id, dl.city, dl.state, dl.region
ORDER BY revenue DESC
LIMIT {limit};
""",
        }

        queries["PR1"] = {
            "description": "Product mix and revenue by subcategory.",
            "defaults": {"start_date": "2023-01-01", "end_date": "2023-12-31"},
            "sql": """
SELECT
    dp.subcategory,
    COUNT(DISTINCT dp.product_id) AS active_products,
    SUM(ol.quantity) AS quantity_sold,
    SUM(ol.total_price) AS revenue
FROM order_lines ol
JOIN dim_products dp ON ol.product_record_id = dp.record_id
WHERE ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
  AND ol.order_date BETWEEN dp.from_date AND dp.to_date
GROUP BY dp.subcategory
ORDER BY revenue DESC;
""",
        }

        queries["PR2"] = {
            "description": "Price-band distribution across order lines.",
            "defaults": {"start_date": "2023-01-01", "end_date": "2024-12-31"},
            "sql": """
SELECT
    CASE
        WHEN ol.unit_price < 4 THEN 'Under $4'
        WHEN ol.unit_price < 6 THEN '$4-$5.99'
        WHEN ol.unit_price < 8 THEN '$6-$7.99'
        ELSE '$8+'
    END AS price_band,
    COUNT(*) AS line_count,
    SUM(ol.total_price) AS revenue
FROM order_lines ol
WHERE ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
GROUP BY price_band
ORDER BY price_band;
""",
        }

        queries["TR1"] = {
            "description": "Quarterly revenue and order growth.",
            "defaults": {"start_year": 2023, "end_year": 2024},
            "sql": """
SELECT
    EXTRACT(YEAR FROM ol.order_date) AS year,
    FLOOR((EXTRACT(MONTH FROM ol.order_date) - 1) / 3) + 1 AS quarter,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.total_price) AS revenue
FROM order_lines ol
WHERE EXTRACT(YEAR FROM ol.order_date) BETWEEN {start_year} AND {end_year}
GROUP BY year, quarter
ORDER BY year, quarter;
""",
        }

        queries["TM1"] = {
            "description": "Order cadence by day-part for a selected region.",
            "defaults": {"region": "South", "start_date": "2023-01-01", "end_date": "2024-12-31"},
            "sql": """
SELECT
    CASE
        WHEN EXTRACT(HOUR FROM ol.order_time) BETWEEN 5 AND 10 THEN 'Morning'
        WHEN EXTRACT(HOUR FROM ol.order_time) BETWEEN 11 AND 14 THEN 'Midday'
        WHEN EXTRACT(HOUR FROM ol.order_time) BETWEEN 15 AND 17 THEN 'Afternoon'
        ELSE 'Evening'
    END AS day_part,
    COUNT(DISTINCT ol.order_id) AS orders,
    SUM(ol.total_price) AS revenue,
    AVG(ol.total_price) AS avg_line_value
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE dl.region = '{region}'
  AND ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}'
GROUP BY day_part
ORDER BY day_part;
""",
        }

        queries["QC1"] = {
            "description": "Average lines per order for a given window.",
            "defaults": {"start_date": "2023-01-01", "end_date": "2024-12-31"},
            "sql": """
SELECT
    COUNT(*) * 1.0 / NULLIF(COUNT(DISTINCT ol.order_id), 0) AS avg_lines_per_order,
    SUM(ol.quantity) / NULLIF(COUNT(DISTINCT ol.order_id), 0) AS avg_items_per_order
FROM order_lines ol
WHERE ol.order_date BETWEEN DATE '{start_date}' AND DATE '{end_date}';
""",
        }

        queries["QC2"] = {
            "description": "Seasonal revenue comparison across regions.",
            "defaults": {"start_year": 2023, "end_year": 2024},
            "sql": """
SELECT
    dl.region,
    CASE
        WHEN EXTRACT(MONTH FROM ol.order_date) IN (12, 1, 2) THEN 'Winter'
        WHEN EXTRACT(MONTH FROM ol.order_date) IN (3, 4, 5) THEN 'Spring'
        WHEN EXTRACT(MONTH FROM ol.order_date) IN (6, 7, 8) THEN 'Summer'
        ELSE 'Fall'
    END AS season,
    SUM(ol.total_price) AS revenue,
    COUNT(DISTINCT ol.order_id) AS orders
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE EXTRACT(YEAR FROM ol.order_date) BETWEEN {start_year} AND {end_year}
GROUP BY dl.region, season
ORDER BY dl.region, season;
""",
        }

        return queries

    def get_query(self, query_id: str, params: dict[str, Any] | None = None) -> str:
        if query_id not in self._queries:
            raise ValueError(f"Query '{query_id}' not found")

        entry = self._queries[query_id]
        defaults = dict(entry.get("defaults", {}))
        if params:
            defaults.update(params)
        try:
            return entry["sql"].format(**defaults)
        except KeyError as exc:  # pragma: no cover - defensive
            missing = exc.args[0]
            raise ValueError(f"Missing parameter '{missing}' for query '{query_id}'") from exc

    def get_all_queries(self) -> dict[str, str]:
        return {query_id: self.get_query(query_id) for query_id in self._queries}


__all__ = ["CoffeeShopQueryManager"]
