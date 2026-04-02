"""AI/ML function definitions and platform support registry.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AIMLFunctionCategory(str, Enum):
    """Categories of AI/ML SQL functions."""

    SENTIMENT = "sentiment"
    CLASSIFICATION = "classification"
    SUMMARIZATION = "summarization"
    COMPLETION = "completion"
    EMBEDDING = "embedding"
    TRANSLATION = "translation"
    EXTRACTION = "extraction"
    PREDICTION = "prediction"


@dataclass
class PlatformSupport:
    """Platform-specific support information for an AI/ML function."""

    platform: str
    function_name: str
    syntax_template: str
    requires_model: bool = False
    default_model: str = ""
    min_version: str = ""
    notes: str = ""
    cost_per_1k_tokens: float = 0.0

    def format_query(self, input_column: str, **kwargs: Any) -> str:
        """Format the function call with the given input column."""
        return self.syntax_template.format(input=input_column, **kwargs)


@dataclass
class AIMLFunction:
    """Definition of an AI/ML SQL function."""

    function_id: str
    category: AIMLFunctionCategory
    name: str
    description: str
    platforms: dict[str, PlatformSupport] = field(default_factory=dict)
    sample_input: str = ""
    expected_output_type: str = "string"
    latency_class: str = "high"  # low (<100ms), medium (100-500ms), high (>500ms)

    def is_supported_on(self, platform: str) -> bool:
        """Check if this function is supported on the given platform."""
        return platform.lower() in self.platforms

    def get_platform_support(self, platform: str) -> PlatformSupport | None:
        """Get platform-specific support information."""
        return self.platforms.get(platform.lower())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "function_id": self.function_id,
            "category": self.category.value,
            "name": self.name,
            "description": self.description,
            "platforms": list(self.platforms.keys()),
            "latency_class": self.latency_class,
        }


class AIMLFunctionRegistry:
    """Registry of AI/ML SQL functions across platforms."""

    def __init__(self) -> None:
        """Initialize the registry with known AI/ML functions."""
        self._functions: dict[str, AIMLFunction] = {}
        self._register_functions()

    def _register_functions(self) -> None:
        """Register all known AI/ML functions."""
        # Sentiment Analysis
        self._functions["sentiment_analysis"] = AIMLFunction(
            function_id="sentiment_analysis",
            category=AIMLFunctionCategory.SENTIMENT,
            name="Sentiment Analysis",
            description="Analyze sentiment of text (positive, negative, neutral)",
            sample_input="This product is amazing! I love it.",
            expected_output_type="string",
            latency_class="medium",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.SENTIMENT",
                    syntax_template="SNOWFLAKE.CORTEX.SENTIMENT({input})",
                    requires_model=False,
                    notes="Returns float between -1 (negative) and 1 (positive)",
                    cost_per_1k_tokens=0.002,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.UNDERSTAND_TEXT",
                    syntax_template="ML.UNDERSTAND_TEXT(MODEL `{model}`, (SELECT {input} AS text_content), STRUCT('CLASSIFY_TEXT' AS nlu_option))",
                    requires_model=True,
                    default_model="sentiment_model",
                    notes="Requires pre-trained or custom NLU model",
                    cost_per_1k_tokens=0.004,
                ),
                "databricks": PlatformSupport(
                    platform="databricks",
                    function_name="ai_analyze_sentiment",
                    syntax_template="ai_analyze_sentiment({input})",
                    requires_model=False,
                    min_version="14.0",
                    notes="Built-in AI function in Databricks SQL",
                    cost_per_1k_tokens=0.003,
                ),
            },
        )

        # Text Classification
        self._functions["text_classification"] = AIMLFunction(
            function_id="text_classification",
            category=AIMLFunctionCategory.CLASSIFICATION,
            name="Text Classification",
            description="Classify text into predefined categories",
            sample_input="The stock market showed strong gains today.",
            expected_output_type="string",
            latency_class="medium",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.CLASSIFY_TEXT",
                    syntax_template="SNOWFLAKE.CORTEX.CLASSIFY_TEXT({input}, {categories})",
                    requires_model=False,
                    notes="Categories provided as array of strings",
                    cost_per_1k_tokens=0.003,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.PREDICT",
                    syntax_template="ML.PREDICT(MODEL `{model}`, (SELECT {input} AS text_content))",
                    requires_model=True,
                    default_model="text_classifier",
                    notes="Requires trained classification model",
                    cost_per_1k_tokens=0.004,
                ),
                "databricks": PlatformSupport(
                    platform="databricks",
                    function_name="ai_classify",
                    syntax_template="ai_classify({input}, ARRAY({categories}))",
                    requires_model=False,
                    min_version="14.0",
                    notes="Built-in AI function in Databricks SQL",
                    cost_per_1k_tokens=0.003,
                ),
            },
        )

        # Text Summarization
        self._functions["summarization"] = AIMLFunction(
            function_id="summarization",
            category=AIMLFunctionCategory.SUMMARIZATION,
            name="Text Summarization",
            description="Generate a summary of input text",
            sample_input="A long article about climate change and its effects...",
            expected_output_type="string",
            latency_class="high",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.SUMMARIZE",
                    syntax_template="SNOWFLAKE.CORTEX.SUMMARIZE({input})",
                    requires_model=False,
                    notes="Uses default summarization model",
                    cost_per_1k_tokens=0.005,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.GENERATE_TEXT",
                    syntax_template="ML.GENERATE_TEXT(MODEL `{model}`, CONCAT('Summarize: ', {input}), STRUCT(100 AS max_output_tokens))",
                    requires_model=True,
                    default_model="text-bison",
                    notes="Uses PaLM or Gemini model",
                    cost_per_1k_tokens=0.01,
                ),
                "databricks": PlatformSupport(
                    platform="databricks",
                    function_name="ai_summarize",
                    syntax_template="ai_summarize({input})",
                    requires_model=False,
                    min_version="14.0",
                    notes="Built-in AI function in Databricks SQL",
                    cost_per_1k_tokens=0.006,
                ),
            },
        )

        # LLM Completion
        self._functions["completion"] = AIMLFunction(
            function_id="completion",
            category=AIMLFunctionCategory.COMPLETION,
            name="LLM Completion",
            description="Generate text completion using LLM",
            sample_input="Complete this sentence: The future of AI is",
            expected_output_type="string",
            latency_class="high",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.COMPLETE",
                    syntax_template="SNOWFLAKE.CORTEX.COMPLETE('{model}', {input})",
                    requires_model=True,
                    default_model="mistral-large",
                    notes="Supports multiple models: llama3.1-70b, mistral-large, etc.",
                    cost_per_1k_tokens=0.012,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.GENERATE_TEXT",
                    syntax_template="ML.GENERATE_TEXT(MODEL `{model}`, {input}, STRUCT(256 AS max_output_tokens, 0.7 AS temperature))",
                    requires_model=True,
                    default_model="gemini-pro",
                    notes="Uses Vertex AI models (Gemini, PaLM)",
                    cost_per_1k_tokens=0.015,
                ),
                "databricks": PlatformSupport(
                    platform="databricks",
                    function_name="ai_query",
                    syntax_template="ai_query('{model}', {input})",
                    requires_model=True,
                    default_model="databricks-meta-llama-3-1-70b-instruct",
                    notes="Uses Foundation Model APIs",
                    cost_per_1k_tokens=0.01,
                ),
            },
        )

        # Text Embedding
        self._functions["embedding"] = AIMLFunction(
            function_id="embedding",
            category=AIMLFunctionCategory.EMBEDDING,
            name="Text Embedding",
            description="Generate vector embeddings for text",
            sample_input="This is a sample text for embedding.",
            expected_output_type="array",
            latency_class="low",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.EMBED_TEXT_768",
                    syntax_template="SNOWFLAKE.CORTEX.EMBED_TEXT_768('{model}', {input})",
                    requires_model=True,
                    default_model="e5-base-v2",
                    notes="Returns 768-dimensional vector",
                    cost_per_1k_tokens=0.0001,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.GENERATE_EMBEDDING",
                    syntax_template="ML.GENERATE_EMBEDDING(MODEL `{model}`, STRUCT({input} AS content))",
                    requires_model=True,
                    default_model="textembedding-gecko",
                    notes="Returns 768-dimensional vector",
                    cost_per_1k_tokens=0.0001,
                ),
                "databricks": PlatformSupport(
                    platform="databricks",
                    function_name="ai_embed",
                    syntax_template="ai_embed('{model}', {input})",
                    requires_model=True,
                    default_model="databricks-bge-large-en",
                    notes="Uses Databricks embedding models",
                    cost_per_1k_tokens=0.0001,
                ),
            },
        )

        # Translation
        self._functions["translation"] = AIMLFunction(
            function_id="translation",
            category=AIMLFunctionCategory.TRANSLATION,
            name="Text Translation",
            description="Translate text between languages",
            sample_input="Hello, how are you today?",
            expected_output_type="string",
            latency_class="medium",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.TRANSLATE",
                    syntax_template="SNOWFLAKE.CORTEX.TRANSLATE({input}, '{source_lang}', '{target_lang}')",
                    requires_model=False,
                    notes="Supports many language pairs",
                    cost_per_1k_tokens=0.004,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.TRANSLATE",
                    syntax_template="ML.TRANSLATE({input}, '{target_lang}')",
                    requires_model=False,
                    notes="Uses Cloud Translation API",
                    cost_per_1k_tokens=0.02,
                ),
            },
        )

        # Entity Extraction
        self._functions["entity_extraction"] = AIMLFunction(
            function_id="entity_extraction",
            category=AIMLFunctionCategory.EXTRACTION,
            name="Named Entity Extraction",
            description="Extract named entities (people, places, organizations) from text",
            sample_input="Apple CEO Tim Cook announced the new iPhone in Cupertino.",
            expected_output_type="array",
            latency_class="medium",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.CORTEX.EXTRACT_ANSWER",
                    syntax_template="SNOWFLAKE.CORTEX.EXTRACT_ANSWER({input}, '{question}')",
                    requires_model=False,
                    notes="Uses question-based extraction",
                    cost_per_1k_tokens=0.003,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.UNDERSTAND_TEXT",
                    syntax_template="ML.UNDERSTAND_TEXT(MODEL `{model}`, (SELECT {input} AS text_content), STRUCT('EXTRACT_ENTITIES' AS nlu_option))",
                    requires_model=True,
                    default_model="entity_extractor",
                    notes="Extracts predefined entity types",
                    cost_per_1k_tokens=0.004,
                ),
                "databricks": PlatformSupport(
                    platform="databricks",
                    function_name="ai_extract",
                    syntax_template="ai_extract({input}, ARRAY({entity_types}))",
                    requires_model=False,
                    min_version="14.0",
                    notes="Built-in AI function",
                    cost_per_1k_tokens=0.003,
                ),
            },
        )

        # Anomaly Detection (ML/Prediction)
        self._functions["anomaly_detection"] = AIMLFunction(
            function_id="anomaly_detection",
            category=AIMLFunctionCategory.PREDICTION,
            name="Anomaly Detection",
            description="Detect anomalies in numerical data",
            sample_input="[100, 102, 98, 99, 500, 101, 97]",
            expected_output_type="boolean",
            latency_class="low",
            platforms={
                "snowflake": PlatformSupport(
                    platform="snowflake",
                    function_name="SNOWFLAKE.ML.ANOMALY_DETECTION",
                    syntax_template="SELECT * FROM TABLE(SNOWFLAKE.ML.ANOMALY_DETECTION!DETECT_ANOMALIES(INPUT_DATA => {input_table}, TIMESTAMP_COLNAME => '{ts_col}', TARGET_COLNAME => '{target_col}'))",
                    requires_model=True,
                    default_model="ANOMALY_DETECTION",
                    notes="Time-series anomaly detection",
                    cost_per_1k_tokens=0.001,
                ),
                "bigquery": PlatformSupport(
                    platform="bigquery",
                    function_name="ML.DETECT_ANOMALIES",
                    syntax_template="ML.DETECT_ANOMALIES(MODEL `{model}`, (SELECT * FROM {input_table}), STRUCT(0.01 AS contamination))",
                    requires_model=True,
                    default_model="anomaly_model",
                    notes="Requires trained anomaly detection model",
                    cost_per_1k_tokens=0.002,
                ),
            },
        )

    def get_function(self, function_id: str) -> AIMLFunction | None:
        """Get a function by ID."""
        return self._functions.get(function_id)

    def get_all_functions(self) -> dict[str, AIMLFunction]:
        """Get all registered functions."""
        return self._functions.copy()

    def get_functions_by_category(self, category: AIMLFunctionCategory) -> list[AIMLFunction]:
        """Get all functions in a category."""
        return [f for f in self._functions.values() if f.category == category]

    def get_functions_for_platform(self, platform: str) -> list[AIMLFunction]:
        """Get all functions supported on a platform."""
        platform_lower = platform.lower()
        return [f for f in self._functions.values() if f.is_supported_on(platform_lower)]

    def get_supported_platforms(self) -> set[str]:
        """Get all platforms with AI/ML function support."""
        platforms: set[str] = set()
        for func in self._functions.values():
            platforms.update(func.platforms.keys())
        return platforms

    def get_categories(self) -> list[AIMLFunctionCategory]:
        """Get all function categories."""
        return list(AIMLFunctionCategory)

    def export_registry(self) -> dict[str, Any]:
        """Export the registry as a dictionary."""
        return {
            "functions": {func_id: func.to_dict() for func_id, func in self._functions.items()},
            "platforms": list(self.get_supported_platforms()),
            "categories": [c.value for c in self.get_categories()],
        }
