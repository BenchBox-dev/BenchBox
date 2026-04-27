<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# AI/ML Primitives Benchmark

```{tags} advanced, concept, ai-primitives, custom-benchmark
```

> **CLI name:** `ai_primitives` - use `benchbox run --benchmark ai_primitives`

The AI/ML Primitives benchmark tests SQL-based AI functions across cloud data platforms. It enables consistent evaluation of AI capabilities in Snowflake Cortex, BigQuery ML, and Databricks AI Functions using TPC-H data.

## Overview

| Property | Value |
|----------|-------|
| **Total Queries** | 16 |
| **Categories** | 4 (generative, nlp, transform, embedding) |
| **Data Source** | TPC-H (shared data) |
| **Supported Platforms** | Snowflake, BigQuery, Databricks |
| **Cost Control** | Built-in budget enforcement |

### Why AI Primitives?

Modern cloud data platforms increasingly offer built-in AI/ML capabilities through SQL functions:

- **Snowflake Cortex**: `COMPLETE`, `SUMMARIZE`, `SENTIMENT`, `EXTRACT_ANSWER`, `EMBED_TEXT`
- **BigQuery ML**: `ML.GENERATE_TEXT`, `ML.UNDERSTAND_TEXT`, `ML.GENERATE_EMBEDDING`
- **Databricks AI**: `ai_query`, `ai_summarize`, `ai_classify`, `ai_generate`

The AI Primitives benchmark provides:

1. **Standardized Testing**: Same queries across all platforms
2. **Cost Estimation**: Pre-execution cost estimates with budget enforcement
3. **Performance Comparison**: Consistent metrics for platform evaluation
4. **Production Data**: Uses TPC-H customer/supplier comments as realistic text

## Query Categories

### Generative (4 queries)

Text generation and completion tasks:

| Query ID | Description |
|----------|-------------|
| `generative_complete_simple` | Basic text completion with short prompt |
| `generative_complete_customer_profile` | Generate customer profile summaries from comments |
| `generative_question_answer` | Answer questions about customer data |
| `generative_sql_generation` | Generate SQL from natural language |

### NLP (5 queries)

Natural language processing and understanding:

| Query ID | Description |
|----------|-------------|
| `nlp_sentiment_analysis` | Analyze sentiment of customer comments |
| `nlp_classification` | Classify customer feedback into categories |
| `nlp_entity_extraction` | Extract entities (products, locations, etc.) |
| `nlp_language_detection` | Detect language of supplier comments |
| `nlp_keyword_extraction` | Extract key terms from order comments |

### Transform (4 queries)

Text transformation tasks:

| Query ID | Description |
|----------|-------------|
| `transform_summarize` | Summarize long customer comments |
| `transform_translate` | Translate supplier comments |
| `transform_grammar_correction` | Correct grammar in customer feedback |
| `transform_rewrite_professional` | Rewrite comments in professional tone |

### Embedding (3 queries)

Vector embedding generation:

| Query ID | Description |
|----------|-------------|
| `embedding_customer_comments` | Generate embeddings for customer comments |
| `embedding_supplier_descriptions` | Generate embeddings for supplier descriptions |
| `embedding_similarity_search` | Find similar items using vector similarity |

## Quick Start

### CLI Usage

```bash
# Run AI Primitives benchmark on Snowflake
benchbox run --platform snowflake --benchmark ai_primitives --scale 0.01

# Dry run to estimate costs first
benchbox run --platform snowflake --benchmark ai_primitives --dry-run ./preview

# Set cost budget (fails if exceeded)
benchbox run --platform snowflake --benchmark ai_primitives \
  --benchmark-option max_cost_usd=1.00

# Run specific categories only
benchbox run --platform databricks --benchmark ai_primitives \
  --benchmark-option categories=nlp,transform
```

### Programmatic Usage

