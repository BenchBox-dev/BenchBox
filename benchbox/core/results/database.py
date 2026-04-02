"""Historical result database for time-series analysis and ranking.

This module provides SQLite-based storage for benchmark results, enabling:
- Historical tracking and time-series analysis
- Performance trend detection and regression alerts
- Automated platform rankings
- Year-over-year comparisons

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchbox.core.results.models import BenchmarkResults

logger = logging.getLogger(__name__)

# Default database location
DEFAULT_DB_PATH = Path.home() / ".benchbox" / "results.db"

# Schema version for migrations
SCHEMA_VERSION = 1
_RANKING_METRIC_CONFIG = {
    "geometric_mean": ("geometric_mean_ms", "ASC"),
    "power_at_size": ("power_at_size", "DESC"),
    "cost_efficiency": ("total_cost / NULLIF(successful_queries, 0)", "ASC"),
}


@dataclass
class StoredResult:
    """A result stored in the database."""

    id: int
    execution_id: str
    platform: str
    platform_version: str | None
    benchmark: str
    scale_factor: float
    timestamp: datetime
    duration_seconds: float
    total_queries: int
    successful_queries: int
    failed_queries: int
    geometric_mean_ms: float | None
    power_at_size: float | None
    throughput_at_size: float | None
    qph_at_size: float | None
    total_cost: float | None
    validation_status: str
    config_hash: str
    metadata: dict[str, Any]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> StoredResult:
        """Create StoredResult from database row."""
        return cls(
            id=row["id"],
            execution_id=row["execution_id"],
            platform=row["platform"],
            platform_version=row["platform_version"],
            benchmark=row["benchmark"],
            scale_factor=row["scale_factor"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            duration_seconds=row["duration_seconds"],
            total_queries=row["total_queries"],
            successful_queries=row["successful_queries"],
            failed_queries=row["failed_queries"],
            geometric_mean_ms=row["geometric_mean_ms"],
            power_at_size=row["power_at_size"],
            throughput_at_size=row["throughput_at_size"],
            qph_at_size=row["qph_at_size"],
            total_cost=row["total_cost"],
            validation_status=row["validation_status"],
            config_hash=row["config_hash"],
            metadata=json.loads(row["metadata_json"]) if row["metadata_json"] else {},
        )


@dataclass
class StoredQuery:
    """A query result stored in the database."""

    id: int
    result_id: int
    query_id: str
    stream_id: str | None
    execution_order: int
    execution_time_ms: float
    status: str
    rows_returned: int | None
    cost: float | None
    iteration: int | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> StoredQuery:
        """Create StoredQuery from database row."""
        return cls(
            id=row["id"],
            result_id=row["result_id"],
            query_id=row["query_id"],
            stream_id=row["stream_id"],
            execution_order=row["execution_order"],
            execution_time_ms=row["execution_time_ms"],
            status=row["status"],
            rows_returned=row["rows_returned"],
            cost=row["cost"],
            iteration=row["iteration"],
        )


@dataclass
class PlatformRanking:
    """Platform ranking for a specific benchmark and metric."""

    rank: int
    platform: str
    platform_version: str | None
    benchmark: str
    scale_factor: float
    score: float
    sample_count: int
    latest_timestamp: datetime
    trend: str  # "up", "down", "stable", "new"
    trend_change: float | None  # Percentage change from previous period


@dataclass
class PerformanceTrend:
    """Performance trend for a platform over time."""

    platform: str
    benchmark: str
    scale_factor: float
    period_start: datetime
    period_end: datetime
    avg_geometric_mean_ms: float
    min_geometric_mean_ms: float
    max_geometric_mean_ms: float
    sample_count: int
    change_pct: float | None  # Change from previous period
    is_regression: bool  # True if >10% slowdown


@dataclass
class RankingConfig:
    """Configuration for ranking calculations."""

    metric: str = "geometric_mean"  # geometric_mean, power_at_size, cost_efficiency
    min_samples: int = 1  # Minimum samples to include in ranking
    lookback_days: int = 90  # Only consider results from last N days
    require_success: bool = True  # Only include successful runs


class ResultDatabase:
    """SQLite database for historical benchmark results.

    Provides storage, retrieval, and analysis of benchmark results including:
    - Result storage with deduplication
    - Time-series queries
    - Performance trend detection
    - Platform ranking calculations
    """

    def __init__(self, db_path: Path | str | None = None):
        """Initialize the result database.

        Args:
            db_path: Path to SQLite database file. Uses default if None.
        """
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        """Get a database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self) -> None:
        """Initialize or migrate database schema."""
        with self._connection() as conn:
            cursor = conn.cursor()

            # Check current schema version
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY
                )
            """
            )

            cursor.execute("SELECT version FROM schema_version LIMIT 1")
            row = cursor.fetchone()
            current_version = row[0] if row else 0

            if current_version < SCHEMA_VERSION:
                self._create_tables(cursor)
                cursor.execute("DELETE FROM schema_version")
                cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)",
                    (SCHEMA_VERSION,),
                )
                conn.commit()
                logger.info(f"Database schema initialized at version {SCHEMA_VERSION}")

    def _create_tables(self, cursor: sqlite3.Cursor) -> None:
        """Create all database tables."""
        # Main results table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                execution_id TEXT UNIQUE NOT NULL,
                platform TEXT NOT NULL,
                platform_version TEXT,
                benchmark TEXT NOT NULL,
                scale_factor REAL NOT NULL,
                timestamp TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                total_queries INTEGER NOT NULL,
                successful_queries INTEGER NOT NULL,
                failed_queries INTEGER NOT NULL,
                geometric_mean_ms REAL,
                power_at_size REAL,
                throughput_at_size REAL,
                qph_at_size REAL,
                total_cost REAL,
                validation_status TEXT NOT NULL,
                config_hash TEXT NOT NULL,
                metadata_json TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """
        )

        # Query results table
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS queries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                result_id INTEGER NOT NULL,
                query_id TEXT NOT NULL,
                stream_id TEXT,
                execution_order INTEGER NOT NULL,
                execution_time_ms REAL NOT NULL,
                status TEXT NOT NULL,
                rows_returned INTEGER,
                cost REAL,
                iteration INTEGER,
                FOREIGN KEY (result_id) REFERENCES results(id) ON DELETE CASCADE
            )
        """
        )

        # Platforms table for version tracking
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS platforms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                version TEXT,
                config_hash TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                UNIQUE(name, version, config_hash)
            )
        """
        )

        # Create indexes for common queries
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_platform ON results(platform)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_benchmark ON results(benchmark)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_results_timestamp ON results(timestamp)")
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_results_platform_benchmark ON results(platform, benchmark, scale_factor)"
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queries_result ON queries(result_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_queries_query_id ON queries(query_id)")

    def _compute_config_hash(self, result: BenchmarkResults) -> str:
        """Compute a hash of the configuration for deduplication."""
        config_data = {
            "platform": result.platform,
            "benchmark": result.benchmark_name,
            "scale_factor": result.scale_factor,
            "tunings": result.tunings_applied or {},
        }
        config_str = json.dumps(config_data, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()[:16]

    def store_result(self, result: BenchmarkResults) -> int:
        """Store a benchmark result in the database.

        Args:
            result: BenchmarkResults to store

        Returns:
            Database ID of the stored result

        Raises:
            ValueError: If result with same execution_id already exists
        """
        config_hash = self._compute_config_hash(result)

        # Extract platform version
        platform_version = None
        if result.platform_info:
            platform_version = result.platform_info.get("platform_version")

        # Extract cost
        total_cost = None
        if result.cost_summary:
            total_cost = result.cost_summary.get("total_cost")

        # Build metadata
        metadata = {
            "system_profile": result.system_profile,
            "platform_info": result.platform_info,
            "tunings_applied": result.tunings_applied,
            "test_execution_type": result.test_execution_type,
        }

        with self._connection() as conn:
            cursor = conn.cursor()

            # Check for duplicate
            cursor.execute(
                "SELECT id FROM results WHERE execution_id = ?",
                (result.execution_id,),
            )
            if cursor.fetchone():
                raise ValueError(f"Result with execution_id '{result.execution_id}' already exists")

            # Convert geometric_mean from seconds to milliseconds for storage
            geometric_mean_ms = None
            if result.geometric_mean_execution_time is not None:
                geometric_mean_ms = result.geometric_mean_execution_time * 1000.0

            # Insert result
            cursor.execute(
                """
                INSERT INTO results (
                    execution_id, platform, platform_version, benchmark, scale_factor,
                    timestamp, duration_seconds, total_queries, successful_queries,
                    failed_queries, geometric_mean_ms, power_at_size, throughput_at_size,
                    qph_at_size, total_cost, validation_status, config_hash, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    result.execution_id,
                    result.platform,
                    platform_version,
                    result.benchmark_name,
                    result.scale_factor,
                    result.timestamp.isoformat(),
                    result.duration_seconds,
                    result.total_queries,
                    result.successful_queries,
                    result.failed_queries,
                    geometric_mean_ms,
                    result.power_at_size,
                    result.throughput_at_size,
                    result.qph_at_size,
                    total_cost,
                    result.validation_status,
                    config_hash,
                    json.dumps(metadata),
                ),
            )
            result_id = cursor.lastrowid

            # Insert query results
            if result.execution_phases and result.execution_phases.power_test:
                for execution in result.execution_phases.power_test.query_executions:
                    cursor.execute(
                        """
                        INSERT INTO queries (
                            result_id, query_id, stream_id, execution_order,
                            execution_time_ms, status, rows_returned, cost, iteration
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                        (
                            result_id,
                            execution.query_id,
                            execution.stream_id,
                            execution.execution_order,
                            execution.execution_time_ms,
                            execution.status,
                            execution.rows_returned,
                            execution.cost,
                            execution.iteration,
                        ),
                    )

            # Update platforms table
            cursor.execute(
                """
                INSERT INTO platforms (name, version, config_hash, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name, version, config_hash)
                DO UPDATE SET last_seen = excluded.last_seen
            """,
                (
                    result.platform,
                    platform_version,
                    config_hash,
                    result.timestamp.isoformat(),
                    result.timestamp.isoformat(),
                ),
            )

            conn.commit()
            logger.info(f"Stored result {result.execution_id} for {result.platform}/{result.benchmark_name}")
            return result_id

    def get_result(self, execution_id: str) -> StoredResult | None:
        """Get a result by execution ID.

        Args:
            execution_id: Unique execution identifier

        Returns:
            StoredResult or None if not found
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM results WHERE execution_id = ?",
                (execution_id,),
            )
            row = cursor.fetchone()
            return StoredResult.from_row(row) if row else None

    def get_result_by_id(self, result_id: int) -> StoredResult | None:
        """Get a result by database ID.

        Args:
            result_id: Database ID

        Returns:
            StoredResult or None if not found
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM results WHERE id = ?", (result_id,))
            row = cursor.fetchone()
            return StoredResult.from_row(row) if row else None

    def get_queries(self, result_id: int) -> list[StoredQuery]:
        """Get all queries for a result.

        Args:
            result_id: Database ID of the result

        Returns:
            List of StoredQuery objects
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM queries WHERE result_id = ? ORDER BY execution_order",
                (result_id,),
            )
            return [StoredQuery.from_row(row) for row in cursor.fetchall()]

    def query_results(
        self,
        platform: str | None = None,
        benchmark: str | None = None,
        scale_factor: float | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        validation_status: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> list[StoredResult]:
        """Query results with filters.

        Args:
            platform: Filter by platform name
            benchmark: Filter by benchmark name
            scale_factor: Filter by scale factor
            start_date: Filter results after this date
            end_date: Filter results before this date
            validation_status: Filter by validation status
            limit: Maximum results to return
            offset: Number of results to skip

        Returns:
            List of matching StoredResult objects
        """
        conditions = []
        params: list[Any] = []

        if platform:
            conditions.append("platform = ?")
            params.append(platform)
        if benchmark:
            conditions.append("benchmark = ?")
            params.append(benchmark)
        if scale_factor is not None:
            conditions.append("scale_factor = ?")
            params.append(scale_factor)
        if start_date:
            conditions.append("timestamp >= ?")
            params.append(start_date.isoformat())
        if end_date:
            conditions.append("timestamp <= ?")
            params.append(end_date.isoformat())
        if validation_status:
            conditions.append("validation_status = ?")
            params.append(validation_status)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.extend([limit, offset])

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT * FROM results
                WHERE {where_clause}
                ORDER BY timestamp DESC
                LIMIT ? OFFSET ?
            """,
                params,
            )
            return [StoredResult.from_row(row) for row in cursor.fetchall()]

    def count_results(
        self,
        platform: str | None = None,
        benchmark: str | None = None,
    ) -> int:
        """Count results matching filters.

        Args:
            platform: Filter by platform name
            benchmark: Filter by benchmark name

        Returns:
            Number of matching results
        """
        conditions = []
        params: list[Any] = []

        if platform:
            conditions.append("platform = ?")
            params.append(platform)
        if benchmark:
            conditions.append("benchmark = ?")
            params.append(benchmark)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM results WHERE {where_clause}",
                params,
            )
            return cursor.fetchone()[0]

    def get_platforms(self) -> list[str]:
        """Get list of all platforms in the database.

        Returns:
            List of platform names
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT platform FROM results ORDER BY platform")
            return [row[0] for row in cursor.fetchall()]

    def get_benchmarks(self) -> list[str]:
        """Get list of all benchmarks in the database.

        Returns:
            List of benchmark names
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT benchmark FROM results ORDER BY benchmark")
            return [row[0] for row in cursor.fetchall()]

    def delete_result(self, execution_id: str) -> bool:
        """Delete a result by execution ID.

        Args:
            execution_id: Unique execution identifier

        Returns:
            True if deleted, False if not found
        """
        with self._connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM results WHERE execution_id = ?",
                (execution_id,),
            )
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(f"Deleted result {execution_id}")
            return deleted

    def calculate_rankings(
        self,
        benchmark: str,
        scale_factor: float,
        config: RankingConfig | None = None,
    ) -> list[PlatformRanking]:
        """Calculate platform rankings for a benchmark.

        Args:
            benchmark: Benchmark name
            scale_factor: Scale factor
            config: Ranking configuration

        Returns:
            List of PlatformRanking sorted by rank
        """
        config = config or RankingConfig()

        # Calculate cutoff date
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta

        cutoff = cutoff - timedelta(days=config.lookback_days)

        with self._connection() as conn:
            cursor = conn.cursor()

            # Build query based on metric
            metric_col, order = _RANKING_METRIC_CONFIG.get(config.metric, _RANKING_METRIC_CONFIG["geometric_mean"])

            validation_filter = ""
            if config.require_success:
                validation_filter = "AND validation_status = 'PASSED'"

            # Get current period rankings
            cursor.execute(
                f"""
                SELECT
                    platform,
                    platform_version,
                    AVG({metric_col}) as avg_score,
                    COUNT(*) as sample_count,
                    MAX(timestamp) as latest_timestamp
                FROM results
                WHERE benchmark = ?
                    AND scale_factor = ?
                    AND timestamp >= ?
                    AND {metric_col} IS NOT NULL
                    {validation_filter}
                GROUP BY platform, platform_version
                HAVING COUNT(*) >= ?
                ORDER BY avg_score {order}
            """,
                (benchmark, scale_factor, cutoff.isoformat(), config.min_samples),
            )

            current_results = cursor.fetchall()

            # Get previous period for trend calculation
            prev_cutoff = cutoff - timedelta(days=config.lookback_days)
            cursor.execute(
                f"""
                SELECT
                    platform,
                    AVG({metric_col}) as avg_score
                FROM results
                WHERE benchmark = ?
                    AND scale_factor = ?
                    AND timestamp >= ?
                    AND timestamp < ?
                    AND {metric_col} IS NOT NULL
                    {validation_filter}
                GROUP BY platform
            """,
                (
                    benchmark,
                    scale_factor,
                    prev_cutoff.isoformat(),
                    cutoff.isoformat(),
                ),
            )

            previous_scores = {row["platform"]: row["avg_score"] for row in cursor.fetchall()}

            # Build rankings
            rankings = []
            for rank, row in enumerate(current_results, 1):
                platform = row["platform"]
                current_score = row["avg_score"]
                prev_score = previous_scores.get(platform)
                trend, trend_change = self._calculate_ranking_trend(current_score, prev_score, config.metric)

                rankings.append(
                    PlatformRanking(
                        rank=rank,
                        platform=platform,
                        platform_version=row["platform_version"],
                        benchmark=benchmark,
                        scale_factor=scale_factor,
                        score=current_score,
                        sample_count=row["sample_count"],
                        latest_timestamp=datetime.fromisoformat(row["latest_timestamp"]),
                        trend=trend,
                        trend_change=trend_change,
                    )
                )

            return rankings

    @staticmethod
    def _calculate_ranking_trend(
        current_score: float,
        previous_score: float | None,
        metric: str,
    ) -> tuple[str, float | None]:
        """Determine the trend between the current and previous ranking windows."""
        if previous_score is None:
            return "new", None
        if previous_score == 0:
            return "stable", 0.0

        change_pct = ((current_score - previous_score) / previous_score) * 100
        if metric in ("geometric_mean", "cost_efficiency"):
            if change_pct < -5:
                return "up", change_pct
            if change_pct > 5:
                return "down", change_pct
            return "stable", change_pct

        if change_pct > 5:
            return "up", change_pct
        if change_pct < -5:
            return "down", change_pct
        return "stable", change_pct

    def get_performance_trends(
        self,
        platform: str,
        benchmark: str,
        scale_factor: float,
        periods: int = 6,
        period_days: int = 30,
    ) -> list[PerformanceTrend]:
        """Get performance trends for a platform over time.

        Args:
            platform: Platform name
            benchmark: Benchmark name
            scale_factor: Scale factor
            periods: Number of periods to analyze
            period_days: Days per period

        Returns:
            List of PerformanceTrend objects, newest first
        """
        from datetime import timedelta

        now = datetime.now(timezone.utc)
        trends = []

        with self._connection() as conn:
            cursor = conn.cursor()

            for i in range(periods):
                period_end = now - timedelta(days=i * period_days)
                period_start = period_end - timedelta(days=period_days)

                cursor.execute(
                    """
                    SELECT
                        AVG(geometric_mean_ms) as avg_gm,
                        MIN(geometric_mean_ms) as min_gm,
                        MAX(geometric_mean_ms) as max_gm,
                        COUNT(*) as sample_count
                    FROM results
                    WHERE platform = ?
                        AND benchmark = ?
                        AND scale_factor = ?
                        AND timestamp >= ?
                        AND timestamp < ?
                        AND geometric_mean_ms IS NOT NULL
                        AND validation_status = 'PASSED'
                """,
                    (
                        platform,
                        benchmark,
                        scale_factor,
                        period_start.isoformat(),
                        period_end.isoformat(),
                    ),
                )

                row = cursor.fetchone()

                if row["sample_count"] == 0:
                    continue

                trends.append(
                    PerformanceTrend(
                        platform=platform,
                        benchmark=benchmark,
                        scale_factor=scale_factor,
                        period_start=period_start,
                        period_end=period_end,
                        avg_geometric_mean_ms=row["avg_gm"],
                        min_geometric_mean_ms=row["min_gm"],
                        max_geometric_mean_ms=row["max_gm"],
                        sample_count=row["sample_count"],
                        change_pct=None,  # Calculated below
                        is_regression=False,  # Calculated below
                    )
                )

        # Calculate period-over-period changes
        for i in range(len(trends) - 1):
            current = trends[i]
            previous = trends[i + 1]
            if previous.avg_geometric_mean_ms > 0:
                change = (
                    (current.avg_geometric_mean_ms - previous.avg_geometric_mean_ms) / previous.avg_geometric_mean_ms
                ) * 100
                trends[i] = PerformanceTrend(
                    platform=current.platform,
                    benchmark=current.benchmark,
                    scale_factor=current.scale_factor,
                    period_start=current.period_start,
                    period_end=current.period_end,
                    avg_geometric_mean_ms=current.avg_geometric_mean_ms,
                    min_geometric_mean_ms=current.min_geometric_mean_ms,
                    max_geometric_mean_ms=current.max_geometric_mean_ms,
                    sample_count=current.sample_count,
                    change_pct=change,
                    is_regression=change > 10,  # >10% slowdown
                )

        return trends

    def detect_regressions(
        self,
        threshold_pct: float = 10.0,
        lookback_days: int = 30,
    ) -> list[PerformanceTrend]:
        """Detect performance regressions across all platforms.

        Args:
            threshold_pct: Percentage slowdown to consider a regression
            lookback_days: Compare current period to this many days ago

        Returns:
            List of PerformanceTrend objects where regression was detected
        """
        regressions = []

        platforms = self.get_platforms()
        benchmarks = self.get_benchmarks()

        for platform in platforms:
            for benchmark in benchmarks:
                # Get scale factors for this combination
                with self._connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute(
                        """
                        SELECT DISTINCT scale_factor
                        FROM results
                        WHERE platform = ? AND benchmark = ?
                    """,
                        (platform, benchmark),
                    )
                    scale_factors = [row[0] for row in cursor.fetchall()]

                for sf in scale_factors:
                    trends = self.get_performance_trends(platform, benchmark, sf, periods=2, period_days=lookback_days)

                    for trend in trends:
                        if trend.is_regression and trend.change_pct and trend.change_pct > threshold_pct:
                            regressions.append(trend)

        return regressions

    def get_summary_stats(self) -> dict[str, Any]:
        """Get summary statistics for the database.

        Returns:
            Dictionary with summary stats
        """
        with self._connection() as conn:
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(*) FROM results")
            total_results = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM queries")
            total_queries = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT platform) FROM results")
            unique_platforms = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT benchmark) FROM results")
            unique_benchmarks = cursor.fetchone()[0]

            cursor.execute("SELECT MIN(timestamp), MAX(timestamp) FROM results")
            row = cursor.fetchone()
            earliest = row[0]
            latest = row[1]

            return {
                "total_results": total_results,
                "total_queries": total_queries,
                "unique_platforms": unique_platforms,
                "unique_benchmarks": unique_benchmarks,
                "earliest_result": earliest,
                "latest_result": latest,
                "database_path": str(self.db_path),
                "schema_version": SCHEMA_VERSION,
            }

    def import_results_from_directory(
        self,
        directory: Path,
        pattern: str = "**/*.json",
    ) -> tuple[int, int]:
        """Import results from JSON files in a directory.

        Args:
            directory: Directory containing result files
            pattern: Glob pattern for files

        Returns:
            Tuple of (imported_count, skipped_count)
        """
        from benchbox.core.results.loader import load_result_file

        imported = 0
        skipped = 0

        for file_path in directory.glob(pattern):
            try:
                result, _ = load_result_file(file_path)
                self.store_result(result)
                imported += 1
            except ValueError as e:
                if "already exists" in str(e):
                    skipped += 1
                else:
                    logger.warning(f"Failed to import {file_path}: {e}")
                    skipped += 1
            except Exception as e:
                logger.warning(f"Failed to import {file_path}: {e}")
                skipped += 1

        return imported, skipped
