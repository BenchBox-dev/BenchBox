# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.base import BaseBenchmark

from .evaluator import AccuracyMetrics, NL2SQLEvaluator, SQLComparisonResult, SQLMatchType
from .queries import NL2SQLQuery, NL2SQLQueryCategory, NL2SQLQueryManager, QueryDifficulty

if TYPE_CHECKING:
    from benchbox.core.connection import DatabaseConnection

logger = logging.getLogger(__name__)


PLATFORM_NL2SQL_PROMPTS: dict[str, dict[str, str]] = {
    "snowflake": {
        "system": """You are a SQL expert. Generate valid Snowflake SQL based on the user's natural language query.
Only output the SQL query, nothing else. Do not include explanations or markdown formatting.""",
        "template": """Given the following database schema:
{schema}

Convert this natural language query to SQL:
{question}

SQL:""",
        "function": "SNOWFLAKE.CORTEX.COMPLETE",
        "model": "mistral-large",
    },
    "bigquery": {
        "system": """You are a SQL expert. Generate valid BigQuery SQL based on the user's natural language query.
Only output the SQL query, nothing else. Do not include explanations or markdown formatting.""",
        "template": """Given the following database schema:
{schema}

Convert this natural language query to SQL:
{question}

SQL:""",
        "function": "ML.GENERATE_TEXT",
        "model": "gemini-pro",
    },
    "databricks": {
        "system": """You are a SQL expert. Generate valid Spark SQL based on the user's natural language query.
Only output the SQL query, nothing else. Do not include explanations or markdown formatting.""",
        "template": """Given the following database schema:
{schema}

Convert this natural language query to SQL:
{question}

SQL:""",
        "function": "ai_query",
        "model": "databricks-meta-llama-3-1-70b-instruct",
    },
}


@dataclass
class NL2SQLQueryResult:
    query_id: str
    natural_language: str
    generated_sql: str
    expected_sql: str
    platform: str
    success: bool
    match_type: SQLMatchType
    generation_time_ms: float
    execution_time_ms: float = 0.0
    error_message: str = ""
    tokens_used: int = 0
    cost_estimated: float = 0.0
    comparison: SQLComparisonResult | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_id": self.query_id,
            "natural_language": self.natural_language,
            "generated_sql": self.generated_sql,
            "expected_sql": self.expected_sql,
            "platform": self.platform,
            "success": self.success,
            "match_type": self.match_type.value,
            "generation_time_ms": self.generation_time_ms,
            "execution_time_ms": self.execution_time_ms,
            "error_message": self.error_message,
            "tokens_used": self.tokens_used,
            "cost_estimated": self.cost_estimated,
            "comparison": self.comparison.to_dict() if self.comparison else None,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class NL2SQLBenchmarkResults:
    platform: str
    started_at: datetime
    completed_at: datetime | None = None
    query_results: list[NL2SQLQueryResult] = field(default_factory=list)
    accuracy_metrics: AccuracyMetrics = field(default_factory=AccuracyMetrics)
    total_generation_time_ms: float = 0.0
    total_execution_time_ms: float = 0.0
    total_cost_estimated: float = 0.0
    difficulty_breakdown: dict[str, AccuracyMetrics] = field(default_factory=dict)
    category_breakdown: dict[str, AccuracyMetrics] = field(default_factory=dict)

    def add_result(self, result: NL2SQLQueryResult) -> None:
        self.query_results.append(result)
        self.accuracy_metrics.add_result(result.match_type)
        self.total_generation_time_ms += result.generation_time_ms
        self.total_execution_time_ms += result.execution_time_ms
        self.total_cost_estimated += result.cost_estimated

    def add_difficulty_result(self, difficulty: QueryDifficulty, match_type: SQLMatchType) -> None:
        key = difficulty.value
        if key not in self.difficulty_breakdown:
            self.difficulty_breakdown[key] = AccuracyMetrics()
        self.difficulty_breakdown[key].add_result(match_type)

    def add_category_result(self, category: NL2SQLQueryCategory, match_type: SQLMatchType) -> None:
        key = category.value
        if key not in self.category_breakdown:
            self.category_breakdown[key] = AccuracyMetrics()
        self.category_breakdown[key].add_result(match_type)

    def complete(self) -> None:
        self.completed_at = datetime.now(timezone.utc)

    @property
    def avg_generation_time_ms(self) -> float:
        n = len(self.query_results)
        return self.total_generation_time_ms / n if n > 0 else 0.0

    @property
    def avg_execution_time_ms(self) -> float:
        n = len(self.query_results)
        return self.total_execution_time_ms / n if n > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "accuracy_metrics": self.accuracy_metrics.to_dict(),
            "total_generation_time_ms": self.total_generation_time_ms,
            "total_execution_time_ms": self.total_execution_time_ms,
            "avg_generation_time_ms": self.avg_generation_time_ms,
            "avg_execution_time_ms": self.avg_execution_time_ms,
            "total_cost_estimated": self.total_cost_estimated,
            "difficulty_breakdown": {k: v.to_dict() for k, v in self.difficulty_breakdown.items()},
            "category_breakdown": {k: v.to_dict() for k, v in self.category_breakdown.items()},
            "query_results": [r.to_dict() for r in self.query_results],
        }


