"""AI/ML SQL function query management.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .functions import AIMLFunctionCategory, AIMLFunctionRegistry


@dataclass
class AIMLQuery:
    """A benchmark query for an AI/ML function."""

    query_id: str
    function_id: str
    category: AIMLFunctionCategory
    name: str
    description: str
    platform_queries: dict[str, str] = field(default_factory=dict)
    requires_sample_data: bool = True
    batch_size: int = 10
    timeout_seconds: int = 120

    def get_query(self, platform: str) -> str | None:
        """Get the query for a specific platform."""
        return self.platform_queries.get(platform.lower())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "query_id": self.query_id,
            "function_id": self.function_id,
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "platforms": list(self.platform_queries.keys()),
            "batch_size": self.batch_size,
            "timeout_seconds": self.timeout_seconds,
        }


class AIMLQueryManager:
    """Manager for AI/ML benchmark queries."""

    def __init__(self) -> None:
        """Initialize the query manager."""
        self._registry = AIMLFunctionRegistry()
        self._queries: dict[str, AIMLQuery] = {}
        self._build_queries()

    def _build_queries(self) -> None:
        """Build benchmark queries from the function registry."""
        # Sentiment Analysis Queries
        self._queries["sentiment_single"] = AIMLQuery(
            query_id="sentiment_single",
            function_id="sentiment_analysis",
            category=AIMLFunctionCategory.SENTIMENT,
            name="Single Text Sentiment",
            description="Analyze sentiment of a single text value",
            batch_size=1,
            timeout_seconds=30,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.SENTIMENT(text_content) AS sentiment
FROM aiml_sample_data
WHERE id = 1
""",
                "bigquery": """
SELECT *
FROM ML.UNDERSTAND_TEXT(
    MODEL `aiml_sentiment_model`,
    (SELECT text_content FROM aiml_sample_data WHERE id = 1),
    STRUCT('CLASSIFY_TEXT' AS nlu_option)
)
""",
                "databricks": """
SELECT ai_analyze_sentiment(text_content) AS sentiment
FROM aiml_sample_data
WHERE id = 1
""",
            },
        )

        self._queries["sentiment_batch"] = AIMLQuery(
            query_id="sentiment_batch",
            function_id="sentiment_analysis",
            category=AIMLFunctionCategory.SENTIMENT,
            name="Batch Sentiment Analysis",
            description="Analyze sentiment of multiple texts in batch",
            batch_size=100,
            timeout_seconds=120,
            platform_queries={
                "snowflake": """
SELECT id, text_content, SNOWFLAKE.CORTEX.SENTIMENT(text_content) AS sentiment
FROM aiml_sample_data
ORDER BY id
LIMIT 100
""",
                "databricks": """
SELECT id, text_content, ai_analyze_sentiment(text_content) AS sentiment
FROM aiml_sample_data
ORDER BY id
LIMIT 100
""",
            },
        )

        self._queries["sentiment_aggregation"] = AIMLQuery(
            query_id="sentiment_aggregation",
            function_id="sentiment_analysis",
            category=AIMLFunctionCategory.SENTIMENT,
            name="Sentiment Aggregation",
            description="Aggregate sentiment scores by category",
            batch_size=100,
            timeout_seconds=180,
            platform_queries={
                "snowflake": """
SELECT
    category,
    COUNT(*) AS count,
    AVG(SNOWFLAKE.CORTEX.SENTIMENT(text_content)) AS avg_sentiment,
    MIN(SNOWFLAKE.CORTEX.SENTIMENT(text_content)) AS min_sentiment,
    MAX(SNOWFLAKE.CORTEX.SENTIMENT(text_content)) AS max_sentiment
FROM aiml_sample_data
GROUP BY category
ORDER BY category
""",
                "databricks": """
SELECT
    category,
    COUNT(*) AS count,
    AVG(ai_analyze_sentiment(text_content)) AS avg_sentiment,
    MIN(ai_analyze_sentiment(text_content)) AS min_sentiment,
    MAX(ai_analyze_sentiment(text_content)) AS max_sentiment
FROM aiml_sample_data
GROUP BY category
ORDER BY category
""",
            },
        )

        # Classification Queries
        self._queries["classification_single"] = AIMLQuery(
            query_id="classification_single",
            function_id="text_classification",
            category=AIMLFunctionCategory.CLASSIFICATION,
            name="Single Text Classification",
            description="Classify a single text into categories",
            batch_size=1,
            timeout_seconds=30,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.CLASSIFY_TEXT(
    text_content,
    ARRAY_CONSTRUCT('Technology', 'Finance', 'Healthcare', 'Entertainment', 'Sports')
) AS classification
FROM aiml_sample_data
WHERE id = 1
""",
                "databricks": """
SELECT ai_classify(
    text_content,
    ARRAY('Technology', 'Finance', 'Healthcare', 'Entertainment', 'Sports')
) AS classification
FROM aiml_sample_data
WHERE id = 1
""",
            },
        )

        self._queries["classification_batch"] = AIMLQuery(
            query_id="classification_batch",
            function_id="text_classification",
            category=AIMLFunctionCategory.CLASSIFICATION,
            name="Batch Classification",
            description="Classify multiple texts into categories",
            batch_size=50,
            timeout_seconds=120,
            platform_queries={
                "snowflake": """
SELECT
    id,
    text_content,
    SNOWFLAKE.CORTEX.CLASSIFY_TEXT(
        text_content,
        ARRAY_CONSTRUCT('Technology', 'Finance', 'Healthcare', 'Entertainment', 'Sports')
    ) AS classification
FROM aiml_sample_data
ORDER BY id
LIMIT 50
""",
                "databricks": """
SELECT
    id,
    text_content,
    ai_classify(
        text_content,
        ARRAY('Technology', 'Finance', 'Healthcare', 'Entertainment', 'Sports')
    ) AS classification
FROM aiml_sample_data
ORDER BY id
LIMIT 50
""",
            },
        )

        # Summarization Queries
        self._queries["summarization_single"] = AIMLQuery(
            query_id="summarization_single",
            function_id="summarization",
            category=AIMLFunctionCategory.SUMMARIZATION,
            name="Single Text Summarization",
            description="Summarize a single long text",
            batch_size=1,
            timeout_seconds=60,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.SUMMARIZE(long_text) AS summary
FROM aiml_long_texts
WHERE id = 1
""",
                "bigquery": """
SELECT *
FROM ML.GENERATE_TEXT(
    MODEL `gemini-pro`,
    (SELECT CONCAT('Summarize this text in 2-3 sentences: ', long_text) AS prompt
     FROM aiml_long_texts WHERE id = 1),
    STRUCT(150 AS max_output_tokens, 0.3 AS temperature)
)
""",
                "databricks": """
SELECT ai_summarize(long_text) AS summary
FROM aiml_long_texts
WHERE id = 1
""",
            },
        )

        self._queries["summarization_batch"] = AIMLQuery(
            query_id="summarization_batch",
            function_id="summarization",
            category=AIMLFunctionCategory.SUMMARIZATION,
            name="Batch Summarization",
            description="Summarize multiple long texts",
            batch_size=10,
            timeout_seconds=300,
            platform_queries={
                "snowflake": """
SELECT id, SNOWFLAKE.CORTEX.SUMMARIZE(long_text) AS summary
FROM aiml_long_texts
ORDER BY id
LIMIT 10
""",
                "databricks": """
SELECT id, ai_summarize(long_text) AS summary
FROM aiml_long_texts
ORDER BY id
LIMIT 10
""",
            },
        )

        # LLM Completion Queries
        self._queries["completion_simple"] = AIMLQuery(
            query_id="completion_simple",
            function_id="completion",
            category=AIMLFunctionCategory.COMPLETION,
            name="Simple Completion",
            description="Generate simple text completion",
            batch_size=1,
            timeout_seconds=60,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.COMPLETE(
    'mistral-large',
    'Complete this sentence: The most important factor in database performance is'
) AS completion
""",
                "bigquery": """
SELECT *
FROM ML.GENERATE_TEXT(
    MODEL `gemini-pro`,
    (SELECT 'Complete this sentence: The most important factor in database performance is' AS prompt),
    STRUCT(100 AS max_output_tokens, 0.7 AS temperature)
)
""",
                "databricks": """
SELECT ai_query(
    'databricks-meta-llama-3-1-70b-instruct',
    'Complete this sentence: The most important factor in database performance is'
) AS completion
""",
            },
        )

        self._queries["completion_with_context"] = AIMLQuery(
            query_id="completion_with_context",
            function_id="completion",
            category=AIMLFunctionCategory.COMPLETION,
            name="Completion with Context",
            description="Generate completion using row data as context",
            batch_size=10,
            timeout_seconds=120,
            platform_queries={
                "snowflake": """
SELECT
    id,
    SNOWFLAKE.CORTEX.COMPLETE(
        'mistral-large',
        CONCAT('Based on this text: "', text_content, '", answer: What is the main topic?')
    ) AS answer
FROM aiml_sample_data
ORDER BY id
LIMIT 10
""",
                "databricks": """
SELECT
    id,
    ai_query(
        'databricks-meta-llama-3-1-70b-instruct',
        CONCAT('Based on this text: "', text_content, '", answer: What is the main topic?')
    ) AS answer
FROM aiml_sample_data
ORDER BY id
LIMIT 10
""",
            },
        )

        # Embedding Queries
        self._queries["embedding_single"] = AIMLQuery(
            query_id="embedding_single",
            function_id="embedding",
            category=AIMLFunctionCategory.EMBEDDING,
            name="Single Text Embedding",
            description="Generate embedding for a single text",
            batch_size=1,
            timeout_seconds=30,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', text_content) AS embedding
FROM aiml_sample_data
WHERE id = 1
""",
                "bigquery": """
SELECT *
FROM ML.GENERATE_EMBEDDING(
    MODEL `textembedding-gecko`,
    (SELECT text_content AS content FROM aiml_sample_data WHERE id = 1)
)
""",
                "databricks": """
SELECT ai_embed('databricks-bge-large-en', text_content) AS embedding
FROM aiml_sample_data
WHERE id = 1
""",
            },
        )

        self._queries["embedding_batch"] = AIMLQuery(
            query_id="embedding_batch",
            function_id="embedding",
            category=AIMLFunctionCategory.EMBEDDING,
            name="Batch Embedding Generation",
            description="Generate embeddings for multiple texts",
            batch_size=100,
            timeout_seconds=120,
            platform_queries={
                "snowflake": """
SELECT id, SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', text_content) AS embedding
FROM aiml_sample_data
ORDER BY id
LIMIT 100
""",
                "databricks": """
SELECT id, ai_embed('databricks-bge-large-en', text_content) AS embedding
FROM aiml_sample_data
ORDER BY id
LIMIT 100
""",
            },
        )

        self._queries["embedding_similarity"] = AIMLQuery(
            query_id="embedding_similarity",
            function_id="embedding",
            category=AIMLFunctionCategory.EMBEDDING,
            name="Embedding Similarity Search",
            description="Find similar texts using embedding distance",
            batch_size=10,
            timeout_seconds=60,
            platform_queries={
                "snowflake": """
WITH target AS (
    SELECT SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', text_content) AS embedding
    FROM aiml_sample_data
    WHERE id = 1
),
candidates AS (
    SELECT id, text_content, SNOWFLAKE.CORTEX.EMBED_TEXT_768('e5-base-v2', text_content) AS embedding
    FROM aiml_sample_data
    WHERE id != 1
    LIMIT 50
)
SELECT
    c.id,
    c.text_content,
    VECTOR_COSINE_SIMILARITY(t.embedding, c.embedding) AS similarity
FROM candidates c, target t
ORDER BY similarity DESC
LIMIT 10
""",
            },
        )

        # Translation Queries
        self._queries["translation_single"] = AIMLQuery(
            query_id="translation_single",
            function_id="translation",
            category=AIMLFunctionCategory.TRANSLATION,
            name="Single Text Translation",
            description="Translate a single text",
            batch_size=1,
            timeout_seconds=30,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.TRANSLATE(text_content, 'en', 'es') AS translation
FROM aiml_sample_data
WHERE id = 1
""",
                "bigquery": """
SELECT ML.TRANSLATE(text_content, 'es') AS translation
FROM aiml_sample_data
WHERE id = 1
""",
            },
        )

        self._queries["translation_batch"] = AIMLQuery(
            query_id="translation_batch",
            function_id="translation",
            category=AIMLFunctionCategory.TRANSLATION,
            name="Batch Translation",
            description="Translate multiple texts",
            batch_size=50,
            timeout_seconds=120,
            platform_queries={
                "snowflake": """
SELECT id, text_content, SNOWFLAKE.CORTEX.TRANSLATE(text_content, 'en', 'es') AS spanish
FROM aiml_sample_data
ORDER BY id
LIMIT 50
""",
                "bigquery": """
SELECT id, text_content, ML.TRANSLATE(text_content, 'es') AS spanish
FROM aiml_sample_data
ORDER BY id
LIMIT 50
""",
            },
        )

        # Entity Extraction Queries
        self._queries["extraction_single"] = AIMLQuery(
            query_id="extraction_single",
            function_id="entity_extraction",
            category=AIMLFunctionCategory.EXTRACTION,
            name="Single Entity Extraction",
            description="Extract entities from a single text",
            batch_size=1,
            timeout_seconds=30,
            platform_queries={
                "snowflake": """
SELECT SNOWFLAKE.CORTEX.EXTRACT_ANSWER(
    text_content,
    'What are the named entities (people, places, organizations)?'
) AS entities
FROM aiml_sample_data
WHERE id = 1
""",
                "databricks": """
SELECT ai_extract(
    text_content,
    ARRAY('person', 'location', 'organization')
) AS entities
FROM aiml_sample_data
WHERE id = 1
""",
            },
        )

    def get_query(self, query_id: str) -> AIMLQuery | None:
        """Get a query by ID."""
        return self._queries.get(query_id)

    def get_all_queries(self) -> dict[str, AIMLQuery]:
        """Get all queries."""
        return self._queries.copy()

    def get_queries_by_category(self, category: AIMLFunctionCategory) -> list[AIMLQuery]:
        """Get all queries in a category."""
        return [q for q in self._queries.values() if q.category == category]

    def get_queries_for_platform(self, platform: str) -> list[AIMLQuery]:
        """Get all queries that have implementations for a platform."""
        platform_lower = platform.lower()
        return [q for q in self._queries.values() if platform_lower in q.platform_queries]

    def get_query_ids(self) -> list[str]:
        """Get all query IDs."""
        return list(self._queries.keys())

    def get_categories(self) -> list[AIMLFunctionCategory]:
        """Get all query categories."""
        return list(set(q.category for q in self._queries.values()))

    def export_queries(self) -> dict[str, Any]:
        """Export all queries as a dictionary."""
        return {query_id: query.to_dict() for query_id, query in self._queries.items()}
