"""Top-level orchestration for the explorer static build pipeline.

Scans a directory of schema-v2 result bundles, transforms each into the
explorer read model, and writes a DuckDB snapshot to the output directory.
DuckDB is the sole browser-facing store for user-visible metrics;
`ManifestEntry` is an internal dataclass that seeds DuckDB, not a JSON
artifact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from benchbox.core.explorer_pipeline.duckdb_builder import DuckDBSnapshotBuilder
from benchbox.core.explorer_pipeline.models import (
    BenchmarkSummary,
    DetailResult,
    ManifestEntry,
    PlatformRow,
    get_ranking_config,
    is_ranking_eligible,
)
from benchbox.core.explorer_pipeline.transformer import (
    BundleTransformer,
    _platform_percentile_stats,
)

logger = logging.getLogger(__name__)

SUBMISSION_MANIFEST_FILENAME = "submission-manifest.json"
COMMUNITY_TRUST_LABEL = "community-submission"

# Type alias for the summary accumulator: (benchmark, scale_factor, phase) → rows
_SummaryKey = tuple[str, float, str]
_SummaryAccum = dict[_SummaryKey, list[tuple[ManifestEntry, DetailResult]]]


def _sf_str(scale_factor: float) -> str:
    """Format scale factor for filenames, e.g. 0.01 → '0.01', 1.0 → '1'."""
    return f"{scale_factor:g}"


def _natural_sort_key(s: str) -> list[int | str]:
    """Sort key for strings with embedded numbers: Q1 < Q2 < Q10 < Q22."""
    return [int(c) if c.isdigit() else c.lower() for c in re.split(r"(\d+)", s) if c]


def _build_short_ids(result_ids: list[str]) -> dict[str, str]:
    """Build a short_id → result_id mapping using sha256 prefixes.

    Default prefix length is 8 hex characters.  If any two result_ids share a
    prefix at the current length, all short IDs are extended by 2 characters
    and the process repeats until all prefixes are unique.  At sha256's 64-char
    maximum, uniqueness is guaranteed for any realistic corpus size.
    """
    if not result_ids:
        return {}
    for length in range(8, 65, 2):
        candidate: dict[str, str] = {hashlib.sha256(rid.encode()).hexdigest()[:length]: rid for rid in result_ids}
        # If every entry is unique the dict has as many keys as inputs.
        if len(candidate) == len(result_ids):
            return candidate
    # sha256 is 64 hex chars; we never get here, but satisfy the type checker.
    raise RuntimeError("Could not build collision-free short IDs (sha256 limit reached)")


def _platform_row_sort_key(benchmark: str) -> Callable[[PlatformRow], tuple[bool, float]]:
    """Return a sort key function for PlatformRows using the benchmark's RankingConfig.

    Eligible rows sort before ineligible ones; within eligible rows, the primary
    metric direction is derived from the ranking config so future benchmark families
    with non-standard metric directions sort correctly without touching this function.
    """
    cfg = get_ranking_config(benchmark)
    desc = cfg.primary_order == "desc"

    def _key(row: PlatformRow) -> tuple[bool, float]:
        ineligible = not row.is_ranking_eligible
        primary_val = getattr(row, cfg.primary_metric, None)
        if primary_val is None:
            return (ineligible, float("inf"))
        metric = -primary_val if desc else primary_val
        return (ineligible, metric)

    return _key


def _build_benchmark_summaries(
    accum: _SummaryAccum,
    full_to_short: dict[str, str],
) -> list[tuple[_SummaryKey, BenchmarkSummary]]:
    """Build one BenchmarkSummary per (benchmark, scale_factor, phase) bucket."""
    summaries = []
    for key, pairs in sorted(accum.items()):
        benchmark, scale_factor, phase = key

        # Union of all query IDs emitted by any platform for this key
        all_query_ids = sorted(
            {dt.query_id for _, detail in pairs for dt in detail.display_timings},
            key=_natural_sort_key,
        )

        platform_rows: list[PlatformRow] = []
        for entry, detail in pairs:
            timings: dict[str, float | None] = dict.fromkeys(all_query_ids, None)
            for dt in detail.display_timings:
                timings[dt.query_id] = dt.display_ms

            row = PlatformRow(
                result_id=entry.result_id,
                short_id=full_to_short.get(entry.result_id, ""),
                platform_id=entry.platform_id,
                platform=entry.platform,
                platform_version=entry.platform_version,
                tuning_mode=entry.tuning_mode,
                tuning_hash=entry.tuning_hash,
                execution_mode=entry.execution_mode,
                trust_label=entry.trust_label,
                run_date=entry.run_date,
                is_ranking_eligible=is_ranking_eligible(entry),
                power_score=entry.power_score,
                display_geomean_ms=entry.display_geomean_ms,
                sample_geomean_ms=entry.geomean_ms,
                cost_usd=entry.cost_usd,
                compliance_class=entry.compliance_class,
                percentile_stats=_platform_percentile_stats(detail.display_timings),
                phase_durations=detail.phase_durations,
                timings=timings,
            )
            platform_rows.append(row)

        platform_rows.sort(key=_platform_row_sort_key(benchmark))

        summary = BenchmarkSummary(
            benchmark=benchmark,
            scale_factor=scale_factor,
            phase=phase,
            query_ids=all_query_ids,
            platforms=platform_rows,
            ranking=get_ranking_config(benchmark),
        )
        summaries.append((key, summary))
    return summaries


# Human-readable labels for benchmark families (mirrors frontend BENCHMARK_LABELS).
_BENCHMARK_LABELS: dict[str, str] = {
    "tpch": "TPC-H",
    "tpcds": "TPC-DS",
    "ssb": "SSB",
    "star_schema": "SSB",
    "clickbench": "ClickBench",
    "nyctaxi": "NYC Taxi",
    "h2odb": "H2O DB",
    "datavault": "DataVault",
}


def _humanize_benchmark(benchmark: str) -> str:
    return _BENCHMARK_LABELS.get(benchmark, benchmark.upper())


def _rank_platforms_in_cohort(
    summary: BenchmarkSummary,
    cohort_key: str,
    full_to_short: dict[str, str],
) -> tuple[list[dict[str, Any]], str, bool]:
    """Rank platforms within a single cohort and return (platform_entries, primary_metric, higher_is_better).

    Platform entries include rank, speedup_vs_best, and all display fields needed
    by both the cohort_platforms list and the platform_agg accumulator.
    """
    ranking = summary.ranking
    primary_metric = ranking.primary_metric if ranking else "display_geomean_ms"
    higher_is_better = (ranking.primary_order == "desc") if ranking else False

    def _get_val(row: PlatformRow, _pm: str = primary_metric) -> float | None:
        return row.power_score if _pm == "power_score" else row.display_geomean_ms

    def _sort_key(row: PlatformRow, _hib: bool = higher_is_better) -> tuple[bool, float]:
        val = _get_val(row)
        if val is None:
            return (True, 0.0)
        return (False, -val if _hib else val)

    sorted_rows = sorted(summary.platforms, key=_sort_key)
    non_null_vals = [_get_val(r) for r in sorted_rows if _get_val(r) is not None]
    best_val: float | None = (
        (min(non_null_vals) if not higher_is_better else max(non_null_vals)) if non_null_vals else None
    )
    # Assign ranks with standard competition ranking (ties share the lowest rank;
    # the rank after a tie group jumps by the tie size - matches computeRankTable).
    ranks_by_idx: list[int | None] = []
    current_rank = 1
    for i, row in enumerate(sorted_rows):
        val = _get_val(row)
        if val is None:
            ranks_by_idx.append(None)
        else:
            if i > 0:
                prev_val = _get_val(sorted_rows[i - 1])
                if prev_val is not None and val != prev_val:
                    current_rank = i + 1
            ranks_by_idx.append(current_rank)

    entries: list[dict[str, Any]] = []
    for i, row in enumerate(sorted_rows):
        val = _get_val(row)
        rank = ranks_by_idx[i]
        speedup: float | None = None
        if val is not None and best_val is not None and best_val != 0:
            speedup = val / best_val if higher_is_better else best_val / val
        entries.append(
            {
                "platform_id": row.platform_id,
                "platform": row.platform,
                "result_id": row.result_id,
                "short_id": full_to_short.get(row.result_id, ""),
                "tuning_mode": row.tuning_mode,
                "trust_label": row.trust_label,
                "rank": rank,
                "total": len(non_null_vals),
                "metric_value": val,
                "speedup_vs_best": speedup,
            }
        )
    return entries, primary_metric, higher_is_better


def _compute_average_ranks(platform_agg: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert per-platform cohort rank accumulator into sorted summary rows.

    Platforms with equal avg_rank are ordered alphabetically by platform_id.
    """
    records: list[dict[str, Any]] = []
    for pdata in platform_agg.values():
        ranks = pdata["ranks"]
        # 1-decimal precision matches the frontend's `.toFixed(1)` display and
        # Home.tsx's re-rounding when filters narrow the cohort set.
        avg_rank = round(sum(r["rank"] for r in ranks.values()) / len(ranks), 1) if ranks else None
        records.append(
            {
                "platform_id": pdata["platform_id"],
                "platform": pdata["platform"],
                "ranks": ranks,
                "avg_rank": avg_rank,
                "n_cohorts": len(ranks),
            }
        )
    # Primary sort: avg_rank ascending (None last). Secondary: platform_id for stable ties.
    records.sort(key=lambda p: (p["avg_rank"] is None, p["avg_rank"] or float("inf"), p["platform_id"]))
    return records


