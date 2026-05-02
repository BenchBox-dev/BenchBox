"""Read model schemas for the BenchBox results explorer.

These Pydantic v2 models define the JSON shapes written by the static build
pipeline and consumed by the results-explorer frontend.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, Field

from benchbox.core.cost.models import NormalizedCost
from benchbox.core.cost.pricing import PRICING_VERSION

_COST_MODEL_SOURCE = "benchbox.core.cost.pricing"


def unavailable_normalized_cost_payload() -> dict[str, Any]:
    """Return the explicit normalized-cost unavailable payload for old bundles."""
    return NormalizedCost(
        normalized_cost_usd=None,
        cost_model_version=PRICING_VERSION,
        cost_model_source=_COST_MODEL_SOURCE,
        cost_scope="compute_only",
        cost_status="unavailable",
        billing_unit="unknown",
        pricing_region="unknown",
    ).to_dict()


# ---------------------------------------------------------------------------
# Platform identity helpers
# ---------------------------------------------------------------------------

# Provenance suffixes appended to platform.name that are NOT part of the
# canonical engine identity (trust source, not platform variant).
# Only strip the "-trust-{source}" provenance suffix pattern. The original
# two-branch regex also stripped bare "-local"/"-ci" suffixes, causing false
# positives for legitimate platform IDs like "clickhouse-local" and
# "clickhouse-server" that end with a trust-like word.
_PROVENANCE_SUFFIX_RE = re.compile(
    r"[-_]trust[-_](?:ci|community|local|unknown)",
    re.IGNORECASE,
)


def _platform_id(raw: str) -> str:
    """Return a canonical platform identifier, stripping provenance suffixes.

    Examples::

        "DuckDB-trust-ci"    -> "duckdb"
        "DuckDB"             -> "duckdb"
        "polars-df"          -> "polars-df"
        "ClickHouse Cloud"   -> "clickhouse-cloud"
    """
    stripped = _PROVENANCE_SUFFIX_RE.sub("", raw).strip()
    return stripped.lower().replace(" ", "-")


# ---------------------------------------------------------------------------
# Ranking eligibility constants
# ---------------------------------------------------------------------------

# Excluded visibility values: "public-self-reported", "community-submission",
# "private", "internal" - these are visible in the explorer but excluded from
# ranking calculations to preserve leaderboard integrity.
RANKING_ELIGIBLE_VISIBILITIES: frozenset[str] = frozenset(
    {
        "public-curated",
        "public-verified",
    }
)

# Excluded trust labels: "community-submission", "local" - results from
# unverified sources are displayed but excluded from official rankings.
RANKING_ELIGIBLE_TRUST_LABELS: frozenset[str] = frozenset(
    {
        "maintainer-run",
        "ci-verified",
    }
)


class ManifestEntry(BaseModel):
    """One row in manifest.json - the nav index for the explorer."""

    result_id: str
    benchmark: str
    scale_factor: float
    platform: str
    platform_id: str = ""
    driver_version: str | None
    run_date: str
    power_score: float | None
    total_duration_s: float
    geomean_ms: float | None = None
    display_geomean_ms: float | None = None
    query_count: int
    trust_label: str
    visibility: str
    # Extended fields (null for bundles predating these fields)
    platform_version: str | None = None
    execution_mode: str | None = None
    tuning_mode: str | None = None
    tuning_hash: str | None = None
    test_type: str | None = None
    validation_status: str | None = None
    cost_usd: float | None = None
    normalized_cost: dict[str, Any] = Field(default_factory=unavailable_normalized_cost_payload)
    compliance_class: str | None = None


class QueryTiming(BaseModel):
    """Per-query timing stored in a detail JSON file."""

    query_id: str
    duration_ms: float
    status: str
    run_type: str | None = None
    iter: int | None = None
    stream: int | None = None


class QueryDisplayTiming(BaseModel):
    """Canonical display timing for one logical query in a DetailResult."""

    query_id: str
    display_ms: float | None  # None when all measurement runs failed
    sample_count: int  # number of passing runs that contributed


class DetailResult(BaseModel):
    """Full detail for a single result, written to details/{result_id}.json."""

    result_id: str
    benchmark: str
    scale_factor: float
    platform: str
    platform_id: str = ""
    driver_version: str | None
    run_date: str
    total_duration_s: float
    geomean_ms: float | None = None
    display_geomean_ms: float | None = None
    power_score: float | None
    environment: dict[str, Any]
    queries: list[QueryTiming]
    display_timings: list[QueryDisplayTiming] = []
    has_plans: bool
    has_tuning: bool
    bundle_download_url: str
    trust_label: str
    visibility: str
    # Extended fields (null for bundles predating these fields)
    platform_version: str | None = None
    execution_mode: str | None = None
    tuning_mode: str | None = None
    tuning_hash: str | None = None
    test_type: str | None = None
    validation_status: str | None = None
    cost_usd: float | None = None
    normalized_cost: dict[str, Any] = Field(default_factory=unavailable_normalized_cost_payload)
    compliance_class: str | None = None
    # Phase durations in seconds (None for pre-pipeline rows).
    phase_durations: dict[str, float] | None = None


# ---------------------------------------------------------------------------
# Ranking eligibility helpers
# ---------------------------------------------------------------------------


def is_ranking_eligible(entry: ManifestEntry) -> bool:
    """Return True if this entry may appear in ranked tables."""
    return entry.visibility in RANKING_ELIGIBLE_VISIBILITIES and entry.trust_label in RANKING_ELIGIBLE_TRUST_LABELS


def select_canonical_row(entries: list[ManifestEntry]) -> ManifestEntry | None:
    """Select the single canonical row for a ranked matrix display.

    Given multiple ManifestEntries for the same (platform_id, benchmark,
    scale_factor, phase), returns the one entry that best represents this
    platform in a ranked view.

    Selection priority (descending):
      1. is_ranking_eligible - ranking-eligible rows beat non-eligible
      2. run_date descending - newest run wins within the same eligibility tier
      3. result_id ascending - deterministic tiebreaker when date and eligibility
         are equal; result_id is a content-hash-prefixed string so ordering is
         arbitrary but stable across pipeline runs.
    """
    if not entries:
        return None
    return max(
        entries,
        key=lambda e: (is_ranking_eligible(e), e.run_date, e.result_id),
    )


# ---------------------------------------------------------------------------
# Ranking metric registry
# ---------------------------------------------------------------------------


class RankingConfig(BaseModel):
    """Describes how to rank a benchmark family's results."""

    primary_metric: str  # field name on PlatformRow, e.g. "power_score"
    secondary_metric: str  # fallback display field, e.g. "display_geomean_ms"
    primary_order: str  # "asc" (lower is better) | "desc" (higher is better)


