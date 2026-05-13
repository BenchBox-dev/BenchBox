"""Join Order Benchmark schema definitions.

This module defines the database schema for the Join Order Benchmark, which is based
on the Internet Movie Database (IMDB) dataset. The schema includes 21 tables with
complex relationships designed to test join order optimization capabilities.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from benchbox.sql_compat.local_exemptions import compat_local


class JoinOrderSchema:
    """Schema manager for the Join Order Benchmark."""

    def __init__(self) -> None:
        """Initialize the Join Order schema manager."""
        self._tables = self._define_tables()

    def _define_tables(self) -> dict[str, dict]:
        """Define the Join Order Benchmark database schema tables."""
        tables = {}

        # Main dimension tables
        tables["title"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "title TEXT NOT NULL",
                "imdb_index VARCHAR(12)",
                "kind_id INTEGER NOT NULL",
                "production_year INTEGER",
                "imdb_id INTEGER",
                "phonetic_code VARCHAR(5)",
                "episode_of_id INTEGER",
                "season_nr INTEGER",
                "episode_nr INTEGER",
                "series_years VARCHAR(49)",
                "md5sum VARCHAR(32)",
            ],
            "foreign_keys": [
                "FOREIGN KEY (kind_id) REFERENCES kind_type(id)",
                "FOREIGN KEY (episode_of_id) REFERENCES title(id)",
            ],
        }

        tables["name"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "name TEXT NOT NULL",
                "imdb_index VARCHAR(12)",
                "imdb_id INTEGER",
                "gender VARCHAR(1)",
                "name_pcode_cf VARCHAR(5)",
                "name_pcode_nf VARCHAR(5)",
                "surname_pcode VARCHAR(5)",
                "md5sum VARCHAR(32)",
            ],
            "foreign_keys": [],
        }

        tables["company_name"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "name TEXT NOT NULL",
                "country_code VARCHAR(255)",
                "imdb_id INTEGER",
                "name_pcode_nf VARCHAR(5)",
                "name_pcode_sf VARCHAR(5)",
                "md5sum VARCHAR(32)",
            ],
            "foreign_keys": [],
        }

        tables["keyword"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "keyword TEXT NOT NULL",
                "phonetic_code VARCHAR(5)",
            ],
            "foreign_keys": [],
        }

        tables["char_name"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "name TEXT NOT NULL",
                "imdb_index VARCHAR(12)",
                "imdb_id INTEGER",
                "name_pcode_nf VARCHAR(5)",
                "surname_pcode VARCHAR(5)",
                "md5sum VARCHAR(32)",
            ],
            "foreign_keys": [],
        }

        # Lookup/reference tables
        tables["kind_type"] = {
            "columns": ["id INTEGER PRIMARY KEY", "kind VARCHAR(15) NOT NULL"],
            "foreign_keys": [],
        }

        tables["company_type"] = {
            "columns": ["id INTEGER PRIMARY KEY", "kind VARCHAR(32) NOT NULL"],
            "foreign_keys": [],
        }

        tables["info_type"] = {
            "columns": ["id INTEGER PRIMARY KEY", "info VARCHAR(32) NOT NULL"],
            "foreign_keys": [],
        }

        tables["role_type"] = {
            "columns": ["id INTEGER PRIMARY KEY", "role VARCHAR(32) NOT NULL"],
            "foreign_keys": [],
        }

        tables["comp_cast_type"] = {
            "columns": ["id INTEGER PRIMARY KEY", "kind VARCHAR(32) NOT NULL"],
            "foreign_keys": [],
        }

        tables["link_type"] = {
            "columns": ["id INTEGER PRIMARY KEY", "link VARCHAR(32) NOT NULL"],
            "foreign_keys": [],
        }

        # Relationship/junction tables
        tables["cast_info"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "person_id INTEGER NOT NULL",
                "movie_id INTEGER NOT NULL",
                "person_role_id INTEGER",
                "note TEXT",
                "nr_order INTEGER",
                "role_id INTEGER NOT NULL",
            ],
            "foreign_keys": [
                "FOREIGN KEY (person_id) REFERENCES name(id)",
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (person_role_id) REFERENCES char_name(id)",
                "FOREIGN KEY (role_id) REFERENCES role_type(id)",
            ],
        }

        tables["movie_companies"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER NOT NULL",
                "company_id INTEGER NOT NULL",
                "company_type_id INTEGER NOT NULL",
                "note TEXT",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (company_id) REFERENCES company_name(id)",
                "FOREIGN KEY (company_type_id) REFERENCES company_type(id)",
            ],
        }

        tables["movie_info"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER NOT NULL",
                "info_type_id INTEGER NOT NULL",
                "info TEXT NOT NULL",
                "note TEXT",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (info_type_id) REFERENCES info_type(id)",
            ],
        }

        tables["movie_info_idx"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER NOT NULL",
                "info_type_id INTEGER NOT NULL",
                "info TEXT NOT NULL",
                "note TEXT",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (info_type_id) REFERENCES info_type(id)",
            ],
        }

        tables["movie_keyword"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER NOT NULL",
                "keyword_id INTEGER NOT NULL",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (keyword_id) REFERENCES keyword(id)",
            ],
        }

        tables["movie_link"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER NOT NULL",
                "linked_movie_id INTEGER NOT NULL",
                "link_type_id INTEGER NOT NULL",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (linked_movie_id) REFERENCES title(id)",
                "FOREIGN KEY (link_type_id) REFERENCES link_type(id)",
            ],
        }

        tables["person_info"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "person_id INTEGER NOT NULL",
                "info_type_id INTEGER NOT NULL",
                "info TEXT NOT NULL",
                "note TEXT",
            ],
            "foreign_keys": [
                "FOREIGN KEY (person_id) REFERENCES name(id)",
                "FOREIGN KEY (info_type_id) REFERENCES info_type(id)",
            ],
        }

        tables["complete_cast"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER",
                "subject_id INTEGER NOT NULL",
                "status_id INTEGER NOT NULL",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (subject_id) REFERENCES comp_cast_type(id)",
                "FOREIGN KEY (status_id) REFERENCES comp_cast_type(id)",
            ],
        }

        # Alternative name tables
        tables["aka_name"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "person_id INTEGER NOT NULL",
                "name TEXT NOT NULL",
                "imdb_index VARCHAR(12)",
                "name_pcode_cf VARCHAR(5)",
                "name_pcode_nf VARCHAR(5)",
                "surname_pcode VARCHAR(5)",
                "md5sum VARCHAR(32)",
            ],
            "foreign_keys": ["FOREIGN KEY (person_id) REFERENCES name(id)"],
        }

        tables["aka_title"] = {
            "columns": [
                "id INTEGER PRIMARY KEY",
                "movie_id INTEGER NOT NULL",
                "title TEXT NOT NULL",
                "imdb_index VARCHAR(12)",
                "kind_id INTEGER NOT NULL",
                "production_year INTEGER",
                "phonetic_code VARCHAR(5)",
                "episode_of_id INTEGER",
                "season_nr INTEGER",
                "episode_nr INTEGER",
                "note TEXT",
                "md5sum VARCHAR(32)",
            ],
            "foreign_keys": [
                "FOREIGN KEY (movie_id) REFERENCES title(id)",
                "FOREIGN KEY (kind_id) REFERENCES kind_type(id)",
                "FOREIGN KEY (episode_of_id) REFERENCES title(id)",
            ],
        }

        return tables

    @compat_local(
        kind="type_mapping",
        platform_specific=True,
        reason=(
            "Substitutes dialect-specific type tokens: VARCHAR→CHARACTER VARYING for postgres, "
            "TEXT→TEXT CHARACTER SET utf8mb4 for mysql. "
            "Pure column-type translation - no engine/layout policy."
        ),
    )
    def get_create_table_sql(
        self,
        table_name: str,
        dialect: str = "sqlite",
        *,
        include_foreign_keys: bool = False,
    ) -> str:
        """Generate CREATE TABLE SQL for a specific table.

        Args:
            table_name: Name of the table
            dialect: SQL dialect ('sqlite', 'postgres', 'mysql', 'duckdb')

        Returns:
            SQL CREATE TABLE statement
        """
        if table_name not in self._tables:
            raise ValueError(f"Table {table_name} not found in schema")

        table = self._tables[table_name]
        columns = table["columns"]

        # Adjust column definitions for different dialects
        if dialect == "postgres":
            columns = [col.replace("VARCHAR", "CHARACTER VARYING") for col in columns]
        elif dialect == "mysql":
            columns = [col.replace("TEXT", "TEXT CHARACTER SET utf8mb4") for col in columns]

        sql = f"CREATE TABLE {table_name} (\n"
        sql += ",\n".join(f"    {col}" for col in columns)

        # The canonical IMDb dataset contains dangling references, so foreign
        # keys are opt-in metadata rather than default load-time constraints.
        if include_foreign_keys and dialect in ["postgres", "mysql"] and "foreign_keys" in table:
            for fk in table["foreign_keys"]:
                sql += f",\n    {fk}"

        sql += "\n);"
        return sql

    def get_create_tables_sql(self, dialect: str = "sqlite", *, include_foreign_keys: bool = False) -> str:
        """Generate CREATE TABLE SQL for all tables.

        Args:
            dialect: SQL dialect ('sqlite', 'postgres', 'mysql', 'duckdb')

        Returns:
            SQL CREATE TABLE statements for all tables
        """
        # Order tables to handle dependencies
        table_order = [
            # Reference tables first
            "kind_type",
            "company_type",
            "info_type",
            "role_type",
            "comp_cast_type",
            "link_type",
            # Main dimension tables
            "title",
            "name",
            "company_name",
            "keyword",
            "char_name",
            # Relationship tables
            "cast_info",
            "movie_companies",
            "movie_info",
            "movie_info_idx",
            "movie_keyword",
            "movie_link",
            "person_info",
            "complete_cast",
            "aka_name",
            "aka_title",
        ]

        sql_statements = []
        for table_name in table_order:
            sql_statements.append(
                self.get_create_table_sql(table_name, dialect, include_foreign_keys=include_foreign_keys)
            )

        return "\n\n".join(sql_statements)

    def get_table_names(self) -> list[str]:
        """Get list of all table names.

        Returns:
            List of table names
        """
        return list(self._tables.keys())

    def get_table_info(self, table_name: str) -> dict:
        """Get information about a specific table.

        Args:
            table_name: Name of the table

        Returns:
            Dictionary with table column and foreign key information
        """
        if table_name not in self._tables:
            raise ValueError(f"Table {table_name} not found in schema")

        return self._tables[table_name].copy()

    def get_relationship_tables(self) -> list[str]:
        """Get list of relationship/junction tables.

        Returns:
            List of relationship table names
        """
        return [
            "cast_info",
            "movie_companies",
            "movie_info",
            "movie_info_idx",
            "movie_keyword",
            "movie_link",
            "person_info",
            "complete_cast",
            "aka_name",
            "aka_title",
        ]

    def get_dimension_tables(self) -> list[str]:
        """Get list of main dimension tables.

        Returns:
            List of dimension table names
        """
        return [
            "title",
            "name",
            "company_name",
            "keyword",
            "char_name",
            "kind_type",
            "company_type",
            "info_type",
            "role_type",
            "comp_cast_type",
            "link_type",
        ]
