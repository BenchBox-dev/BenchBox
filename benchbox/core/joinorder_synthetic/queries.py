"""Join Order Benchmark query management.

This module provides functionality to load and manage the Join Order Benchmark
queries that test join order optimization capabilities using the IMDB dataset.
All queries are designed to stress-test query optimizers with complex multi-table
joins and varying selectivity patterns.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
from pathlib import Path
from typing import Optional

from benchbox.utils.printing import emit


class JoinOrderQueryManager:
    """Manager for Join Order Benchmark queries."""

    def __init__(self, queries_dir: Optional[str] = None) -> None:
        """Initialize the Join Order query manager.

        Args:
            queries_dir: Path to directory containing Join Order Benchmark query files.
                        If None, uses embedded queries.
        """
        self._queries_dir = queries_dir
        self._queries = self._load_queries()

    def _load_queries(self) -> dict[str, str]:
        """Load all Join Order Benchmark queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """

        # If queries_dir is provided, load from files
        if self._queries_dir and os.path.exists(self._queries_dir):
            return self._load_queries_from_files()

        # Otherwise, use embedded queries
        return self._load_embedded_queries()

    def _load_queries_from_files(self) -> dict[str, str]:
        """Load queries from the Join Order Benchmark query files directory.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        queries = {}
        queries_path = Path(self._queries_dir)

        # Load all query files matching pattern [0-9]+[a-z].sql
        for query_file in sorted(queries_path.glob("*.sql")):
            if query_file.stem.replace(".", "").replace("-", "").isalnum():
                query_id = query_file.stem
                try:
                    with open(query_file, encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            queries[query_id] = content
                except Exception as e:
                    emit(f"Warning: Could not load query {query_id}: {e}")

        return queries

    def _load_embedded_queries(self) -> dict[str, str]:
        """Load embedded Join Order Benchmark queries based on the original benchmark.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        queries = {}

        # Query 1a: Production companies with top 250 rank
        queries["1a"] = """
SELECT MIN(mc.note) AS production_note,
       MIN(t.title) AS movie_title,
       MIN(t.production_year) AS movie_year
FROM company_type AS ct,
     info_type AS it,
     movie_companies AS mc,
     movie_info_idx AS mi_idx,
     title AS t
WHERE ct.kind = 'production companies'
  AND it.info = 'top 250 rank'
  AND mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'
  AND (mc.note LIKE '%(co-production)%'
       OR mc.note LIKE '%(presents)%')
  AND ct.id = mc.company_type_id
  AND t.id = mc.movie_id
  AND t.id = mi_idx.movie_id
  AND mc.movie_id = mi_idx.movie_id
  AND it.id = mi_idx.info_type_id;
"""

        # Query 1b: Variant of 1a with different predicates
        queries["1b"] = """
SELECT MIN(mc.note) AS production_note,
       MIN(t.title) AS movie_title,
       MIN(t.production_year) AS movie_year
FROM company_type AS ct,
     info_type AS it,
     movie_companies AS mc,
     movie_info_idx AS mi_idx,
     title AS t
WHERE ct.kind = 'production companies'
  AND it.info = 'bottom 10 rank'
  AND mc.note NOT LIKE '%(as Metro-Goldwyn-Mayer Pictures)%'
  AND (mc.note LIKE '%(co-production)%'
       OR mc.note LIKE '%(presents)%')
  AND ct.id = mc.company_type_id
  AND t.id = mc.movie_id
  AND t.id = mi_idx.movie_id
  AND mc.movie_id = mi_idx.movie_id
  AND it.id = mi_idx.info_type_id;
"""

        # Query 2a: Movies with specific keywords
        queries["2a"] = """
SELECT MIN(t.title) AS movie_title
FROM company_name AS cn,
     keyword AS k,
     movie_companies AS mc,
     movie_keyword AS mk,
     title AS t
WHERE cn.country_code ='[de]'
  AND k.keyword ='character-name-in-title'
  AND cn.id = mc.company_id
  AND mc.movie_id = t.id
  AND t.id = mk.movie_id
  AND mk.keyword_id = k.id
  AND mc.movie_id = mk.movie_id;
"""

        # Query 3a: Cast information with specific roles
        queries["3a"] = """
SELECT MIN(t.title) AS movie_title
FROM keyword AS k,
     movie_info AS mi,
     movie_keyword AS mk,
     title AS t
WHERE k.keyword LIKE '%sequel%'
  AND mi.info IN ('Sweden',
                  'Norway',
                  'Germany',
                  'Denmark',
                  'Swedish',
                  'Denish',
                  'Norwegian',
                  'German',
                  'USA',
                  'American')
  AND t.production_year > 1990
  AND t.id = mi.movie_id
  AND t.id = mk.movie_id
  AND mk.keyword_id = k.id
  AND mi.movie_id = mk.movie_id;
"""

        # Query 4a: Complex join with multiple tables
        queries["4a"] = """
SELECT MIN(mi_idx.info) AS rating,
       MIN(t.title) AS movie_title
FROM info_type AS it,
     keyword AS k,
     movie_info_idx AS mi_idx,
     movie_keyword AS mk,
     title AS t
WHERE it.info ='rating'
  AND k.keyword LIKE '%sequel%'
  AND mi_idx.info > '2.0'
  AND t.production_year > 1990
  AND t.id = mi_idx.movie_id
  AND t.id = mk.movie_id
  AND mk.keyword_id = k.id
  AND it.id = mi_idx.info_type_id
  AND mi_idx.movie_id = mk.movie_id;
"""

        # Query 5a: European movies
        queries["5a"] = """
SELECT MIN(t.title) AS typical_european_movie
FROM company_type AS ct,
     info_type AS it,
     movie_companies AS mc,
     movie_info AS mi,
     title AS t
WHERE ct.kind = 'production companies'
  AND mc.note LIKE '%(theatrical)%'
  AND mc.note LIKE '%(France)%'
  AND mi.info IN ('Sweden',
                  'Norway',
                  'Germany',
                  'Denmark',
                  'Swedish',
                  'Denish',
                  'Norwegian',
                  'German')
  AND t.production_year > 2005
  AND t.id = mi.movie_id
  AND t.id = mc.movie_id
  AND mc.movie_id = mi.movie_id
  AND ct.id = mc.company_type_id
  AND it.id = mi.info_type_id;
"""

        # Query 6a: Cast and company information
        queries["6a"] = """
SELECT MIN(k.keyword) AS movie_keyword,
       MIN(n.name) AS actor_name,
       MIN(t.title) AS hero_movie
FROM cast_info AS ci,
     keyword AS k,
     movie_keyword AS mk,
     name AS n,
     title AS t
WHERE k.keyword IN ('superhero',
                    'sequel',
                    'second-part',
                    'marvel-comics',
                    'based-on-comic',
                    'tv-special',
                    'fight',
                    'violence')
  AND n.name LIKE '%Downey%Robert%'
  AND t.production_year > 2000
  AND k.id = mk.keyword_id
  AND t.id = mk.movie_id
  AND t.id = ci.movie_id
  AND ci.person_id = n.id
  AND mk.movie_id = ci.movie_id;
"""

        # Query 7a: Production year and company information
        queries["7a"] = """
SELECT MIN(n.name) AS of_person,
       MIN(t.title) AS biography_movie
FROM aka_name AS an,
     cast_info AS ci,
     info_type AS it,
     link_type AS lt,
     movie_link AS ml,
     name AS n,
     person_info AS pi,
     title AS t
WHERE an.name LIKE '%a%'
  AND it.info ='mini biography'
  AND lt.link ='features'
  AND n.name_pcode_cf LIKE 'D%'
  AND n.gender='m'
  AND pi.note ='Volker Boehm'
  AND t.production_year BETWEEN 1980 AND 1995
  AND n.id = an.person_id
  AND n.id = pi.person_id
  AND ci.person_id = n.id
  AND t.id = ci.movie_id
  AND ml.linked_movie_id = t.id
  AND lt.id = ml.link_type_id
  AND it.id = pi.info_type_id
  AND pi.person_id = an.person_id
  AND pi.person_id = ci.person_id
  AND an.person_id = ci.person_id
  AND ci.movie_id = ml.linked_movie_id;
"""

        # Query 8a: Complex cast information
        queries["8a"] = """
SELECT MIN(an1.name) AS actress_pseudonym,
       MIN(t.title) AS japanese_movie_dubbed
FROM aka_name AS an1,
     cast_info AS ci,
     company_name AS cn,
     movie_companies AS mc,
     name AS n1,
     role_type AS rt,
     title AS t
WHERE ci.note ='(voice: Japanese version)'
  AND cn.country_code ='[jp]'
  AND mc.note LIKE '%(Japan)%'
  AND mc.note NOT LIKE '%(USA)%'
  AND n1.name LIKE '%Yo%'
  AND n1.name NOT LIKE '%Yu%'
  AND rt.role ='actress'
  AND an1.person_id = n1.id
  AND n1.id = ci.person_id
  AND ci.movie_id = t.id
  AND t.id = mc.movie_id
  AND mc.company_id = cn.id
  AND ci.role_id = rt.id
  AND an1.person_id = ci.person_id
  AND ci.movie_id = mc.movie_id;
"""

        # Query 9a: Movie information with specific criteria
        queries["9a"] = """
SELECT MIN(an.name) AS alternative_name,
       MIN(chn.name) AS voiced_character_name,
       MIN(n.name) AS voicing_actress,
       MIN(t.title) AS american_movie
FROM aka_name AS an,
     char_name AS chn,
     cast_info AS ci,
     company_name AS cn,
     movie_companies AS mc,
     name AS n,
     role_type AS rt,
     title AS t
WHERE ci.note IN ('(voice)',
                  '(voice: Japanese version)',
                  '(voice) (uncredited)',
                  '(voice: English version)')
  AND cn.country_code ='[us]'
  AND mc.note LIKE '%(USA)%'
  AND mc.note NOT LIKE '%(worldwide)%'
  AND n.gender ='f'
  AND n.name LIKE '%An%'
  AND rt.role ='actress'
  AND t.production_year BETWEEN 2005 AND 2015
  AND ci.movie_id = t.id
  AND t.id = mc.movie_id
  AND ci.movie_id = mc.movie_id
  AND mc.company_id = cn.id
  AND ci.role_id = rt.id
  AND n.id = ci.person_id
  AND chn.id = ci.person_role_id
  AND an.person_id = n.id
  AND an.person_id = ci.person_id;
"""

        # Query 10a: Movie ratings and keywords
        queries["10a"] = """
SELECT MIN(chn.name) AS character,
       MIN(t.title) AS movie_with_american_producer
FROM char_name AS chn,
     cast_info AS ci,
     company_name AS cn,
     company_type AS ct,
     movie_companies AS mc,
     role_type AS rt,
     title AS t
WHERE ci.note LIKE '%(producer)%'
  AND cn.country_code = '[us]'
  AND rt.role = 'producer'
  AND t.production_year > 1990
  AND t.id = mc.movie_id
  AND t.id = ci.movie_id
  AND ci.movie_id = mc.movie_id
  AND chn.id = ci.person_role_id
  AND rt.id = ci.role_id
  AND cn.id = mc.company_id
  AND ct.id = mc.company_type_id;
"""

        # Include more core queries in demonstrate various join patterns
        # These represent the key optimization challenges in the benchmark

        # Query 11a: Multiple table joins with filtering
        queries["11a"] = """
SELECT MIN(cn.name) AS from_company,
       MIN(lt.link) AS movie_link_type,
       MIN(t.title) AS non_polish_sequel_movie
FROM company_name AS cn,
     company_type AS ct,
     keyword AS k,
     link_type AS lt,
     movie_companies AS mc,
     movie_info AS mi,
     movie_keyword AS mk,
     movie_link AS ml,
     title AS t
WHERE cn.country_code !='[pl]'
  AND (cn.name LIKE '%Film%'
       OR cn.name LIKE '%Warner%')
  AND ct.kind ='production companies'
  AND k.keyword ='sequel'
  AND lt.link LIKE '%follow%'
  AND mc.note IS NULL
  AND mi.info IN ('Sweden',
                  'Norway',
                  'Germany',
                  'Denmark',
                  'Swedish',
                  'Denish',
                  'Norwegian',
                  'German',
                  'English')
  AND t.production_year BETWEEN 1950 AND 2010
  AND lt.id = ml.link_type_id
  AND ml.movie_id = t.id
  AND t.id = mk.movie_id
  AND mk.keyword_id = k.id
  AND t.id = mc.movie_id
  AND mc.company_type_id = ct.id
  AND mc.company_id = cn.id
  AND mi.movie_id = t.id
  AND ml.movie_id = mk.movie_id
  AND ml.movie_id = mc.movie_id
  AND mk.movie_id = mc.movie_id
  AND ml.movie_id = mi.movie_id
  AND mk.movie_id = mi.movie_id
  AND mc.movie_id = mi.movie_id;
"""

        # Query 12a: Cast and production information
        queries["12a"] = """
SELECT MIN(cn.name) AS movie_company,
       MIN(mi_idx.info) AS rating,
       MIN(t.title) AS drama_horror_movie
FROM company_name AS cn,
     company_type AS ct,
     info_type AS it1,
     info_type AS it2,
     movie_companies AS mc,
     movie_info AS mi,
     movie_info_idx AS mi_idx,
     title AS t
WHERE cn.country_code = '[us]'
  AND ct.kind = 'production companies'
  AND it1.info = 'genres'
  AND it2.info = 'rating'
  AND mi.info IN ('Drama',
                  'Horror',
                  'Western',
                  'Family')
  AND mi_idx.info > '8.0'
  AND t.production_year BETWEEN 2005 AND 2008
  AND t.id = mi.movie_id
  AND t.id = mi_idx.movie_id
  AND mi.movie_id = mi_idx.movie_id
  AND t.id = mc.movie_id
  AND ct.id = mc.company_type_id
  AND cn.id = mc.company_id
  AND mc.movie_id = mi.movie_id
  AND mc.movie_id = mi_idx.movie_id
  AND mi.movie_id = mc.movie_id
  AND it1.id = mi.info_type_id
  AND it2.id = mi_idx.info_type_id;
"""

        return queries

    def get_query(self, query_id: str) -> str:
        """Get a Join Order Benchmark query by ID.

        Args:
            query_id: Query identifier (e.g., '1a', '2b', etc.)

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
        """Get all Join Order Benchmark queries.

        Returns:
            Dictionary mapping query IDs to SQL text
        """
        return self._queries.copy()

    def get_query_ids(self) -> list[str]:
        """Get list of all query IDs.

        Returns:
            List of query IDs in sorted order
        """
        return sorted(self._queries.keys())

    def get_query_count(self) -> int:
        """Get total number of queries.

        Returns:
            Number of queries available
        """
        return len(self._queries)

    def get_queries_by_complexity(self) -> dict[str, list[str]]:
        """Categorize queries by complexity based on table count.

        Returns:
            Dictionary mapping complexity levels to query IDs
        """
        complexity_map = {"simple": [], "medium": [], "complex": []}

        for query_id, query_sql in self._queries.items():
            # Count FROM clauses and JOIN keywords to estimate complexity
            from_count = query_sql.upper().count("FROM")
            join_count = query_sql.upper().count("JOIN")
            table_count = len(
                [
                    line
                    for line in query_sql.split("\n")
                    if "AS " in line and any(keyword in line.upper() for keyword in ["FROM", "JOIN", ","])
                ]
            )

            # Rough complexity classification
            total_complexity = from_count + join_count + (table_count // 2)

            if total_complexity <= 3:
                complexity_map["simple"].append(query_id)
            elif total_complexity <= 6:
                complexity_map["medium"].append(query_id)
            else:
                complexity_map["complex"].append(query_id)

        return complexity_map

    def get_queries_by_pattern(self) -> dict[str, list[str]]:
        """Categorize queries by join pattern.

        Returns:
            Dictionary mapping join patterns to query IDs
        """
        pattern_map = {
            "star_join": [],  # Central table with many relationships
            "chain_join": [],  # Sequential joins
            "complex_join": [],  # Mixed patterns
        }

        for query_id, query_sql in self._queries.items():
            # Simple heuristic based on table patterns
            if "movie_companies" in query_sql and "movie_info" in query_sql:
                pattern_map["star_join"].append(query_id)
            elif query_sql.count("JOIN") >= 2:
                pattern_map["complex_join"].append(query_id)
            else:
                pattern_map["chain_join"].append(query_id)

        return pattern_map
