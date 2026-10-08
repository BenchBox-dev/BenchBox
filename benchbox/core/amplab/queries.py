# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from typing import Any

from benchbox.core.query_manager import ParameterizedQueryManager


class AMPLabQueryManager(ParameterizedQueryManager):
    def __init__(self) -> None:

        self._queries = self._load_queries()

    def _load_queries(self) -> dict[str, str]:

        queries = {}

        queries["1"] = """
SELECT pageURL, pageRank
FROM rankings
WHERE pageRank > {pagerank_threshold};
"""

        queries["1a"] = """
SELECT
    COUNT(*) as total_pages,
    AVG(pageRank) as avg_pagerank,
    MAX(pageRank) as max_pagerank
FROM rankings
WHERE pageRank > {pagerank_threshold};
"""

        queries["2"] = """
SELECT
    sourceIP,
    SUM(adRevenue) as totalRevenue,
    AVG(pageRank) as avgPageRank
FROM uservisits uv
JOIN rankings r ON uv.destURL = r.pageURL
WHERE uv.visitDate BETWEEN '{start_date}' AND '{end_date}'
GROUP BY sourceIP
ORDER BY totalRevenue DESC
LIMIT {limit_rows};
"""

        queries["2a"] = """
SELECT
    uv.destURL,
    uv.visitDate,
    uv.adRevenue,
    r.pageRank,
    r.avgDuration
FROM uservisits uv
JOIN rankings r ON uv.destURL = r.pageURL
WHERE r.pageRank > {pagerank_threshold}
  AND uv.visitDate >= '{start_date}'
ORDER BY r.pageRank DESC
LIMIT {limit_rows};
"""

        queries["3"] = """
SELECT
    sourceIP,
    COUNT(*) as visit_count,
    SUM(adRevenue) as total_revenue,
    AVG(duration) as avg_duration
FROM uservisits
WHERE visitDate BETWEEN '{start_date}' AND '{end_date}'
  AND searchWord LIKE '%{search_term}%'
GROUP BY sourceIP
HAVING COUNT(*) > {min_visits}
ORDER BY total_revenue DESC
LIMIT {limit_rows};
"""

        queries["3a"] = """
SELECT
    url,
    LENGTH(contents) as content_length,
    CASE
        WHEN contents LIKE '%{keyword1}%' THEN 1
        ELSE 0
    END as has_keyword1,
    CASE
        WHEN contents LIKE '%{keyword2}%' THEN 1
        ELSE 0
    END as has_keyword2
FROM documents
WHERE LENGTH(contents) > {min_content_length}
ORDER BY content_length DESC
LIMIT {limit_rows};
"""

        queries["4"] = """
SELECT
    countryCode,
    languageCode,
    COUNT(*) as visit_count,
    SUM(adRevenue) as total_revenue,
    AVG(duration) as avg_duration,
    COUNT(DISTINCT sourceIP) as unique_visitors
FROM uservisits
WHERE visitDate >= '{start_date}'
  AND adRevenue > {min_revenue}
GROUP BY countryCode, languageCode
HAVING COUNT(*) > {min_visits}
ORDER BY total_revenue DESC
LIMIT {limit_rows};
"""

        queries["5"] = """
SELECT
    uv.countryCode,
    COUNT(DISTINCT uv.destURL) as unique_pages,
    COUNT(*) as total_visits,
    SUM(uv.adRevenue) as total_revenue,
    AVG(r.pageRank) as avg_pagerank,
    AVG(uv.duration) as avg_duration
FROM uservisits uv
JOIN rankings r ON uv.destURL = r.pageURL
WHERE uv.visitDate >= '{start_date}'
  AND r.pageRank > {pagerank_threshold}
GROUP BY uv.countryCode
HAVING COUNT(*) > {min_visits}
ORDER BY total_revenue DESC
LIMIT {limit_rows};
"""

        return queries

    def _generate_default_params(self, query_id: str) -> dict[str, Any]:

        defaults = {
            "pagerank_threshold": 1000,
            "min_revenue": 1.0,
            "min_visits": 10,
            "min_content_length": 1000,
            "start_date": "2000-01-01",
            "end_date": "2000-01-03",
            "limit_rows": 100,
            "search_term": "database",
            "keyword1": "web",
            "keyword2": "data",
        }

        return defaults
