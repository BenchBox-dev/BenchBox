<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Custom Benchmarks

```{tags} advanced, guide, custom-benchmark, python-api
```

Complete guide to creating, implementing, and integrating custom benchmarks with the BenchBox framework.

---

##  Creating Custom Benchmarks

### Basic Custom Benchmark

The simplest way to create a custom benchmark is to inherit from `BaseBenchmark`:

```python
from benchbox.base import BaseBenchmark
from pathlib import Path
from typing import Dict, Union, Optional
import csv
import random

class SimpleBenchmark(BaseBenchmark):
    """Simple custom benchmark for demonstration."""

    def __init__(self, scale_factor: float = 1.0, output_dir: Optional[Path] = None):
        super().__init__(scale_factor, output_dir)

        # Define queries
        self._queries = {
            "count_all": "SELECT COUNT(*) FROM test_table",
            "sum_values": "SELECT SUM(value) FROM test_table",
            "avg_by_category": "SELECT category, AVG(value) FROM test_table GROUP BY category",
            "top_values": "SELECT * FROM test_table ORDER BY value DESC LIMIT 10"
        }

        # Define schema
        self._schema = {
            "test_table": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "primary_key": True},
                    {"name": "category", "type": "VARCHAR(10)", "nullable": False},
                    {"name": "value", "type": "DOUBLE", "nullable": False},
                    {"name": "created_at", "type": "TIMESTAMP", "nullable": True}
                ]
            }
        }

    def generate_data(self) -> Dict[str, Path]:
        """Generate simple test data."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Calculate row count based on scale factor
        base_rows = 1000
        row_count = int(base_rows * self.scale_factor)

        # Generate test_table data
        test_file = self.output_dir / "test_table.csv"

        categories = ['A', 'B', 'C', 'D']

        with open(test_file, 'w', newline='') as f:
            writer = csv.writer(f, delimiter='|')

            for i in range(row_count):
                category = random.choice(categories)
                value = random.uniform(1.0, 1000.0)
                created_at = f"2023-01-{(i % 30) + 1:02d} 12:00:00"

                writer.writerow([i, category, value, created_at])

        return {"test_table": test_file}

    def get_queries(self) -> Dict[Union[int, str], str]:
        """Get all benchmark queries."""
        return self._queries.copy()

    def get_query(self, query_id: Union[int, str]) -> str:
        """Get specific query by ID."""
        if query_id not in self._queries:
            raise ValueError(f"Query '{query_id}' not found")
        return self._queries[query_id]

    def get_create_tables_sql(self, dialect: str = "standard", tuning_config=None) -> str:
        """Get DDL statements for benchmark tables."""
        return """
        CREATE TABLE test_table (
            id INTEGER PRIMARY KEY,
            category VARCHAR(10) NOT NULL,
            value DOUBLE NOT NULL,
            created_at TIMESTAMP
        );
        """

    def get_table_names(self) -> list:
        """Get list of table names."""
        return list(self._schema.keys())

# Usage example
def test_simple_benchmark():
    """Test the simple custom benchmark."""
    import duckdb

    # Initialize benchmark
    benchmark = SimpleBenchmark(scale_factor=0.1)

    # Generate data
    data_files = benchmark.generate_data()
    print(f"Generated data: {list(data_files.keys())}")

    # Setup database
    conn = duckdb.connect(":memory:")

    # Create tables
    ddl = benchmark.get_create_tables_sql("duckdb")
    conn.execute(ddl)

    # Load data
    for table_name, file_path in data_files.items():
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', header=false, delimiter='|')
        """)

        # Check row count
        count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
        print(f"Loaded {count} rows into {table_name}")

    # Run queries
    queries = benchmark.get_queries()
    for query_id, query_sql in queries.items():
        result = conn.execute(query_sql).fetchall()
        print(f"{query_id}: {result}")

    conn.close()

if __name__ == "__main__":
    test_simple_benchmark()
```

---

## Benchmark Architecture

### Advanced-level Benchmark Structure

For more complex benchmarks, use a modular architecture:

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import json

@dataclass
class TableSchema:
    """Schema definition for a benchmark table."""
    name: str
    columns: List[Dict[str, Any]]
    primary_key: Optional[List[str]] = None
    foreign_keys: Optional[List[Dict[str, Any]]] = None
    indexes: Optional[List[Dict[str, Any]]] = None

