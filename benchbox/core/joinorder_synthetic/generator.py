"""Synthetic Join Order schema smoke-test data generation.

This module creates synthetic data with uniformly-random distributions for
joinorder schema smoke testing only. It is not a substitute for canonical JOB;
see ``benchbox.core.joinorder`` for the canonical IMDb 2013 implementation.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import TYPE_CHECKING, Union

from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler

if TYPE_CHECKING:
    from cloudpathlib import CloudPath

    from benchbox.utils.cloud_storage import DatabricksPath

PathLike = Union[Path, "CloudPath", "DatabricksPath"]

from benchbox.core.joinorder.schema import JoinOrderSchema
from benchbox.core.manifest_utils import write_generator_manifest
from benchbox.utils.compression_mixin import CompressionMixin


class JoinOrderGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Synthetic data generator for Join Order Benchmark."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        *,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_regenerate: bool = False,
        **kwargs,
    ) -> None:
        """Initialize the Join Order data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = ~1GB)
            output_dir: Output directory for generated data files
                (defaults to benchmark_runs/datagen/joinorder_synthetic_sf{X})
            verbose: Verbosity level (-v=1, -vv=2; bool True treated as 1)
            quiet: Suppress all output
            force_regenerate: Force regeneration even if data exists
            **kwargs: Additional arguments including compression options
        """
        # Initialize compression mixin first so compression attributes are available downstream
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        # Use default path if None is provided (handled by create_path_handler)
        if output_dir is None:
            # This will be set by the benchmark's BaseBenchmark.__init__ via self.output_dir
            # For standalone use, create a default path
            from benchbox.utils.scale_factor import format_scale_factor

            sf_str = format_scale_factor(scale_factor)
            output_dir = Path.cwd() / "benchmark_runs" / "datagen" / f"joinorder_synthetic_{sf_str}"
        self.output_dir = create_path_handler(output_dir)
        self.schema = JoinOrderSchema()
        self.force_regenerate = force_regenerate
        # Store verbosity flags for potential progress output in the future
        if isinstance(verbose, bool):
            self.verbose_level = 1 if verbose else 0
        else:
            self.verbose_level = int(verbose or 0)
        self.verbose_enabled = self.verbose_level >= 1 and not quiet
        self.very_verbose = self.verbose_level >= 2 and not quiet
        self.quiet = bool(quiet)

        # Base row counts keep the historical smoke-test table sizes while
        # bringing SF=1 closer to BenchBox's ~1GB synthetic baseline.
        self.base_row_counts = {
            # Reference tables (small, relatively static)
            "kind_type": 7,
            "company_type": 4,
            "info_type": 113,
            "role_type": 12,
            "comp_cast_type": 4,
            "link_type": 18,
            # Main dimension tables
            "title": 500_000,  # Movies/TV shows
            "name": 800_000,  # People
            "company_name": 60_000,  # Companies
            "keyword": 24_000,  # Keywords
            "char_name": 600_000,  # Character names
            # Large relationship tables
            "cast_info": 7_000_000,  # Person-movie relationships
            "movie_companies": 520_000,  # Movie-company relationships
            "movie_info": 3_000_000,  # Movie metadata
            "movie_info_idx": 280_000,  # Movie ratings/rankings
            "movie_keyword": 1_000_000,  # Movie-keyword relationships
            # Smaller relationship tables
            "movie_link": 6_000,  # Movie-movie relationships
            "person_info": 600_000,  # Person metadata
            "complete_cast": 30_000,  # Cast completion info
            "aka_name": 180_000,  # Alternative names
            "aka_title": 80_000,  # Alternative titles
        }

        # Track per-table row counts for manifest output
        self._manifest_row_counts: dict[str, int] = {}

    def generate_data(self) -> list[Path]:
        """Generate synthetic Join Order Benchmark data files.

        Returns:
            List of generated data file paths
        """
        # Use centralized cloud/local generation handler, but adapt for List[Path] return type
        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            self._generate_data_local,
            False,  # verbose=False for JoinOrder
        )
        self._write_manifest(table_paths)

        # Convert dict values to list for backward compatibility
        return list(table_paths.values())

    def _generate_data_local(self, output_dir: Path) -> dict[str, Path]:
        """Generate data locally (original implementation)."""
        # Temporarily modify instance output_dir to use provided output_dir
        original_output_dir = self.output_dir
        self.output_dir = output_dir
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            generated_files = {}
            self._manifest_row_counts = {}

            # Generate lookup tables first (to get valid IDs)
            lookup_data = self._generate_lookup_tables()

            # Generate main dimension tables
            dimension_data = self._generate_dimension_tables(lookup_data)

            # Generate relationship tables
            relationship_data = self._generate_relationship_tables(dimension_data)

            # Write all data to files
            all_data = {**lookup_data, **dimension_data, **relationship_data}

            for table_name, data in all_data.items():
                file_path = self._write_table_data(table_name, data)
                generated_files[table_name] = file_path
                self._manifest_row_counts[table_name] = len(data)

            return generated_files
        finally:
            # Restore original output_dir
            self.output_dir = original_output_dir

    def _generate_lookup_tables(self) -> dict[str, list[tuple]]:
        """Generate lookup/reference table data.

        Returns:
            Dictionary mapping table names to row data
        """
        data = {}

        # kind_type: Types of titles (movie, tv series, etc.)
        data["kind_type"] = [
            (1, "movie"),
            (2, "tv series"),
            (3, "tv movie"),
            (4, "video movie"),
            (5, "tv mini series"),
            (6, "video game"),
            (7, "episode"),
        ]

        # company_type: Types of companies
        data["company_type"] = [
            (1, "distributors"),
            (2, "production companies"),
            (3, "special effects companies"),
            (4, "miscellaneous companies"),
        ]

        # info_type: Types of movie information
        info_types = [
            "rating",
            "votes",
            "genres",
            "languages",
            "countries",
            "release dates",
            "running times",
            "locations",
            "budget",
            "gross",
            "keywords",
            "plot",
            "goofs",
            "trivia",
            "quotes",
            "soundtrack",
            "technical",
            "color info",
            "sound mix",
            "certificates",
            "filming locations",
            "production dates",
            "top 250 rank",
            "bottom 10 rank",
        ]
        data["info_type"] = [(i + 1, info_type) for i, info_type in enumerate(info_types)]

        # role_type: Types of roles
        data["role_type"] = [
            (1, "actor"),
            (2, "actress"),
            (3, "producer"),
            (4, "writer"),
            (5, "cinematographer"),
            (6, "composer"),
            (7, "costume designer"),
            (8, "director"),
            (9, "editor"),
            (10, "miscellaneous crew"),
            (11, "production designer"),
            (12, "guest"),
        ]

        # comp_cast_type: Cast completion types
        data["comp_cast_type"] = [
            (1, "cast"),
            (2, "crew"),
            (3, "complete"),
            (4, "incomplete"),
        ]

        # link_type: Movie link types
        data["link_type"] = [
            (1, "follows"),
            (2, "followed by"),
            (3, "remake of"),
            (4, "remade as"),
            (5, "references"),
            (6, "referenced in"),
            (7, "spoofs"),
            (8, "spoofed in"),
            (9, "features"),
            (10, "featured in"),
            (11, "spin off from"),
            (12, "spin off"),
            (13, "version of"),
            (14, "similar to"),
            (15, "edited into"),
            (16, "edited from"),
            (17, "alternate language version of"),
            (18, "unknown link"),
        ]

        return data

    def _generate_dimension_tables(self, lookup_data: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
        """Generate main dimension table data.

        Args:
            lookup_data: Previously generated lookup table data

        Returns:
            Dictionary mapping table names to row data
        """
        data = {}

        # Generate titles (movies, TV shows, etc.)
        title_count = int(self.base_row_counts["title"] * self.scale_factor)
        data["title"] = self._generate_titles(title_count)

        # Generate names (people)
        name_count = int(self.base_row_counts["name"] * self.scale_factor)
        data["name"] = self._generate_names(name_count)

        # Generate company names
        company_count = int(self.base_row_counts["company_name"] * self.scale_factor)
        data["company_name"] = self._generate_companies(company_count)

        # Generate keywords
        keyword_count = int(self.base_row_counts["keyword"] * self.scale_factor)
        data["keyword"] = self._generate_keywords(keyword_count)

        # Generate character names
        char_count = int(self.base_row_counts["char_name"] * self.scale_factor)
        data["char_name"] = self._generate_character_names(char_count)

        return data

    def _generate_relationship_tables(self, dimension_data: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
        """Generate relationship table data.

        Args:
            dimension_data: Previously generated dimension table data

        Returns:
            Dictionary mapping table names to row data
        """
        data = {}

        # Extract max IDs from dimension tables
        max_title_id = max(row[0] for row in dimension_data["title"])
        max_name_id = max(row[0] for row in dimension_data["name"])
        max_company_id = max(row[0] for row in dimension_data["company_name"])
        max_keyword_id = max(row[0] for row in dimension_data["keyword"])
        max_char_id = max(row[0] for row in dimension_data["char_name"])

        # Generate cast_info (person-movie relationships)
        cast_count = int(self.base_row_counts["cast_info"] * self.scale_factor)
        data["cast_info"] = self._generate_cast_info(cast_count, max_name_id, max_title_id, max_char_id)

        # Generate movie_companies
        mc_count = int(self.base_row_counts["movie_companies"] * self.scale_factor)
        data["movie_companies"] = self._generate_movie_companies(mc_count, max_title_id, max_company_id)

        # Generate movie_info
        mi_count = int(self.base_row_counts["movie_info"] * self.scale_factor)
        data["movie_info"] = self._generate_movie_info(mi_count, max_title_id)

        # Generate movie_info_idx
        mi_idx_count = int(self.base_row_counts["movie_info_idx"] * self.scale_factor)
        data["movie_info_idx"] = self._generate_movie_info_idx(mi_idx_count, max_title_id)

        # Generate movie_keyword
        mk_count = int(self.base_row_counts["movie_keyword"] * self.scale_factor)
        data["movie_keyword"] = self._generate_movie_keyword(mk_count, max_title_id, max_keyword_id)

        # Generate movie_link (movie-movie relationships)
        ml_count = int(self.base_row_counts["movie_link"] * self.scale_factor)
        data["movie_link"] = self._generate_movie_link(ml_count, max_title_id)

        # Generate person_info (person metadata)
        pi_count = int(self.base_row_counts["person_info"] * self.scale_factor)
        data["person_info"] = self._generate_person_info(pi_count, max_name_id)

        # Generate complete_cast (cast completeness info)
        cc_count = int(self.base_row_counts["complete_cast"] * self.scale_factor)
        data["complete_cast"] = self._generate_complete_cast(cc_count, max_title_id)

        # Generate aka_name (alternative person names)
        an_count = int(self.base_row_counts["aka_name"] * self.scale_factor)
        data["aka_name"] = self._generate_aka_name(an_count, max_name_id)

        # Generate aka_title (alternative movie titles)
        at_count = int(self.base_row_counts["aka_title"] * self.scale_factor)
        data["aka_title"] = self._generate_aka_title(at_count, max_title_id)

        return data

    def _generate_titles(self, count: int) -> list[tuple]:
        """Generate title data."""
        titles = []
        movie_prefixes = ["The", "A", "An", ""]
        movie_words = [
            "Adventure",
            "Mystery",
            "Romance",
            "Comedy",
            "Drama",
            "Action",
            "Horror",
            "Thriller",
        ]

        for i in range(1, count + 1):
            prefix = random.choice(movie_prefixes)
            word1 = random.choice(movie_words)
            word2 = random.choice(movie_words)

            title = f"{prefix} {word1} {word2}".strip()
            kind_id = random.randint(1, 7)
            production_year = random.randint(1950, 2023) if random.random() > 0.1 else None

            titles.append(
                (
                    i,
                    title,
                    None,
                    kind_id,
                    production_year,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
            )

        return titles

    def _generate_names(self, count: int) -> list[tuple]:
        """Generate name data."""
        names = []
        first_names = [
            "John",
            "Jane",
            "Michael",
            "Sarah",
            "David",
            "Lisa",
            "Robert",
            "Mary",
            "James",
            "Jennifer",
        ]
        last_names = [
            "Smith",
            "Johnson",
            "Williams",
            "Brown",
            "Jones",
            "Garcia",
            "Miller",
            "Davis",
            "Rodriguez",
            "Martinez",
        ]

        for i in range(1, count + 1):
            first = random.choice(first_names)
            last = random.choice(last_names)
            name = f"{first} {last}"
            gender = random.choice(["m", "f"]) if random.random() > 0.1 else None

            names.append((i, name, None, None, gender, None, None, None, None))

        return names

    def _generate_companies(self, count: int) -> list[tuple]:
        """Generate company name data."""
        companies = []
        company_types = [
            "Studios",
            "Productions",
            "Pictures",
            "Films",
            "Entertainment",
            "Media",
        ]
        company_names = [
            "Universal",
            "Warner",
            "Disney",
            "Sony",
            "Paramount",
            "Fox",
            "MGM",
            "Columbia",
        ]
        countries = [
            "[us]",
            "[uk]",
            "[de]",
            "[fr]",
            "[jp]",
            "[ca]",
            "[au]",
            "[it]",
            "[es]",
            "[in]",
        ]

        for i in range(1, count + 1):
            name_part = random.choice(company_names)
            type_part = random.choice(company_types)
            name = f"{name_part} {type_part}"
            country = random.choice(countries)

            companies.append((i, name, country, None, None, None, None))

        return companies

    def _generate_keywords(self, count: int) -> list[tuple]:
        """Generate keyword data."""
        keywords = []
        keyword_list = [
            "action",
            "adventure",
            "comedy",
            "drama",
            "horror",
            "thriller",
            "romance",
            "sequel",
            "superhero",
            "character-name-in-title",
            "based-on-novel",
            "violence",
            "murder",
            "love",
            "friendship",
            "betrayal",
            "revenge",
            "family",
            "war",
            "crime",
            "mystery",
            "fantasy",
            "sci-fi",
        ]

        for i in range(1, count + 1):
            keyword = keyword_list[i - 1] if i <= len(keyword_list) else f"keyword_{i}"

            keywords.append((i, keyword, None))

        return keywords

    def _generate_character_names(self, count: int) -> list[tuple]:
        """Generate character name data."""
        chars = []
        char_names = [
            "John Doe",
            "Jane Smith",
            "The Hero",
            "The Villain",
            "Detective Brown",
            "Dr. Johnson",
        ]

        for i in range(1, count + 1):
            name = char_names[i - 1] if i <= len(char_names) else f"Character {i}"

            chars.append((i, name, None, None, None, None, None))

        return chars

    def _generate_cast_info(self, count: int, max_name_id: int, max_title_id: int, max_char_id: int) -> list[tuple]:
        """Generate cast_info data."""
        cast_info = []

        for i in range(1, count + 1):
            person_id = random.randint(1, max_name_id)
            movie_id = random.randint(1, max_title_id)
            person_role_id = random.randint(1, max_char_id) if random.random() > 0.3 else None
            role_id = random.randint(1, 12)
            note = None
            nr_order = random.randint(1, 20) if random.random() > 0.5 else None

            cast_info.append((i, person_id, movie_id, person_role_id, note, nr_order, role_id))

        return cast_info

    def _generate_movie_companies(self, count: int, max_title_id: int, max_company_id: int) -> list[tuple]:
        """Generate movie_companies data."""
        movie_companies = []

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            company_id = random.randint(1, max_company_id)
            company_type_id = random.randint(1, 4)
            note = None

            movie_companies.append((i, movie_id, company_id, company_type_id, note))

        return movie_companies

    def _generate_movie_info(self, count: int, max_title_id: int) -> list[tuple]:
        """Generate movie_info data."""
        movie_info = []
        info_values = {
            1: ["8.5", "7.2", "6.8", "9.1", "5.5"],  # rating
            2: ["1000", "5000", "50000", "100000"],  # votes
            3: ["Drama", "Comedy", "Action", "Horror", "Romance"],  # genres
            4: ["English", "Spanish", "French", "German", "Japanese"],  # languages
            5: ["USA", "UK", "Germany", "France", "Japan"],  # countries
        }

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            info_type_id = random.randint(1, 24)

            info = random.choice(info_values[info_type_id]) if info_type_id in info_values else f"info_{i}"

            movie_info.append((i, movie_id, info_type_id, info, None))

        return movie_info

    def _generate_movie_info_idx(self, count: int, max_title_id: int) -> list[tuple]:
        """Generate movie_info_idx data."""
        movie_info_idx = []

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            info_type_id = random.choice([1, 2, 23, 24])  # rating, votes, top 250, bottom 10

            if info_type_id == 1:  # rating
                info = f"{random.uniform(1.0, 10.0):.1f}"
            elif info_type_id == 2:  # votes
                info = str(random.randint(100, 1000000))
            elif info_type_id == 23:  # top 250 rank
                info = str(random.randint(1, 250))
            else:  # bottom 10 rank
                info = str(random.randint(1, 10))

            movie_info_idx.append((i, movie_id, info_type_id, info, None))

        return movie_info_idx

    def _generate_movie_keyword(self, count: int, max_title_id: int, max_keyword_id: int) -> list[tuple]:
        """Generate movie_keyword data."""
        movie_keyword = []

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            keyword_id = random.randint(1, max_keyword_id)

            movie_keyword.append((i, movie_id, keyword_id))

        return movie_keyword

    def _generate_movie_link(self, count: int, max_title_id: int) -> list[tuple]:
        """Generate movie_link data (movie-movie relationships)."""
        # 18 link types hardcoded in lookup data
        max_link_type_id = 18
        movie_link = []
        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            linked_movie_id = random.randint(1, max_title_id)
            link_type_id = random.randint(1, max_link_type_id)
            movie_link.append((i, movie_id, linked_movie_id, link_type_id))
        return movie_link

    def _generate_person_info(self, count: int, max_name_id: int) -> list[tuple]:
        """Generate person_info data (biographical metadata for people)."""
        # 113 info types hardcoded in lookup data
        max_info_type_id = 113
        info_samples = ["Born in USA", "Studied at university", "Award winner", "Director known for drama", None]
        person_info = []
        for i in range(1, count + 1):
            person_id = random.randint(1, max_name_id)
            info_type_id = random.randint(1, max_info_type_id)
            info = f"Info text {i % 1000}"
            note = random.choice(info_samples)
            person_info.append((i, person_id, info_type_id, info, note))
        return person_info

    def _generate_complete_cast(self, count: int, max_title_id: int) -> list[tuple]:
        """Generate complete_cast data (cast completeness records)."""
        # 4 comp_cast_type values
        max_cast_type_id = 4
        complete_cast = []
        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            subject_id = random.randint(1, max_cast_type_id)
            status_id = random.randint(1, max_cast_type_id)
            complete_cast.append((i, movie_id, subject_id, status_id))
        return complete_cast

    def _generate_aka_name(self, count: int, max_name_id: int) -> list[tuple]:
        """Generate aka_name data (alternative person names)."""
        first_names = ["Al", "Bob", "Chris", "Dan", "Ed", "Frank", "George", "Hank"]
        last_names = ["Anderson", "Baker", "Clark", "Davis", "Evans", "Foster", "Green"]
        aka_name = []
        for i in range(1, count + 1):
            person_id = random.randint(1, max_name_id)
            first = random.choice(first_names)
            last = random.choice(last_names)
            name = f"{first} {last}"
            aka_name.append((i, person_id, name, None, None, None, None, None))
        return aka_name

    def _generate_aka_title(self, count: int, max_title_id: int) -> list[tuple]:
        """Generate aka_title data (alternative movie titles)."""
        # 7 kind_type values
        max_kind_id = 7
        title_words = ["Journey", "Return", "Rise", "Fall", "Dawn", "Dusk", "Storm"]
        aka_title = []
        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            word = random.choice(title_words)
            title = f"Alternative {word} {i % 10000}"
            kind_id = random.randint(1, max_kind_id)
            production_year = random.randint(1950, 2023) if random.random() > 0.1 else None
            aka_title.append((i, movie_id, title, None, kind_id, production_year, None, None, None, None, None, None))
        return aka_title

    def _write_table_data(self, table_name: str, data: list[tuple]) -> PathLike:
        """Write table data to CSV file.

        Args:
            table_name: Name of the table
            data: List of row tuples

        Returns:
            Path to the generated file
        """
        file_path = self.output_dir / f"{table_name}.csv"

        with open(file_path, "w", encoding="utf-8") as f:
            for row in data:
                # Convert None values to empty strings and escape quotes
                row_str = []
                for value in row:
                    if value is None:
                        row_str.append("")
                    else:
                        # Escape quotes and wrap in quotes if necessary
                        str_value = str(value).replace('"', '""')
                        if "," in str_value or '"' in str_value or "\n" in str_value:
                            row_str.append(f'"{str_value}"')
                        else:
                            row_str.append(str_value)

                f.write(",".join(row_str) + "\n")

        return file_path

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        """Write manifest describing generated Join Order dataset."""
        write_generator_manifest(
            self,
            "joinorder",
            table_paths,
            self._manifest_row_counts,
            metadata={"csv_delimiter": ",", "csv_null_marker": ""},
        )

    def get_table_row_count(self, table_name: str) -> int:
        """Get expected row count for a table.

        Args:
            table_name: Name of the table

        Returns:
            Expected number of rows
        """
        if table_name not in self.base_row_counts:
            return 0

        return int(self.base_row_counts[table_name] * self.scale_factor)

    def get_total_size_estimate(self) -> int:
        """Get estimated total size in bytes.

        Returns:
            Estimated total size in bytes
        """
        # Rough estimate: ~100 bytes per row on average
        total_rows = sum(self.get_table_row_count(table) for table in self.base_row_counts)
        return total_rows * 100
