export type CardOrigin = { href: string; label: string };

export type Card = {
  href: string;
  title: string;
  description: string;
  meta: string;
  linkLabel?: string;
  origin?: CardOrigin;
};

export type CardGroup = { title: string; subtitle: string; cards: Card[] };

export const benchmarkGroups: CardGroup[] = [
  {
    "title": "TPC Standards",
    "subtitle": "Official industry standards for comparing databases",
    "cards": [
      {
        "href": "/docs/benchmarks/tpc-h.html",
        "title": "TPC-H",
        "description": "Standard data warehouse benchmark with 22 business intelligence queries.",
        "meta": "8 tables • 22 queries",
        "linkLabel": "TPC-H Documentation →",
        "origin": {
          "href": "http://www.tpc.org/tpch/",
          "label": "TPC.org Standard ↗"
        }
      },
      {
        "href": "/docs/benchmarks/tpc-ds.html",
        "title": "TPC-DS",
        "description": "Complex decision support benchmark modeling multi-dimensional analysis.",
        "meta": "25 tables • 99 queries",
        "linkLabel": "TPC-DS Documentation →",
        "origin": {
          "href": "http://www.tpc.org/tpcds/",
          "label": "TPC.org Standard ↗"
        }
      },
      {
        "href": "/docs/benchmarks/tpc-di.html",
        "title": "TPC-DI",
        "description": "Data integration benchmark testing ETL operations and data quality.",
        "meta": "15 tables • ETL workflow",
        "linkLabel": "TPC-DI Documentation →",
        "origin": {
          "href": "http://www.tpc.org/tpcdi/",
          "label": "TPC.org Standard ↗"
        }
      }
    ]
  },
  {
    "title": "Academic Benchmarks",
    "subtitle": "Research benchmarks from academia",
    "cards": [
      {
        "href": "/docs/benchmarks/ssb.html",
        "title": "Star Schema Benchmark",
        "description": "Simplified data warehouse testing basic OLAP functionality.",
        "meta": "4 tables • 13 queries",
        "linkLabel": "SSB Documentation →",
        "origin": {
          "href": "https://www.cs.umb.edu/~poneil/StarSchemaB.PDF",
          "label": "Original Paper ↗"
        }
      },
      {
        "href": "/docs/benchmarks/amplab.html",
        "title": "AMPLab",
        "description": "Big data benchmark focusing on machine learning and analytics workloads.",
        "meta": "3 tables • 8 queries",
        "linkLabel": "AMPLab Documentation →",
        "origin": {
          "href": "https://amplab.cs.berkeley.edu/benchmark/",
          "label": "Original Site ↗"
        }
      },
      {
        "href": "/docs/benchmarks/join-order.html",
        "title": "Join Order Benchmark",
        "description": "Query optimizer testing with complex multi-table joins from IMDB data.",
        "meta": "21 tables • 113 queries",
        "linkLabel": "Join Order Documentation →",
        "origin": {
          "href": "https://www.vldb.org/pvldb/vol9/p204-leis.pdf",
          "label": "Original Paper ↗"
        }
      }
    ]
  },
  {
    "title": "Industry Benchmarks",
    "subtitle": "Real-world benchmarks from practitioners",
    "cards": [
      {
        "href": "/docs/benchmarks/clickbench.html",
        "title": "ClickBench",
        "description": "Analytics benchmark with real-world web analytics queries.",
        "meta": "1 table • 43 queries",
        "linkLabel": "ClickBench Documentation →",
        "origin": {
          "href": "https://benchmark.clickhouse.com/",
          "label": "Official Site ↗"
        }
      },
      {
        "href": "/docs/benchmarks/h2odb.html",
        "title": "H2ODB",
        "description": "Data science benchmark testing aggregation and join performance.",
        "meta": "2 tables • 10 queries",
        "linkLabel": "H2ODB Documentation →",
        "origin": {
          "href": "https://duckdblabs.github.io/db-benchmark/",
          "label": "Official Site ↗"
        }
      },
      {
        "href": "/docs/benchmarks/coffeeshop.html",
        "title": "CoffeeShop",
        "description": "Small analytical benchmark modeling a coffee shop with sales and inventory.",
        "meta": "3 tables • 11 queries",
        "linkLabel": "CoffeeShop Documentation →",
        "origin": {
          "href": "https://josuebogran.substack.com/p/databricks-vs-snowflake-vs-fabric",
          "label": "Original Post ↗"
        }
      }
    ]
  },
  {
    "title": "Real-World Data",
    "subtitle": "Benchmarks built on public real-world datasets",
    "cards": [
      {
        "href": "/docs/benchmarks/nyctaxi.html",
        "title": "NYC Taxi",
        "description": "Real-world transportation analytics with geospatial and temporal queries.",
        "meta": "2 tables • 25 queries",
        "linkLabel": "NYC Taxi Documentation →",
        "origin": {
          "href": "https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page",
          "label": "NYC TLC Data ↗"
        }
      },
      {
        "href": "/docs/benchmarks/flightdata.html",
        "title": "Flight Data",
        "description": "US domestic flight analytics with on-time performance and carrier metrics.",
        "meta": "BTS data • 20 queries",
        "linkLabel": "Flight Data Documentation →",
        "origin": {
          "href": "https://www.transtats.bts.gov/",
          "label": "US BTS TranStats ↗"
        }
      }
    ]
  },
  {
    "title": "Time-Series Benchmarks",
    "subtitle": "Workloads for time-series databases and columnar monitoring engines",
    "cards": [
      {
        "href": "/docs/benchmarks/tsbs-devops.html",
        "title": "TSBS DevOps",
        "description": "Time-series benchmark for infrastructure monitoring and observability.",
        "meta": "Time-series • 18 queries",
        "linkLabel": "TSBS Documentation →",
        "origin": {
          "href": "https://github.com/timescale/tsbs",
          "label": "Original Repo ↗"
        }
      }
    ]
  },
  {
    "title": "BenchBox Primitives",
    "subtitle": "Fundamental database operation testing",
    "cards": [
      {
        "href": "/docs/benchmarks/read-primitives.html",
        "title": "Read Primitives",
        "description": "Read operation testing across 26 categories.",
        "meta": "TPC-H schema • 136 queries",
        "linkLabel": "Primitives Documentation →"
      },
      {
        "href": "/docs/benchmarks/write-primitives.html",
        "title": "Write Primitives",
        "description": "Comprehensive write operation testing including bulk loads and merges.",
        "meta": "TPC-H schema • 12 operations",
        "linkLabel": "Write Primitives Documentation →"
      },
      {
        "href": "/docs/benchmarks/transaction-primitives.html",
        "title": "Transaction Primitives",
        "description": "ACID transaction testing with isolation levels, commits, and rollbacks.",
        "meta": "TPC-H schema • 12 operations",
        "linkLabel": "Transaction Primitives Documentation →"
      },
      {
        "href": "/docs/benchmarks/metadata-primitives.html",
        "title": "Metadata Primitives",
        "description": "Catalog introspection via INFORMATION_SCHEMA, SHOW, DESCRIBE, and PRAGMA.",
        "meta": "10 categories • 62 queries",
        "linkLabel": "Metadata Primitives Documentation →"
      },
      {
        "href": "/docs/benchmarks/ai-primitives.html",
        "title": "AI Primitives",
        "description": "SQL-based AI functions (Snowflake Cortex, BigQuery ML, Databricks AI) with cost controls.",
        "meta": "TPC-H data • 16 queries",
        "linkLabel": "AI Primitives Documentation →"
      }
    ]
  },
  {
    "title": "AI & ML Benchmarks",
    "subtitle": "Vector similarity and other AI-shaped analytical workloads",
    "cards": [
      {
        "href": "/docs/benchmarks/vector-search.html",
        "title": "Vector Search",
        "description": "Vector similarity search with kNN, ANN, and filtered queries on embedding data.",
        "meta": "Embeddings • 6 queries",
        "linkLabel": "Vector Search Documentation →"
      }
    ]
  },
  {
    "title": "BenchBox Experimental",
    "subtitle": "Experimental benchmarks for specialized testing",
    "cards": [
      {
        "href": "/docs/benchmarks/tpc-havoc.html",
        "title": "TPC-Havoc",
        "description": "Query optimizer stress testing with 220 syntax variants of TPC-H queries.",
        "meta": "TPC-H schema • 220 variants",
        "linkLabel": "TPC-Havoc Documentation →"
      },
      {
        "href": "/docs/benchmarks/tpch-skew.html",
        "title": "TPC-H Skew",
        "description": "Test optimizer behavior on non-uniform data distributions (Zipfian, exponential).",
        "meta": "TPC-H schema • Skewed data",
        "linkLabel": "TPC-H Skew Documentation →"
      },
      {
        "href": "/docs/benchmarks/tpc-ds-obt.html",
        "title": "TPC-DS-OBT",
        "description": "TPC-DS queries on a single denormalized \"One Big Table\" schema.",
        "meta": "1 wide table • 17 queries",
        "linkLabel": "TPC-DS-OBT Documentation →"
      },
      {
        "href": "/docs/benchmarks/datavault.html",
        "title": "Data Vault",
        "description": "TPC-H adapted for Data Vault 2.0 modeling (Hub-Link-Satellite pattern).",
        "meta": "21 tables • 22 queries",
        "linkLabel": "Data Vault Documentation →"
      }
    ]
  }
];