@dataclass
class QueryMetadata:
    """Metadata for benchmark queries."""
    query_id: str
    name: str
    description: str
    category: str
    complexity: str  # 'simple', 'medium', 'complex'
    sql_features: List[str]
    estimated_runtime_ms: Optional[int] = None

class DataGenerator(ABC):
    """Abstract base class for data generators."""

    @abstractmethod
    def generate_table_data(self, table_schema: TableSchema, scale_factor: float, output_path: Path) -> Path:
        """Generate data for a specific table."""
        pass

class QueryManager(ABC):
    """Abstract base class for query managers."""

    @abstractmethod
    def get_query_metadata(self, query_id: str) -> QueryMetadata:
        """Get metadata for a specific query."""
        pass

    @abstractmethod
    def get_queries_by_category(self, category: str) -> Dict[str, str]:
        """Get queries filtered by category."""
        pass

class AdvancedBenchmark(BaseBenchmark):
    """Advanced-level benchmark with modular architecture."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Optional[Path] = None,
        data_generator: Optional[DataGenerator] = None,
        query_manager: Optional[QueryManager] = None
    ):
        super().__init__(scale_factor, output_dir)

        self.data_generator = data_generator or self._create_default_data_generator()
        self.query_manager = query_manager or self._create_default_query_manager()

        # Load benchmark configuration
        self.config = self._load_benchmark_config()
        self.schemas = self._load_table_schemas()

    def _create_default_data_generator(self) -> DataGenerator:
        """Create default data generator."""
        return DefaultDataGenerator()

    def _create_default_query_manager(self) -> QueryManager:
        """Create default query manager."""
        return DefaultQueryManager()

    def _load_benchmark_config(self) -> Dict[str, Any]:
        """Load benchmark configuration."""
        # Override in subclasses to load from config files
        return {
            "name": "Advanced-level Benchmark",
            "version": "1.0.0",
            "description": "Advanced-level benchmark template"
        }

    def _load_table_schemas(self) -> Dict[str, TableSchema]:
        """Load table schemas."""
        # Override in subclasses to define actual schemas
        return {}

    def generate_data(self) -> Dict[str, Path]:
        """Generate data using the configured data generator."""
        self.output_dir.mkdir(parents=True, exist_ok=True)

        data_files = {}

        for table_name, schema in self.schemas.items():
            print(f"Generating data for {table_name}...")

            output_path = self.output_dir / f"{table_name}.csv"
            generated_file = self.data_generator.generate_table_data(
                schema, self.scale_factor, output_path
            )

            data_files[table_name] = generated_file

        return data_files

    def get_queries(self) -> Dict[Union[int, str], str]:
        """Get all queries from the query manager."""
        return self.query_manager.get_all_queries()

    def get_query(self, query_id: Union[int, str]) -> str:
        """Get specific query."""
        return self.query_manager.get_query(str(query_id))

    def get_query_metadata(self, query_id: str) -> QueryMetadata:
        """Get query metadata."""
        return self.query_manager.get_query_metadata(query_id)

    def get_queries_by_category(self, category: str) -> Dict[str, str]:
        """Get queries by category."""
        return self.query_manager.get_queries_by_category(category)

class DefaultDataGenerator(DataGenerator):
    """Default data generator implementation."""

    def generate_table_data(self, table_schema: TableSchema, scale_factor: float, output_path: Path) -> Path:
        """Generate realistic data based on schema."""

        # Calculate row count
        base_rows = self._get_base_row_count(table_schema.name)
        row_count = int(base_rows * scale_factor)

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f, delimiter='|')

            for i in range(row_count):
                row = []
                for column in table_schema.columns:
                    value = self._generate_column_value(column, i, row_count)
                    row.append(value)

                writer.writerow(row)

        return output_path

    def _get_base_row_count(self, table_name: str) -> int:
        """Get base row count for table."""
        # Override for specific table sizing
        return 1000

    def _generate_column_value(self, column: Dict[str, Any], row_id: int, total_rows: int) -> Any:
        """Generate value for a specific column."""

        column_type = column["type"].upper()
        column_name = column["name"].lower()

        # Handle different data types
        if "INTEGER" in column_type or "INT" in column_type:
            if column.get("primary_key"):
                return row_id
            else:
                return random.randint(1, 1000)

        elif "VARCHAR" in column_type or "TEXT" in column_type:
            if "category" in column_name:
                return random.choice(['A', 'B', 'C', 'D', 'E'])
            elif "name" in column_name:
                return f"Name_{random.randint(1, 1000)}"
            else:
                return f"Value_{row_id}"

        elif "DOUBLE" in column_type or "FLOAT" in column_type:
            return round(random.uniform(1.0, 1000.0), 2)

        elif "TIMESTAMP" in column_type or "DATE" in column_type:
            return f"2023-{random.randint(1, 12):02d}-{random.randint(1, 28):02d} 12:00:00"

        else:
            return f"default_{row_id}"

class DefaultQueryManager(QueryManager):
    """Default query manager implementation."""

    def __init__(self):
        self.queries = {}
        self.metadata = {}

    def add_query(self, query_id: str, query_sql: str, metadata: QueryMetadata):
        """Add a query to the manager."""
        self.queries[query_id] = query_sql
        self.metadata[query_id] = metadata

    def get_query(self, query_id: str) -> str:
        """Get specific query."""
        if query_id not in self.queries:
            raise ValueError(f"Query '{query_id}' not found")
        return self.queries[query_id]

    def get_all_queries(self) -> Dict[str, str]:
        """Get all queries."""
        return self.queries.copy()

    def get_query_metadata(self, query_id: str) -> QueryMetadata:
        """Get query metadata."""
        if query_id not in self.metadata:
            raise ValueError(f"Metadata for query '{query_id}' not found")
        return self.metadata[query_id]

    def get_queries_by_category(self, category: str) -> Dict[str, str]:
        """Get queries by category."""
        filtered_queries = {}

        for query_id, metadata in self.metadata.items():
            if metadata.category == category:
                filtered_queries[query_id] = self.queries[query_id]

        return filtered_queries
```

---

##  Data Generation Strategies

### Realistic Data Generation

```python
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
import string

class RealisticDataGenerator(DataGenerator):
    """Generate realistic data for benchmarks."""

    def __init__(self, seed: int = 42):
        self.fake = Faker()
        self.fake.seed_instance(seed)
        random.seed(seed)
        np.random.seed(seed)

    def generate_table_data(self, table_schema: TableSchema, scale_factor: float, output_path: Path) -> Path:
        """Generate realistic data based on table schema."""

        # Determine table characteristics
        table_config = self._get_table_config(table_schema.name)
        row_count = int(table_config["base_rows"] * scale_factor)

        print(f"Generating {row_count} rows for {table_schema.name}")

        # Generate data in batches for memory efficiency
        batch_size = 10000

        with open(output_path, 'w', newline='') as f:
            writer = csv.writer(f, delimiter='|')

            for batch_start in range(0, row_count, batch_size):
                batch_end = min(batch_start + batch_size, row_count)
                batch_data = self._generate_batch(
                    table_schema, batch_start, batch_end, table_config
                )

                for row in batch_data:
                    writer.writerow(row)

        return output_path

    def _get_table_config(self, table_name: str) -> Dict[str, Any]:
        """Get configuration for specific table types."""

        configs = {
            "customer": {
                "base_rows": 10000,
                "distributions": {
                    "segment": {"AUTOMOBILE": 0.3, "BUILDING": 0.3, "FURNITURE": 0.25, "MACHINERY": 0.15},
                    "nation": "uniform"
                }
            },
            "orders": {
                "base_rows": 50000,
                "date_range": (datetime(2020, 1, 1), datetime(2023, 12, 31)),
                "order_priority": ["1-URGENT", "2-HIGH", "3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
            },
            "lineitem": {
                "base_rows": 200000,
                "lines_per_order": (1, 7),  # Min, max lines per order
                "discount_range": (0.0, 0.10),
                "tax_range": (0.0, 0.08)
            },
            "part": {
                "base_rows": 5000,
                "part_types": ["ECONOMY ANODIZED", "ECONOMY BRUSHED", "ECONOMY BURNISHED"],
                "containers": ["SM CASE", "SM BOX", "SM PACK", "LG CASE", "LG BOX", "LG PACK"]
            }
        }

        return configs.get(table_name, {"base_rows": 1000})

    def _generate_batch(
        self,
        table_schema: TableSchema,
        start_id: int,
        end_id: int,
        table_config: Dict[str, Any]
    ) -> List[List[Any]]:
        """Generate a batch of rows."""

        batch_data = []

        for row_id in range(start_id, end_id):
            row = []

            for column in table_schema.columns:
                value = self._generate_realistic_value(column, row_id, table_config)
                row.append(value)

            batch_data.append(row)

        return batch_data

    def _generate_realistic_value(
        self,
        column: Dict[str, Any],
        row_id: int,
        table_config: Dict[str, Any]
    ) -> Any:
        """Generate realistic value based on column semantics."""

        column_name = column["name"].lower()
        column_type = column["type"].upper()

        # Primary key handling
        if column.get("primary_key"):
            return row_id

        # Foreign key handling
        if column_name.endswith("_key") and not column.get("primary_key"):
            # Generate foreign key reference
            return self._generate_foreign_key_value(column_name, row_id, table_config)

        # Name fields
        if "name" in column_name:
            if "customer" in column_name or "supplier" in column_name:
                return self.fake.company()
            elif "nation" in column_name:
                return self.fake.country()
            else:
                return self.fake.name()

        # Address fields
        if "address" in column_name:
            return self.fake.address().replace('\n', ', ')

        # Phone fields
        if "phone" in column_name:
            return self.fake.phone_number()

        # Comment fields
        if "comment" in column_name:
            return self.fake.text(max_nb_chars=100)

        # Date fields
        if "date" in column_name or "TIMESTAMP" in column_type or "DATE" in column_type:
            if "date_range" in table_config:
                start_date, end_date = table_config["date_range"]
                return self.fake.date_between(start_date=start_date, end_date=end_date)
            else:
                return self.fake.date_between(start_date='-2y', end_date='today')

        # Numeric fields with semantic meaning
        if "price" in column_name or "amount" in column_name:
            return round(random.uniform(10.0, 10000.0), 2)

        elif "quantity" in column_name:
            return random.randint(1, 50)

        elif "discount" in column_name:
            if "discount_range" in table_config:
                min_val, max_val = table_config["discount_range"]
                return round(random.uniform(min_val, max_val), 2)
            else:
                return round(random.uniform(0.0, 0.10), 2)

        elif "tax" in column_name:
            if "tax_range" in table_config:
                min_val, max_val = table_config["tax_range"]
                return round(random.uniform(min_val, max_val), 2)
            else:
                return round(random.uniform(0.0, 0.08), 2)

        # Priority and status fields
        elif "priority" in column_name:
            if "order_priority" in table_config:
                return random.choice(table_config["order_priority"])
            else:
                return random.choice(["HIGH", "MEDIUM", "LOW"])

        elif "status" in column_name:
            return random.choice(["F", "O", "P"])  # Fulfilled, Open, Pending

        # Segment and category fields
        elif "segment" in column_name or "mktsegment" in column_name:
            if "distributions" in table_config and "segment" in table_config["distributions"]:
                segments = list(table_config["distributions"]["segment"].keys())
                weights = list(table_config["distributions"]["segment"].values())
                return np.random.choice(segments, p=weights)
            else:
                return random.choice(["AUTOMOBILE", "BUILDING", "FURNITURE", "MACHINERY"])

        # Generic type-based generation
        elif "INTEGER" in column_type or "INT" in column_type:
            return random.randint(1, 100000)

        elif "DOUBLE" in column_type or "FLOAT" in column_type or "DECIMAL" in column_type:
            return round(random.uniform(1.0, 1000.0), 2)

        elif "VARCHAR" in column_type or "TEXT" in column_type:
            max_length = self._extract_varchar_length(column_type)
            text = self.fake.text(max_nb_chars=max_length)
            return text[:max_length] if max_length else text

        else:
            return f"value_{row_id}"

    def _generate_foreign_key_value(self, column_name: str, row_id: int, table_config: Dict[str, Any]) -> int:
        """Generate realistic foreign key values."""

        # Map foreign key columns to their referenced table sizes
        fk_mappings = {
            "custkey": 10000,      # customer table size
            "orderkey": 50000,     # orders table size
            "partkey": 5000,       # part table size
            "suppkey": 1000,       # supplier table size
            "nationkey": 25,       # nation table size
            "regionkey": 5         # region table size
        }

        # Extract the base name (remove prefixes like o_, l_, etc.)
        base_name = column_name.split('_')[-1]

        if base_name in fk_mappings:
            max_value = fk_mappings[base_name]
            return random.randint(0, max_value - 1)
        else:
            # Default foreign key generation
            return random.randint(0, 1000)

    def _extract_varchar_length(self, column_type: str) -> Optional[int]:
        """Extract length from VARCHAR(n) type."""
        import re
        match = re.search(r'VARCHAR\((\d+)\)', column_type)
        return int(match.group(1)) if match else None

# Example usage with realistic data
class ECommerceBenchmark(AdvancedBenchmark):
    """E-commerce benchmark with realistic data."""

    def _create_default_data_generator(self) -> DataGenerator:
        return RealisticDataGenerator()

    def _load_table_schemas(self) -> Dict[str, TableSchema]:
        return {
            "customer": TableSchema(
                name="customer",
                columns=[
                    {"name": "custkey", "type": "INTEGER", "primary_key": True},
                    {"name": "name", "type": "VARCHAR(25)", "nullable": False},
                    {"name": "address", "type": "VARCHAR(40)", "nullable": False},
                    {"name": "nationkey", "type": "INTEGER", "nullable": False},
                    {"name": "phone", "type": "VARCHAR(15)", "nullable": False},
                    {"name": "acctbal", "type": "DECIMAL(15,2)", "nullable": False},
                    {"name": "mktsegment", "type": "VARCHAR(10)", "nullable": False},
                    {"name": "comment", "type": "VARCHAR(117)", "nullable": True}
                ]
            ),
            "orders": TableSchema(
                name="orders",
                columns=[
                    {"name": "orderkey", "type": "INTEGER", "primary_key": True},
                    {"name": "custkey", "type": "INTEGER", "nullable": False},
                    {"name": "orderstatus", "type": "VARCHAR(1)", "nullable": False},
                    {"name": "totalprice", "type": "DECIMAL(15,2)", "nullable": False},
                    {"name": "orderdate", "type": "DATE", "nullable": False},
                    {"name": "orderpriority", "type": "VARCHAR(15)", "nullable": False},
                    {"name": "clerk", "type": "VARCHAR(15)", "nullable": False},
                    {"name": "shippriority", "type": "INTEGER", "nullable": False},
                    {"name": "comment", "type": "VARCHAR(79)", "nullable": True}
                ]
            )
        }

    def _create_default_query_manager(self) -> QueryManager:
        query_manager = DefaultQueryManager()

        # Add e-commerce specific queries
        query_manager.add_query(
            "customer_orders",
            """
            SELECT c.name, COUNT(o.orderkey) as order_count, SUM(o.totalprice) as total_spent
            FROM customer c
            JOIN orders o ON c.custkey = o.custkey
            GROUP BY c.custkey, c.name
            ORDER BY total_spent DESC
            LIMIT 10
            """,
            QueryMetadata(
                query_id="customer_orders",
                name="Top Customers by Revenue",
                description="Find top 10 customers by total purchase amount",
                category="analytics",
                complexity="medium",
                sql_features=["JOIN", "GROUP BY", "ORDER BY", "LIMIT"]
            )
        )

        query_manager.add_query(
            "monthly_revenue",
            """
            SELECT
                EXTRACT(YEAR FROM orderdate) as year,
                EXTRACT(MONTH FROM orderdate) as month,
                SUM(totalprice) as monthly_revenue,
                COUNT(*) as order_count
            FROM orders
            GROUP BY EXTRACT(YEAR FROM orderdate), EXTRACT(MONTH FROM orderdate)
            ORDER BY year, month
            """,
            QueryMetadata(
                query_id="monthly_revenue",
                name="Monthly Revenue Trend",
                description="Calculate monthly revenue and order count trends",
                category="time_series",
                complexity="simple",
                sql_features=["EXTRACT", "GROUP BY", "ORDER BY"]
            )
        )

        return query_manager

# Usage example
def test_ecommerce_benchmark():
    """Test the e-commerce benchmark."""

    benchmark = ECommerceBenchmark(scale_factor=0.01)

    # Generate data
    data_files = benchmark.generate_data()

    # Test queries
    queries = benchmark.get_queries()
    for query_id in queries:
        metadata = benchmark.get_query_metadata(query_id)
        print(f"Query: {metadata.name}")
        print(f"Category: {metadata.category}")
        print(f"Complexity: {metadata.complexity}")
        print()

if __name__ == "__main__":
    test_ecommerce_benchmark()
```

---

## Query Management

### Advanced-level Query Management

```python
from typing import Set
import re
import sqlparse

class AdvancedQueryManager(QueryManager):
    """Advanced-level query manager with analysis capabilities."""

    def __init__(self):
        super().__init__()
        self.query_analysis_cache = {}

    def add_query_from_file(self, query_id: str, file_path: Path, metadata: QueryMetadata):
        """Add query from SQL file."""
        with open(file_path, 'r') as f:
            query_sql = f.read()

        self.add_query(query_id, query_sql, metadata)

    def add_queries_from_directory(self, directory: Path, pattern: str = "*.sql"):
        """Add all queries from a directory."""
        for sql_file in directory.glob(pattern):
            query_id = sql_file.stem

            # Create default metadata
            metadata = QueryMetadata(
                query_id=query_id,
                name=query_id.replace('_', ' ').title(),
                description=f"Query loaded from {sql_file.name}",
                category="unknown",
                complexity="unknown",
                sql_features=[]
            )

            self.add_query_from_file(query_id, sql_file, metadata)

    def analyze_query_features(self, query_id: str) -> Set[str]:
        """Analyze SQL features used in a query."""

        if query_id in self.query_analysis_cache:
            return self.query_analysis_cache[query_id]

        query_sql = self.get_query(query_id)
        features = set()

        # Parse SQL to extract features
        try:
            parsed = sqlparse.parse(query_sql)[0]
            features = self._extract_features_from_tokens(parsed.tokens)
        except:
            # Fallback to regex-based analysis
            features = self._extract_features_regex(query_sql)

        # Cache results
        self.query_analysis_cache[query_id] = features
        return features

    def _extract_features_from_tokens(self, tokens) -> Set[str]:
        """Extract SQL features from parsed tokens."""
        features = set()

        def analyze_token(token):
            if token.ttype is sqlparse.tokens.Keyword:
                keyword = token.value.upper()

                # Map keywords to features
                keyword_mappings = {
                    'JOIN': 'joins',
                    'INNER JOIN': 'joins',
                    'LEFT JOIN': 'joins',
                    'RIGHT JOIN': 'joins',
                    'FULL JOIN': 'joins',
                    'GROUP BY': 'aggregation',
                    'HAVING': 'aggregation',
                    'WINDOW': 'window_functions',
                    'OVER': 'window_functions',
                    'WITH': 'cte',
                    'RECURSIVE': 'recursive_cte',
                    'UNION': 'set_operations',
                    'INTERSECT': 'set_operations',
                    'EXCEPT': 'set_operations',
                    'EXISTS': 'subqueries',
                    'IN': 'subqueries',
                    'ANY': 'subqueries',
                    'ALL': 'subqueries',
                    'CASE': 'conditional_logic',
                    'WHEN': 'conditional_logic',
                    'ORDER BY': 'sorting'
                }

                for kw, feature in keyword_mappings.items():
                    if kw in keyword:
                        features.add(feature)

            # Recursive analysis for nested tokens
            if hasattr(token, 'tokens'):
                for subtoken in token.tokens:
                    analyze_token(subtoken)

        for token in tokens:
            analyze_token(token)

        return features

    def _extract_features_regex(self, query_sql: str) -> Set[str]:
        """Extract SQL features using regex patterns."""
        features = set()

        query_upper = query_sql.upper()

        # Define patterns for SQL features
        patterns = {
            'joins': r'\b(JOIN|INNER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|FULL\s+JOIN)\b',
            'aggregation': r'\b(GROUP\s+BY|HAVING|COUNT|SUM|AVG|MIN|MAX)\b',
            'window_functions': r'\b(OVER\s*\(|ROW_NUMBER|RANK|DENSE_RANK|LAG|LEAD)\b',
            'cte': r'\bWITH\b',
            'recursive_cte': r'\bWITH\s+RECURSIVE\b',
            'set_operations': r'\b(UNION|INTERSECT|EXCEPT)\b',
            'subqueries': r'\b(EXISTS|IN\s*\(|ANY\s*\(|ALL\s*\()\b',
            'conditional_logic': r'\b(CASE\s+WHEN|IF\()\b',
            'sorting': r'\bORDER\s+BY\b'
        }

        for feature, pattern in patterns.items():
            if re.search(pattern, query_upper):
                features.add(feature)

        return features

    def calculate_query_complexity(self, query_id: str) -> str:
        """Calculate query complexity score."""

        query_sql = self.get_query(query_id)
        features = self.analyze_query_features(query_id)

        # Complexity scoring
        complexity_score = 0

        # Base score from query length
        complexity_score += len(query_sql.split()) // 10

        # Feature-based scoring
        feature_weights = {
            'joins': 3,
            'aggregation': 2,
            'window_functions': 4,
            'cte': 3,
            'recursive_cte': 5,
            'set_operations': 3,
            'subqueries': 2,
            'conditional_logic': 1,
            'sorting': 1
        }

        for feature in features:
            complexity_score += feature_weights.get(feature, 1)

        # Count number of tables
        table_count = len(re.findall(r'\bFROM\s+(\w+)', query_sql, re.IGNORECASE))
        complexity_score += table_count

        # Classify complexity
        if complexity_score <= 5:
            return "simple"
        elif complexity_score <= 15:
            return "medium"
        else:
            return "complex"

    def get_query_statistics(self) -> Dict[str, Any]:
        """Get statistics about all queries."""

        total_queries = len(self.queries)

        # Analyze all queries
        complexities = []
        features_count = {}
        categories_count = {}

        for query_id in self.queries:
            # Complexity analysis
            complexity = self.calculate_query_complexity(query_id)
            complexities.append(complexity)

            # Feature analysis
            features = self.analyze_query_features(query_id)
            for feature in features:
                features_count[feature] = features_count.get(feature, 0) + 1

            # Category analysis
            metadata = self.get_query_metadata(query_id)
            category = metadata.category
            categories_count[category] = categories_count.get(category, 0) + 1

        # Calculate distributions
        complexity_dist = {
            complexity: complexities.count(complexity)
            for complexity in ["simple", "medium", "complex"]
        }

        return {
            "total_queries": total_queries,
            "complexity_distribution": complexity_dist,
            "feature_usage": features_count,
            "category_distribution": categories_count,
            "most_common_features": sorted(features_count.items(), key=lambda x: x[1], reverse=True)[:5]
        }

    def export_query_catalog(self, output_file: Path):
        """Export query catalog to JSON."""

        catalog = {
            "metadata": {
                "total_queries": len(self.queries),
                "generated_at": datetime.now().isoformat()
            },
            "statistics": self.get_query_statistics(),
            "queries": {}
        }

        for query_id in self.queries:
            metadata = self.get_query_metadata(query_id)
            features = self.analyze_query_features(query_id)
            complexity = self.calculate_query_complexity(query_id)

            catalog["queries"][query_id] = {
                "name": metadata.name,
                "description": metadata.description,
                "category": metadata.category,
                "complexity": complexity,
                "sql_features": list(features),
                "estimated_runtime_ms": metadata.estimated_runtime_ms,
                "query_sql": self.get_query(query_id)
            }

        with open(output_file, 'w') as f:
            json.dump(catalog, f, indent=2)

# Example: Web Analytics Benchmark
class WebAnalyticsBenchmark(AdvancedBenchmark):
    """Web analytics benchmark with realistic queries."""

    def _create_default_query_manager(self) -> QueryManager:
        query_manager = AdvancedQueryManager()

        # Page views analysis
        query_manager.add_query(
            "daily_page_views",
            """
            SELECT
                DATE(timestamp) as date,
                page_url,
                COUNT(*) as page_views,
                COUNT(DISTINCT user_id) as unique_visitors
            FROM page_views
            WHERE timestamp >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
            GROUP BY DATE(timestamp), page_url
            ORDER BY date DESC, page_views DESC
            """,
            QueryMetadata(
                query_id="daily_page_views",
                name="Daily Page Views Analysis",
                description="Analyze daily page views and unique visitors",
                category="analytics",
                complexity="medium",
                sql_features=["aggregation", "date_functions", "filtering"]
            )
        )

        # User journey analysis
        query_manager.add_query(
            "user_journey",
            """
            WITH user_sessions AS (
                SELECT
                    user_id,
                    session_id,
                    page_url,
                    timestamp,
                    ROW_NUMBER() OVER (PARTITION BY user_id, session_id ORDER BY timestamp) as step_number
                FROM page_views
                WHERE timestamp >= DATE_SUB(CURRENT_DATE, INTERVAL 7 DAY)
            ),
            journey_paths AS (
                SELECT
                    user_id,
                    session_id,
                    STRING_AGG(page_url, ' -> ' ORDER BY step_number) as journey_path,
                    COUNT(*) as steps
                FROM user_sessions
                GROUP BY user_id, session_id
            )
            SELECT
                journey_path,
                COUNT(*) as session_count,
                AVG(steps) as avg_steps
            FROM journey_paths
            WHERE steps >= 2
            GROUP BY journey_path
            ORDER BY session_count DESC
            LIMIT 20
            """,
            QueryMetadata(
                query_id="user_journey",
                name="User Journey Analysis",
                description="Analyze most common user journey paths",
                category="behavior_analysis",
                complexity="complex",
                sql_features=["cte", "window_functions", "aggregation", "string_functions"]
            )
        )

        # Conversion funnel
        query_manager.add_query(
            "conversion_funnel",
            """
            WITH funnel_steps AS (
                SELECT
                    user_id,
                    MAX(CASE WHEN page_url LIKE '%/product/%' THEN 1 ELSE 0 END) as viewed_product,
                    MAX(CASE WHEN page_url LIKE '%/cart%' THEN 1 ELSE 0 END) as added_to_cart,
                    MAX(CASE WHEN page_url LIKE '%/checkout%' THEN 1 ELSE 0 END) as started_checkout,
                    MAX(CASE WHEN page_url LIKE '%/confirmation%' THEN 1 ELSE 0 END) as completed_purchase
                FROM page_views
                WHERE timestamp >= DATE_SUB(CURRENT_DATE, INTERVAL 30 DAY)
                GROUP BY user_id
            )
            SELECT
                'Total Users' as step,
                COUNT(*) as users,
                100.0 as conversion_rate
            FROM funnel_steps

            UNION ALL

            SELECT
                'Viewed Product' as step,
                SUM(viewed_product) as users,
                100.0 * SUM(viewed_product) / COUNT(*) as conversion_rate
            FROM funnel_steps

            UNION ALL

            SELECT
                'Added to Cart' as step,
                SUM(added_to_cart) as users,
                100.0 * SUM(added_to_cart) / COUNT(*) as conversion_rate
            FROM funnel_steps

            UNION ALL

            SELECT
                'Started Checkout' as step,
                SUM(started_checkout) as users,
                100.0 * SUM(started_checkout) / COUNT(*) as conversion_rate
            FROM funnel_steps

            UNION ALL

            SELECT
                'Completed Purchase' as step,
                SUM(completed_purchase) as users,
                100.0 * SUM(completed_purchase) / COUNT(*) as conversion_rate
            FROM funnel_steps
            """,
            QueryMetadata(
                query_id="conversion_funnel",
                name="E-commerce Conversion Funnel",
                description="Analyze conversion rates through purchase funnel",
                category="conversion_analysis",
                complexity="complex",
                sql_features=["cte", "conditional_logic", "set_operations", "aggregation"]
            )
        )

        return query_manager

def test_web_analytics_benchmark():
    """Test web analytics benchmark with query analysis."""

    benchmark = WebAnalyticsBenchmark()
    query_manager = benchmark.query_manager

    # Analyze queries
    stats = query_manager.get_query_statistics()

    print("Query Analysis Results:")
    print(f"Total queries: {stats['total_queries']}")
    print(f"Complexity distribution: {stats['complexity_distribution']}")
    print(f"Most common features: {stats['most_common_features']}")

    # Export catalog
    query_manager.export_query_catalog(Path("web_analytics_catalog.json"))
    print("Query catalog exported to web_analytics_catalog.json")

if __name__ == "__main__":
    test_web_analytics_benchmark()
```

---

## See Also

- [Getting Started](../usage/getting-started.md) - Basic BenchBox usage
- [Examples](../usage/examples.md) - Practical implementation examples
- [API Reference](../reference/api-reference.md) - Complete API documentation
- [Performance Monitoring](performance.md) - Performance analysis for custom benchmarks

---

*This guide provides systematic patterns for creating custom benchmarks in BenchBox. Start with simple examples and gradually implement more advanced features as needed.*