# Per-benchmark-family ranking configuration.  The frontend reads this from
# the emitted BenchmarkSummary artifact so no ranking logic lives in TS.
RANKING_METRIC_BY_FAMILY: dict[str, RankingConfig] = {
    "tpch": RankingConfig(
        primary_metric="power_score",
        secondary_metric="display_geomean_ms",
        primary_order="desc",
    ),
    "tpcds": RankingConfig(
        primary_metric="power_score",
        secondary_metric="display_geomean_ms",
        primary_order="desc",
    ),
    "star_schema": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
    "ssb": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
    "clickbench": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
    "nyctaxi": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
    "tsbs-devops": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
    "h2odb": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
    "datavault": RankingConfig(
        primary_metric="display_geomean_ms",
        secondary_metric="power_score",
        primary_order="asc",
    ),
}

# Default for benchmark families not in the registry.
_DEFAULT_RANKING = RankingConfig(
    primary_metric="display_geomean_ms",
    secondary_metric="power_score",
    primary_order="asc",
)


def get_ranking_config(benchmark: str) -> RankingConfig:
    """Return the ranking configuration for a benchmark family."""
    return RANKING_METRIC_BY_FAMILY.get(benchmark, _DEFAULT_RANKING)


# ---------------------------------------------------------------------------
# Benchmark summary artifact (Platform × Query matrix)
# ---------------------------------------------------------------------------


class PercentileStats(BaseModel):
    """P50/P90/P95/P99 of per-query display_ms values for a single platform.

    Computed over the set of display_timings medians (one value per query_id).
    Uses linear interpolation identical to ``textcharts.percentile_ladder.compute_percentile``
    so the explorer renderer and CLI output agree exactly.
    """

    p50: float
    p90: float
    p95: float
    p99: float


class PlatformRow(BaseModel):
    """One platform's results in a BenchmarkSummary matrix artifact."""

    result_id: str
    # 8+ character sha256 prefix used for compact Compare URLs.  Empty string
    # only for rows produced by pipeline versions that predate this field.
    short_id: str = ""
    platform_id: str  # canonical (provenance-stripped)
    platform: str  # raw display name from bundle
    platform_version: str | None
    tuning_mode: str | None
    tuning_hash: str | None
    execution_mode: str | None
    trust_label: str
    run_date: str
    is_ranking_eligible: bool
    power_score: float | None
    display_geomean_ms: float | None  # median-per-query geomean (new contract)
    sample_geomean_ms: float | None  # raw all-sample geomean (audit only)
    cost_usd: float | None
    compliance_class: str | None = None
    # Percentile stats over display_timings medians (None for pre-pipeline rows).
    percentile_stats: PercentileStats | None = None
    # Phase durations in seconds keyed by phase name (None for pre-pipeline rows).
    phase_durations: dict[str, float] | None = None
    # query_id → display_ms from QueryDisplayTiming; None means platform
    # did not run that query or all runs failed.
    timings: dict[str, float | None]


