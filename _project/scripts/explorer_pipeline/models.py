"""Read model schemas for the BenchBox results explorer.

These Pydantic v2 models define the JSON shapes written by the static build
pipeline and consumed by the results-explorer frontend.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from benchbox.core.cost.models import NormalizedCost
from benchbox.core.cost.pricing import PRICING_VERSION
from benchbox.core.results.status import validation_status_is_non_clean

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

# Raw bundle slugs remain on ManifestEntry/DetailResult for auditability. These
# aliases are only used for derived cohort/ranking identity; they do not rewrite
# the submitted evidence or result IDs.
CANONICAL_BENCHMARK_ALIASES: dict[str, str] = {
    "star_schema": "ssb",
}


def canonical_benchmark_slug(raw: str) -> str:
    """Return the stable benchmark family slug used by cohort/ranking keys."""
    normalized = raw.strip().lower()
    return CANONICAL_BENCHMARK_ALIASES.get(normalized, normalized)


def canonical_phase(raw: str | None) -> str:
    """Return an explicit phase identity without guessing missing provenance.

    A missing test type is legacy/unknown evidence, not proof that a run is a
    power test. Keeping it in its own cohort prevents accidental aggregation.
    """
    normalized = (raw or "").strip().lower()
    return normalized if normalized else "unknown"


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
        # Vendor-supplied results ARE ranked (decision D2), with a distinct badge
        # rather than exclusion — the conflict of interest is disclosed, not
        # hidden. Kept in lockstep with provenance.RANKING_ELIGIBLE_VISIBILITIES.
        "public-vendor-reported",
    }
)

# Excluded trust labels: "community-submission", "local" - results from
# unverified sources are displayed but excluded from official rankings.
#
# "ci" is bundle_publisher.VALID_LABELS' actual spelling for an automated-CI
# result - the publisher has never accepted "ci-verified" as a valid label
# (see tests/unit/core/publishing/test_bundle_publisher_label.py's bad-label
# parametrization), so a set containing only "ci-verified" made every
# CI-produced bundle structurally unrankable despite the publisher treating
# "ci" as first-class. "ci-verified" is kept alongside it (rather than
# replaced) only because TrustBadge.tsx still renders it as a distinct,
# reachable-from-historical-data label; no current producer emits it.
RANKING_ELIGIBLE_TRUST_LABELS: frozenset[str] = frozenset(
    {
        "maintainer-run",
        "ci",
        "ci-verified",
        # Vendor-produced results are ranked with a distinct "Vendor Supplied"
        # badge (decision D2). See provenance.SOURCE_TO_TRUST_LABEL.
        "vendor-supplied",
    }
)

# Unofficial TPC compliance classes must never receive an official rank, even
# when the bundle carries a ranking-eligible trust label. `benchbox publish`
# requires the `unofficial-research` label for these results, but the explorer
# build derives trust from the sidecar contract, not the publish-time label, so
# an unofficial result could otherwise inherit `maintainer-run` and be ranked.
# Fail closed on the compliance signal the bundle carries itself.
UNOFFICIAL_COMPLIANCE_CLASSES: frozenset[str] = frozenset(
    {
        "unofficial_nonstandard",
        "unofficial_subscale",
    }
)

APPLIED_TUNING_STATUSES: frozenset[str] = frozenset({"applied_unverified", "applied_verified"})


class ManifestEntry(BaseModel):
    """One result row in the explorer browser read model."""

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
    # Logical benchmark query denominator used by display/comparison
    # eligibility. ``query_count`` remains the raw bundle summary count and can
    # include repeated samples.
    logical_query_count: int = 0
    has_display_timing: bool = False
    valid_query_count: int = 0
    missing_query_count: int = 0
    zero_timing_count: int = 0
    display_exclusion_reason: str | None = None
    comparison_exclusion_reason: str | None = None
    ranking_exclusion_reason: str | None = None
    trust_label: str
    visibility: str
    # How the run was funded (provenance.funding); "unspecified" when the bundle
    # declares no funding. Orthogonal to trust_label - a disclosure, not a rank.
    funding: str = "unspecified"
    # Extended fields (null for bundles predating these fields)
    platform_version: str | None = None
    execution_mode: str | None = None
    tuning_mode: str | None = None
    # Self-derived, display-only tuning fingerprint (see transformer._tuning_hash).
    # Kept for legacy bundles; NEVER a join/dedup/grouping key.
    tuning_hash: str | None = None
    # ADR-1 bundle-emitted tuning identities, ingested verbatim from the
    # bundle's platform.tuning summary (never recomputed here): the canonical
    # requested-config hash and the physical applied-ledger hash. Null for
    # legacy bundles predating these fields. Display-only, like tuning_hash.
    requested_config_hash: str | None = None
    applied_ledger_hash: str | None = None
    # ADR-1 tuning verified-state, ingested verbatim from platform.tuning
    # (never recomputed): not_applicable / noop / applied_unverified /
    # applied_verified / failed. applied_verified is earned only via the
    # post-load introspection receipt's corroboration. Null for legacy bundles
    # predating the applied ledger (treated downstream as "unknown"). Distinct
    # from the run/query validation_status field.
    tuning_validation_status: str | None = None
    # ADR-1 per-statement introspection receipt, read verbatim from the
    # {stem}.applied.json companion's "receipt" sub-object and stored as a
    # canonical JSON string (sort_keys, compact separators). Null when the
    # companion is absent/unreadable/malformed or carries no receipt -- a
    # broken companion never fails the build. Never recomputed or re-derived:
    # the explorer renders the verdicts as recorded. Display-only.
    applied_receipt: str | None = None
    # Accepted plausibility overrides, read verbatim from the
    # {stem}.override.json companion (never recomputed): covered rule
    # ids plus the audit fields. Empty/absent when the companion is
    # missing, invalid, or expired -- a broken companion never fails the
    # build. Display-only; NEVER a join/dedup/grouping key.
    override_rules: list[str] = Field(default_factory=list)
    override_evidence: str | None = None
    override_approver: str | None = None
    override_expires: str | None = None
    # ADR-3 seam: explicit tuning-policy generation marker, ingested verbatim
    # from platform.tuning (never derived from benchbox_version). Null for
    # legacy bundles predating the field (treated downstream as "pre-seam").
    # Display-only, like the hashes above; NEVER a join/dedup/grouping key.
    tuning_policy_generation: str | None = None
    test_type: str | None = None
    validation_status: str | None = None
    failed_query_count: int = 0
    cost_usd: float | None = None
    normalized_cost: dict[str, Any] = Field(default_factory=unavailable_normalized_cost_payload)
    deployment_class: str | None = None
    cloud_provider: str | None = None
    cloud_region: str | None = None
    instance_or_warehouse: str | None = None
    storage_format: str | None = None
    compliance_class: str | None = None
    basis_availability: BasisAvailability | None = None

    @model_validator(mode="after")
    def _default_logical_query_count(self) -> ManifestEntry:
        if self.logical_query_count == 0 and self.query_count > 0:
            self.logical_query_count = self.query_count
        return self


class BasisAvailability(BaseModel):
    """Measurement basis availability for a result bundle."""

    has_warmup: bool = False
    measurement_pass_count: int = 0
    warmup_status: str = "no_warmup_recorded"
    available_bases: list[str] = Field(default_factory=list)
    unavailable_bases: dict[str, str] = Field(default_factory=dict)
    query_pass_counts: dict[str, int] = Field(default_factory=dict)
    varying_pass_queries: dict[str, int] = Field(default_factory=dict)


class QueryTiming(BaseModel):
    """Per-query timing stored in the browser detail read model."""

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


@dataclass(frozen=True)
class TimingEligibility:
    """Display-timing eligibility counts and row-level exclusion reasons."""

    has_display_timing: bool
    logical_query_count: int
    valid_query_count: int
    missing_query_count: int
    zero_timing_count: int
    display_exclusion_reason: str | None
    comparison_exclusion_reason: str | None


def display_timing_is_valid(display_ms: float | None) -> bool:
    """Return True when a display timing can support charts and comparisons."""
    return display_ms is not None and math.isfinite(float(display_ms)) and float(display_ms) > 0


def timing_exclusion_reason(display_ms: float | None) -> str | None:
    """Return the cell-level exclusion reason for one display timing."""
    if display_timing_is_valid(display_ms):
        return None
    if display_ms is None:
        return "missing_timing"
    value = float(display_ms)
    if not math.isfinite(value):
        return "invalid_timing"
    if value == 0:
        return "zero_timing"
    return "non_positive_timing"


def timing_eligibility(
    display_timings: list[QueryDisplayTiming],
    logical_query_count: int | None = None,
    *,
    query_count: int | None = None,
) -> TimingEligibility:
    """Compute the canonical row-level timing eligibility contract.

    Exact zero timings remain auditable but do not count as valid display
    evidence. Missing count includes emitted NULL/invalid timings plus query
    slots in the logical benchmark query denominator that have no
    display-timing row. Raw repeated execution samples must not be passed as
    ``logical_query_count``.
    """
    if logical_query_count is None:
        if query_count is None:
            raise TypeError("timing_eligibility requires logical_query_count")
        logical_query_count = query_count

    valid_query_count = 0
    missing_query_count = 0
    zero_timing_count = 0
    seen_query_ids: set[str] = set()

    for timing in display_timings:
        seen_query_ids.add(timing.query_id)
        reason = timing_exclusion_reason(timing.display_ms)
        if reason is None:
            valid_query_count += 1
        elif reason == "zero_timing":
            zero_timing_count += 1
        else:
            missing_query_count += 1

    logical_count = int(logical_query_count)
    missing_query_count += max(logical_count - len(seen_query_ids), 0)
    has_display_timing = valid_query_count > 0
    display_reason = _display_exclusion_reason(
        query_count=logical_count,
        valid_query_count=valid_query_count,
        missing_query_count=missing_query_count,
        zero_timing_count=zero_timing_count,
    )
    comparison_reason = _comparison_exclusion_reason(
        query_count=logical_count,
        valid_query_count=valid_query_count,
        display_exclusion_reason=display_reason,
    )
    return TimingEligibility(
        has_display_timing=has_display_timing,
        logical_query_count=logical_count,
        valid_query_count=valid_query_count,
        missing_query_count=missing_query_count,
        zero_timing_count=zero_timing_count,
        display_exclusion_reason=display_reason,
        comparison_exclusion_reason=comparison_reason,
    )


def _display_exclusion_reason(
    *,
    query_count: int,
    valid_query_count: int,
    missing_query_count: int,
    zero_timing_count: int,
) -> str | None:
    if valid_query_count > 0:
        return None
    if query_count <= 0:
        return "no_queries"
    if zero_timing_count > 0 and missing_query_count == 0:
        return "zero_timings_only"
    if missing_query_count > 0 and zero_timing_count == 0:
        return "missing_timings"
    return "no_valid_display_timing"


def _comparison_exclusion_reason(
    *,
    query_count: int,
    valid_query_count: int,
    display_exclusion_reason: str | None,
) -> str | None:
    if display_exclusion_reason is not None:
        return display_exclusion_reason
    if valid_query_count < 2:
        return "insufficient_valid_queries"
    if query_count > 0 and valid_query_count * 2 < query_count:
        return "insufficient_query_coverage"
    return None


class DetailResult(BaseModel):
    """Full detail for a single result, used to populate DuckDB detail tables."""

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
    has_display_timing: bool = False
    valid_query_count: int = 0
    logical_query_count: int = 0
    missing_query_count: int = 0
    zero_timing_count: int = 0
    display_exclusion_reason: str | None = None
    comparison_exclusion_reason: str | None = None
    ranking_exclusion_reason: str | None = None
    environment: dict[str, Any]
    queries: list[QueryTiming]
    display_timings: list[QueryDisplayTiming] = []
    has_plans: bool
    # True only when the pipeline has actually copied a ``*.plans.json`` sidecar
    # to the published bundles directory. The explorer UI gates the plan
    # download link on this — ``has_plans`` reflects only source-side detection
    # and is unsafe as a download-link gate because the pipeline may exclude
    # plan sidecars from publication.
    plans_published: bool = False
    has_tuning: bool
    bundle_download_url: str
    trust_label: str
    visibility: str
    # Extended fields (null for bundles predating these fields)
    platform_version: str | None = None
    execution_mode: str | None = None
    tuning_mode: str | None = None
    # Self-derived, display-only tuning fingerprint (see transformer._tuning_hash).
    # Kept for legacy bundles; NEVER a join/dedup/grouping key.
    tuning_hash: str | None = None
    # ADR-1 bundle-emitted tuning identities, ingested verbatim from the
    # bundle's platform.tuning summary (never recomputed here): the canonical
    # requested-config hash and the physical applied-ledger hash. Null for
    # legacy bundles predating these fields. Display-only, like tuning_hash.
    requested_config_hash: str | None = None
    applied_ledger_hash: str | None = None
    # ADR-1 tuning verified-state, ingested verbatim from platform.tuning
    # (never recomputed): not_applicable / noop / applied_unverified /
    # applied_verified / failed. applied_verified is earned only via the
    # post-load introspection receipt's corroboration. Null for legacy bundles
    # predating the applied ledger (treated downstream as "unknown"). Distinct
    # from the run/query validation_status field.
    tuning_validation_status: str | None = None
    # ADR-1 per-statement introspection receipt, read verbatim from the
    # {stem}.applied.json companion's "receipt" sub-object and stored as a
    # canonical JSON string (sort_keys, compact separators). Null when the
    # companion is absent/unreadable/malformed or carries no receipt -- a
    # broken companion never fails the build. Never recomputed or re-derived:
    # the explorer renders the verdicts as recorded. Display-only.
    applied_receipt: str | None = None
    # Accepted plausibility overrides, read verbatim from the
    # {stem}.override.json companion (never recomputed): covered rule
    # ids plus the audit fields. Empty/absent when the companion is
    # missing, invalid, or expired -- a broken companion never fails the
    # build. Display-only; NEVER a join/dedup/grouping key.
    override_rules: list[str] = Field(default_factory=list)
    override_evidence: str | None = None
    override_approver: str | None = None
    override_expires: str | None = None
    # ADR-3 seam: explicit tuning-policy generation marker, ingested verbatim
    # from platform.tuning (never derived from benchbox_version). Null for
    # legacy bundles predating the field (treated downstream as "pre-seam").
    # Display-only, like the hashes above; NEVER a join/dedup/grouping key.
    tuning_policy_generation: str | None = None
    test_type: str | None = None
    validation_status: str | None = None
    failed_query_count: int = 0
    cost_usd: float | None = None
    normalized_cost: dict[str, Any] = Field(default_factory=unavailable_normalized_cost_payload)
    compliance_class: str | None = None
    # Phase durations in seconds (None for pre-pipeline rows).
    phase_durations: dict[str, float] | None = None
    # ADR-2 §3: the platform-rendered physical tuning mechanisms (e.g.
    # indexes, clustering keys, distribution styles) and, for platforms that
    # expose one (currently TPC benchmarks on Databricks), the physical
    # rendering strategy actually used.
    #
    # Tri-state, deliberately: `None` means the bundle never recorded a
    # logical tuning profile at all -- unknown, not "rendered nothing" --
    # e.g. a legacy bundle predating this field. `[]` means a logical
    # profile WAS recorded and it genuinely rendered zero physical
    # mechanisms -- a real, comparable value (this is exactly the ADR-2
    # motivating case: one platform renders six mechanisms, another renders
    # zero, for the same tuned template). Collapsing these to the same value
    # anywhere downstream would make a legacy/unknown bundle compared against
    # a modern zero-mechanism bundle look like a genuine "different
    # mechanisms" mismatch instead of "nothing to compare".
    physical_mechanisms: list[str] | None = None
    physical_rendering_id: str | None = None
    basis_availability: BasisAvailability | None = None


# ---------------------------------------------------------------------------
# Ranking eligibility helpers
# ---------------------------------------------------------------------------


def is_ranking_eligible(entry: ManifestEntry) -> bool:
    """Return True if this entry may appear in ranked tables."""
    return (
        entry.visibility in RANKING_ELIGIBLE_VISIBILITIES
        and entry.trust_label in RANKING_ELIGIBLE_TRUST_LABELS
        and entry.compliance_class not in UNOFFICIAL_COMPLIANCE_CLASSES
        and entry.failed_query_count == 0
        and not validation_status_is_non_clean(entry.validation_status)
        and custom_tuning_is_materially_applied(entry)
        and entry.comparison_exclusion_reason is None
    )


def custom_tuning_is_materially_applied(entry: ManifestEntry) -> bool:
    """Return whether a custom-mode run has execution-derived applied tuning evidence.

    ``custom`` records how tuning was requested, not whether the adapter changed
    physical execution.  Fail closed for legacy/unknown, noop, and failed custom
    runs so a configuration label alone cannot create a ranked tuning claim.
    Other canonical modes retain their existing ranking policy.
    """
    return entry.tuning_mode != "custom" or entry.tuning_validation_status in APPLIED_TUNING_STATUSES


def ranking_exclusion_reason(entry: ManifestEntry, primary_metric: str | None = None) -> str | None:
    """Return the row-level reason an entry cannot receive a rank."""
    if entry.visibility not in RANKING_ELIGIBLE_VISIBILITIES:
        return "visibility_not_rankable"
    if entry.trust_label not in RANKING_ELIGIBLE_TRUST_LABELS:
        return "trust_not_rankable"
    if entry.compliance_class in UNOFFICIAL_COMPLIANCE_CLASSES:
        return "unofficial_compliance"
    if entry.failed_query_count != 0:
        return "failed_queries"
    if validation_status_is_non_clean(entry.validation_status):
        return "validation_not_clean"
    if not custom_tuning_is_materially_applied(entry):
        return "tuning_not_applied"
    if entry.comparison_exclusion_reason is not None:
        return entry.comparison_exclusion_reason

    metric = primary_metric or get_ranking_config(entry.benchmark).primary_metric
    value = entry.power_score if metric == "power_score" else entry.display_geomean_ms
    if value is None:
        return "missing_primary_metric"
    if not math.isfinite(float(value)) or float(value) <= 0:
        return "non_positive_primary_metric"
    return None


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
    has_display_timing: bool = False
    logical_query_count: int = 0
    valid_query_count: int = 0
    missing_query_count: int = 0
    zero_timing_count: int = 0
    display_exclusion_reason: str | None = None
    comparison_exclusion_reason: str | None = None
    ranking_exclusion_reason: str | None = None
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


# ---------------------------------------------------------------------------
# Bundle input document (schema-v2 result bundle JSON, ingest side)
# ---------------------------------------------------------------------------


class _BundleBlock(BaseModel):
    """Lenient base for schema-v2 bundle input blocks.

    The explorer input gate (``_ensure_explorer_input_schema``) only pins the
    bundle schema version, not block structure, so every nested block carries
    legacy variants: missing blocks, explicit nulls, and occasionally a scalar
    where a mapping belongs. Coercing all of those to an empty block preserves
    the historical ingest behavior (every extractor treats them as "absent")
    while letting the rest of the pipeline work with typed models. Unknown
    keys are kept (``extra=\"allow\"``) so the typed view never drops
    evidence the raw bundle carries.
    """

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def _coerce_mapping(cls, data: Any) -> Any:
        if isinstance(data, Mapping):
            return data
        return {}


class BundleRunBlock(_BundleBlock):
    """Typed view of a bundle ``run`` block."""

    # Timestamp stays untyped: ``_utc_run_date_from_timestamp`` enforces the
    # strict UTC-calendar-date grammar and must keep raising its own errors.
    timestamp: Any = None
    total_duration_ms: float = 0.0

    @field_validator("total_duration_ms", mode="before")
    @classmethod
    def _coerce_duration(cls, value: Any) -> Any:
        if value is None:
            return 0.0
        return value


class BundleBenchmarkBlock(_BundleBlock):
    """Typed view of a bundle ``benchmark`` block."""

    id: str = "unknown"
    scale_factor: float = 0.0
    test_type: str | None = None
    compliance_class: str | None = None

    @field_validator("test_type", mode="before")
    @classmethod
    def _coerce_test_type(cls, value: Any) -> Any:
        # Falsy (including "") means "not recorded"; the extractor falls back
        # to the phases block. Verbatim otherwise: no stripping.
        return str(value) if value else None

    @field_validator("compliance_class", mode="before")
    @classmethod
    def _coerce_compliance_class(cls, value: Any) -> Any:
        # Verbatim ingest: only an explicit null means "not recorded".
        return None if value is None else str(value)


class BundleLogicalProfile(_BundleBlock):
    """Typed view of ``platform.tuning.logical_profile`` (ADR-2 section 3)."""

    physical_mechanisms: Any = None
    physical_rendering_id: Any = None


class BundleAppliedBlock(_BundleBlock):
    """Typed view of ``platform.tuning.applied``."""

    receipt: Any = None


class BundleTuningBlock(_BundleBlock):
    """Typed view of a bundle ``platform.tuning`` summary block."""

    requested_config_hash: str | None = None
    applied_ledger_hash: str | None = None
    validation_status: str | None = None
    tuning_policy_generation: str | None = None
    requested: Any = None
    applied: BundleAppliedBlock = Field(default_factory=BundleAppliedBlock)
    logical_profile: BundleLogicalProfile | None = None

    @field_validator("logical_profile", mode="before")
    @classmethod
    def _coerce_logical_profile(cls, value: Any) -> Any:
        # A non-object profile is "no profile recorded" (unknown), not an
        # empty recording: only a real mapping carries the tri-state split
        # `_physical_mechanisms` depends on.
        if value is None or isinstance(value, Mapping):
            return value
        return None

    @field_validator(
        "requested_config_hash",
        "applied_ledger_hash",
        "validation_status",
        "tuning_policy_generation",
        mode="before",
    )
    @classmethod
    def _coerce_verbatim_hash(cls, value: Any) -> Any:
        # ADR-1 identities are ingested verbatim and display-only; falsy
        # values (including explicit nulls) mean "not recorded".
        return str(value) if value else None


class BundleCloudBlock(_BundleBlock):
    """Typed view of a bundle ``platform.cloud`` block."""

    provider: Any = None
    region: Any = None
    location: Any = None


class BundleComputeBlock(_BundleBlock):
    """Typed view of a bundle ``platform.compute`` block."""

    node_type: Any = None
    warehouse_size: Any = None
    warehouse: Any = None
    cluster_id: Any = None
    cluster_name: Any = None
    rpu: Any = None
    serverless_slots: Any = None
    worker_shape: Any = None
    driver_shape: Any = None


class BundleStorageBlock(_BundleBlock):
    """Typed view of a bundle ``platform.storage`` block."""

    table_format: Any = None


class BundlePlatformConfig(_BundleBlock):
    """Typed view of a bundle ``platform.config`` block."""

    execution_mode: Any = None


class BundleDeploymentBlock(_BundleBlock):
    """Typed view of a bundle ``platform.deployment`` block."""

    deployment_type: Any = None
    endpoint_class: Any = None
    cloud_provider: Any = None
    cloud_region: Any = None
    instance_type: Any = None
    warehouse_size: Any = None
    node_count: Any = None
    cluster_size: Any = None
    storage_format: Any = None
    storage_tier: Any = None


class BundlePlatformRuntime(_BundleBlock):
    """Typed view of an ``environment.platform_runtime`` block."""

    runtime_type: Any = None


class BundleContainerBlock(_BundleBlock):
    """Typed view of an ``environment.container`` block (presence only)."""


class BundlePlatformBlock(_BundleBlock):
    """Typed view of a bundle ``platform`` block."""

    name: str = "unknown"
    version: Any = None
    client_version: Any = None
    config: BundlePlatformConfig = Field(default_factory=BundlePlatformConfig)
    tuning: BundleTuningBlock = Field(default_factory=BundleTuningBlock)
    deployment: BundleDeploymentBlock = Field(default_factory=BundleDeploymentBlock)
    cloud: BundleCloudBlock = Field(default_factory=BundleCloudBlock)
    compute: BundleComputeBlock = Field(default_factory=BundleComputeBlock)
    storage: BundleStorageBlock = Field(default_factory=BundleStorageBlock)

    @field_validator("name", mode="before")
    @classmethod
    def _coerce_name(cls, value: Any) -> Any:
        if value is None:
            return "unknown"
        return value


class BundleConfigBlock(_BundleBlock):
    """Typed view of a bundle top-level ``config`` block."""

    tuning_mode: Any = None
    tuning_config: Any = None
    tuning: Any = None
    execution_mode: Any = None
    mode: Any = None
    options: Any = None


class BundleExecutionBlock(_BundleBlock):
    """Typed view of a bundle top-level ``execution`` block."""

    tuning_mode: Any = None
    execution_mode: Any = None
    mode: Any = None
    driver_version_actual: Any = None
    driver_version_resolved: Any = None
    driver_version_requested: Any = None
    driver_actual_version: Any = None
    driver_resolved_version: Any = None
    driver_requested_version: Any = None


class BundleSummaryQueries(_BundleBlock):
    """Typed view of a bundle ``summary.queries`` block."""

    total: Any = None


class BundleTpcMetrics(_BundleBlock):
    """Typed view of a bundle ``summary.tpc_metrics`` block."""

    power_at_size: Any = None
    qphh_at_size: Any = None
    qphds_at_size: Any = None


class BundleSummaryBlock(_BundleBlock):
    """Typed view of a bundle ``summary`` block."""

    queries: BundleSummaryQueries = Field(default_factory=BundleSummaryQueries)
    # ``validation`` is str-or-mapping by schema; ``normalize_validation_status``
    # owns that split, so the leaf stays variant-typed.
    validation: Any = None
    tpc_metrics: BundleTpcMetrics = Field(default_factory=BundleTpcMetrics)


class BundlePhaseBlock(_BundleBlock):
    """Typed view of one entry in a bundle ``phases`` block."""

    duration_ms: Any = None


class BundleQueryRow(_BundleBlock):
    """One execution row from a bundle ``queries`` list.

    ``query_id`` is resolved at parse time from the legacy ``id`` / ``query_id``
    key split. Numeric leaves stay variant-typed: each consumer coerces them
    with its own fallback (skip the row, default to zero, ...), so the model
    preserves the raw value instead of pre-deciding.
    """

    query_id: str = ""
    run_type: str | None = None
    status: str = "pass"
    ms: Any = None
    execution_time_ms: Any = None
    iter: Any = None
    stream: Any = None
    dataframe_skip_summary: Any = None

    @model_validator(mode="before")
    @classmethod
    def _resolve_identity(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return {}
        resolved = dict(data)
        resolved["query_id"] = str(data.get("id") or data.get("query_id", ""))
        if "status" in data and data["status"] is None:
            # Explicit null is not a pass; downstream normalizes any
            # non-allow-listed value to "fail".
            resolved["status"] = "fail"
        return resolved

    @field_validator("run_type", mode="before")
    @classmethod
    def _coerce_run_type(cls, value: Any) -> Any:
        if value is None:
            return None
        return value if isinstance(value, str) else str(value)


class BundleStatementOverhead(_BundleBlock):
    """Typed view of ``environment.client_link.statement_overhead_ms``."""

    min: Any = None
    median: Any = None


class BundleClientLink(_BundleBlock):
    """Typed view of an ``environment.client_link`` block."""

    collection_status: Any = None
    client_region: Any = None
    client_cloud: Any = None
    statement_overhead_ms: BundleStatementOverhead = Field(default_factory=BundleStatementOverhead)


class BundleEnvironmentBlock(_BundleBlock):
    """Typed view of a bundle ``environment`` block."""

    os: Any = None
    arch: Any = None
    cpu_count: Any = None
    memory_gb: Any = None
    python: Any = None
    cpu_model: Any = None
    cpu_identity_provenance: Any = None
    platform_runtime: BundlePlatformRuntime = Field(default_factory=BundlePlatformRuntime)
    container: BundleContainerBlock = Field(default_factory=BundleContainerBlock)
    client_link: BundleClientLink = Field(default_factory=BundleClientLink)


class BundleProvenanceBlock(_BundleBlock):
    """Typed view of a bundle ``provenance`` block."""

    funding: Any = None


class BundleDocument(_BundleBlock):
    """Typed view of one schema-v2 result bundle for explorer ingest.

    This is the ingest-side counterpart to the ``ManifestEntry`` /
    ``DetailResult`` read models: every transformer extractor takes this
    document (or one of its blocks) instead of a raw ``dict[str, Any]``.
    Only the fields the explorer projects are declared; everything else
    rides along as extras.
    """

    run: BundleRunBlock = Field(default_factory=BundleRunBlock)
    benchmark: BundleBenchmarkBlock = Field(default_factory=BundleBenchmarkBlock)
    platform: BundlePlatformBlock = Field(default_factory=BundlePlatformBlock)
    config: BundleConfigBlock = Field(default_factory=BundleConfigBlock)
    execution: BundleExecutionBlock = Field(default_factory=BundleExecutionBlock)
    summary: BundleSummaryBlock = Field(default_factory=BundleSummaryBlock)
    phases: dict[str, BundlePhaseBlock] = Field(default_factory=dict)
    queries: list[BundleQueryRow] = Field(default_factory=list)
    environment: BundleEnvironmentBlock = Field(default_factory=BundleEnvironmentBlock)
    provenance: BundleProvenanceBlock = Field(default_factory=BundleProvenanceBlock)
    cost: dict[str, Any] = Field(default_factory=dict)
    normalized_cost: dict[str, Any] = Field(default_factory=dict)

    @field_validator("phases", mode="before")
    @classmethod
    def _coerce_phases(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return {}
        return {str(name): block for name, block in value.items()}

    @field_validator("queries", mode="before")
    @classmethod
    def _coerce_queries(cls, value: Any) -> Any:
        # Non-object rows are skipped downstream; drop them at parse time so
        # the typed list only carries real execution rows.
        if not isinstance(value, list):
            return []
        return [row for row in value if isinstance(row, Mapping)]

    @field_validator("cost", "normalized_cost", mode="before")
    @classmethod
    def _coerce_cost_block(cls, value: Any) -> Any:
        # Cost blocks stay raw mappings: ``_normalized_cost_from_block`` owns
        # their strict validation and error messages.
        if isinstance(value, Mapping):
            return dict(value)
        return {}


__all__ = [
    "BenchmarkSummary",
    "BundleAppliedBlock",
    "BundleBenchmarkBlock",
    "BundleConfigBlock",
    "BundleDeploymentBlock",
    "BundleDocument",
    "BundleEnvironmentBlock",
    "BundleExecutionBlock",
    "BundleLogicalProfile",
    "BundlePlatformBlock",
    "BundleProvenanceBlock",
    "BundleQueryRow",
    "BundleRunBlock",
    "BundleSummaryBlock",
    "BundleTuningBlock",
    "CANONICAL_BENCHMARK_ALIASES",
    "DetailResult",
    "ManifestEntry",
    "PercentileStats",
    "PlatformRow",
    "QueryDisplayTiming",
    "QueryTiming",
    "RankingConfig",
    "RANKING_ELIGIBLE_TRUST_LABELS",
    "UNOFFICIAL_COMPLIANCE_CLASSES",
    "RANKING_ELIGIBLE_VISIBILITIES",
    "RANKING_METRIC_BY_FAMILY",
    "TimingEligibility",
    "display_timing_is_valid",
    "get_ranking_config",
    "canonical_benchmark_slug",
    "canonical_phase",
    "is_ranking_eligible",
    "MetaRank",
    "ranking_exclusion_reason",
    "select_canonical_row",
    "timing_eligibility",
    "timing_exclusion_reason",
    "unavailable_normalized_cost_payload",
]