```python
from benchbox.core.ai_primitives import AIPrimitivesBenchmark

# Initialize with cost budget
benchmark = AIPrimitivesBenchmark(
    scale_factor=0.01,
    max_cost_usd=1.00,
    dry_run=False
)

# Estimate costs before execution
total_cost, estimates = benchmark.estimate_cost(
    platform="snowflake",
    categories=["nlp", "transform"]
)
print(f"Estimated cost: ${total_cost:.4f}")

# Run benchmark
result = benchmark.run_benchmark(
    connection=snowflake_connection,
    platform="snowflake",
    categories=["nlp"]
)

print(f"Successful: {result.successful_queries}/{result.total_queries}")
print(f"Total cost: ${result.total_cost_estimated_usd:.4f}")
```

## Platform Support

### Snowflake (Cortex)

Snowflake Cortex provides LLM functions directly in SQL:

```sql
-- Text completion
SELECT SNOWFLAKE.CORTEX.COMPLETE('llama3-8b', 'Summarize: ' || comment) AS summary
FROM customer LIMIT 10;

-- Sentiment analysis
SELECT SNOWFLAKE.CORTEX.SENTIMENT(c_comment) AS sentiment
FROM customer WHERE c_nationkey = 1;

-- Embedding generation
SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', c_comment) AS embedding
FROM customer LIMIT 10;
```

**Supported Models**: `llama3-8b`, `llama3-70b`, `mistral-large`, `mixtral-8x7b`

### BigQuery (ML Functions)

BigQuery ML provides AI functions through external model connections:

```sql
-- Text generation
SELECT ML.GENERATE_TEXT(
    MODEL `project.dataset.llm_model`,
    (SELECT 'Summarize: ' || comment AS prompt),
    STRUCT(100 AS max_output_tokens)
).ml_generate_text_result AS summary
FROM `project.dataset.customer` LIMIT 10;

-- Embedding generation
SELECT ML.GENERATE_EMBEDDING(
    MODEL `project.dataset.embedding_model`,
    (SELECT c_comment AS content)
).ml_generate_embedding_result AS embedding
FROM `project.dataset.customer` LIMIT 10;
```

**Setup Required**: Create external model connection to Vertex AI or other LLM provider.

### Databricks (AI Functions)

Databricks provides AI functions through Foundation Model APIs:

```sql
-- Text completion
SELECT ai_query(
    'databricks-meta-llama-3-1-70b-instruct',
    CONCAT('Summarize this customer: ', c_comment)
) AS summary
FROM customer LIMIT 10;

-- Classification
SELECT ai_classify(c_comment, ARRAY('positive', 'negative', 'neutral')) AS sentiment
FROM customer LIMIT 10;
```

**Supported Models**: Foundation Model APIs including Llama, DBRX, and external endpoints.

## Cost Management

AI queries incur costs based on token usage. The benchmark provides built-in cost controls.

### Cost Estimation

```python
from benchbox.core.ai_primitives import AIPrimitivesBenchmark

benchmark = AIPrimitivesBenchmark(scale_factor=0.01)

# Get detailed cost estimates
total_cost, estimates = benchmark.estimate_cost(platform="snowflake")

for estimate in estimates:
    print(f"{estimate.query_id}: ${estimate.estimated_cost_usd:.4f}")
    print(f"  Tokens: {estimate.estimated_tokens}")
    print(f"  Model: {estimate.model}")
```

### Budget Enforcement

```bash
# Set maximum cost (execution fails if exceeded)
benchbox run --platform snowflake --benchmark ai_primitives \
  --benchmark-option max_cost_usd=1.00

# Dry run mode (estimates only, no AI calls)
benchbox run --platform snowflake --benchmark ai_primitives \
  --dry-run ./cost_preview
```

### Typical Costs (Estimated)

