export type TagCategory = { slug: string; title: string; tags: readonly string[] };

export const TAG_CATEGORIES: readonly TagCategory[] = [
  { slug: "audience", title: "By Audience", tags: ["beginner", "intermediate", "advanced", "contributor"] },
  { slug: "benchmark", title: "By Benchmark", tags: ["tpc-h", "tpc-ds", "tpc-di", "tpc-havoc", "tpch-skew", "ssb", "clickbench", "h2odb", "join-order", "amplab", "nyctaxi", "coffeeshop", "datavault", "tsbs-devops", "read-primitives", "write-primitives", "transaction-primitives", "metadata-primitives", "ai-primitives", "custom-benchmark"] },
  { slug: "platform", title: "By Platform", tags: ["duckdb", "sqlite", "postgresql", "datafusion", "snowflake", "databricks", "bigquery", "redshift", "motherduck", "starburst", "clickhouse", "trino", "presto", "firebolt", "timescaledb", "influxdb", "athena", "aws-glue", "emr-serverless", "athena-spark", "dataproc", "dataproc-serverless", "azure", "fabric", "fabric-spark", "synapse-spark", "spark", "pyspark", "pandas", "polars", "dask", "modin", "cudf", "datafusion-df"] },
  { slug: "platform-type", title: "By Platform Type", tags: ["sql-platform", "dataframe-platform", "cloud-platform", "embedded-platform", "cloud-storage"] },
  { slug: "content-type", title: "By Content Type", tags: ["guide", "tutorial", "reference", "concept", "quickstart"] },
  { slug: "feature", title: "By Feature", tags: ["architecture", "cli", "cloud", "e2e", "python-api", "configuration", "data-generation", "performance", "tuning", "validation", "testing", "visualization"] },
];
