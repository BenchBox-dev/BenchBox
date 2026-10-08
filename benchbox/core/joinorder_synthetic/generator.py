# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        if output_dir is None:
            from benchbox.utils.scale_factor import format_scale_factor

            sf_str = format_scale_factor(scale_factor)
            output_dir = Path.cwd() / "benchmark_runs" / "datagen" / f"joinorder_synthetic_{sf_str}"
        self.output_dir = create_path_handler(output_dir)
        self.schema = JoinOrderSchema()
        self.force_regenerate = force_regenerate
        if isinstance(verbose, bool):
            self.verbose_level = 1 if verbose else 0
        else:
            self.verbose_level = int(verbose or 0)
        self.verbose_enabled = self.verbose_level >= 1 and not quiet
        self.very_verbose = self.verbose_level >= 2 and not quiet
        self.quiet = bool(quiet)

        self.base_row_counts = {
            "kind_type": 7,
            "company_type": 4,
            "info_type": 113,
            "role_type": 12,
            "comp_cast_type": 4,
            "link_type": 18,
            "title": 500_000,
            "name": 800_000,
            "company_name": 60_000,
            "keyword": 24_000,
            "char_name": 600_000,
            "cast_info": 7_000_000,
            "movie_companies": 520_000,
            "movie_info": 3_000_000,
            "movie_info_idx": 280_000,
            "movie_keyword": 1_000_000,
            "movie_link": 6_000,
            "person_info": 600_000,
            "complete_cast": 30_000,
            "aka_name": 180_000,
            "aka_title": 80_000,
        }

        self._manifest_row_counts: dict[str, int] = {}

    def generate_data(self) -> list[Path]:
        table_paths = self._handle_cloud_or_local_generation(
            self.output_dir,
            self._generate_data_local,
            False,
        )
        self._write_manifest(table_paths)

        return list(table_paths.values())

    def _generate_data_local(self, output_dir: Path) -> dict[str, Path]:
        random.seed(42)
        original_output_dir = self.output_dir
        self.output_dir = output_dir
        try:
            self.output_dir.mkdir(parents=True, exist_ok=True)
            generated_files = {}
            self._manifest_row_counts = {}

            lookup_data = self._generate_lookup_tables()

            dimension_data = self._generate_dimension_tables(lookup_data)

            relationship_data = self._generate_relationship_tables(dimension_data)

            all_data = {**lookup_data, **dimension_data, **relationship_data}
            self._plant_golden_entities(dimension_data, relationship_data)

            for table_name, data in all_data.items():
                file_path = self._write_table_data(table_name, data)
                generated_files[table_name] = file_path
                self._manifest_row_counts[table_name] = len(data)

            return generated_files
        finally:
            self.output_dir = original_output_dir

    def _generate_lookup_tables(self) -> dict[str, list[tuple]]:
        data = {}

        data["kind_type"] = [
            (1, "movie"),
            (2, "tv series"),
            (3, "tv movie"),
            (4, "video movie"),
            (5, "tv mini series"),
            (6, "video game"),
            (7, "episode"),
        ]

        data["company_type"] = [
            (1, "distributors"),
            (2, "production companies"),
            (3, "special effects companies"),
            (4, "miscellaneous companies"),
        ]

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

        data["comp_cast_type"] = [
            (1, "cast"),
            (2, "crew"),
            (3, "complete"),
            (4, "incomplete"),
        ]

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
        data = {}

        title_count = int(self.base_row_counts["title"] * self.scale_factor)
        data["title"] = self._generate_titles(title_count)

        name_count = int(self.base_row_counts["name"] * self.scale_factor)
        data["name"] = self._generate_names(name_count)

        company_count = int(self.base_row_counts["company_name"] * self.scale_factor)
        data["company_name"] = self._generate_companies(company_count)

        keyword_count = int(self.base_row_counts["keyword"] * self.scale_factor)
        data["keyword"] = self._generate_keywords(keyword_count)

        char_count = int(self.base_row_counts["char_name"] * self.scale_factor)
        data["char_name"] = self._generate_character_names(char_count)

        return data

    def _generate_relationship_tables(self, dimension_data: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
        data = {}

        max_title_id = max(row[0] for row in dimension_data["title"])
        max_name_id = max(row[0] for row in dimension_data["name"])
        max_company_id = max(row[0] for row in dimension_data["company_name"])
        max_keyword_id = max(row[0] for row in dimension_data["keyword"])
        max_char_id = max(row[0] for row in dimension_data["char_name"])

        cast_count = int(self.base_row_counts["cast_info"] * self.scale_factor)
        data["cast_info"] = self._generate_cast_info(cast_count, max_name_id, max_title_id, max_char_id)

        mc_count = int(self.base_row_counts["movie_companies"] * self.scale_factor)
        data["movie_companies"] = self._generate_movie_companies(mc_count, max_title_id, max_company_id)

        mi_count = int(self.base_row_counts["movie_info"] * self.scale_factor)
        data["movie_info"] = self._generate_movie_info(mi_count, max_title_id)

        mi_idx_count = int(self.base_row_counts["movie_info_idx"] * self.scale_factor)
        data["movie_info_idx"] = self._generate_movie_info_idx(mi_idx_count, max_title_id)

        mk_count = int(self.base_row_counts["movie_keyword"] * self.scale_factor)
        data["movie_keyword"] = self._generate_movie_keyword(mk_count, max_title_id, max_keyword_id)

        ml_count = int(self.base_row_counts["movie_link"] * self.scale_factor)
        data["movie_link"] = self._generate_movie_link(ml_count, max_title_id)

        pi_count = int(self.base_row_counts["person_info"] * self.scale_factor)
        data["person_info"] = self._generate_person_info(pi_count, max_name_id)

        cc_count = int(self.base_row_counts["complete_cast"] * self.scale_factor)
        data["complete_cast"] = self._generate_complete_cast(cc_count, max_title_id)

        an_count = int(self.base_row_counts["aka_name"] * self.scale_factor)
        data["aka_name"] = self._generate_aka_name(an_count, max_name_id)

        at_count = int(self.base_row_counts["aka_title"] * self.scale_factor)
        data["aka_title"] = self._generate_aka_title(at_count, max_title_id)

        return data

    def _generate_titles(self, count: int) -> list[tuple]:
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
            if random.random() < 0.30:
                kind_id = random.choice([1, 1, 1, 2])
                production_year = random.randint(self._SEED_YEAR_LOW - 15, self._SEED_YEAR_HIGH)
            else:
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

    _SEED_COMPANIES = ("Warner Bros", "Warner Films", "Universal Films")
    _SEED_COUNTRIES = ("[us]", "[us]", "[ru]", "[pl]")
    _SEED_NAMES = ("Robert Downey", "Downey Robert", "Angelina Smith")
    _SEED_KEYWORDS_EXTRA = ("marvel-cinematic-universe", "sequel")
    _GOLDEN_KEYWORDS = (
        "marvel-cinematic-universe",
        "murder",
        "blood",
        "violence",
        "superhero",
        "sequel",
        "character-name-in-title",
    )
    _GOLDEN_CI_NOTES = ("(writer)", "(voice)", "(producer)")
    _GOLDEN_CI_NOTES_EXTRA = ("(voice) (uncredited)", "(voice) (uncredited)", "(producer)")
    _SEED_NOTES = ("(producer)", "(producer)", "(co-production)", "(presents)")
    _SEED_MC_NOTES = (
        "(2002) (USA) (theatrical)",
        "(2005) (worldwide) (theatrical)",
        "(USA) (VHS)",
        "(Japan) (Blu-ray)",
        "(France) (theatrical)",
    )
    _SEED_MI_INFO = ("Sweden", "Germany", "Norwegian", "USA")
    _SEED_ROLES = ("producer", "producer", "actor")
    _SEED_YEAR_LOW, _SEED_YEAR_HIGH = 2005, 2010

    def _generate_names(self, count: int) -> list[tuple]:
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
            if random.random() < 0.08:
                name = random.choice(self._SEED_NAMES)
            else:
                first = random.choice(first_names)
                last = random.choice(last_names)
                name = f"{first} {last}"
            gender = random.choice(["m", "f"]) if random.random() > 0.1 else None

            names.append((i, name, None, None, gender, None, None, None, None))

        return names

    def _generate_companies(self, count: int) -> list[tuple]:
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
            if random.random() < 0.10:
                name = random.choice(self._SEED_COMPANIES)
                country = random.choice(self._SEED_COUNTRIES)
            else:
                name_part = random.choice(company_names)
                type_part = random.choice(company_types)
                name = f"{name_part} {type_part}"
                country = random.choice(countries)

            companies.append((i, name, country, None, None, None, None))

        return companies

    def _generate_keywords(self, count: int) -> list[tuple]:
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
            if random.random() < 0.10:
                keyword = random.choice(self._SEED_KEYWORDS_EXTRA)

            keywords.append((i, keyword, None))

        return keywords

    def _generate_character_names(self, count: int) -> list[tuple]:
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
        cast_info = []

        for i in range(1, count + 1):
            person_id = random.randint(1, max_name_id)
            movie_id = random.randint(1, max_title_id)
            person_role_id = random.randint(1, max_char_id) if random.random() > 0.3 else None
            if random.random() < 0.15:
                role_id = random.choice([3, 3, 1])
            else:
                role_id = random.randint(1, 12)
            if random.random() < 0.12:
                note = random.choice(self._SEED_NOTES)
            else:
                note = None
            nr_order = random.randint(1, 20) if random.random() > 0.5 else None

            cast_info.append((i, person_id, movie_id, person_role_id, note, nr_order, role_id))

        return cast_info

    def _generate_movie_companies(self, count: int, max_title_id: int, max_company_id: int) -> list[tuple]:
        movie_companies = []

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            company_id = random.randint(1, max_company_id)
            company_type_id = random.randint(1, 4)
            if random.random() < 0.12:
                note = random.choice(self._SEED_MC_NOTES)
            else:
                note = None

            movie_companies.append((i, movie_id, company_id, company_type_id, note))

        return movie_companies

    def _generate_movie_info(self, count: int, max_title_id: int) -> list[tuple]:
        movie_info = []
        info_values = {
            1: ["8.5", "7.2", "6.8", "9.1", "5.5"],
            2: ["1000", "5000", "50000", "100000"],
            3: ["Drama", "Comedy", "Action", "Horror", "Romance"],
            4: ["English", "Spanish", "French", "German", "Japanese"],
            5: ["USA", "UK", "Germany", "France", "Japan"],
        }

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            info_type_id = random.randint(1, 24)

            if random.random() < 0.15:
                info = random.choice(self._SEED_MI_INFO)
            else:
                info = random.choice(info_values[info_type_id]) if info_type_id in info_values else f"info_{i}"

            movie_info.append((i, movie_id, info_type_id, info, None))

        return movie_info

    def _generate_movie_info_idx(self, count: int, max_title_id: int) -> list[tuple]:
        movie_info_idx = []

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            info_type_id = random.choice([1, 2, 23, 24])

            if info_type_id == 1:
                info = f"{random.uniform(1.0, 10.0):.1f}"
            elif info_type_id == 2:
                info = str(random.randint(100, 1000000))
            elif info_type_id == 23:
                info = str(random.randint(1, 250))
            else:
                info = str(random.randint(1, 10))

            movie_info_idx.append((i, movie_id, info_type_id, info, None))

        return movie_info_idx

    def _generate_movie_keyword(self, count: int, max_title_id: int, max_keyword_id: int) -> list[tuple]:
        movie_keyword = []

        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            keyword_id = random.randint(1, max_keyword_id)

            movie_keyword.append((i, movie_id, keyword_id))

        return movie_keyword

    def _generate_movie_link(self, count: int, max_title_id: int) -> list[tuple]:
        max_link_type_id = 18
        movie_link = []
        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            linked_movie_id = random.randint(1, max_title_id)
            link_type_id = random.randint(1, max_link_type_id)
            movie_link.append((i, movie_id, linked_movie_id, link_type_id))
        return movie_link

    def _generate_person_info(self, count: int, max_name_id: int) -> list[tuple]:
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
        max_cast_type_id = 4
        complete_cast = []
        for i in range(1, count + 1):
            movie_id = random.randint(1, max_title_id)
            subject_id = random.randint(1, max_cast_type_id)
            status_id = random.randint(1, max_cast_type_id)
            complete_cast.append((i, movie_id, subject_id, status_id))
        return complete_cast

    def _generate_aka_name(self, count: int, max_name_id: int) -> list[tuple]:
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

    _GOLDEN_COUNT = 60

    def _plant_golden_entities(
        self,
        dimension_data: dict[str, list[tuple]],
        relationship_data: dict[str, list[tuple]],
    ) -> None:
        titles = dimension_data["title"]
        names = dimension_data["name"]
        companies = dimension_data["company_name"]
        keywords = dimension_data["keyword"]
        title_cols = len(titles[0]) if titles else 0
        name_cols = len(names[0]) if names else 0
        company_cols = len(companies[0]) if companies else 0
        keyword_cols = len(keywords[0]) if keywords else 0
        next_title = max(row[0] for row in titles) + 1 if titles else 1
        next_name = max(row[0] for row in names) + 1 if names else 1
        next_company = max(row[0] for row in companies) + 1 if companies else 1
        next_keyword = max(row[0] for row in keywords) + 1 if keywords else 1
        golden_titles = list(range(next_title, next_title + self._GOLDEN_COUNT))
        golden_names = list(range(next_name, next_name + self._GOLDEN_COUNT))
        golden_companies = list(range(next_company, next_company + self._GOLDEN_COUNT))
        golden_keywords = list(range(next_keyword, next_keyword + self._GOLDEN_COUNT))
        for offset in range(self._GOLDEN_COUNT):
            title_row = [golden_titles[offset], f"Golden Adventure {offset}", None, 1, 2005 + (offset % 6)]
            title_row += [None] * (title_cols - len(title_row))
            if offset % 3 == 0:
                title_row[9] = 50 + (offset % 50)
            titles.append(tuple(title_row))
            name_row = [golden_names[offset], "Downey Robert" if offset % 2 == 0 else "Angelina Smith"]
            name_row += [None] * (name_cols - len(name_row))
            names.append(tuple(name_row))
            company_row = [golden_companies[offset], "Warner Films" if offset % 2 == 0 else "Universal Films", "[us]"]
            if offset % 4 >= 2:
                company_row[2] = "[ru]"
                company_row[1] = "Moscow Films"
            company_row += [None] * (company_cols - len(company_row))
            companies.append(tuple(company_row))
            keyword_row = [golden_keywords[offset], self._GOLDEN_KEYWORDS[offset % len(self._GOLDEN_KEYWORDS)]]
            keyword_row += [None] * (keyword_cols - len(keyword_row))
            keywords.append(tuple(keyword_row))
        cast_info = relationship_data["cast_info"]
        for index, row in enumerate(cast_info[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_names[index % len(golden_names)]
            row_list[2] = golden_titles[index % len(golden_titles)]
            row_list[4] = self._GOLDEN_CI_NOTES_EXTRA[index % len(self._GOLDEN_CI_NOTES_EXTRA)]
            row_list[6] = 3 if index % 2 == 0 else 1
            cast_info[index] = tuple(row_list)
        movie_companies = relationship_data["movie_companies"]
        for index, row in enumerate(movie_companies[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_titles[index % len(golden_titles)]
            row_list[2] = golden_companies[index % len(golden_companies)]
            row_list[4] = "(2005) (USA) (theatrical)"
            movie_companies[index] = tuple(row_list)
        movie_keyword = relationship_data["movie_keyword"]
        for index, row in enumerate(movie_keyword[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_titles[index % len(golden_titles)]
            row_list[2] = golden_keywords[index % len(golden_keywords)]
            movie_keyword[index] = tuple(row_list)
        movie_info = relationship_data["movie_info"]
        for index, row in enumerate(movie_info[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_titles[index % len(golden_titles)]
            row_list[3] = "Sweden" if index % 2 == 0 else "Germany"
            movie_info[index] = tuple(row_list)
        aka_name = relationship_data["aka_name"]
        for index, row in enumerate(aka_name[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_names[index % len(golden_names)]
            row_list[2] = "Golden Alias"
            aka_name[index] = tuple(row_list)
        complete_cast = relationship_data["complete_cast"]
        for index, row in enumerate(complete_cast[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_titles[index % len(golden_titles)]
            row_list[2] = 1
            row_list[3] = 3
            complete_cast[index] = tuple(row_list)
        movie_link = relationship_data["movie_link"]
        for index, row in enumerate(movie_link[: self._GOLDEN_COUNT]):
            row_list = list(row)
            row_list[1] = golden_titles[index % len(golden_titles)]
            row_list[2] = golden_titles[(index + 1) % len(golden_titles)]
            row_list[3] = 1
            movie_link[index] = tuple(row_list)

    def _write_table_data(self, table_name: str, data: list[tuple]) -> PathLike:
        file_path = self.output_dir / f"{table_name}.csv"

        with open(file_path, "w", encoding="utf-8") as f:
            for row in data:
                row_str = []
                for value in row:
                    if value is None:
                        row_str.append("")
                    else:
                        str_value = str(value).replace('"', '""')
                        if "," in str_value or '"' in str_value or "\n" in str_value:
                            row_str.append(f'"{str_value}"')
                        else:
                            row_str.append(str_value)

                f.write(",".join(row_str) + "\n")

        return file_path

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        write_generator_manifest(
            self,
            "joinorder",
            table_paths,
            self._manifest_row_counts,
            metadata={"csv_delimiter": ",", "csv_null_marker": ""},
        )

    def get_table_row_count(self, table_name: str) -> int:
        if table_name not in self.base_row_counts:
            return 0

        return int(self.base_row_counts[table_name] * self.scale_factor)

    def get_total_size_estimate(self) -> int:
        total_rows = sum(self.get_table_row_count(table) for table in self.base_row_counts)
        return total_rows * 100