| Category | Queries | Est. Cost (SF=0.01) |
|----------|---------|---------------------|
| Generative | 4 | ~$0.05-0.15 |
| NLP | 5 | ~$0.02-0.08 |
| Transform | 4 | ~$0.03-0.10 |
| Embedding | 3 | ~$0.01-0.05 |
| **Total** | **16** | **~$0.10-0.40** |

*Costs vary by platform, model, and actual token usage.*

## Configuration Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `scale_factor` | float | 0.01 | TPC-H scale factor (affects data volume) |
| `max_cost_usd` | float | 0.0 | Maximum allowed cost (0 = unlimited) |
| `dry_run` | bool | False | Estimate costs without executing |
| `categories` | list | all | Filter by category |
| `queries` | list | all | Run specific query IDs |

## Result Structure

```python
@dataclass
class AIBenchmarkResult:
    benchmark: str = "AI Primitives"
    platform: str = ""
    scale_factor: float = 1.0
    dry_run: bool = False
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    skipped_queries: int = 0
    total_execution_time_ms: float = 0.0
    total_cost_estimated_usd: float = 0.0
    cost_tracker: CostTracker | None = None
    query_results: list[AIQueryResult] = field(default_factory=list)
```

## Unsupported Platforms

The following platforms do not have built-in AI functions and will skip AI queries:

- DuckDB
- ClickHouse
- SQLite
- PostgreSQL
- DataFusion
- Trino/Presto
- Redshift
- Azure Synapse Analytics
- Microsoft Fabric

When running on these platforms, queries are skipped with informative messages.

## Best Practices

### 1. Start with Dry Run

Always estimate costs before running AI queries:

```bash
benchbox run --platform snowflake --benchmark ai_primitives \
  --dry-run ./preview --scale 0.01
```

### 2. Use Small Scale Factors

AI functions process text row-by-row. Start with `--scale 0.01`:

```bash
benchbox run --platform databricks --benchmark ai_primitives --scale 0.01
```

### 3. Set Cost Budgets

Prevent runaway costs with budget limits:

```python
benchmark = AIPrimitivesBenchmark(
    scale_factor=0.01,
    max_cost_usd=1.00  # Hard limit
)
```

### 4. Test by Category

Run specific categories to focus testing:

```bash
# Test NLP only
benchbox run --platform snowflake --benchmark ai_primitives \
  --benchmark-option categories=nlp
```

### 5. Monitor Actual Costs

Compare estimates vs actuals in results:

```python
result = benchmark.run_benchmark(connection, "snowflake")
print(f"Estimated: ${result.total_cost_estimated_usd:.4f}")
print(f"Tracker: {result.cost_tracker.get_summary()}")
```

## Extending the Benchmark

### Adding New Queries

Add queries to `benchbox/core/ai_primitives/catalog/queries.yaml`:

```yaml
- id: my_new_query
  category: nlp
  description: My new AI query
  model: llama3-8b
  estimated_tokens: 100
  batch_size: 10
  cost_per_1k_tokens: 0.0003
  sql: |
    SELECT 'placeholder' as result
  variants:
    snowflake: |
      SELECT SNOWFLAKE.CORTEX.SENTIMENT(c_comment) FROM customer LIMIT 10
    bigquery: |
      -- BigQuery variant
    databricks: |
      -- Databricks variant
  skip_on:
    - duckdb
    - clickhouse
```

### Adding New Platforms

1. Add platform to `SUPPORTED_PLATFORMS` in `benchmark.py`
2. Add query variants in `queries.yaml`
3. Implement cost estimation for the platform's pricing model

## Related Documentation

- [Read Primitives](read-primitives.md) - SQL operation testing
- [Write Primitives](write-primitives.md) - Write operation testing
- [TPC-H](tpc-h.md) - Source data for AI queries
- [Snowflake](../platforms/snowflake.md) - Snowflake platform guide
- [BigQuery](../platforms/bigquery.md) - BigQuery platform guide
- [Databricks](../platforms/databricks.md) - Databricks platform guide