class NL2SQLBenchmark(BaseBenchmark):
    SUPPORTED_PLATFORMS = {"snowflake", "bigquery", "databricks"}

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | str | None = None,
        execute_validation: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(scale_factor, output_dir, **kwargs)

        self._name = "Natural Language to SQL Testing Framework"
        self._version = "1.0"
        self._description = (
            "Tests NL2SQL capabilities of platforms with AI query generation features. "
            "Measures accuracy, latency, and cost of natural language query interfaces."
        )

        self.query_manager = NL2SQLQueryManager()
        self.execute_validation = execute_validation

        self.token_costs = {
            "snowflake": 0.002,
            "bigquery": 0.001,
            "databricks": 0.003,
        }

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return self._description

    def get_supported_platforms(self) -> set[str]:
        return self.SUPPORTED_PLATFORMS.copy()

    def get_queries(self) -> dict[str, str]:
        return {qid: q.natural_language for qid, q in self.query_manager.get_all_queries().items()}

    def get_query(self, query_id: int | str, *, params: dict[str, Any] | None = None) -> str:
        query = self.query_manager.get_query(str(query_id))
        if query is None:
            available = ", ".join(self.query_manager.get_query_ids())
            raise ValueError(f"Unknown query ID: {query_id}. Available: {available}")
        return query.natural_language

    def get_expected_sql(self, query_id: str) -> str:
        query = self.query_manager.get_query(query_id)
        if query is None:
            raise ValueError(f"Unknown query ID: {query_id}")
        return query.expected_sql

    def generate_data(self) -> list[str | Path]:
        logger.info("NL2SQL benchmark uses existing TPC-H style tables, no data generation needed")
        return []

    def get_queries_by_category(self, category: NL2SQLQueryCategory) -> list[NL2SQLQuery]:
        return self.query_manager.get_queries_by_category(category)

    def get_queries_by_difficulty(self, difficulty: QueryDifficulty) -> list[NL2SQLQuery]:
        return self.query_manager.get_queries_by_difficulty(difficulty)

    def get_categories(self) -> list[NL2SQLQueryCategory]:
        return self.query_manager.get_categories()

    def get_difficulty_levels(self) -> list[QueryDifficulty]:
        return self.query_manager.get_difficulty_levels()

    def _build_nl2sql_prompt(
        self,
        query: NL2SQLQuery,
        platform: str,
    ) -> str:
        config = PLATFORM_NL2SQL_PROMPTS.get(platform.lower(), PLATFORM_NL2SQL_PROMPTS["snowflake"])
        template = config["template"]

        return template.format(
            schema=query.schema_context,
            question=query.natural_language,
        )

    def _build_platform_sql(
        self,
        query: NL2SQLQuery,
        platform: str,
    ) -> str:
        config = PLATFORM_NL2SQL_PROMPTS.get(platform.lower())
        if config is None:
            raise ValueError(f"Unsupported platform: {platform}")

        prompt = self._build_nl2sql_prompt(query, platform)
        system_prompt = config["system"]
        function = config["function"]
        model = config["model"]

        if platform.lower() == "snowflake":
            return f"""
SELECT {function}(
    '{model}',
    CONCAT(
        '{system_prompt}

',
        $${prompt}$$
    )
) AS generated_sql
"""
        elif platform.lower() == "bigquery":
            return f"""
SELECT *
FROM {function}(
    MODEL `{model}`,
    (SELECT $${system_prompt}

{prompt}$$ AS prompt),
    STRUCT(500 AS max_output_tokens, 0.1 AS temperature)
)
"""
        elif platform.lower() == "databricks":
            return f"""
SELECT {function}(
    '{model}',
    $${system_prompt}

{prompt}$$
) AS generated_sql
"""
        else:
            raise ValueError(f"Unsupported platform: {platform}")

    def _extract_generated_sql(
        self,
        result: Any,
        platform: str,
    ) -> str:
        if result is None or len(result) == 0:
            return ""

        row = result[0]

        if isinstance(row, dict):
            sql = row.get("generated_sql") or row.get("ml_generate_text_result") or row.get("text") or ""
        elif isinstance(row, (list, tuple)):
            sql = str(row[0]) if len(row) > 0 else ""
        else:
            sql = str(row)

        sql = sql.strip()

        if sql.startswith("```sql"):
            sql = sql[6:]
        elif sql.startswith("```"):
            sql = sql[3:]
        if sql.endswith("```"):
            sql = sql[:-3]

        return sql.strip()

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def evaluate_nl2sql(
        self,
        connection: DatabaseConnection,
        query_id: str,
        platform: str | None = None,
        timeout_seconds: int | None = None,
    ) -> NL2SQLQueryResult:
        query = self.query_manager.get_query(query_id)
        if query is None:
            return NL2SQLQueryResult(
                query_id=query_id,
                natural_language="",
                generated_sql="",
                expected_sql="",
                platform=platform or "unknown",
                success=False,
                match_type=SQLMatchType.ERROR,
                generation_time_ms=0.0,
                error_message=f"Unknown query ID: {query_id}",
            )

        if platform is None:
            platform = getattr(connection, "platform", "unknown")

        platform_lower = platform.lower()
        if platform_lower not in self.SUPPORTED_PLATFORMS:
            return NL2SQLQueryResult(
                query_id=query_id,
                natural_language=query.natural_language,
                generated_sql="",
                expected_sql=query.expected_sql,
                platform=platform,
                success=False,
                match_type=SQLMatchType.ERROR,
                generation_time_ms=0.0,
                error_message=f"Unsupported platform: {platform}",
            )

        nl2sql_sql = self._build_platform_sql(query, platform_lower)

        start_time = time.perf_counter()
        try:
            cursor = connection.execute(nl2sql_sql.strip())
            result = cursor.fetchall() if hasattr(cursor, "fetchall") else []
            generation_time_ms = (time.perf_counter() - start_time) * 1000

            generated_sql = self._extract_generated_sql(result, platform_lower)

        except Exception as e:
            generation_time_ms = (time.perf_counter() - start_time) * 1000
            return NL2SQLQueryResult(
                query_id=query_id,
                natural_language=query.natural_language,
                generated_sql="",
                expected_sql=query.expected_sql,
                platform=platform,
                success=False,
                match_type=SQLMatchType.ERROR,
                generation_time_ms=generation_time_ms,
                error_message=f"NL2SQL generation failed: {str(e)}",
            )

        evaluator = NL2SQLEvaluator(
            connection=connection if self.execute_validation else None,
            case_sensitive=False,
            ignore_whitespace=True,
        )

        comparison = evaluator.compare(
            generated_sql,
            query.expected_sql,
            execute=self.execute_validation,
        )

        prompt = self._build_nl2sql_prompt(query, platform_lower)
        input_tokens = self._estimate_tokens(prompt)
        output_tokens = self._estimate_tokens(generated_sql)
        total_tokens = input_tokens + output_tokens
        cost = (total_tokens / 1000) * self.token_costs.get(platform_lower, 0.002)

        return NL2SQLQueryResult(
            query_id=query_id,
            natural_language=query.natural_language,
            generated_sql=generated_sql,
            expected_sql=query.expected_sql,
            platform=platform,
            success=comparison.match_type in {SQLMatchType.EXACT, SQLMatchType.SEMANTIC},
            match_type=comparison.match_type,
            generation_time_ms=generation_time_ms,
            execution_time_ms=0.0,
            error_message=comparison.error_message,
            tokens_used=total_tokens,
            cost_estimated=cost,
            comparison=comparison,
        )

    def run_benchmark(
        self,
        connection: DatabaseConnection,
        platform: str | None = None,
        query_ids: list[str] | None = None,
        categories: list[NL2SQLQueryCategory] | None = None,
        difficulties: list[QueryDifficulty] | None = None,
    ) -> NL2SQLBenchmarkResults:
        if platform is None:
            platform = getattr(connection, "platform", "unknown")

        results = NL2SQLBenchmarkResults(
            platform=platform,
            started_at=datetime.now(timezone.utc),
        )

        if query_ids is not None:
            queries_to_run = [
                self.query_manager.get_query(qid) for qid in query_ids if self.query_manager.get_query(qid) is not None
            ]
        else:
            all_queries = list(self.query_manager.get_all_queries().values())

            if categories is not None:
                all_queries = [q for q in all_queries if q.category in categories]

            if difficulties is not None:
                all_queries = [q for q in all_queries if q.difficulty in difficulties]

            queries_to_run = all_queries

        for query in queries_to_run:
            if query is None:
                continue

            logger.info(f"Evaluating NL2SQL: {query.query_id}")
            result = self.evaluate_nl2sql(connection, query.query_id, platform)
            results.add_result(result)
            results.add_difficulty_result(query.difficulty, result.match_type)
            results.add_category_result(query.category, result.match_type)

            if result.success:
                logger.info(f"  ✓ {query.query_id}: {result.match_type.value} ({result.generation_time_ms:.2f}ms)")
            else:
                logger.warning(f"  ✗ {query.query_id}: {result.match_type.value}")
                if result.error_message:
                    logger.debug(f"    Error: {result.error_message}")

        results.complete()
        return results

    def export_benchmark_spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "supported_platforms": list(self.SUPPORTED_PLATFORMS),
            "categories": [c.value for c in NL2SQLQueryCategory],
            "difficulty_levels": [d.value for d in QueryDifficulty],
            "queries": self.query_manager.export_queries(),
            "platform_configs": {
                platform: {
                    "model": config["model"],
                    "function": config["function"],
                }
                for platform, config in PLATFORM_NL2SQL_PROMPTS.items()
            },
        }