export const platformGroups: CardGroup[] = [
  {
    "title": "Single-Node Analytics Engines",
    "subtitle": "In-process and local columnar databases",
    "cards": [
      {
        "href": "/docs/platforms/duckdb.html",
        "title": "DuckDB",
        "description": "In-process analytical database. Built-in, no setup required.",
        "meta": "Built-in • OLAP"
      },
      {
        "href": "/docs/platforms/clickhouse-local-mode.html",
        "title": "ClickHouse Local (chDB)",
        "description": "Embedded ClickHouse via chDB for in-process columnar analytics.",
        "meta": "In-process • OLAP"
      },
      {
        "href": "/docs/platforms/clickhouse-server.html",
        "title": "ClickHouse Server",
        "description": "Self-hosted ClickHouse for high-performance columnar analytics.",
        "meta": "Self-hosted • OLAP"
      },
      {
        "href": "/docs/platforms/datafusion.html",
        "title": "DataFusion",
        "description": "Apache Arrow-native query engine for in-memory analytics.",
        "meta": "In-process • Arrow"
      },
      {
        "href": "/docs/platforms/cedardb.html",
        "title": "CedarDB",
        "description": "High-performance analytical database from TUM (formerly Umbra).",
        "meta": "Single-node • OLAP"
      }
    ]
  },
  {
    "title": "Row-Based & Postgres-Compatible",
    "subtitle": "Traditional relational databases",
    "cards": [
      {
        "href": "/docs/platforms/postgresql.html",
        "title": "PostgreSQL",
        "description": "The world's most advanced open source relational database.",
        "meta": "OLTP/OLAP • Relational"
      },
      {
        "href": "/docs/platforms/sqlite.html",
        "title": "SQLite",
        "description": "Embedded transactional database for testing and CI/CD.",
        "meta": "Built-in • OLTP"
      },
      {
        "href": "/docs/platforms/pg_duckdb.html",
        "title": "pg_duckdb",
        "description": "DuckDB-powered Postgres extension for vectorized OLAP on Postgres tables.",
        "meta": "Extension • OLAP"
      },
      {
        "href": "/docs/platforms/pg_mooncake.html",
        "title": "pg_mooncake",
        "description": "Columnar storage extension for Postgres with Iceberg and Delta Lake support.",
        "meta": "Extension • Lakehouse"
      }
    ]
  },
  {
    "title": "Cloud Data Platforms",
    "subtitle": "Enterprise cloud data warehouses and lakehouses",
    "cards": [
      {
        "href": "/docs/platforms/snowflake.html",
        "title": "Snowflake",
        "description": "Multi-cloud data warehouse with elastic compute.",
        "meta": "Cloud • Warehouse"
      },
      {
        "href": "/docs/platforms/databricks.html",
        "title": "Databricks SQL",
        "description": "Data Intelligence Platform with lakehouse architecture.",
        "meta": "Cloud • Lakehouse"
      },
      {
        "href": "/docs/platforms/bigquery.html",
        "title": "Google BigQuery",
        "description": "Google Cloud serverless data warehouse.",
        "meta": "GCP • Serverless"
      },
      {
        "href": "/docs/platforms/clickhouse-cloud.html",
        "title": "ClickHouse Cloud",
        "description": "Managed ClickHouse with serverless and dedicated options.",
        "meta": "Cloud • OLAP"
      },
      {
        "href": "/docs/platforms/redshift.html",
        "title": "Amazon Redshift",
        "description": "AWS cloud data warehouse (serverless or provisioned).",
        "meta": "AWS • Warehouse"
      },
      {
        "href": "/docs/platforms/athena.html",
        "title": "Amazon Athena",
        "description": "AWS serverless query service for S3 data lakes.",
        "meta": "AWS • Serverless"
      },
      {
        "href": "/docs/platforms/azure-platforms.html",
        "title": "Azure Synapse Analytics",
        "description": "Microsoft Azure analytics service.",
        "meta": "Azure • Analytics"
      },
      {
        "href": "/docs/platforms/microsoft-fabric.html",
        "title": "Microsoft Fabric Warehouse",
        "description": "Fabric SQL warehouse with OneLake-native storage.",
        "meta": "Azure • Warehouse"
      },
      {
        "href": "/docs/platforms/fabric-lakehouse.html",
        "title": "Microsoft Fabric Lakehouse SQL",
        "description": "SQL endpoint over Fabric lakehouses on OneLake.",
        "meta": "Azure • Lakehouse"
      },
      {
        "href": "/docs/platforms/firebolt.html",
        "title": "Firebolt",
        "description": "Cloud data warehouse optimized for analytics.",
        "meta": "Cloud • OLAP"
      },
      {
        "href": "/docs/platforms/databend.html",
        "title": "Databend",
        "description": "Open source cloud-native data warehouse written in Rust.",
        "meta": "Cloud • Rust"
      },
      {
        "href": "/docs/platforms/motherduck.html",
        "title": "MotherDuck",
        "description": "Serverless cloud DuckDB with hybrid local/cloud execution.",
        "meta": "Cloud • DuckDB"
      },
      {
        "href": "/docs/platforms/starburst.html",
        "title": "Starburst",
        "description": "Enterprise Trino with managed cloud offering.",
        "meta": "Cloud • Federation"
      }
    ]
  },
  {
    "title": "Distributed Query Engines",
    "subtitle": "Open source MPP and federated SQL engines",
    "cards": [
      {
        "href": "/docs/platforms/trino.html",
        "title": "Trino",
        "description": "Distributed SQL query engine for federated data.",
        "meta": "Distributed • Federation"
      },
      {
        "href": "/docs/platforms/presto.html",
        "title": "PrestoDB",
        "description": "Distributed SQL query engine (Meta's fork).",
        "meta": "Distributed • Federation"
      },
      {
        "href": "/docs/platforms/spark.html",
        "title": "Apache Spark SQL",
        "description": "Distributed SQL engine for large-scale data processing.",
        "meta": "Distributed • Spark"
      },
      {
        "href": "/docs/platforms/doris.html",
        "title": "Apache Doris",
        "description": "MPP analytical database with real-time ingestion and MySQL protocol.",
        "meta": "MPP • Real-time"
      },
      {
        "href": "/docs/platforms/starrocks.html",
        "title": "StarRocks",
        "description": "High-performance columnar MPP engine for sub-second analytics.",
        "meta": "MPP • Columnar"
      },
      {
        "href": "/docs/platforms/lakesail.html",
        "title": "LakeSail Sail",
        "description": "Rust-based Spark-compatible engine on DataFusion via Spark Connect.",
        "meta": "Rust • Spark Connect"
      },
      {
        "href": "/docs/platforms/velox.html",
        "title": "Apache Gluten + Velox",
        "description": "Native C++ Spark acceleration layer powered by Meta's Velox.",
        "meta": "Spark • Native acceleration"
      },
      {
        "href": "/docs/platforms/singlestore.html",
        "title": "SingleStore",
        "description": "Distributed SQL with real-time analytics and MySQL protocol.",
        "meta": "Distributed • HTAP"
      }
    ]
  },
  {
    "title": "Managed Spark Services",
    "subtitle": "Cloud-managed Spark for lakehouse and data lake analytics",
    "cards": [
      {
        "href": "/docs/platforms/quanton.html",
        "title": "Onehouse Quanton",
        "description": "Serverless Spark with Hudi, Iceberg, and Delta Lake support.",
        "meta": "Serverless • Multi-format"
      },
      {
        "href": "/docs/platforms/aws-glue.html",
        "title": "AWS Glue",
        "description": "Serverless data integration service with Spark ETL.",
        "meta": "AWS • ETL"
      },
      {
        "href": "/docs/platforms/emr-serverless.html",
        "title": "Amazon EMR Serverless",
        "description": "Serverless Spark with automatic scaling.",
        "meta": "AWS • Serverless"
      },
      {
        "href": "/docs/platforms/athena-spark.html",
        "title": "Amazon Athena for Apache Spark",
        "description": "Interactive Spark notebooks on Amazon Athena.",
        "meta": "AWS • Interactive"
      },
      {
        "href": "/docs/platforms/gcp-dataproc.html",
        "title": "Google Cloud Dataproc",
        "description": "Managed Spark and Hadoop clusters on Google Cloud.",
        "meta": "GCP • Clusters"
      },
      {
        "href": "/docs/platforms/dataproc-serverless.html",
        "title": "Google Cloud Dataproc Serverless",
        "description": "Serverless Spark with no cluster management.",
        "meta": "GCP • Serverless"
      },
      {
        "href": "/docs/platforms/fabric-spark.html",
        "title": "Microsoft Fabric Spark",
        "description": "SaaS Spark with OneLake integration.",
        "meta": "Azure • SaaS"
      },
      {
        "href": "/docs/platforms/synapse-spark.html",
        "title": "Azure Synapse Analytics Spark",
        "description": "Enterprise Spark pools with ADLS Gen2.",
        "meta": "Azure • Enterprise"
      },
      {
        "href": "/docs/platforms/snowpark-connect.html",
        "title": "Snowpark Connect for Spark",
        "description": "PySpark API compatibility on Snowflake.",
        "meta": "Snowflake • PySpark API"
      }
    ]
  },
  {
    "title": "Time Series Databases",
    "subtitle": "Optimized for time-stamped data",
    "cards": [
      {
        "href": "/docs/platforms/timescaledb.html",
        "title": "TimescaleDB",
        "description": "Time-series database built on PostgreSQL.",
        "meta": "Time-series • PostgreSQL"
      },
      {
        "href": "/docs/platforms/influxdb.html",
        "title": "InfluxDB",
        "description": "Time-series database for metrics and events.",
        "meta": "Time-series • IoT"
      },
      {
        "href": "/docs/platforms/questdb.html",
        "title": "QuestDB",
        "description": "High-performance time-series database with Postgres wire protocol.",
        "meta": "Time-series • PG wire"
      }
    ]
  },
  {
    "title": "DataFrame Platforms",
    "subtitle": "Native DataFrame APIs instead of SQL",
    "cards": [
      {
        "href": "/docs/platforms/polars.html",
        "title": "Polars",
        "description": "Fast Rust-based DataFrame library with lazy evaluation.",
        "meta": "polars-df • Expression API"
      },
      {
        "href": "/docs/platforms/pandas-dataframe.html",
        "title": "Pandas",
        "description": "Reference Python DataFrame implementation.",
        "meta": "pandas-df • Pandas API"
      },
      {
        "href": "/docs/platforms/pyspark-dataframe.html",
        "title": "PySpark DataFrame",
        "description": "Apache Spark DataFrame API for distributed computing.",
        "meta": "pyspark-df • Distributed"
      },
      {
        "href": "/docs/platforms/datafusion-dataframe.html",
        "title": "DataFusion DataFrame",
        "description": "Arrow-native DataFrame with lazy evaluation.",
        "meta": "datafusion-df • Arrow"
      },
      {
        "href": "/docs/platforms/dask-dataframe.html",
        "title": "Dask",
        "description": "Parallel computing library with DataFrame API.",
        "meta": "dask-df • Distributed"
      },
      {
        "href": "/docs/platforms/cudf.html",
        "title": "cuDF (RAPIDS)",
        "description": "GPU-accelerated DataFrame library from NVIDIA.",
        "meta": "cudf-df • GPU"
      },
      {
        "href": "/docs/platforms/databricks-dataframe.html",
        "title": "Databricks DataFrame",
        "description": "Databricks PySpark DataFrame execution on serverless or classic compute.",
        "meta": "databricks-df • PySpark"
      }
    ]
  }
];

