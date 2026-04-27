<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Vector Search Benchmark

```{tags} advanced, concept, vector-search, custom-benchmark
```

> **CLI name:** `vector_search` - use `benchbox run --benchmark vector_search`

The Vector Search benchmark tests similarity-search performance across OLAP
databases that support array/vector operations. It covers exact kNN, filtered
kNN, and approximate (ANN) search over synthetic embedding data.

## Overview

| Property            | Value                                               |
| ------------------- | --------------------------------------------------- |
| **Total Queries**   | 6                                                   |
| **Data Source**     | Synthetic embeddings (reproducible)                 |
| **Default Dimensions** | 128                                              |
| **Primary Target**  | DuckDB (`array_cosine_similarity`, `array_distance`) |
| **Dialect Variants**| pgvector, ClickHouse, Snowflake, StarRocks, Doris  |

## Query Coverage

| ID / Area               | Description                                              |
| ----------------------- | -------------------------------------------------------- |
| Exact kNN (cosine)      | Exact k-nearest neighbors by cosine similarity           |
| Exact kNN (L2)          | Exact k-nearest neighbors by Euclidean distance          |
| Filtered kNN            | Metadata predicate + distance ordering                   |
| Large-k ground truth    | Ground-truth generation for recall evaluation            |
| ANN search              | Same SQL form; relies on HNSW index from load phase      |
| Multi-category filtered | Multi-predicate filtered similarity search               |

## Scale Factors

| Scale | Vectors | Notes                               |
| ----: | ------: | ----------------------------------- |
|  0.01 |  ~10 K  | Quick smoke test                    |
|   0.1 | ~100 K  | Dev / CI                            |
|   1.0 |   ~1 M  | Default - representative workload   |

## Usage

```bash
# Default: 128-dimensional vectors, SF=1 (~1M vectors)
benchbox run --platform duckdb --benchmark vector_search --scale 1.0

# Smaller vectors for quick tests
benchbox run --platform duckdb --benchmark vector_search --scale 0.1 \
  --benchmark-option dimensions=64

# Higher-dimensional embeddings
benchbox run --platform duckdb --benchmark vector_search --scale 1.0 \
  --benchmark-option dimensions=768
```

## Benchmark Options

| Option       | Default | Description                    |
| ------------ | ------: | ------------------------------ |
| `dimensions` |     128 | Embedding vector dimensionality |

## Platform Support

Vector Search targets engines with native array / vector operations:

| Platform        | Support      | Notes                                                   |
| --------------- | ------------ | ------------------------------------------------------- |
| DuckDB          | Primary      | Native `array_cosine_similarity` / `array_distance`     |
| PostgreSQL      | Via pgvector | Requires `pgvector` extension                           |
| ClickHouse      | Yes          | Dialect variant uses ClickHouse vector ops              |
| Snowflake       | Yes          | Dialect variant uses Snowflake vector ops               |
| StarRocks       | Yes          | Dialect variant uses StarRocks vector distance fns      |
| Doris           | Yes          | Dialect variant uses Doris array distance fns           |

## Notes

- Synthetic data is reproducible - the same seed produces identical embeddings
  across runs.
- ANN queries reuse kNN SQL but rely on an HNSW (or equivalent) index being
  built during the `load` phase.
- Recall is evaluated against the large-k ground-truth query; compare
  approximate vs. exact results after a run.

## See Also

- [AI Primitives](ai-primitives.md) - SQL-based AI functions on cloud platforms
- [Read Primitives](read-primitives.md) - companion SQL operation coverage