def _build_meta_leaderboard(
    summaries: list[tuple[_SummaryKey, BenchmarkSummary]],
    generated_at: str,
    full_to_short: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Build the cross-benchmark meta-leaderboard artifact.

    Only cohorts with ≥2 platforms are included.  Platforms are ranked 1-based
    by the cohort's primary metric within each cohort.  Platforms with a null
    primary metric (all queries failed) are assigned no rank for that cohort.
    Per-platform average rank is computed across cohorts in which the platform
    participated (N/A cohorts are excluded from the average, not penalised).

    When the same platform_id appears more than once in a cohort (different
    tuning_mode or trust_label), cohort_platforms keeps every variant - the
    cohort_metadata DuckDB table is lossless on publishable variants - but
    platform_agg (the cross-cohort "avg rank per platform" summary on Home)
    keeps only the BEST rank that platform achieved in the cohort. Otherwise
    cross-cohort averages would depend on how many variants each platform
    happened to publish, which is not a fair ranking signal.
    """
    if full_to_short is None:
        full_to_short = {}
    eligible = [(key, s) for key, s in summaries if len(s.platforms) >= 2]
    if not eligible:
        return {"generated_at": generated_at, "cohorts": [], "platforms": []}

    cohort_records: list[dict[str, Any]] = []
    # platform_id → {"platform_id", "platform", "ranks": {cohort_key: {rank, total, ...}}}
    platform_agg: dict[str, dict[str, Any]] = {}

    for (benchmark, scale_factor, phase), summary in eligible:
        sf = _sf_str(scale_factor)
        cohort_key = f"{benchmark}-sf{sf}-{phase}"
        label = f"{_humanize_benchmark(benchmark)} SF{sf}"

        platform_entries, primary_metric, higher_is_better = _rank_platforms_in_cohort(
            summary, cohort_key, full_to_short
        )

        for entry in platform_entries:
            pid = entry["platform_id"]
            rank = entry["rank"]
            if pid not in platform_agg:
                platform_agg[pid] = {"platform_id": pid, "platform": entry["platform"], "ranks": {}}
            if rank is not None:
                # When the same platform ranks in this cohort more than once
                # (variant rows), keep the best rank. Worse variants must not
                # clobber better ones via last-write-wins.
                existing = platform_agg[pid]["ranks"].get(cohort_key)
                if existing is None or rank < existing["rank"]:
                    platform_agg[pid]["ranks"][cohort_key] = {
                        "rank": rank,
                        "total": entry["total"],
                        "metric_value": entry["metric_value"],
                        "speedup_vs_best": entry["speedup_vs_best"],
                    }

        # Strip internal "total" field before storing in cohort record.
        cohort_platforms = [{k: v for k, v in e.items() if k != "total"} for e in platform_entries]
        cohort_records.append(
            {
                "key": cohort_key,
                "benchmark": benchmark,
                "scale_factor": scale_factor,
                "phase": phase,
                "label": label,
                "href": f"/results/{benchmark}/?sf={scale_factor}&phase={phase}",
                "platform_count": len(summary.platforms),
                "primary_metric": primary_metric,
                "primary_order": "desc" if higher_is_better else "asc",
                "platforms": cohort_platforms,
            }
        )

    return {
        "generated_at": generated_at,
        "cohorts": cohort_records,
        "platforms": _compute_average_ranks(platform_agg),
    }


@dataclass(frozen=True)
class BuildStats:
    """Counts emitted by a successful pipeline run, for caller display."""

    processed: int
    skipped: int
    cohorts: int
    output_dir: Path


class ExplorerPipeline:
    """Orchestrates the full static build pipeline for the results explorer."""

    def __init__(
        self,
        transformer: BundleTransformer | None = None,
        duckdb_builder: DuckDBSnapshotBuilder | None = None,
    ) -> None:
        self._transformer = transformer or BundleTransformer()
        self._duckdb_builder = duckdb_builder or DuckDBSnapshotBuilder()

    def run(
        self,
        data_dir: Path,
        output_dir: Path,
        trust_label: str = "maintainer-run",
        visibility: str = "public-curated",
        bundle_url_prefix: str = "/results/data/bundles",
    ) -> BuildStats:
        """Execute the full pipeline.

        Steps:
        1. Scan ``data_dir/bundles/`` recursively for primary ``*.json`` bundle files.
        2. Transform each bundle to ManifestEntry + DetailResult.
        3. Sweep any legacy metric-bearing artifacts from earlier pipeline versions.
        4. Write ``output_dir/results.duckdb`` (the ten canonical browser tables).
        5. Copy bundles to ``output_dir/bundles/{result_id}.json`` as a read-only
           download affordance - never fetched for user-visible metrics.

        Args:
            data_dir: Root data directory containing a ``bundles/`` sub-directory.
            output_dir: Destination directory for all generated artifacts.
            trust_label: Trust label to attach to every result.
            visibility: Visibility label to attach to every result.
            bundle_url_prefix: URL path prefix for bundle download links.
                Joined with ``/{result_id}.json`` to form each detail's
                ``bundle_download_url``.  Must match the path at which GitHub
                Pages (or another host) serves the copied bundle files.
        """
        bundles_dir = data_dir / "bundles"
        if not bundles_dir.exists():
            logger.warning("Bundles directory does not exist: %s", bundles_dir)
            bundle_files: list[Path] = []
        else:
            bundle_files = sorted(
                path
                for path in bundles_dir.rglob("*.json")
                if path.is_file()
                and not path.name.endswith((".plans.json", ".tuning.json"))
                and path.name != SUBMISSION_MANIFEST_FILENAME
            )
            logger.info("Found %d bundle(s) in %s", len(bundle_files), bundles_dir)

        output_dir.mkdir(parents=True, exist_ok=True)

        out_bundles_dir = output_dir / "bundles"
        if out_bundles_dir.exists():
            shutil.rmtree(out_bundles_dir)
        out_bundles_dir.mkdir(parents=True)

        # Drop derived directories and files from earlier pipeline versions
        # that emitted per-cohort / per-result / manifest JSON artifacts. The
        # DuckDB browser store replaces them; leaving them behind would mask
        # stale data.
        for legacy_name in ("benchmarks", "details", "compare"):
            legacy_dir = output_dir / legacy_name
            if legacy_dir.exists():
                shutil.rmtree(legacy_dir)
        for legacy_file in (
            "manifest.json",
            "meta_leaderboard.json",
            "short_ids.json",
            "results_schema.json",
        ):
            legacy_path = output_dir / legacy_file
            if legacy_path.exists():
                legacy_path.unlink()

        manifest_entries: list[ManifestEntry] = []
        # Accumulator for benchmark summary artifacts (zero extra I/O - reuses
        # already-loaded bundle data from the single pass).
        summary_accum: _SummaryAccum = defaultdict(list)
        # Keyed by result_id; populated alongside manifest_entries so build_full()
        # has per-result detail data without a second I/O pass.
        details_map: dict[str, DetailResult] = {}
        skipped_bundles = 0

        for bundle_path in bundle_files:
            try:
                bundle_data, bundle_raw = self._transformer.load_bundle_full(bundle_path)
                result_id = self._transformer.result_id_from_bundle(bundle_path, data=bundle_data, raw=bundle_raw)
                prefix = bundle_url_prefix.rstrip("/")
                bundle_download_url = f"{prefix}/{result_id}.json"

                # Per-bundle trust label: if a submission-manifest.json sidecar
                # exists alongside this bundle, it was community-submitted.
                effective_trust = trust_label
                manifest_sidecar = bundle_path.parent / SUBMISSION_MANIFEST_FILENAME
                if manifest_sidecar.is_file():
                    effective_trust = COMMUNITY_TRUST_LABEL
                    logger.debug(
                        "Found submission manifest for %s - using trust_label=%r",
                        bundle_path.name,
                        effective_trust,
                    )

                entry = self._transformer.to_manifest_entry(
                    bundle_path,
                    trust_label=effective_trust,
                    visibility=visibility,
                    result_id=result_id,
                    data=bundle_data,
                )
                manifest_entries.append(entry)

                detail = self._transformer.to_detail_result(
                    bundle_path,
                    result_id,
                    trust_label=effective_trust,
                    visibility=visibility,
                    bundle_download_url=bundle_download_url,
                    data=bundle_data,
                )

                dest_bundle = (out_bundles_dir / f"{result_id}.json").resolve()
                if not dest_bundle.is_relative_to(out_bundles_dir.resolve()):
                    skipped_bundles += 1
                    logger.warning(
                        "Skipping bundle copy for %s - result_id %r escapes bundles directory",
                        bundle_path,
                        result_id,
                    )
                    continue
                shutil.copy2(bundle_path, dest_bundle)

                # Accumulate for benchmark summary artifacts.
                phase = detail.test_type or "power"
                summary_key: _SummaryKey = (entry.benchmark, entry.scale_factor, phase)
                summary_accum[summary_key].append((entry, detail))
                details_map[entry.result_id] = detail

                logger.debug("Processed bundle %s → %s", bundle_path.name, result_id)

            except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
                skipped_bundles += 1
                logger.warning("Skipping bundle %s - %s: %s", bundle_path, type(exc).__name__, exc)

        generated_at = datetime.now(tz=timezone.utc).isoformat()
        logger.info("Processed %d bundle(s)", len(manifest_entries))
        if skipped_bundles:
            logger.warning("Skipped %d bundle(s) due to processing errors", skipped_bundles)

        # Build short ID lookup table (short → full result_id).
        all_result_ids = [e.result_id for e in manifest_entries]
        short_id_map = _build_short_ids(all_result_ids)  # short → full
        full_to_short = {v: k for k, v in short_id_map.items()}  # full → short

        # Build per-(benchmark, scale, phase) summaries for DuckDB population.
        # The JSON emission was removed when BenchmarkIndex migrated to DuckDB
        # (W4 slice 3); `_build_benchmark_summaries` still seeds the
        # `benchmark_matrix_cells` and `benchmark_rankings` DuckDB tables via
        # `_DuckDBBuilder`.
        summaries = _build_benchmark_summaries(summary_accum, full_to_short)
        logger.info(
            "Built %d benchmark summary(ies) for DuckDB population",
            len(summaries),
        )

        # Build the cross-benchmark meta-leaderboard for DuckDB population.
        # The JSON emission was removed when Home migrated to DuckDB (W4 slice 1);
        # the `meta` dict below still seeds the `cohort_metadata` and
        # `meta_leaderboard` DuckDB tables via `_DuckDBBuilder`.
        meta = _build_meta_leaderboard(summaries, generated_at, full_to_short)
        logger.info(
            "Built meta-leaderboard (%d cohorts, %d platforms) for DuckDB population",
            len(meta["cohorts"]),
            len(meta["platforms"]),
        )

        duckdb_path = output_dir / "results.duckdb"
        self._duckdb_builder.build_full(
            entries=manifest_entries,
            details_map=details_map,
            summaries=summaries,
            short_id_map=short_id_map,
            full_to_short=full_to_short,
            meta=meta,
            bundle_url_prefix=bundle_url_prefix,
            output_path=duckdb_path,
        )
        logger.info("Wrote full DuckDB browser store to %s", duckdb_path)

        return BuildStats(
            processed=len(manifest_entries),
            skipped=skipped_bundles,
            cohorts=len(summaries),
            output_dir=output_dir,
        )


__all__ = ["BuildStats", "ExplorerPipeline"]
