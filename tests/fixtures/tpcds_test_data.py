# Copyright 2026 Joe Harris / BenchBox Project

# TPC Benchmark™ DS (TPC-DS) - Copyright © Transaction Processing Performance Council
# This implementation is based on the TPC-DS specification.

# Licensed under the MIT License. See LICENSE file in the project root for details.

import random
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from unittest.mock import MagicMock, Mock

import pytest

from benchbox.core.tpcds.benchmark import TPCDSBenchmark
from benchbox.core.tpcds.queries import TPCDSQueryManager


class TPCDSTestDataGenerator:
    def __init__(self, scale_factor: float = 0.001):
        self.scale_factor = scale_factor
        self.base_year = 1998
        self.end_year = 2002

    def generate_date_dim_data(self, num_rows: int = 100) -> list[tuple]:
        data = []
        current_date = datetime(self.base_year, 1, 1)

        for i in range(num_rows):
            date_sk = i + 1
            date_id = f"AAAAAAAA{chr(65 + (i % 26))}AAAAAAA"
            date_str = current_date.strftime("%Y-%m-%d")

            month_seq = (current_date.year - self.base_year) * 12 + current_date.month
            week_seq = (current_date - datetime(self.base_year, 1, 1)).days // 7 + 1
            quarter_seq = (current_date.year - self.base_year) * 4 + ((current_date.month - 1) // 3) + 1

            year = current_date.year
            dow = current_date.weekday()
            moy = current_date.month
            dom = current_date.day
            qoy = ((current_date.month - 1) // 3) + 1

            fy_year = year if current_date.month >= 3 else year - 1
            fy_quarter_seq = quarter_seq
            fy_week_seq = week_seq

            day_name = current_date.strftime("%A")
            quarter_name = f"{year}Q{qoy}"

            holiday = "Y" if current_date.month == 12 and current_date.day == 25 else "N"
            weekend = "Y" if dow in [5, 6] else "N"
            following_holiday = "N"

            first_dom = 1
            last_dom = (
                (current_date.replace(month=current_date.month + 1, day=1) - timedelta(days=1)).day
                if current_date.month < 12
                else 31
            )

            same_day_ly = date_sk - 365 if date_sk > 365 else 0
            same_day_lq = date_sk - 90 if date_sk > 90 else 0

            current_day = "Y" if i == 0 else "N"
            current_week = "Y" if i < 7 else "N"
            current_month = "Y" if i < 31 else "N"
            current_quarter = "Y" if i < 90 else "N"
            current_year = "Y" if i < 365 else "N"

            data.append(
                (
                    date_sk,
                    date_id,
                    date_str,
                    month_seq,
                    week_seq,
                    quarter_seq,
                    year,
                    dow,
                    moy,
                    dom,
                    qoy,
                    fy_year,
                    fy_quarter_seq,
                    fy_week_seq,
                    day_name,
                    quarter_name,
                    holiday,
                    weekend,
                    following_holiday,
                    first_dom,
                    last_dom,
                    same_day_ly,
                    same_day_lq,
                    current_day,
                    current_week,
                    current_month,
                    current_quarter,
                    current_year,
                )
            )

            current_date += timedelta(days=random.randint(1, 7))

        return data

    def generate_customer_address_data(self, num_rows: int = 50) -> list[tuple]:
        states = ["CA", "NY", "TX", "FL", "PA", "IL", "OH", "GA", "NC", "MI"]
        counties = {
            "CA": ["Los Angeles", "Orange", "San Diego", "Santa Clara"],
            "NY": ["New York", "Kings", "Queens", "Suffolk"],
            "TX": ["Harris", "Dallas", "Tarrant", "Bexar"],
            "FL": ["Miami-Dade", "Broward", "Palm Beach", "Hillsborough"],
            "PA": ["Philadelphia", "Allegheny", "Montgomery", "Bucks"],
        }

        cities = {
            "Los Angeles": ["Los Angeles", "Long Beach", "Pasadena"],
            "Orange": ["Anaheim", "Santa Ana", "Irvine"],
            "New York": ["New York", "Manhattan"],
            "Kings": ["Brooklyn"],
            "Harris": ["Houston", "Pasadena", "Baytown"],
        }

        street_names = [
            "Main",
            "Oak",
            "Pine",
            "Elm",
            "Cedar",
            "Maple",
            "First",
            "Second",
            "Third",
        ]
        street_types = ["St", "Ave", "Dr", "Way", "Blvd", "Rd", "Ln", "Ct"]
        location_types = ["condo", "single family", "apartment"]

        data = []
        for i in range(num_rows):
            ca_address_sk = i + 1
            ca_address_id = f"AAAAAAAA{chr(65 + (i % 26))}AAAAAAA"

            ca_street_number = str(random.randint(1, 9999))
            ca_street_name = random.choice(street_names)
            ca_street_type = random.choice(street_types)
            ca_suite_number = f"Suite {random.randint(100, 999)}" if random.random() > 0.5 else ""

            ca_state = random.choice(states)
            ca_county = random.choice(counties.get(ca_state, ["Generic County"]))
            ca_city = random.choice(cities.get(ca_county, ["Generic City"]))

            ca_zip = f"{random.randint(10000, 99999)}"
            ca_country = "United States"

            gmt_offsets = {
                "CA": -8.0,
                "NY": -5.0,
                "TX": -6.0,
                "FL": -5.0,
                "PA": -5.0,
                "IL": -6.0,
                "OH": -5.0,
                "GA": -5.0,
                "NC": -5.0,
                "MI": -5.0,
            }
            ca_gmt_offset = gmt_offsets.get(ca_state, -5.0)

            ca_location_type = random.choice(location_types)

            data.append(
                (
                    ca_address_sk,
                    ca_address_id,
                    ca_street_number,
                    ca_street_name,
                    ca_street_type,
                    ca_suite_number,
                    ca_city,
                    ca_county,
                    ca_state,
                    ca_zip,
                    ca_country,
                    ca_gmt_offset,
                    ca_location_type,
                )
            )

        return data

    def generate_item_data(self, num_rows: int = 30) -> list[tuple]:
        categories = ["Electronics", "Books", "Clothing", "Home", "Sports", "Toys"]
        brands = ["Brand#1", "Brand#2", "Brand#3", "Brand#4", "Brand#5"]
        classes = ["Economy", "Standard", "Premium"]
        manufacturers = [
            "Manufacturer#1",
            "Manufacturer#2",
            "Manufacturer#3",
            "Manufacturer#4",
        ]
        sizes = ["small", "medium", "large", "extra large"]
        colors = ["red", "blue", "green", "black", "white", "brown", "yellow"]
        units = ["Each", "Box", "Case", "Dozen", "Gross"]
        containers = ["Bag", "Box", "Can", "Carton", "Case", "Jar", "Pack", "Tube"]

        data = []
        for i in range(num_rows):
            i_item_sk = i + 1
            i_item_id = f"AAAAAAAA{chr(65 + (i % 26))}AAAAAAA"

            start_date = datetime(self.base_year, 1, 1) + timedelta(days=random.randint(0, 365))
            end_date = start_date + timedelta(days=random.randint(365, 1095))

            i_rec_start_date = start_date.strftime("%Y-%m-%d")
            i_rec_end_date = end_date.strftime("%Y-%m-%d")

            category = random.choice(categories)
            brand = random.choice(brands)
            item_class = random.choice(classes)
            manufacturer = random.choice(manufacturers)

            color = random.choice(colors)
            size = random.choice(sizes)
            adjectives = ["Premium", "Deluxe", "Standard", "Economy", "Professional"]
            adjective = random.choice(adjectives)

            i_item_desc = f"{adjective} {color} {category.lower()} item"
            i_product_name = i_item_desc

            wholesale_cost = round(random.uniform(1.0, 100.0), 2)
            markup = random.uniform(1.5, 3.0)
            i_current_price = round(wholesale_cost * markup, 2)
            i_wholesale_cost = wholesale_cost

            i_brand_id = hash(brand) % 10000
            i_class_id = hash(item_class) % 100
            i_category_id = hash(category) % 100
            i_manufact_id = hash(manufacturer) % 1000
            i_manager_id = random.randint(1, 100)

            i_brand = brand
            i_class = item_class
            i_category = category
            i_manufact = manufacturer
            i_size = size
            i_formulation = random.choice(["standard", "premium", "deluxe"])
            i_color = color
            i_units = random.choice(units)
            i_container = random.choice(containers)

            data.append(
                (
                    i_item_sk,
                    i_item_id,
                    i_rec_start_date,
                    i_rec_end_date,
                    i_item_desc,
                    i_current_price,
                    i_wholesale_cost,
                    i_brand_id,
                    i_brand,
                    i_class_id,
                    i_class,
                    i_category_id,
                    i_category,
                    i_manufact_id,
                    i_manufact,
                    i_size,
                    i_formulation,
                    i_color,
                    i_units,
                    i_container,
                    i_manager_id,
                    i_product_name,
                )
            )

        return data


class TPCDSTestDatabase:
    def __init__(self, db_path: Optional[Path] = None):
        self.db_path = db_path or Path(tempfile.mktemp(suffix=".db"))
        self.connection = None
        self.data_generator = TPCDSTestDataGenerator()

    def __enter__(self):
        self.connection = sqlite3.connect(str(self.db_path))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.connection:
            self.connection.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def create_schema(self):
        cursor = self.connection.cursor()

        cursor.execute("""
            CREATE TABLE date_dim (
                d_date_sk INTEGER PRIMARY KEY,
                d_date_id TEXT,
                d_date TEXT,
                d_month_seq INTEGER,
                d_week_seq INTEGER,
                d_quarter_seq INTEGER,
                d_year INTEGER,
                d_dow INTEGER,
                d_moy INTEGER,
                d_dom INTEGER,
                d_qoy INTEGER,
                d_fy_year INTEGER,
                d_fy_quarter_seq INTEGER,
                d_fy_week_seq INTEGER,
                d_day_name TEXT,
                d_quarter_name TEXT,
                d_holiday TEXT,
                d_weekend TEXT,
                d_following_holiday TEXT,
                d_first_dom INTEGER,
                d_last_dom INTEGER,
                d_same_day_ly INTEGER,
                d_same_day_lq INTEGER,
                d_current_day TEXT,
                d_current_week TEXT,
                d_current_month TEXT,
                d_current_quarter TEXT,
                d_current_year TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE customer_address (
                ca_address_sk INTEGER PRIMARY KEY,
                ca_address_id TEXT,
                ca_street_number TEXT,
                ca_street_name TEXT,
                ca_street_type TEXT,
                ca_suite_number TEXT,
                ca_city TEXT,
                ca_county TEXT,
                ca_state TEXT,
                ca_zip TEXT,
                ca_country TEXT,
                ca_gmt_offset REAL,
                ca_location_type TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE item (
                i_item_sk INTEGER PRIMARY KEY,
                i_item_id TEXT,
                i_rec_start_date TEXT,
                i_rec_end_date TEXT,
                i_item_desc TEXT,
                i_current_price REAL,
                i_wholesale_cost REAL,
                i_brand_id INTEGER,
                i_brand TEXT,
                i_class_id INTEGER,
                i_class TEXT,
                i_category_id INTEGER,
                i_category TEXT,
                i_manufact_id INTEGER,
                i_manufact TEXT,
                i_size TEXT,
                i_formulation TEXT,
                i_color TEXT,
                i_units TEXT,
                i_container TEXT,
                i_manager_id INTEGER,
                i_product_name TEXT
            )
        """)

        self.connection.commit()

    def populate_data(self):
        cursor = self.connection.cursor()

        date_data = self.data_generator.generate_date_dim_data()
        cursor.executemany(
            """
            INSERT INTO date_dim VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            date_data,
        )

        address_data = self.data_generator.generate_customer_address_data()
        cursor.executemany(
            """
            INSERT INTO customer_address VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            address_data,
        )

        item_data = self.data_generator.generate_item_data()
        cursor.executemany(
            """
            INSERT INTO item VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
            item_data,
        )

        self.connection.commit()

    def get_sample_data(self, table_name: str, limit: int = 10) -> list[tuple]:
        cursor = self.connection.cursor()
        cursor.execute(f"SELECT * FROM {table_name} LIMIT ?", (limit,))
        return cursor.fetchall()


class TPCDSReferenceData:
    def __init__(self):
        self.parameter_sets = self._create_parameter_sets()
        self.expected_results = self._create_expected_results()
        self.performance_baselines = self._create_performance_baselines()

    def _create_parameter_sets(self) -> dict[str, dict[str, Any]]:
        return {
            "baseline_2000": {
                "YEAR": 2000,
                "MONTH": 6,
                "QUARTER": 2,
                "STATE": "CA",
                "CATEGORY": "Electronics",
                "MANAGER": 50,
                "DISCOUNT": 0.15,
                "QUANTITY": 20,
                "COLOR": "blue",
            },
            "edge_case_early": {
                "YEAR": 1998,
                "MONTH": 1,
                "QUARTER": 1,
                "STATE": "AL",
                "CATEGORY": "Books",
                "MANAGER": 1,
                "DISCOUNT": 0.05,
                "QUANTITY": 1,
                "COLOR": "red",
            },
            "edge_case_late": {
                "YEAR": 2002,
                "MONTH": 12,
                "QUARTER": 4,
                "STATE": "WY",
                "CATEGORY": "Toys",
                "MANAGER": 100,
                "DISCOUNT": 0.5,
                "QUANTITY": 40,
                "COLOR": "yellow",
            },
            "performance_test": {
                "YEAR": 2001,
                "MONTH": 9,
                "QUARTER": 3,
                "STATE": "TX",
                "CATEGORY": "Home",
                "MANAGER": 75,
                "DISCOUNT": 0.25,
                "QUANTITY": 30,
                "COLOR": "green",
            },
            "regression_baseline": {
                "YEAR": 1999,
                "MONTH": 3,
                "QUARTER": 1,
                "STATE": "NY",
                "CATEGORY": "Clothing",
                "MANAGER": 25,
                "DISCOUNT": 0.1,
                "QUANTITY": 15,
                "COLOR": "black",
            },
        }

    def _create_expected_results(self) -> dict[str, dict[str, Any]]:
        return {
            "query_1_baseline_2000": {
                "row_count": 100,
                "columns": [
                    "c_customer_id",
                    "c_first_name",
                    "c_last_name",
                    "ca_city",
                    "ca_state_abbr",
                    "ca_zip",
                ],
                "sample_values": {
                    "c_customer_id": "AAAAAAAABAAAAAAA",
                    "ca_state_abbr": "CA",
                    "ca_city": "Midway",
                },
            },
            "query_3_edge_case_early": {
                "row_count": 50,
                "columns": ["dt", "brand", "sales_price"],
                "sample_values": {"dt": "1998-01-01", "brand": "Brand#1"},
            },
        }

    def _create_performance_baselines(self) -> dict[str, dict[str, float]]:
        return {
            "query_generation": {
                "raw_query_time": 0.001,
                "parameterized_query_time": 0.005,
                "enhanced_query_time": 0.01,
            },
            "memory_usage": {
                "single_query_mb": 0.1,
                "batch_100_queries_mb": 5.0,
                "peak_memory_mb": 50.0,
            },
            "throughput": {
                "queries_per_second": 100,
                "concurrent_queries_per_second": 75,
                "stream_queries_per_second": 20,
            },
        }

    def get_parameter_set(self, name: str) -> dict[str, Any]:
        return self.parameter_sets.get(name, {})

    def get_expected_result(self, test_case: str) -> dict[str, Any]:
        return self.expected_results.get(test_case, {})

    def get_performance_baseline(self, category: str) -> dict[str, float]:
        return self.performance_baselines.get(category, {})


class MockTPCDSComponents:
    @staticmethod
    def create_mock_database_introspector() -> Mock:
        mock_introspector = Mock()
        mock_introspector.get_table_row_count.return_value = 1000
        mock_introspector.get_column_statistics.return_value = {
            "min_value": 1,
            "max_value": 100,
            "distinct_count": 100,
            "null_count": 0,
        }
        mock_introspector.get_value_distribution.return_value = [
            "CA",
            "NY",
            "TX",
            "FL",
            "PA",
        ]
        return mock_introspector

    @staticmethod
    def create_mock_distribution_manager() -> Mock:
        mock_manager = Mock()
        mock_manager.get_random_value.return_value = "mock_value"
        mock_manager.get_distribution_info.return_value = {
            "name": "mock_distribution",
            "weight_sets": 1,
            "values": ["value1", "value2", "value3"],
        }
        return mock_manager

    @staticmethod
    def create_mock_parameter_functions() -> Mock:
        mock_functions = Mock()
        mock_functions.uniform.return_value = 42
        mock_functions.date.return_value = "2000-06-15"
        mock_functions.text.return_value = "sample_text"
        mock_functions.distmember.return_value = "mock_member"
        return mock_functions

    @staticmethod
    def create_mock_performance_monitor() -> Mock:
        mock_monitor = Mock()
        mock_monitor.record_timing = MagicMock()
        mock_monitor.increment_counter = MagicMock()
        mock_monitor.get_stats.return_value = {"timings": {}, "counters": {}}
        return mock_monitor


@pytest.fixture
def tpcds_test_data_generator():
    return TPCDSTestDataGenerator()


@pytest.fixture
def tpcds_test_database():
    with TPCDSTestDatabase() as db:
        db.create_schema()
        db.populate_data()
        yield db


@pytest.fixture
def tpcds_reference_data():
    return TPCDSReferenceData()


@pytest.fixture
def mock_database_introspector():
    return MockTPCDSComponents.create_mock_database_introspector()


@pytest.fixture
def mock_distribution_manager():
    return MockTPCDSComponents.create_mock_distribution_manager()


@pytest.fixture
def mock_parameter_functions():
    return MockTPCDSComponents.create_mock_parameter_functions()


@pytest.fixture
def mock_performance_monitor():
    return MockTPCDSComponents.create_mock_performance_monitor()


@pytest.fixture
def sample_tpcds_benchmark():
    return TPCDSBenchmark(
        scale_factor=0.001,
        use_enhanced_parsing=False,
        optimize_performance=True,
        verbose=False,
    )


@pytest.fixture
def sample_query_manager():
    return TPCDSQueryManager(use_enhanced_parsing=False)


@pytest.fixture(scope="session")
def temp_test_directory():
    import shutil
    import tempfile

    temp_dir = Path(tempfile.mkdtemp(prefix="tpcds_test_"))
    yield temp_dir

    if temp_dir.exists():
        shutil.rmtree(temp_dir)


@pytest.fixture
def test_parameters():
    reference = TPCDSReferenceData()
    return {
        "parameter_sets": reference.parameter_sets,
        "combinations": [
            ("baseline_2000", "query_1"),
            ("edge_case_early", "query_3"),
            ("performance_test", "query_10"),
            ("regression_baseline", "query_15"),
        ],
    }


if __name__ == "__main__":
    print("Testing TPC-DS test data generation...")

    generator = TPCDSTestDataGenerator()
    date_data = generator.generate_date_dim_data(10)
    print(f"Generated {len(date_data)} date dimension rows")

    address_data = generator.generate_customer_address_data(5)
    print(f"Generated {len(address_data)} address rows")

    item_data = generator.generate_item_data(5)
    print(f"Generated {len(item_data)} item rows")

    with TPCDSTestDatabase() as db:
        db.create_schema()
        db.populate_data()

        sample_dates = db.get_sample_data("date_dim", 3)
        print(f"Sample dates: {sample_dates}")

        sample_addresses = db.get_sample_data("customer_address", 3)
        print(f"Sample addresses: {sample_addresses}")

    ref_data = TPCDSReferenceData()
    baseline_params = ref_data.get_parameter_set("baseline_2000")
    print(f"Baseline parameters: {baseline_params}")

    performance_baseline = ref_data.get_performance_baseline("query_generation")
    print(f"Performance baseline: {performance_baseline}")

    print("Test data generation completed successfully!")