class BenchmarkSummary(BaseModel):
    """Pre-computed Platform × Query matrix for one (benchmark, scale, phase) tuple.

    Produced by the explorer pipeline and fed into the DuckDB browser store
    (tables ``benchmark_matrix_cells`` and ``benchmark_rankings``), which the
    BenchmarkIndex page queries via ``getBenchmarkSummaryFromDuckDB``.
    """

    benchmark: str
    scale_factor: float
    phase: str  # "power" | "throughput"
    query_ids: list[str]  # ordered union of all query IDs across platforms
    platforms: list[PlatformRow]
    # Human-readable description of the reduction used for matrix cells.
    cell_reduction: str = "median_successful_measurement_ms"
    # Ranking configuration for this benchmark family, serialized into the
    # artifact so the frontend needs no per-family logic.
    ranking: RankingConfig | None = None


# ---------------------------------------------------------------------------
# Comparison artifact (pre-computed per ordered set of result_ids)
# ---------------------------------------------------------------------------


class ComparisonRow(BaseModel):
    """One platform's summary data in a ComparisonArtifact."""

    result_id: str
    platform: str  # raw platform name from the bundle
    # Human-readable label, after disambiguation (e.g. "DuckDB v1.2.0").
    display_label: str
    platform_id: str
    driver_version: str | None
    trust_label: str
    run_date: str
    display_geomean_ms: float | None
    # Raw all-sample geomean retained for audit (see TODO must_preserve).
    geomean_ms: float | None
    power_score: float | None
    total_duration_s: float | None
    execution_mode: str | None
    tuning_mode: str | None
    test_type: str | None
    compliance_class: str | None = None
    query_count: int  # number of queries the result covers (drives parity with buildComparabilityWarnings)


class ComparisonQueryCell(BaseModel):
    """Pre-computed per-query metrics for one query across all rows in a ComparisonArtifact."""

    query_id: str
    # display_ms for each row (same order as ComparisonArtifact.rows); None = absent/failed.
    display_ms_per_row: list[float | None]
    fastest_ms: float | None  # min of non-null display_ms_per_row
    slowest_ms: float | None  # max of non-null display_ms_per_row
    # slowest_ms / display_ms_per_row[i]; None when either is absent.
    speedup_vs_slowest_per_row: list[float | None]


class ComparabilityWarning(BaseModel):
    """Structured comparability concern surfaced on the Compare page.

    Shape mirrors the TypeScript ``ComparabilityWarning`` in
    ``ComparabilityBanner.tsx`` so the artifact's warnings can be rendered
    directly by the explorer with no translation.
    """

    dimension: str
    values: list[str]
    message: str


class ComparisonArtifact(BaseModel):
    """Pre-computed comparison data for an ordered set of result_ids.

    Written to ``data/compare/{hash16}.json`` by the explorer pipeline.
    Hash is sha256(sorted_result_ids_csv)[:16] - deterministic on sorted
    input so both CLI and browser compute the same path.

    ``schema_version`` must be incremented when the shape changes in a
    breaking way. The explorer hard-fails on version mismatch.
    """

    schema_version: int = 2
    benchmark: str
    scale_factor: float
    generated_at: str
    rows: list[ComparisonRow]
    query_cells: list[ComparisonQueryCell]
    comparability_warnings: list[ComparabilityWarning]
    # "power_score" for tpch/tpcds; "display_geomean_ms" for all others.
    ranking_primary_metric: str


class MetaRank(BaseModel):
    """Per-platform rank cell inside a cohort of the meta leaderboard.

    The four optional fields are additive extensions; older consumers that
    only read ``rank``/``total`` continue to work unchanged.
    """

    rank: int
    total: int
    metric_value: float | None = None
    speedup_vs_best: float | None = None
    primary_metric: str | None = None
    primary_order: str | None = None  # "asc" | "desc"


__all__ = [
    "BenchmarkSummary",
    "ComparabilityWarning",
    "ComparisonArtifact",
    "ComparisonQueryCell",
    "ComparisonRow",
    "DetailResult",
    "ManifestEntry",
    "PercentileStats",
    "PlatformRow",
    "QueryDisplayTiming",
    "QueryTiming",
    "RankingConfig",
    "RANKING_ELIGIBLE_TRUST_LABELS",
    "RANKING_ELIGIBLE_VISIBILITIES",
    "RANKING_METRIC_BY_FAMILY",
    "get_ranking_config",
    "is_ranking_eligible",
    "MetaRank",
    "select_canonical_row",
    "unavailable_normalized_cost_payload",
]
