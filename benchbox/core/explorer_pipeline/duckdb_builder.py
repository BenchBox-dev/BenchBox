"""DuckDB snapshot builder for the results explorer.

Creates results.duckdb containing all canonical browser metric tables and views.
This file is loaded by DuckDB-WASM in the browser for filtering and analysis.

Also emits results_schema.json next to results.duckdb so the frontend column
picker doesn't need to hardcode _COLUMNS.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from benchbox.core.explorer_pipeline.compare_math import (
    speedup_vs_best as _speedup_vs_best,
    speedup_vs_slowest as _speedup_vs_slowest,
)
from benchbox.core.explorer_pipeline.models import (
    BenchmarkSummary,
    DetailResult,
    ManifestEntry,
    is_ranking_eligible,
)

logger = logging.getLogger(__name__)

# Type alias for the summary accumulator key: (benchmark, scale_factor, phase)
_SummaryKey = tuple[str, float, str]

# Keys that ``pipeline._build_meta_leaderboard`` contractually emits on every
# cohort platform row. ``_populate_cohort_metadata`` validates this contract
# before writing - a missing key is an upstream bug, not a nullable field.
_COHORT_PLATFORM_REQUIRED_KEYS = frozenset({"platform_id", "platform", "result_id", "short_id", "trust_label"})

# If this module grows further, consider splitting DDL (_create_schema,
# _create_views) from the ten _populate_* helpers into sibling modules
# ``duckdb_schema.py`` and ``duckdb_populate.py``. Kept cohesive for now so the
# ten-table contract stays readable in a single file.


class DuckDBSnapshotBuilder:
    """Builds results.duckdb from a collection of manifest entries."""

    # Ordered column definitions matching ManifestEntry fields exactly.
    # Used by the legacy build() method; kept for backward compatibility.
    _COLUMNS = [
        ("result_id", "VARCHAR"),
        ("benchmark", "VARCHAR"),
        ("scale_factor", "DOUBLE"),
        ("platform", "VARCHAR"),
        ("driver_version", "VARCHAR"),
        ("run_date", "VARCHAR"),
        ("power_score", "DOUBLE"),
        ("total_duration_s", "DOUBLE"),
        ("geomean_ms", "DOUBLE"),
        ("query_count", "INTEGER"),
        ("trust_label", "VARCHAR"),
        ("visibility", "VARCHAR"),
        ("platform_version", "VARCHAR"),
        ("execution_mode", "VARCHAR"),
        ("tuning_mode", "VARCHAR"),
        ("tuning_hash", "VARCHAR"),
        ("test_type", "VARCHAR"),
        ("validation_status", "VARCHAR"),
        ("cost_usd", "DOUBLE"),
    ]

    def build(self, entries: list[ManifestEntry], output_path: Path) -> None:
        """Create results.duckdb with a ``results`` table.

        Overwrites any existing file at *output_path*.

        Args:
            entries: List of ManifestEntry objects to persist.
            output_path: Destination path for the .duckdb file.
        """
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "duckdb is required for DuckDBSnapshotBuilder. Install the explorer dependency set with: uv sync --extra explorer"
            ) from exc

        col_names = [name for name, _ in self._COLUMNS]
        # Guard: _entry_to_tuple must return exactly as many values as _COLUMNS.
        # This assertion fires at build time if the two fall out of sync.
        _sentinel = self._entry_to_tuple(
            ManifestEntry(
                result_id="",
                benchmark="",
                scale_factor=0.0,
                platform="",
                driver_version=None,
                run_date="",
                power_score=None,
                total_duration_s=0.0,
                query_count=0,
                trust_label="",
                visibility="",
            )
        )
        if len(_sentinel) != len(col_names):
            raise AssertionError(
                f"_entry_to_tuple returns {len(_sentinel)} values but _COLUMNS has {len(col_names)} columns"
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove stale database so we always start clean.
        if output_path.exists():
            output_path.unlink()

        col_defs = ", ".join(f"{name} {dtype}" for name, dtype in self._COLUMNS)

        rows = [self._entry_to_tuple(e) for e in entries]

        with duckdb.connect(str(output_path)) as con:
            con.execute(f"CREATE TABLE results ({col_defs})")
            if rows:
                placeholders = ", ".join("?" * len(col_names))
                con.executemany(f"INSERT INTO results VALUES ({placeholders})", rows)

        logger.info("Wrote %d rows to %s", len(rows), output_path)

        schema_path = output_path.with_name("results_schema.json")
        schema = {"columns": [{"name": name, "type": dtype} for name, dtype in self._COLUMNS]}
        schema_path.write_text(json.dumps(schema, indent=2))
        logger.info("Wrote schema to %s", schema_path)

    def build_full(
        self,
        entries: list[ManifestEntry],
        details_map: dict[str, DetailResult],
        summaries: list[tuple[_SummaryKey, BenchmarkSummary]],
        short_id_map: dict[str, str],
        full_to_short: dict[str, str],
        meta: dict[str, Any],
        bundle_url_prefix: str,
        output_path: Path,
    ) -> None:
        """Build the canonical 10-table DuckDB browser store.

        Creates all tables and views defined in browser-duckdb-schema.sql and
        populates them from pipeline data in a single pass. Overwrites any
        existing file at *output_path*. The legacy build() method remains
        available for callers that only need the 19-column results table.

        Args:
            entries: All ManifestEntry objects for this pipeline run.
            details_map: result_id → DetailResult for each processed bundle.
            summaries: Sequence of ((benchmark, scale_factor, phase), BenchmarkSummary).
            short_id_map: short_id → result_id mapping from _build_short_ids.
            full_to_short: result_id → short_id reverse mapping.
            meta: Meta-leaderboard dict from _build_meta_leaderboard.
            bundle_url_prefix: URL prefix for bundle download links.
            output_path: Destination path for the .duckdb file.
        """
        try:
            import duckdb
        except ImportError as exc:
            raise ImportError(
                "duckdb is required for DuckDBSnapshotBuilder. Install the explorer dependency set with: uv sync --extra explorer"
            ) from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)
        if output_path.exists():
            output_path.unlink()

        prefix = bundle_url_prefix.rstrip("/")

        with duckdb.connect(str(output_path)) as con:
            self._create_schema(con)
            self._populate_supporting_tables(con, entries, details_map)
            self._populate_results(con, entries, details_map, prefix)
            self._populate_query_display_timings(con, entries, details_map)
            self._populate_query_executions(con, entries, details_map)
            self._populate_benchmark_matrix_cells(con, summaries)
            self._populate_benchmark_rankings(con, summaries, full_to_short)
            self._populate_cohort_metadata(con, meta)
            self._populate_meta_leaderboard(con, meta)
            self._populate_short_ids(con, short_id_map)

        logger.info("Built full DuckDB browser store (%d results) at %s", len(entries), output_path)

    # ------------------------------------------------------------------
    # Schema DDL
    # ------------------------------------------------------------------

    def _create_schema(self, con: Any) -> None:
        """Create all canonical tables and views in one pass."""
        con.execute("""
            CREATE TABLE result_environment (
                result_id  VARCHAR PRIMARY KEY,
                os         VARCHAR,
                arch       VARCHAR,
                cpu_count  INTEGER,
                memory_gb  DOUBLE,
                python     VARCHAR
            )
        """)
        con.execute("""
            CREATE TABLE result_phase_durations (
                result_id  VARCHAR NOT NULL,
                phase      VARCHAR NOT NULL,
                duration_s DOUBLE  NOT NULL,
                PRIMARY KEY (result_id, phase)
            )
        """)
        con.execute("""
            CREATE TABLE results (
                result_id            VARCHAR  PRIMARY KEY,
                benchmark            VARCHAR  NOT NULL,
                scale_factor         DOUBLE   NOT NULL,
                platform             VARCHAR  NOT NULL,
                platform_id          VARCHAR  NOT NULL,
                driver_version       VARCHAR,
                run_date             VARCHAR  NOT NULL,
                power_score          DOUBLE,
                total_duration_s     DOUBLE   NOT NULL,
                geomean_ms           DOUBLE,
                display_geomean_ms   DOUBLE,
                query_count          INTEGER  NOT NULL,
                trust_label          VARCHAR  NOT NULL,
                visibility           VARCHAR  NOT NULL,
                platform_version     VARCHAR,
                execution_mode       VARCHAR,
                tuning_mode          VARCHAR,
                tuning_hash          VARCHAR,
                test_type            VARCHAR,
                validation_status    VARCHAR,
                cost_usd             DOUBLE,
                compliance_class     VARCHAR,
                is_ranking_eligible  BOOLEAN  NOT NULL,
                has_plans            BOOLEAN  NOT NULL,
                has_tuning           BOOLEAN  NOT NULL,
                bundle_download_url  VARCHAR  NOT NULL
            )
        """)
        con.execute("""
            CREATE VIEW result_detail_metrics AS
            SELECT
                r.result_id,
                r.benchmark,
                r.scale_factor,
                r.platform,
                r.platform_id,
                r.driver_version,
                r.run_date,
                r.power_score,
                r.total_duration_s,
                r.geomean_ms,
                r.display_geomean_ms,
                r.query_count,
                r.trust_label,
                r.visibility,
                r.platform_version,
                r.execution_mode,
                r.tuning_mode,
                r.tuning_hash,
                r.test_type,
                r.validation_status,
                r.cost_usd,
                r.compliance_class,
                r.has_plans,
                r.has_tuning,
                r.bundle_download_url,
                e.os,
                e.arch,
                e.cpu_count,
                e.memory_gb,
                e.python
            FROM results r
            LEFT JOIN result_environment e USING (result_id)
        """)
        con.execute("""
            CREATE TABLE query_display_timings (
                result_id    VARCHAR  NOT NULL,
                query_id     VARCHAR  NOT NULL,
                display_ms   DOUBLE,
                sample_count INTEGER  NOT NULL,
                PRIMARY KEY (result_id, query_id)
            )
        """)
        con.execute("""
            CREATE TABLE query_executions (
                result_id    VARCHAR  NOT NULL,
                query_id     VARCHAR  NOT NULL,
                duration_ms  DOUBLE   NOT NULL,
                status       VARCHAR  NOT NULL,
                run_type     VARCHAR,
                iter         INTEGER,
                stream       INTEGER
            )
        """)
        con.execute("CREATE INDEX idx_query_executions_result ON query_executions (result_id)")
        con.execute("""
            CREATE TABLE benchmark_matrix_cells (
                benchmark    VARCHAR  NOT NULL,
                scale_factor DOUBLE   NOT NULL,
                phase        VARCHAR  NOT NULL,
                result_id    VARCHAR  NOT NULL,
                platform_id  VARCHAR  NOT NULL,
                query_id     VARCHAR  NOT NULL,
                display_ms   DOUBLE,
                PRIMARY KEY (benchmark, scale_factor, phase, result_id, query_id)
            )
        """)
        con.execute("CREATE INDEX idx_matrix_cells_cohort ON benchmark_matrix_cells (benchmark, scale_factor, phase)")
        con.execute("""
            CREATE TABLE benchmark_rankings (
                benchmark                    VARCHAR  NOT NULL,
                scale_factor                 DOUBLE   NOT NULL,
                phase                        VARCHAR  NOT NULL,
                result_id                    VARCHAR  NOT NULL,
                platform_id                  VARCHAR  NOT NULL,
                platform                     VARCHAR  NOT NULL,
                short_id                     VARCHAR  NOT NULL,
                trust_label                  VARCHAR  NOT NULL,
                tuning_mode                  VARCHAR,
                tuning_hash                  VARCHAR,
                execution_mode               VARCHAR,
                compliance_class             VARCHAR,
                run_date                     VARCHAR  NOT NULL,
                is_ranking_eligible          BOOLEAN  NOT NULL,
                power_score                  DOUBLE,
                display_geomean_ms           DOUBLE,
                sample_geomean_ms            DOUBLE,
                cost_usd                     DOUBLE,
                primary_metric               VARCHAR  NOT NULL,
                primary_order                VARCHAR  NOT NULL,
                rank                         INTEGER,
                total_in_cohort              INTEGER  NOT NULL,
                percentile_p50               DOUBLE,
                percentile_p90               DOUBLE,
                percentile_p95               DOUBLE,
                percentile_p99               DOUBLE,
                speedup_vs_best              DOUBLE,
                speedup_vs_slowest_in_cohort DOUBLE,
                PRIMARY KEY (benchmark, scale_factor, phase, result_id)
            )
        """)
        con.execute("CREATE INDEX idx_benchmark_rankings_cohort ON benchmark_rankings (benchmark, scale_factor, phase)")
        con.execute("""
            CREATE VIEW platform_index_rows AS
            SELECT
                result_id,
                benchmark,
                scale_factor,
                platform,
                platform_id,
                driver_version,
                run_date,
                power_score,
                total_duration_s,
                geomean_ms,
                display_geomean_ms,
                query_count,
                trust_label,
                tuning_mode,
                execution_mode,
                compliance_class,
                cost_usd
            FROM results
        """)
        con.execute("""
            CREATE TABLE cohort_metadata (
                cohort_key       VARCHAR  NOT NULL,
                benchmark        VARCHAR  NOT NULL,
                scale_factor     DOUBLE   NOT NULL,
                phase            VARCHAR  NOT NULL,
                cohort_label     VARCHAR  NOT NULL,
                cohort_href      VARCHAR  NOT NULL,
                platform_count   INTEGER  NOT NULL,
                primary_metric   VARCHAR  NOT NULL,
                primary_order    VARCHAR  NOT NULL,
                platform_id      VARCHAR  NOT NULL,
                platform         VARCHAR  NOT NULL,
                result_id        VARCHAR  NOT NULL,
                short_id         VARCHAR  NOT NULL,
                tuning_mode      VARCHAR,
                trust_label      VARCHAR  NOT NULL,
                rank             INTEGER,
                metric_value     DOUBLE,
                speedup_vs_best  DOUBLE,
                PRIMARY KEY (cohort_key, result_id)
            )
        """)
        con.execute("CREATE INDEX idx_cohort_metadata_key ON cohort_metadata (cohort_key)")
        con.execute("CREATE INDEX idx_cohort_metadata_platform ON cohort_metadata (cohort_key, platform_id)")
        con.execute("""
            CREATE TABLE meta_leaderboard (
                platform_id  VARCHAR  PRIMARY KEY,
                platform     VARCHAR  NOT NULL,
                avg_rank     DOUBLE,
                n_cohorts    INTEGER  NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE short_ids (
                short_id   VARCHAR  PRIMARY KEY,
                result_id  VARCHAR  NOT NULL UNIQUE
            )
        """)

    # ------------------------------------------------------------------
    # Population helpers
    # ------------------------------------------------------------------

    def _populate_supporting_tables(
        self,
        con: Any,
        entries: list[ManifestEntry],
        details_map: dict[str, DetailResult],
    ) -> None:
        env_rows: list[tuple] = []
        phase_rows: list[tuple] = []
        for entry in entries:
            detail = details_map.get(entry.result_id)
            if detail is None:
                continue
            env = detail.environment or {}
            env_rows.append(
                (
                    entry.result_id,
                    env.get("os"),
                    env.get("arch"),
                    env.get("cpu_count"),
                    env.get("memory_gb"),
                    env.get("python"),
                )
            )
            if detail.phase_durations:
                for phase, duration_s in detail.phase_durations.items():
                    phase_rows.append((entry.result_id, phase, duration_s))

        if env_rows:
            con.executemany("INSERT INTO result_environment VALUES (?, ?, ?, ?, ?, ?)", env_rows)
        if phase_rows:
            con.executemany("INSERT INTO result_phase_durations VALUES (?, ?, ?)", phase_rows)

    def _populate_results(
        self,
        con: Any,
        entries: list[ManifestEntry],
        details_map: dict[str, DetailResult],
        bundle_url_prefix: str,
    ) -> None:
        rows: list[tuple] = []
        for entry in entries:
            detail = details_map.get(entry.result_id)
            has_plans = detail.has_plans if detail is not None else False
            has_tuning = detail.has_tuning if detail is not None else False
            bundle_download_url = f"{bundle_url_prefix}/{entry.result_id}.json"
            rows.append(
                (
                    entry.result_id,
                    entry.benchmark,
                    entry.scale_factor,
                    entry.platform,
                    entry.platform_id,
                    entry.driver_version,
                    entry.run_date,
                    entry.power_score,
                    entry.total_duration_s,
                    entry.geomean_ms,
                    entry.display_geomean_ms,
                    entry.query_count,
                    entry.trust_label,
                    entry.visibility,
                    entry.platform_version,
                    entry.execution_mode,
                    entry.tuning_mode,
                    entry.tuning_hash,
                    entry.test_type,
                    entry.validation_status,
                    entry.cost_usd,
                    entry.compliance_class,
                    is_ranking_eligible(entry),
                    has_plans,
                    has_tuning,
                    bundle_download_url,
                )
            )
        if rows:
            placeholders = ", ".join(["?"] * len(rows[0]))
            con.executemany(f"INSERT INTO results VALUES ({placeholders})", rows)

    def _populate_query_display_timings(
        self,
        con: Any,
        entries: list[ManifestEntry],
        details_map: dict[str, DetailResult],
    ) -> None:
        rows: list[tuple] = []
        for entry in entries:
            detail = details_map.get(entry.result_id)
            if detail is None:
                continue
            for dt in detail.display_timings:
                rows.append((entry.result_id, dt.query_id, dt.display_ms, dt.sample_count))
        if rows:
            con.executemany("INSERT INTO query_display_timings VALUES (?, ?, ?, ?)", rows)

    def _populate_query_executions(
        self,
        con: Any,
        entries: list[ManifestEntry],
        details_map: dict[str, DetailResult],
    ) -> None:
        rows: list[tuple] = []
        for entry in entries:
            detail = details_map.get(entry.result_id)
            if detail is None:
                continue
            for qt in detail.queries:
                rows.append(
                    (
                        entry.result_id,
                        qt.query_id,
                        qt.duration_ms,
                        qt.status,
                        qt.run_type,
                        qt.iter,
                        qt.stream,
                    )
                )
        if rows:
            con.executemany("INSERT INTO query_executions VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    def _populate_benchmark_matrix_cells(
        self,
        con: Any,
        summaries: list[tuple[_SummaryKey, BenchmarkSummary]],
    ) -> None:
        rows: list[tuple] = []
        for (benchmark, scale_factor, phase), summary in summaries:
            for platform_row in summary.platforms:
                for query_id, display_ms in platform_row.timings.items():
                    rows.append(
                        (
                            benchmark,
                            scale_factor,
                            phase,
                            platform_row.result_id,
                            platform_row.platform_id,
                            query_id,
                            display_ms,
                        )
                    )
        if rows:
            con.executemany("INSERT INTO benchmark_matrix_cells VALUES (?, ?, ?, ?, ?, ?, ?)", rows)

    def _populate_benchmark_rankings(
        self,
        con: Any,
        summaries: list[tuple[_SummaryKey, BenchmarkSummary]],
        full_to_short: dict[str, str],
    ) -> None:
        rows: list[tuple] = []
        for (benchmark, scale_factor, phase), summary in summaries:
            ranking = summary.ranking
            primary_metric = ranking.primary_metric if ranking else "display_geomean_ms"
            primary_order = ranking.primary_order if ranking else "asc"
            higher_is_better = primary_order == "desc"

            def _metric_val(row: Any, _pm: str = primary_metric) -> float | None:
                return row.power_score if _pm == "power_score" else row.display_geomean_ms

            def _rank_key(row: Any, _hib: bool = higher_is_better) -> tuple:
                val = _metric_val(row)
                if val is None:
                    return (True, 0.0)
                return (False, -val if _hib else val)

            sorted_rows = sorted(summary.platforms, key=_rank_key)
            total_in_cohort = len(sorted_rows)

            # Best and slowest metric values across the cohort - used to
            # materialise per-result speedup_vs_best / speedup_vs_slowest so
            # TS-side speedup math can be retired.
            cohort_vals = [v for v in (_metric_val(r) for r in sorted_rows) if v is not None and v > 0]
            best_val = (max(cohort_vals) if higher_is_better else min(cohort_vals)) if cohort_vals else None
            slowest_val = (min(cohort_vals) if higher_is_better else max(cohort_vals)) if cohort_vals else None

            for i, platform_row in enumerate(sorted_rows):
                val = _metric_val(platform_row)
                rank = (i + 1) if val is not None else None
                ps = platform_row.percentile_stats
                # Defer the semantics to the canonical reference functions -
                # same module referenced as canonical_ref in visible_metrics.yaml.
                speedup_vs_best = _speedup_vs_best(val, best_val, higher_is_better=higher_is_better)
                speedup_vs_slowest = _speedup_vs_slowest(val, slowest_val, higher_is_better=higher_is_better)
                rows.append(
                    (
                        benchmark,
                        scale_factor,
                        phase,
                        platform_row.result_id,
                        platform_row.platform_id,
                        platform_row.platform,
                        full_to_short.get(platform_row.result_id, ""),
                        platform_row.trust_label,
                        platform_row.tuning_mode,
                        platform_row.tuning_hash,
                        platform_row.execution_mode,
                        platform_row.compliance_class,
                        platform_row.run_date,
                        platform_row.is_ranking_eligible,
                        platform_row.power_score,
                        platform_row.display_geomean_ms,
                        platform_row.sample_geomean_ms,
                        platform_row.cost_usd,
                        primary_metric,
                        primary_order,
                        rank,
                        total_in_cohort,
                        ps.p50 if ps else None,
                        ps.p90 if ps else None,
                        ps.p95 if ps else None,
                        ps.p99 if ps else None,
                        speedup_vs_best,
                        speedup_vs_slowest,
                    )
                )
        if rows:
            placeholders = ", ".join(["?"] * len(rows[0]))
            con.executemany(f"INSERT INTO benchmark_rankings VALUES ({placeholders})", rows)

    def _populate_cohort_metadata(self, con: Any, meta: dict[str, Any]) -> None:
        # One row per (cohort_key, result_id) - every publishable variant is
        # preserved. The same platform may appear more than once per cohort
        # when run with different tuning_mode or trust_label; the UI layer
        # decides any display-time collapsing.
        rows: list[tuple] = []
        for cohort in meta.get("cohorts", []):
            cohort_key = cohort["key"]
            benchmark = cohort["benchmark"]
            scale_factor = cohort["scale_factor"]
            phase = cohort["phase"]
            cohort_label = cohort["label"]
            cohort_href = cohort["href"]
            platform_count = cohort["platform_count"]
            primary_metric = cohort["primary_metric"]
            primary_order = cohort["primary_order"]
            for p in cohort.get("platforms", []):
                # Required keys are contractually emitted by
                # ``pipeline._build_meta_leaderboard``. A missing key here
                # means an upstream change broke the contract; fail loudly
                # rather than silently writing NULLs.
                missing = _COHORT_PLATFORM_REQUIRED_KEYS - p.keys()
                if missing:
                    raise ValueError(
                        f"cohort platform row missing required keys {sorted(missing)} "
                        f"for cohort {cohort_key!r}; upstream contract broken"
                    )
                rows.append(
                    (
                        cohort_key,
                        benchmark,
                        scale_factor,
                        phase,
                        cohort_label,
                        cohort_href,
                        platform_count,
                        primary_metric,
                        primary_order,
                        p["platform_id"],
                        p["platform"],
                        p["result_id"],
                        p["short_id"],
                        p.get("tuning_mode"),
                        p["trust_label"],
                        p.get("rank"),
                        p.get("metric_value"),
                        p.get("speedup_vs_best"),
                    )
                )

        if rows:
            placeholders = ", ".join(["?"] * len(rows[0]))
            con.executemany(f"INSERT INTO cohort_metadata VALUES ({placeholders})", rows)

    def _populate_meta_leaderboard(self, con: Any, meta: dict[str, Any]) -> None:
        rows: list[tuple] = []
        for p in meta.get("platforms", []):
            rows.append(
                (
                    p["platform_id"],
                    p["platform"],
                    p.get("avg_rank"),
                    p.get("n_cohorts", 0),
                )
            )
        if rows:
            con.executemany("INSERT INTO meta_leaderboard VALUES (?, ?, ?, ?)", rows)

    def _populate_short_ids(self, con: Any, short_id_map: dict[str, str]) -> None:
        rows = list(short_id_map.items())
        if rows:
            con.executemany("INSERT INTO short_ids VALUES (?, ?)", rows)

    @staticmethod
    def _entry_to_tuple(entry: ManifestEntry) -> tuple:
        return (
            entry.result_id,
            entry.benchmark,
            entry.scale_factor,
            entry.platform,
            entry.driver_version,
            entry.run_date,
            entry.power_score,
            entry.total_duration_s,
            entry.geomean_ms,
            entry.query_count,
            entry.trust_label,
            entry.visibility,
            entry.platform_version,
            entry.execution_mode,
            entry.tuning_mode,
            entry.tuning_hash,
            entry.test_type,
            entry.validation_status,
            entry.cost_usd,
        )


__all__ = ["DuckDBSnapshotBuilder"]