export const formatGroups: CardGroup[] = [
  {
    "title": "File Formats",
    "subtitle": "Columnar storage for fast analytics",
    "cards": [
      {
        "href": "/docs/advanced/format-conversion.html#apache-parquet",
        "title": "Apache Parquet",
        "description": "Industry-standard columnar format with universal platform support.",
        "meta": "Universal • 3-5x compression"
      },
      {
        "href": "/docs/advanced/format-conversion.html#vortex",
        "title": "Vortex",
        "description": "High-performance columnar format optimized for analytical workloads.",
        "meta": "DuckDB/DataFusion • Best compression"
      }
    ]
  },
  {
    "title": "Table Formats",
    "subtitle": "ACID transactions, time travel, and schema evolution",
    "cards": [
      {
        "href": "/docs/advanced/format-conversion.html#delta-lake",
        "title": "Delta Lake",
        "description": "Open table format with ACID transactions and time travel on Parquet.",
        "meta": "Databricks • Time Travel"
      },
      {
        "href": "/docs/advanced/format-conversion.html#apache-iceberg",
        "title": "Apache Iceberg",
        "description": "Modern table format with hidden partitioning and schema evolution.",
        "meta": "Multi-engine • Enterprise"
      },
      {
        "href": "/docs/advanced/format-conversion.html#apache-hudi",
        "title": "Apache Hudi",
        "description": "Table format optimized for incremental processing and record-level updates.",
        "meta": "Streaming • Upserts"
      },
      {
        "href": "/docs/advanced/format-conversion.html#ducklake",
        "title": "DuckLake",
        "description": "DuckDB's native table format with ACID transactions and optimal performance.",
        "meta": "DuckDB Native • Time Travel"
      }
    ]
  }
];
