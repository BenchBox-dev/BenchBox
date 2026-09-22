"""Validate submission bundles in results-data/bundles/.

Used by CI to check that PRs adding result bundles conform to schema-v2,
have sane timing data, valid platform/benchmark names, and (when a
submission manifest is present) matching SHA-256 hashes. The public
CLI wrapper is `scripts/validate_submission.py`; this module is the
shared implementation used by both develop and the slim published-results
branch.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import re
import statistics
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


def _load_schema_policy_helpers():
    """Load version helpers without running results package initializers.

    Prefers the canonical package import; on the slim published-results
    branch mirror (which ships this module plus
    ``benchbox/core/results/schema_policy.py`` without the installable
    package) loads the helper straight from the mirrored file, mirroring
    how ``_load_bundle_failed_query_count`` loads its policy. There is a
    single implementation: no inline duplicate lives here.
    """
    try:
        from benchbox.core.results.schema_policy import (
            PUBLIC_SUBMISSION_SCHEMA_POLICY,
            result_schema_version_value,
        )

        return PUBLIC_SUBMISSION_SCHEMA_POLICY, result_schema_version_value
    except ImportError:
        pass
    helper_path = Path(__file__).resolve().parents[1] / "core" / "results" / "schema_policy.py"
    spec = importlib.util.spec_from_file_location("_benchbox_schema_policy", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load schema version policy from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclass processing resolves types through
    # sys.modules[module.__name__] and fails on an unregistered module.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module.PUBLIC_SUBMISSION_SCHEMA_POLICY, module.result_schema_version_value


PUBLIC_SUBMISSION_SCHEMA_POLICY, result_schema_version_value = _load_schema_policy_helpers()


# Canonical provenance vocabulary. Import from the one source of truth when the
# full package is present; fall back to inline literals on the slim
# published-results branch mirror (which ships this module without benchbox/).
# Keep the fallback in lockstep with benchbox/core/results/provenance.py.
try:
    from benchbox.core.results.provenance import FUNDING_SOURCES, RESULT_SOURCES
except ImportError:  # pragma: no cover - slim published-results branch mirror.
    FUNDING_SOURCES = ("employer", "personal", "free-trial", "vendor-sponsored", "grant", "unspecified")
    RESULT_SOURCES = ("internal", "community", "vendor")


def _load_bundle_failed_query_count():
    """Load the stdlib-only helper without running results package initializers."""
    helper_path = Path(__file__).resolve().parents[1] / "core" / "results" / "query_status.py"
    spec = importlib.util.spec_from_file_location("_benchbox_query_status", helper_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load failed-query policy from {helper_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.bundle_failed_query_count


bundle_failed_query_count = _load_bundle_failed_query_count()

# Max length for the optional free-text submission_notes manifest field.
SUBMISSION_NOTES_MAX_LEN = 500

# Applied tuning receipts are attacker-controlled submission companions. These
# ceilings sit well above realistic runs while bounding validation and Explorer
# ingestion work. Oversized submissions fail loudly; the Explorer pipeline has
# a separate defensive truncation marker for already-published legacy inputs.
APPLIED_RECEIPT_MAX_ENTRIES = 10_000
APPLIED_COMPANION_MAX_BYTES = 8 * 1024 * 1024

# ---------------------------------------------------------------------------
# Schema-v2 required top-level keys
# ---------------------------------------------------------------------------

REQUIRED_TOP_KEYS = ("result_schema_version", "run", "benchmark", "platform", "summary", "queries")
REQUIRED_RUN_KEYS = {"id", "timestamp", "total_duration_ms"}
REQUIRED_BENCHMARK_KEYS = {"id", "scale_factor"}
REQUIRED_PLATFORM_KEYS = {"name"}
REQUIRED_QUERY_KEYS = {"id", "ms"}

# Standalone fallback used when this module is mirrored to published-results
# without the full BenchBox package.
ACCEPTED_VERSION_PREFIX = "2."
NUMERIC_SCHEMA_VERSION_RE = re.compile(r"^\d+\.\d+(?:\.\d+)?$")
ROW_COUNT_VALIDATION_SCHEMA_VERSION = (2, 2)
ROW_COUNT_VALIDATION_MESSAGE_MAX_CHARS = 500
ROW_COUNT_VALIDATION_STATUSES = frozenset({"PASSED", "FAILED", "SKIPPED", "ERROR"})
ROW_COUNT_VALIDATION_FIELDS = frozenset({"status", "expected", "actual", "error", "warning"})
ROW_COUNT_VALIDATION_REQUIRED_FIELDS = frozenset({"status", "expected", "actual"})

# Companion file suffixes - skipped during bundle discovery, and copied
# alongside their result bundle by publish/submit. `.applied.json` carries the
# applied tuning ledger + `applied_ledger_hash`; leaving it out of this tuple
# dropped that evidence from public bundles and surfaced it as a standalone run
# in discovery paths.
COMPANION_SUFFIXES = (".plans.json", ".tuning.json", ".applied.json")
SUBMISSION_MANIFEST_FILENAME = "submission-manifest.json"
SUBMISSION_MANIFEST_SUFFIX = ".manifest.json"
PUBLIC_CLEAN_VALIDATION_STATUS = "passed"
# Maintainer seed corpus includes partial and historically unvalidated cohorts
# by design. Trusted mirror validation may retain these explicit non-clean
# states; community submissions may not. Explorer ranking still excludes every
# non-clean state, including ``not_run``.
PUBLIC_MIRROR_ALLOWED_VALIDATION_STATUSES = frozenset({"passed", "partial", "not_run"})
PUBLIC_NON_CLEAN_TRANSLATION_STATUSES = {"fallback", "failed"}
CLI_REFUSED_COMPLIANCE_CLASSES = frozenset({"unofficial_nonstandard", "unofficial_subscale"})

# Known benchmarks and platforms - warn (not fail) on unknown values.
KNOWN_BENCHMARKS = {
    "tpch",
    "tpcds",
    "ssb",
    "star_schema",
    "clickbench",
    "nyctaxi",
    "flightdata",
    "tsbs-devops",
    "tsbs_devops",
    "h2odb",
    "amplab",
    "coffeeshop",
    "joinorder",
    "tpch_skew",
    "tpchavoc",
    "datavault",
    "tpcdi",
    "tpcds_obt",
    "read_primitives",
    "write_primitives",
    "metadata_primitives",
    "transaction_primitives",
    "ai_primitives",
    "vector_search",
}
KNOWN_PLATFORMS = {
    # Core
    "duckdb",
    "datafusion",
    "ducklake",
    "polars",
    "sqlite",
    "motherduck",
    # SQL - cloud & managed
    "clickhouse",
    "clickhouse-local",
    "clickhouse-server",
    "clickhouse-cloud",
    "snowflake",
    "databricks",
    "bigquery",
    "redshift",
    "athena",
    "firebolt",
    # SQL - self-hosted & extensions
    "postgresql",
    "timescaledb",
    "pg-duckdb",
    "pg_duckdb",
    "pg-mooncake",
    "pg_mooncake",
    "trino",
    "starburst",
    "presto",
    "influxdb",
    "questdb",
    "starrocks",
    "databend",
    "doris",
    # Spark-family
    "spark",
    "pyspark",
    "lakesail",
    # DataFrame
    "pandas",
    "cudf",
    "dask",
    # Microsoft Fabric / Synapse
    "synapse",
    "fabric_dw",
    "fabric-lakehouse",
    "fabric-spark",
}

# Sanity thresholds
MAX_QUERY_DURATION_MS = 7_200_000  # 2 hours per query
MAX_TOTAL_DURATION_MS = 86_400_000  # 24 hours total

# Normalized cost provenance required before public leaderboard cost totals
# are accepted. Keep this standalone so the published-results validator can run
# without importing the full BenchBox package.
NORMALIZED_COST_MODEL_SOURCE = "benchbox.core.cost.pricing"
NORMALIZED_COST_REQUIRED_KEYS = {
    "normalized_cost_usd",
    "cost_model_version",
    "cost_model_source",
    "cost_scope",
    "cost_status",
    "billing_unit",
    "pricing_region",
}
NORMALIZED_COST_SCOPES = {"compute_only", "compute_plus_storage"}
NORMALIZED_COST_STATUSES = {"normalized", "not_applicable_local", "unavailable"}

# Concrete billing_unit vocabulary the cost calculator can emit for normalized
# cost. Scan-priced platforms report the unit actually billed: BigQuery is
# priced per tebibyte ("tib_scanned"); Athena and Synapse serverless print
# "TB", read as decimal terabytes ("tb_scanned"). See
# docs/development/adr/adr-billing-unit-tb-tib-contract.md. Legacy bundles
# that recorded BigQuery as "tb_scanned" stay valid: the value remains in the
# vocabulary, so no result-bundle schema bump is implied.
NORMALIZED_COST_BILLING_UNITS = frozenset(
    {
        "tib_scanned",
        "tb_scanned",
        "credit",
        "node_hour",
        "dbu",
        "dwu_hour",
        "cu_hour",
        "fbu",
        "instance_hour",
    }
)
DIRECT_COST_TOTAL_KEYS = ("total_usd", "total_cost")
TOP_LEVEL_DIRECT_COST_KEYS = ("cost_usd",)


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class ValidationResult:
    """Collects errors and warnings for a single bundle."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []
        # Metadata extracted during validation, used by format_pr_comment.
        self.benchmark_id: str = "-"
        self.platform_name: str = "-"
        self.scale_factor: str = "-"

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _capture_metadata(data: dict, vr: ValidationResult) -> None:
    """Pull benchmark/platform identifiers out of the bundle for PR-comment formatting."""
    bm = data.get("benchmark")
    if isinstance(bm, dict):
        vr.benchmark_id = bm.get("id", "-")
        sf = bm.get("scale_factor")
        if sf is not None:
            vr.scale_factor = str(sf)
    pl = data.get("platform")
    if isinstance(pl, dict):
        vr.platform_name = pl.get("name", "-")


def _validate_version(version: Any, vr: ValidationResult) -> None:
    if PUBLIC_SUBMISSION_SCHEMA_POLICY is not None:
        decision = PUBLIC_SUBMISSION_SCHEMA_POLICY.evaluate(version)
        if not decision.accepted:
            vr.error(decision.error_message())
        return

    if (
        not isinstance(version, str)
        or not NUMERIC_SCHEMA_VERSION_RE.fullmatch(version.strip())
        or not version.strip().startswith(ACCEPTED_VERSION_PREFIX)
    ):
        vr.error(
            f"Unsupported schema version for public submission schema policy: {version!r}. "
            "public submission schema policy accepts numeric schema version family 2.x."
        )


def _validate_run_section(run: Any, vr: ValidationResult) -> None:
    if not isinstance(run, dict):
        vr.error("'run' must be a dict")
        return
    missing_run = REQUIRED_RUN_KEYS - set(run.keys())
    if missing_run:
        vr.error(f"Missing keys in 'run': {sorted(missing_run)}")

    total_ms = run.get("total_duration_ms")
    if total_ms is None:
        return
    try:
        total_ms_f = float(total_ms)
    except (TypeError, ValueError):
        vr.error(f"Invalid total_duration_ms: {total_ms!r}")
        return
    if total_ms_f < 0:
        vr.error(f"Negative total_duration_ms: {total_ms_f}")
    elif total_ms_f > MAX_TOTAL_DURATION_MS:
        vr.warn(f"Unusually long total_duration_ms: {total_ms_f:.0f} (>{MAX_TOTAL_DURATION_MS})")


def _validate_benchmark_section(benchmark: Any, vr: ValidationResult) -> None:
    if not isinstance(benchmark, dict):
        vr.error("'benchmark' must be a dict")
        return
    missing_bm = REQUIRED_BENCHMARK_KEYS - set(benchmark.keys())
    if missing_bm:
        vr.error(f"Missing keys in 'benchmark': {sorted(missing_bm)}")

    bm_id = benchmark.get("id", "")
    if isinstance(bm_id, str) and bm_id and bm_id not in KNOWN_BENCHMARKS:
        vr.warn(f"Unknown benchmark id: {bm_id!r}")

    sf = benchmark.get("scale_factor")
    if sf is None:
        return
    try:
        sf_f = float(sf)
    except (TypeError, ValueError):
        vr.error(f"Invalid scale_factor: {sf!r}")
        return
    if sf_f <= 0:
        vr.error(f"scale_factor must be positive: {sf_f}")


# ---------------------------------------------------------------------------
# Timing plausibility (warnings only)
#
# These gates catch obviously incorrect measurement regimes — overhead-
# dominated runs whose timings cannot reflect query execution — without
# refusing anything. Every rule emits ``vr.warn`` so the finding is visible
# in the PR comment and available to the later warn-require-override
# contract, but validation still passes. Thresholds were calibrated on the
# September cloud TPC-H runs (Snowflake flat at ~4.5s across 100x data with
# max/min 1.43 and CV 0.08, versus BigQuery 4.51/0.34 and Databricks
# 11.01/0.89 at the same scale).
# ---------------------------------------------------------------------------

# Benchmarks whose queries vary by design. Micro-benchmarks (primitives and
# friends) are uniform by construction — a tight band there is expected, not
# a defect — so the plateau gate stays scoped to this allowlist.
TIMING_PLAUSIBILITY_HETEROGENEOUS_BENCHMARKS = frozenset(
    {
        "tpch",
        "tpch_skew",
        "tpchavoc",
        "tpcds",
        "ssb",
        "star_schema",
        "clickbench",
    }
)

# Within-run spread below both of these marks a plateau. The two conditions
# are near-redundant by construction; both are reported so the PR comment
# carries the raw numbers for human judgment.
PLATEAU_MAX_MIN_RATIO = 2.0
PLATEAU_MAX_CV = 0.15
# Spreads over fewer distinct queries are unevaluable noise, not evidence.
PLATEAU_MIN_DISTINCT_QUERIES = 3

# Cross-scale comparison only runs across a 10x or wider scale span; below
# that, engine noise dominates and the rule stays silent (insufficient
# history, not a pass).
SCALE_INVARIANCE_MIN_SPAN = 10.0
SCALE_INVARIANCE_MIN_GEOMEAN_RATIO = 1.5
SCALE_INVARIANCE_MIN_PER_QUERY_MEDIAN_RATIO = 1.3

# Cross-platform floor comparison needs at least this many peers before the
# median is trustworthy, and stays informational: a genuinely slower engine
# must never be refused by peer comparison alone.
FLOOR_OUTLIER_PEER_MULTIPLE = 3.0
FLOOR_OUTLIER_MIN_PEERS = 2

# Absolute floor for tiny data: a sub-second dataset answering no query
# faster than this is overhead-dominated. Rows evidence is optional — when
# ``rows_loaded`` is absent the warning says so instead of silently passing.
SMALL_SCALE_MAX_FACTOR = 0.1
SMALL_SCALE_FLOOR_MIN_MS = 2000.0
SMALL_SCALE_MAX_ROWS_LOADED = 1_000_000

_PASS_TIMING_STATUSES = frozenset({"SUCCESS", "PASS"})


def _measurement_ms_by_query(data: dict[str, Any]) -> dict[str, list[float]]:
    """Group positive SUCCESS measurement timings by query id.

    Mirrors the query-row conventions used elsewhere in this module: an
    absent ``run_type`` defaults to measurement, and only SUCCESS rows
    count as measurement evidence. Rows with unparseable, non-positive,
    or sub-millisecond ``ms`` are dropped — all-zero runs are owned by
    the queries-section gate, and sub-millisecond minima would make
    spread ratios noise-dominated (timer resolution, not engine speed).
    """
    queries = data.get("queries")
    if not isinstance(queries, list):
        return {}
    grouped: dict[str, list[float]] = {}
    for q in queries:
        if not isinstance(q, dict):
            continue
        run_type = str(q.get("run_type") or "measurement").lower()
        if run_type != "measurement":
            continue
        status = q.get("status")
        if not isinstance(status, str) or status.upper() not in _PASS_TIMING_STATUSES:
            continue
        qid = q.get("id")
        if not isinstance(qid, str) or not qid:
            continue
        try:
            ms = float(q.get("ms"))
        except (TypeError, ValueError):
            continue
        if not math.isfinite(ms) or ms < 1.0:
            continue
        grouped.setdefault(qid, []).append(ms)
    return grouped


def _bundle_benchmark_id(data: dict[str, Any]) -> str | None:
    benchmark = data.get("benchmark")
    if not isinstance(benchmark, dict):
        return None
    bm_id = benchmark.get("id")
    if not isinstance(bm_id, str) or not bm_id.strip():
        return None
    # "TPCH" names the same family as "tpch" for scoping, cohorting, and
    # messages alike; casing or padding must not change the verdict.
    return bm_id.strip().casefold()


def _bundle_platform_key(data: dict[str, Any]) -> str | None:
    platform = data.get("platform")
    if not isinstance(platform, dict):
        return None
    name = platform.get("name")
    return str(name).strip().lower() if name is not None and str(name).strip() else None


def _bundle_scale_factor(data: dict[str, Any]) -> float | None:
    benchmark = data.get("benchmark")
    if not isinstance(benchmark, dict):
        return None
    try:
        sf = float(benchmark.get("scale_factor"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(sf) or sf <= 0:
        return None
    return sf


def _bundle_passed_validation(data: dict[str, Any]) -> bool:
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return False
    return _normalize_status(summary.get("validation")) == PUBLIC_CLEAN_VALIDATION_STATUS


def _bundle_geomean_ms(data: dict[str, Any]) -> float | None:
    """Geometric-mean timing for cross-bundle comparison, or None.

    Geometric only: falling back to an arithmetic mean would compare mixed
    metrics across bundles while the warning message claims "geomean".
    A bundle without a recorded geometric mean simply does not participate.
    """
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return None
    timing = summary.get("timing")
    if not isinstance(timing, dict):
        return None
    try:
        value = float(timing.get("geometric_mean_ms"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def _bundle_rows_loaded(data: dict[str, Any]) -> int | None:
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return None
    payload = summary.get("data")
    if not isinstance(payload, dict):
        return None
    rows = payload.get("rows_loaded")
    if isinstance(rows, bool):
        return None
    if isinstance(rows, float) and not math.isfinite(rows):
        # JSON numbers like 1e309 parse to inf; int() would raise
        # OverflowError, so treat non-finite floats as unreported.
        return None
    try:
        value = int(rows)
    except (TypeError, ValueError, OverflowError):
        return None
    return value if value >= 0 else None


def _warn_timing_plateau(data: dict[str, Any], vr: ValidationResult) -> None:
    """Warn when a heterogeneous benchmark shows an implausibly tight band."""
    bm_id = _bundle_benchmark_id(data)
    if bm_id not in TIMING_PLAUSIBILITY_HETEROGENEOUS_BENCHMARKS:
        return
    grouped = _measurement_ms_by_query(data)
    if len(grouped) < PLATEAU_MIN_DISTINCT_QUERIES:
        return
    means = [statistics.fmean(samples) for samples in grouped.values()]
    peak = max(means)
    floor = min(means)
    ratio = peak / floor
    cv = statistics.pstdev(means) / statistics.fmean(means)
    if ratio < PLATEAU_MAX_MIN_RATIO and cv < PLATEAU_MAX_CV:
        vr.warn(
            f"timing-plateau: benchmark {bm_id!r} per-query means span "
            f"{floor:.0f}-{peak:.0f}ms (max/min {ratio:.2f}, CV {cv:.2f}); "
            "heterogeneous queries should vary more — check for fixed-overhead-dominated measurement"
        )


def _warn_small_scale_floor(data: dict[str, Any], vr: ValidationResult) -> None:
    """Warn when tiny data answers nothing fast."""
    sf = _bundle_scale_factor(data)
    if sf is None or sf > SMALL_SCALE_MAX_FACTOR:
        return
    grouped = _measurement_ms_by_query(data)
    if not grouped:
        return
    floor = min(ms for samples in grouped.values() for ms in samples)
    if floor <= SMALL_SCALE_FLOOR_MIN_MS:
        return
    rows = _bundle_rows_loaded(data)
    if rows is not None and rows >= SMALL_SCALE_MAX_ROWS_LOADED:
        return
    rows_note = f"{rows} rows loaded" if rows is not None else "rows_loaded unreported"
    vr.warn(
        f"small-scale-floor: scale factor {sf:g} ({rows_note}) but fastest measurement is "
        f"{floor:.0f}ms — fixed overhead dominates; expected sub-second answers on this data volume"
    )


def _passed_cohorts(
    entries: list[tuple[dict[str, Any], ValidationResult]],
) -> tuple[
    dict[tuple[str, str], list[tuple[dict[str, Any], ValidationResult]]],
    dict[tuple[str, float], list[tuple[dict[str, Any], ValidationResult]]],
]:
    """Group clean-validation bundles by platform cohort and peer set.

    Only bundles claiming clean validation participate, so mirror-lane
    partials never distort a comparison. Cohorts are further scoped to
    heterogeneous benchmarks — micro-benchmarks are uniform by
    construction, so a tight band or a flat scale curve there is expected
    signal, not a plausibility finding (same rationale as the C1 scope).
    """
    cohorts: dict[tuple[str, str], list[tuple[dict[str, Any], ValidationResult]]] = {}
    peers: dict[tuple[str, float], list[tuple[dict[str, Any], ValidationResult]]] = {}
    for data, vr in entries:
        if not _bundle_passed_validation(data):
            continue
        bm_id = _bundle_benchmark_id(data)
        if bm_id not in TIMING_PLAUSIBILITY_HETEROGENEOUS_BENCHMARKS:
            continue
        platform = _bundle_platform_key(data)
        sf = _bundle_scale_factor(data)
        if bm_id is None:
            continue
        if platform is not None:
            cohorts.setdefault((bm_id, platform), []).append((data, vr))
        if sf is not None:
            peers.setdefault((bm_id, sf), []).append((data, vr))
    return cohorts, peers


def _warn_scale_invariance(
    cohorts: dict[tuple[str, str], list[tuple[dict[str, Any], ValidationResult]]],
) -> None:
    """Warn when timings barely move across a 10x-or-wider scale span."""
    for (bm_id, _platform), members in cohorts.items():
        scales = sorted({sf for data, _ in members if (sf := _bundle_scale_factor(data)) is not None})
        if len(scales) < 2 or scales[-1] / scales[0] < SCALE_INVARIANCE_MIN_SPAN:
            continue
        lo, hi = scales[0], scales[-1]
        lo_geo = [
            g for data, _ in members if _bundle_scale_factor(data) == lo and (g := _bundle_geomean_ms(data)) is not None
        ]
        hi_geo = [
            g for data, _ in members if _bundle_scale_factor(data) == hi and (g := _bundle_geomean_ms(data)) is not None
        ]
        lo_queries = _merged_query_samples(members, lo)
        hi_queries = _merged_query_samples(members, hi)
        shared = [qid for qid in lo_queries if qid in hi_queries]
        geo_ratio = statistics.fmean(hi_geo) / statistics.fmean(lo_geo) if lo_geo and hi_geo else None
        per_query_ratio = (
            statistics.median(statistics.fmean(hi_queries[qid]) / statistics.fmean(lo_queries[qid]) for qid in shared)
            if shared
            else None
        )
        tripped = (geo_ratio is not None and geo_ratio < SCALE_INVARIANCE_MIN_GEOMEAN_RATIO) or (
            per_query_ratio is not None and per_query_ratio < SCALE_INVARIANCE_MIN_PER_QUERY_MEDIAN_RATIO
        )
        if (geo_ratio is None and per_query_ratio is None) or not tripped:
            continue
        detail = (f"geomean x{geo_ratio:.2f}" if geo_ratio is not None else "geomean unevaluable") + (
            f", per-query median x{per_query_ratio:.2f}" if per_query_ratio is not None else ", per-query unevaluable"
        )
        span = hi / lo
        for data, vr in members:
            if _bundle_scale_factor(data) in (lo, hi):
                vr.warn(
                    f"scale-invariant: benchmark {bm_id!r} grows {span:g}x in scale "
                    f"but timings barely move ({detail}); check for result caching or "
                    "fixed-overhead-dominated measurement"
                )


def _merged_query_samples(
    members: list[tuple[dict[str, Any], ValidationResult]],
    scale: float,
) -> dict[str, list[float]]:
    """Merge measurement samples per query id across members at one scale."""
    merged: dict[str, list[float]] = {}
    for data, _vr in members:
        if _bundle_scale_factor(data) != scale:
            continue
        for qid, samples in _measurement_ms_by_query(data).items():
            merged.setdefault(qid, []).extend(samples)
    return merged


def _warn_floor_outlier(
    peers: dict[tuple[str, float], list[tuple[dict[str, Any], ValidationResult]]],
) -> None:
    """Warn when one bundle's fastest query dwarfs the peer median.

    Peers are distinct platforms: same-platform reruns are consolidated to
    one floor per platform (and never count toward the peer quorum), so
    repeated runs of one engine cannot mark themselves an outlier.

    Informational only: a genuinely slower engine must never be refused by
    peer comparison alone.
    """
    for (bm_id, sf), members in peers.items():
        if len(members) < FLOOR_OUTLIER_MIN_PEERS + 1:
            continue
        floors = _peer_floor_timings(members)
        platforms = [_bundle_platform_key(data) for data, _ in members]
        for index, (_data, vr) in enumerate(members):
            own = floors.get(index)
            if own is None:
                continue
            own_platform = platforms[index]
            by_platform: dict[str, list[float]] = {}
            for other, value in floors.items():
                if other == index:
                    continue
                key = platforms[other]
                if key is None or key == own_platform:
                    continue
                by_platform.setdefault(key, []).append(value)
            if len(by_platform) < FLOOR_OUTLIER_MIN_PEERS:
                continue
            peer_median = statistics.median(statistics.median(values) for values in by_platform.values())
            if own > FLOOR_OUTLIER_PEER_MULTIPLE * peer_median:
                vr.warn(
                    f"floor-outlier (informational): fastest measurement {own:.0f}ms is "
                    f"more than {FLOOR_OUTLIER_PEER_MULTIPLE:g}x the peer median "
                    f"at benchmark {bm_id!r} scale {sf:g} — never refused on this signal alone"
                )


def _peer_floor_timings(
    members: list[tuple[dict[str, Any], ValidationResult]],
) -> dict[int, float]:
    """Fastest positive measurement per member, by member index."""
    floors: dict[int, float] = {}
    for index, (data, _vr) in enumerate(members):
        grouped = _measurement_ms_by_query(data)
        if grouped:
            floors[index] = min(ms for samples in grouped.values() for ms in samples)
    return floors


def _warn_cross_bundle_timing(entries: list[tuple[dict[str, Any], ValidationResult]]) -> None:
    """Warn on scale-invariant and peer-floor outliers within one validation set.

    Operates on bundles validated together (e.g. one submission PR): groups
    with a single scale or without peers stay silent — insufficient history
    is not a pass, it is no finding.
    """
    cohorts, peers = _passed_cohorts(entries)
    _warn_scale_invariance(cohorts)
    _warn_floor_outlier(peers)


def _validate_platform_section(platform: Any, vr: ValidationResult) -> None:
    if not isinstance(platform, dict):
        vr.error("'platform' must be a dict")
        return
    missing_pl = REQUIRED_PLATFORM_KEYS - set(platform.keys())
    if missing_pl:
        vr.error(f"Missing keys in 'platform': {sorted(missing_pl)}")

    pl_name = platform.get("name", "")
    if isinstance(pl_name, str) and pl_name:
        normalized = pl_name.lower().replace(" ", "-")
        if normalized not in KNOWN_PLATFORMS:
            vr.warn(f"Unknown platform name: {pl_name!r}")

    _validate_inline_applied_ledger(platform, vr)


def _validate_inline_applied_ledger(platform: dict, vr: ValidationResult) -> None:
    """Bound the applied-tuning ledger inlined at ``platform.tuning.applied``.

    The ledger is carried inside the bundle as well as in the ``.applied.json``
    companion. ``_validate_applied_companion_limits`` bounds the companion by
    filename, so the inlined copy needs its own bounds here: the validator runs
    on attacker-controlled PR JSON, and a hand-authored bundle can inline an
    unbounded ledger while shipping no companion at all.

    Both dimensions are bounded, because either alone is evadable. An entry cap
    alone passes a handful of entries holding multi-megabyte strings; a byte cap
    alone passes a million tiny entries. The serialized size is measured over
    this block only, so it bounds what the inlining added rather than the whole
    bundle.
    """
    tuning = platform.get("tuning")
    if not isinstance(tuning, dict):
        return
    applied = tuning.get("applied")
    if not isinstance(applied, dict):
        return

    for label, count in _oversized_applied_ledger_arrays(applied):
        vr.error(
            f"platform.tuning.applied.{label} exceeds the {APPLIED_RECEIPT_MAX_ENTRIES}-entry limit ({count} entries)"
        )

    try:
        size = len(json.dumps(applied, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError):
        # Unserializable content is a shape problem owned by the producer; this
        # gate gets no say in it and must not broaden rejection semantics.
        return
    if size > APPLIED_COMPANION_MAX_BYTES:
        vr.error(
            f"platform.tuning.applied exceeds the {APPLIED_COMPANION_MAX_BYTES}-byte limit ({size} bytes serialized)"
        )


def _validate_summary_section(
    summary: Any,
    vr: ValidationResult,
    *,
    allow_partial_validation: bool = False,
) -> None:
    if not isinstance(summary, dict):
        vr.error("'summary' must be a dict")
        return
    queries_summary = summary.get("queries", {})
    if isinstance(queries_summary, dict):
        total_q = queries_summary.get("total", 0)
        if isinstance(total_q, (int, float)) and total_q == 0:
            vr.error("summary.queries.total must be greater than 0 for a public result")

    validation_status = _normalize_status(summary.get("validation"))
    allowed = (
        PUBLIC_MIRROR_ALLOWED_VALIDATION_STATUSES
        if allow_partial_validation
        else frozenset({PUBLIC_CLEAN_VALIDATION_STATUS})
    )
    if validation_status not in allowed:
        if validation_status is None:
            vr.error("summary.validation is required for public submissions and must be 'passed'")
        elif allow_partial_validation:
            vr.error(
                f"summary.validation must be one of {sorted(allowed)} for trusted mirror "
                f"validation, got {validation_status!r}"
            )
        else:
            vr.error(f"summary.validation must be 'passed' for public submissions, got {validation_status!r}")


def _normalize_status(value: Any) -> str | None:
    if isinstance(value, dict):
        value = value.get("status")
    if value is None:
        return None
    normalized = str(value).strip().lower()
    return normalized or None


def _validate_translation_section(data: dict, vr: ValidationResult) -> None:
    execution = data.get("execution")
    if not isinstance(execution, dict):
        return

    translation = execution.get("translation")
    if translation is None:
        return

    translation_status = _normalize_status(translation)
    if translation_status is None:
        vr.error("execution.translation.status is required when execution.translation is present")
    elif translation_status in PUBLIC_NON_CLEAN_TRANSLATION_STATUSES:
        vr.error(f"execution.translation.status={translation_status!r} is not accepted for public submissions")


def _validate_environment_client_link(data: dict, vr: ValidationResult) -> None:
    """Shape-check the optional ``environment.client_link`` block when present."""
    environment = data.get("environment")
    if environment is None:
        return
    if not isinstance(environment, dict):
        vr.error("'environment' must be a dict")
        return

    client_link = environment.get("client_link")
    if client_link is None:
        return
    if not isinstance(client_link, dict):
        vr.error("'environment.client_link' must be a dict")
        return

    collection_status = client_link.get("collection_status")
    if collection_status is None:
        vr.error("'environment.client_link.collection_status' is required when 'environment.client_link' is present")
    elif not isinstance(collection_status, str):
        vr.error(f"'environment.client_link.collection_status' must be a string, got {collection_status!r}")
    elif collection_status not in {"available", "partial", "unavailable", "not_requested"}:
        vr.warn(f"Unknown environment.client_link.collection_status: {collection_status!r}")

    source = client_link.get("source")
    if source is not None and not isinstance(source, str):
        vr.error(f"'environment.client_link.source' must be a string, got {source!r}")

    for key in ("client_region", "client_cloud", "collection_error_class", "collection_error_message"):
        value = client_link.get(key)
        if value is not None and not isinstance(value, str):
            vr.error(f"'environment.client_link.{key}' must be a string, got {value!r}")

    overhead = client_link.get("statement_overhead_ms")
    if overhead is not None:
        _validate_overhead_shape(overhead, vr)


def _validate_overhead_shape(overhead: Any, vr: ValidationResult) -> None:
    """Shape-check the ``statement_overhead_ms`` probe block when present."""
    if not isinstance(overhead, dict):
        vr.error("'environment.client_link.statement_overhead_ms' must be a dict")
        return
    samples = overhead.get("samples")
    if samples is not None:
        if isinstance(samples, bool) or not isinstance(samples, int):
            vr.error(f"'environment.client_link.statement_overhead_ms.samples' must be an int, got {samples!r}")
        elif samples < 0:
            vr.error(f"'environment.client_link.statement_overhead_ms.samples' must be non-negative, got {samples!r}")
    for key in ("min", "median"):
        value = overhead.get(key)
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            vr.error(f"'environment.client_link.statement_overhead_ms.{key}' must be a number, got {value!r}")
        elif not math.isfinite(value):
            vr.error(f"'environment.client_link.statement_overhead_ms.{key}' must be finite, got {value!r}")
        elif value < 0:
            vr.error(f"'environment.client_link.statement_overhead_ms.{key}' must be non-negative, got {value!r}")


def _validate_tables_block(data: dict, vr: ValidationResult) -> None:
    """Shape-check the optional ``tables`` block when present.

    Absence means "not measured" and is always accepted; an explicit
    ``load_ms: 0`` stays distinguishable from a missing key.
    """
    tables = data.get("tables")
    if tables is None:
        return
    if not isinstance(tables, dict):
        vr.error("'tables' must be a dict")
        return

    for name, entry in tables.items():
        if not isinstance(entry, dict):
            vr.error(f"'tables.{name}' must be a dict")
            continue
        rows = entry.get("rows")
        if rows is not None:
            if isinstance(rows, bool) or not isinstance(rows, (int, float)):
                vr.error(f"'tables.{name}.rows' must be a number, got {rows!r}")
            elif not math.isfinite(rows):
                vr.error(f"'tables.{name}.rows' must be finite, got {rows!r}")
            elif rows < 0:
                vr.error(f"'tables.{name}.rows' must be non-negative, got {rows!r}")
        load_ms = entry.get("load_ms")
        if load_ms is None:
            continue
        if isinstance(load_ms, bool) or not isinstance(load_ms, (int, float)):
            vr.error(f"'tables.{name}.load_ms' must be a number, got {load_ms!r}")
        elif not math.isfinite(load_ms):
            vr.error(f"'tables.{name}.load_ms' must be finite, got {load_ms!r}")
        elif load_ms < 0:
            vr.error(f"'tables.{name}.load_ms' must be non-negative, got {load_ms!r}")


def _validate_platform_config_clustering(data: dict, vr: ValidationResult) -> None:
    """Shape-check the optional ``platform.config`` clustering field when present.

    The Databricks adapter records the resolved strategy at
    ``platform.config.databricks_clustering_strategy`` (flattened out of
    ``platform_info["configuration"]``); ``platform.tuning`` carries the
    requested-tuning summary and never holds this key.
    """
    platform = data.get("platform")
    if not isinstance(platform, dict):
        return

    config = platform.get("config")
    if config is None:
        return
    if not isinstance(config, dict):
        vr.error("'platform.config' must be a dict")
        return

    strategy = config.get("databricks_clustering_strategy")
    if strategy is None:
        return
    if not isinstance(strategy, str):
        vr.error(f"'platform.config.databricks_clustering_strategy' must be a string, got {strategy!r}")
    elif strategy not in {"z_order", "liquid_clustering", "liquid_clustering_auto", "none"}:
        vr.warn(f"Unknown platform.config.databricks_clustering_strategy: {strategy!r}")


def _warn_pre_cutoff_clustering_claim(data: dict, vr: ValidationResult) -> None:
    """Warn on Databricks ``z_order`` claims that predate provenance.

    Before the #2177 fix, untuned runs reported ``"z_order"`` while
    applying only plain OPTIMIZE compaction. ``export.benchbox_version``
    (introduced in #2199, after the fix) is the cutoff marker: a bundle
    without it that claims ``z_order`` outside any tuning context may be
    a mislabeled untuned run, so readers must treat it as unknown. Tuned
    runs (non-empty ``platform.tuning``) and post-cutoff bundles are
    unaffected. Old bundles are never rewritten; warn only.
    """
    platform = data.get("platform")
    if not isinstance(platform, dict):
        return
    if platform.get("name") != "databricks":
        return
    config = platform.get("config")
    if not isinstance(config, dict):
        return
    if config.get("databricks_clustering_strategy") != "z_order":
        return
    tuning = platform.get("tuning")
    if isinstance(tuning, dict) and tuning:
        return
    export = data.get("export")
    if isinstance(export, dict) and export.get("benchbox_version"):
        return
    vr.warn(
        "platform.config.databricks_clustering_strategy='z_order' on a Databricks "
        "bundle without tuning context or export.benchbox_version predates the "
        "clustering provenance cutoff and may mislabel plain OPTIMIZE compaction; "
        "treat as unknown."
    )


def _raw_normalized_cost_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Find normalized cost in current and transitional bundle shapes."""
    raw = data.get("normalized_cost")
    if isinstance(raw, dict):
        return raw

    cost = data.get("cost")
    if not isinstance(cost, dict):
        return None

    for key in ("normalized_cost", "normalized"):
        raw = cost.get(key)
        if isinstance(raw, dict):
            return raw

    if NORMALIZED_COST_REQUIRED_KEYS.intersection(cost):
        return cost

    return None


def _parse_decimal(value: Any, field_path: str, vr: ValidationResult) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        vr.error(f"{field_path} must be a finite decimal value; got {value!r}")
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        vr.error(f"{field_path} must be a finite decimal value; got {value!r}")
        return None
    if not parsed.is_finite():
        vr.error(f"{field_path} must be a finite decimal value; got {value!r}")
        return None
    return parsed


def _validate_required_cost_string(raw: dict[str, Any], key: str, vr: ValidationResult) -> str | None:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        vr.error(f"normalized_cost.{key} must be a non-empty string")
        return None
    return value


def _validate_normalized_cost_block(
    raw: dict[str, Any], vr: ValidationResult
) -> tuple[bool, Decimal | None, str | None, str | None]:
    """Validate BenchBox normalized cost provenance.

    Returns ``(is_valid, normalized_cost_usd, cost_status, cost_scope)`` so the
    legacy cost-total guard can check whether old fields are consistent with
    the canonical normalized block.
    """
    error_count = len(vr.errors)
    missing = NORMALIZED_COST_REQUIRED_KEYS - set(raw.keys())
    if missing:
        vr.error(f"normalized_cost missing required provenance fields: {sorted(missing)}")

    cost_value = _parse_decimal(raw.get("normalized_cost_usd"), "normalized_cost.normalized_cost_usd", vr)
    _validate_required_cost_string(raw, "cost_model_version", vr)
    model_source = _validate_required_cost_string(raw, "cost_model_source", vr)
    cost_scope = _validate_required_cost_string(raw, "cost_scope", vr)
    cost_status = _validate_required_cost_string(raw, "cost_status", vr)
    billing_unit = _validate_required_cost_string(raw, "billing_unit", vr)
    pricing_region = _validate_required_cost_string(raw, "pricing_region", vr)

    if model_source is not None and model_source != NORMALIZED_COST_MODEL_SOURCE:
        vr.error(f"normalized_cost.cost_model_source must be {NORMALIZED_COST_MODEL_SOURCE!r}; got {model_source!r}")
    if cost_scope is not None and cost_scope not in NORMALIZED_COST_SCOPES:
        vr.error(f"normalized_cost.cost_scope must be one of {sorted(NORMALIZED_COST_SCOPES)}; got {cost_scope!r}")
    if cost_status is not None and cost_status not in NORMALIZED_COST_STATUSES:
        vr.error(f"normalized_cost.cost_status must be one of {sorted(NORMALIZED_COST_STATUSES)}; got {cost_status!r}")

    if cost_value is not None and cost_value < 0:
        vr.error(f"normalized_cost.normalized_cost_usd cannot be negative: {cost_value}")
    if cost_status == "normalized" and cost_value is None:
        vr.error("normalized_cost.cost_status 'normalized' requires normalized_cost_usd")
    if cost_status == "not_applicable_local" and cost_value != Decimal("0"):
        vr.error("normalized_cost.cost_status 'not_applicable_local' requires normalized_cost_usd of 0")
    if cost_status == "unavailable" and cost_value is not None:
        vr.error("normalized_cost.cost_status 'unavailable' must not include normalized_cost_usd")
    if cost_status == "normalized" and billing_unit not in NORMALIZED_COST_BILLING_UNITS:
        vr.error(
            "normalized_cost.cost_status 'normalized' requires a concrete billing_unit "
            f"in {sorted(NORMALIZED_COST_BILLING_UNITS)}; got {billing_unit!r}"
        )
    if cost_status == "normalized" and pricing_region in {"unknown", "not_applicable"}:
        vr.error("normalized_cost.cost_status 'normalized' requires a concrete pricing_region")

    deployment = raw.get("deployment")
    if cost_status == "normalized" and not isinstance(deployment, dict):
        vr.error("normalized_cost.cost_status 'normalized' requires deployment metadata")
    elif deployment is not None and not isinstance(deployment, dict):
        vr.error("normalized_cost.deployment must be an object when present")
    elif isinstance(deployment, dict):
        if cost_status == "normalized":
            for key in ("cloud_provider", "cloud_region"):
                value = deployment.get(key)
                if not isinstance(value, str) or not value:
                    vr.error(f"normalized_cost.deployment.{key} must be a non-empty string for normalized cost")
        node_count = deployment.get("node_count")
        if node_count is not None and (isinstance(node_count, bool) or not isinstance(node_count, int)):
            vr.error(f"normalized_cost.deployment.node_count must be an integer when present; got {node_count!r}")

    return len(vr.errors) == error_count, cost_value, cost_status, cost_scope


def _direct_cost_total_fields(data: dict[str, Any]) -> list[tuple[str, Any]]:
    direct_fields: list[tuple[str, Any]] = []
    cost = data.get("cost")
    if isinstance(cost, dict):
        for key in DIRECT_COST_TOTAL_KEYS:
            if key in cost:
                direct_fields.append((f"cost.{key}", cost[key]))

    for key in TOP_LEVEL_DIRECT_COST_KEYS:
        if key in data:
            direct_fields.append((key, data[key]))

    return direct_fields


def _validate_public_cost_section(data: dict[str, Any], vr: ValidationResult) -> None:
    """Reject public leaderboard cost totals that lack BenchBox provenance."""
    direct_fields = _direct_cost_total_fields(data)
    raw_normalized = _raw_normalized_cost_block(data)

    normalized_valid = True
    normalized_value: Decimal | None = None
    cost_status: str | None = None
    cost_scope: str | None = None
    if raw_normalized is not None:
        normalized_valid, normalized_value, cost_status, cost_scope = _validate_normalized_cost_block(
            raw_normalized, vr
        )

    if not direct_fields:
        return

    field_names = ", ".join(path for path, _value in direct_fields)
    if raw_normalized is None or not normalized_valid:
        vr.error(
            "User-supplied public leaderboard cost totals are not accepted: "
            f"{field_names} require BenchBox normalized_cost provenance"
        )
        return

    if cost_status == "unavailable" or normalized_value is None:
        vr.error(
            "Public leaderboard cost totals require normalized cost availability: "
            f"{field_names} cannot accompany cost_status {cost_status!r}"
        )
        return

    for field_path, value in direct_fields:
        direct_value = _parse_decimal(value, field_path, vr)
        if direct_value is None:
            continue
        if direct_value < 0:
            vr.error(f"{field_path} cannot be negative: {direct_value}")
            continue
        if field_path == "cost_usd" and (cost_status != "normalized" or cost_scope != "compute_only"):
            vr.error("cost_usd is only accepted as a compute_only alias for normalized BenchBox cost")
            continue
        if direct_value != normalized_value:
            vr.error(
                f"{field_path} ({direct_value}) must match normalized_cost.normalized_cost_usd ({normalized_value})"
            )


def _schema_version_tuple(version: Any) -> tuple[int, ...] | None:
    if not isinstance(version, str) or not NUMERIC_SCHEMA_VERSION_RE.fullmatch(version.strip()):
        return None
    return tuple(int(part) for part in version.strip().split("."))


def _validate_row_count_validation(index: int, q: dict[str, Any], version: Any, vr: ValidationResult) -> None:
    if "row_count_validation" not in q:
        return

    version_tuple = _schema_version_tuple(version)
    if version_tuple is None or version_tuple < ROW_COUNT_VALIDATION_SCHEMA_VERSION:
        vr.error(f"queries[{index}].row_count_validation requires schema version 2.2 or later")

    evidence = q.get("row_count_validation")
    if not isinstance(evidence, dict):
        vr.error(f"queries[{index}].row_count_validation must be an object")
        return

    unknown = set(evidence) - ROW_COUNT_VALIDATION_FIELDS
    if unknown:
        vr.error(f"queries[{index}].row_count_validation has unknown fields: {sorted(unknown)}")
    missing = ROW_COUNT_VALIDATION_REQUIRED_FIELDS - set(evidence)
    if missing:
        vr.error(f"queries[{index}].row_count_validation missing fields: {sorted(missing)}")

    status = evidence.get("status")
    if not isinstance(status, str) or status not in ROW_COUNT_VALIDATION_STATUSES:
        vr.error(f"queries[{index}].row_count_validation.status is invalid: {status!r}")

    normalized_counts: dict[str, int | None] = {}
    for field in ("expected", "actual"):
        value = evidence.get(field)
        if value is None:
            normalized_counts[field] = None
        elif isinstance(value, bool) or not isinstance(value, int) or value < 0:
            vr.error(f"queries[{index}].row_count_validation.{field} must be a non-negative integer or null")
            normalized_counts[field] = None
        else:
            normalized_counts[field] = value

    rows = q.get("rows")
    if rows is not None and (isinstance(rows, bool) or not isinstance(rows, int) or rows < 0):
        vr.error(f"queries[{index}].rows must be a non-negative integer or null when row-count evidence is present")
        rows = None
    if normalized_counts["actual"] != rows:
        vr.error(f"queries[{index}].row_count_validation.actual must match queries[{index}].rows")
    if status == "PASSED" and (
        normalized_counts["expected"] is None or normalized_counts["actual"] != normalized_counts["expected"]
    ):
        vr.error(f"queries[{index}].row_count_validation PASSED requires equal integer expected and actual counts")

    for field in ("error", "warning"):
        if field not in evidence:
            continue
        message = evidence[field]
        if not isinstance(message, str):
            vr.error(f"queries[{index}].row_count_validation.{field} must be a string")
        elif len(message) > ROW_COUNT_VALIDATION_MESSAGE_MAX_CHARS:
            vr.error(
                f"queries[{index}].row_count_validation.{field} exceeds "
                f"{ROW_COUNT_VALIDATION_MESSAGE_MAX_CHARS} characters"
            )


def _validate_single_query(index: int, q: Any, version: Any, vr: ValidationResult) -> bool:
    """Validate one queries[i] entry. Returns True if ms>0 was seen (non-zero signal)."""
    if not isinstance(q, dict):
        vr.error(f"queries[{index}] is not a dict")
        return False

    missing_qk = REQUIRED_QUERY_KEYS - set(q.keys())
    if missing_qk:
        vr.error(f"queries[{index}] missing keys: {sorted(missing_qk)}")
        return False

    _validate_row_count_validation(index, q, version, vr)

    ms = q.get("ms")
    if ms is None:
        return False
    try:
        ms_f = float(ms)
    except (TypeError, ValueError):
        vr.error(f"queries[{index}] invalid ms value: {ms!r}")
        return False
    if ms_f < 0:
        vr.error(f"queries[{index}] negative duration: {ms_f}")
    elif ms_f > MAX_QUERY_DURATION_MS:
        vr.warn(f"queries[{index}] unusually long: {ms_f:.0f}ms")
    return ms_f > 0


def _validate_queries_section(queries: Any, version: Any, vr: ValidationResult) -> None:
    if not isinstance(queries, list):
        vr.error("'queries' must be a list")
        return
    if len(queries) == 0:
        vr.error("queries array must not be empty for a public result")
        return

    any_nonzero = False
    any_nonzero_measurement = False
    for i, q in enumerate(queries):
        if _validate_single_query(i, q, version, vr):
            any_nonzero = True
            run_type = str(q.get("run_type") or "measurement").lower() if isinstance(q, dict) else ""
            if run_type == "measurement":
                any_nonzero_measurement = True

    if not any_nonzero:
        vr.error("All query timings are 0ms - likely invalid data")
    elif not any_nonzero_measurement:
        vr.error("queries must contain at least one positive measurement timing")


def _validate_execution_consistency(data: dict[str, Any], vr: ValidationResult) -> None:
    """Reject a clean validation claim that contradicts measurement evidence."""
    summary = data.get("summary")
    if not isinstance(summary, dict) or _normalize_status(summary.get("validation")) != PUBLIC_CLEAN_VALIDATION_STATUS:
        return

    failed = bundle_failed_query_count(data)
    if failed > 0:
        noun = "query" if failed == 1 else "queries"
        vr.error(f"summary.validation='passed' contradicts {failed} failed measurement {noun}")

    queries = data.get("queries")
    if isinstance(queries, list):
        for i, q in enumerate(queries):
            if not isinstance(q, dict):
                continue
            rcv = q.get("row_count_validation")
            if isinstance(rcv, dict):
                rcv_status = rcv.get("status")
                if rcv_status is not None and rcv_status != "PASSED":
                    vr.error(
                        f"summary.validation='passed' contradicts queries[{i}].row_count_validation.status={rcv_status!r}"
                    )


def _validate_validation_phase_consistency(data: dict[str, Any], vr: ValidationResult) -> None:
    """Reject validation claims contradicted by supplied validation-phase evidence."""
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return
    summary_status = _normalize_status(summary.get("validation"))
    if summary_status not in {"passed", "partial"}:
        return

    # ``phases`` is an optional extension to schema-v2. Older valid bundles do
    # not carry phase evidence, so absence of the extension is not evidence of
    # a failed validation claim. When the extension is present, however, keep
    # the consistency check fail-closed for an explicitly missing/unknown
    # validation phase.
    if "phases" not in data:
        return
    phases = data["phases"]
    if not isinstance(phases, dict) or "validation" not in phases:
        phase_status = "unknown"
    else:
        validation_phase = phases["validation"]
        raw_phase_status = validation_phase.get("status") if isinstance(validation_phase, dict) else None
        phase_status = (
            (_normalize_status(raw_phase_status) or "unknown") if isinstance(raw_phase_status, str) else "unknown"
        )

    compatible_phase_statuses = {"passed"} if summary_status == "passed" else {"passed", "partial"}
    if phase_status not in compatible_phase_statuses:
        vr.error(f"summary.validation={summary_status!r} contradicts phases.validation.status={phase_status!r}")


def _validate_bundle(
    data: dict,
    vr: ValidationResult,
    *,
    allow_partial_validation: bool = False,
) -> None:
    """Run all validation checks on a parsed bundle dict."""
    _capture_metadata(data, vr)

    try:
        version = result_schema_version_value(data)
    except ValueError as exc:
        vr.error(str(exc))
        return
    missing_top = set(REQUIRED_TOP_KEYS) - set(data.keys())
    if version is not None:
        missing_top.discard("result_schema_version")
    else:
        missing_top.add("result_schema_version")

    if missing_top:
        vr.error(f"Missing required top-level keys: {sorted(missing_top)}")
        return  # Can't continue without structure

    _validate_version(version, vr)
    _validate_run_section(data.get("run", {}), vr)
    _validate_benchmark_section(data.get("benchmark", {}), vr)
    _validate_platform_section(data.get("platform", {}), vr)
    _validate_summary_section(
        data.get("summary", {}),
        vr,
        allow_partial_validation=allow_partial_validation,
    )
    _validate_translation_section(data, vr)
    _validate_environment_client_link(data, vr)
    _validate_tables_block(data, vr)
    _validate_platform_config_clustering(data, vr)
    _warn_pre_cutoff_clustering_claim(data, vr)
    _validate_public_cost_section(data, vr)
    _validate_queries_section(data.get("queries", []), version, vr)
    _warn_timing_plateau(data, vr)
    _warn_small_scale_floor(data, vr)
    _validate_execution_consistency(data, vr)
    _validate_validation_phase_consistency(data, vr)


def _hash_file(file_path: Path) -> str:
    """SHA-256 of a single file's contents."""
    return _hash_bytes(file_path.read_bytes())


def _hash_bytes(data: bytes) -> str:
    """SHA-256 of already-materialized bytes."""
    return hashlib.sha256(data).hexdigest()


def _is_safe_bundle_filename(name: str) -> bool:
    """Reject filenames that could escape the bundle directory.

    The validator runs in CI on attacker-controlled PR JSON, so manifest-
    supplied filenames must be plain leaf names, not paths.
    """
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    parts = Path(name).parts
    if Path(name).is_absolute() or ".." in parts or len(parts) != 1:
        return False
    return True


def _validate_manifest_hash(manifest_path: Path, bundle_dir: Path, vr: ValidationResult) -> None:
    """Verify the submission manifest hashes match the bundle file contents.

    Contract (see also benchbox/cli/commands/submit.py):
      - manifest.bundle_file: filename of the primary bundle JSON.
      - manifest.bundle_hash: SHA-256 of just that file's contents.
      - manifest.companion_hashes: optional dict of companion-file
        names mapped to their SHA-256s. Empty dict if no companions.

    The hash is per-file. Anything wider (a directory hash) does not
    survive the user copying the bundle files into a results-data/bundles/
    directory that already contains other bundles.
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        vr.error(f"Cannot parse submission manifest JSON: {exc}")
        return
    except OSError as exc:
        vr.error(f"Cannot read submission manifest file: {exc}")
        return

    # Surface ALL missing required fields in one pass so a contributor
    # whose manifest is missing both `bundle_file` and `bundle_hash`
    # sees both errors instead of having to fix-and-retry one at a time.
    #
    # These are ERRORs, not warnings: a present manifest whose whole purpose is
    # the bundle-hash contract must actually carry it. When they were warnings,
    # ValidationResult.ok ignored them, so a present-but-empty `.manifest.json`
    # passed CI *and* — because the pipeline/inventory treat sidecar presence as
    # the community-submission trust signal — granted the community label
    # without the bundle bytes ever being hash-verified.
    bundle_file = manifest.get("bundle_file")
    expected_hash = manifest.get("bundle_hash")
    missing_fields: list[str] = []
    if not isinstance(bundle_file, str) or not bundle_file:
        missing_fields.append("bundle_file")
    if not isinstance(expected_hash, str) or not expected_hash:
        missing_fields.append("bundle_hash")
    if missing_fields:
        for field in missing_fields:
            vr.error(f"Submission manifest has no {field} field")
        return

    if not _is_safe_bundle_filename(bundle_file):
        vr.error(f"Unsafe bundle_file in manifest: {bundle_file!r} (must be a plain filename)")
        return

    primary_path = bundle_dir / bundle_file
    # Symlink defense: the validator runs on PR-supplied content, so a
    # malicious symlink (committed via a crafted git tree) could redirect
    # the hash to attacker-chosen bytes outside the bundle. Reject before
    # is_file() — is_file() follows symlinks. The writer (benchbox submit)
    # uses shutil.copy2, which copies file contents not symlinks, so any
    # symlink in a submitted bundle is suspicious by construction.
    if primary_path.is_symlink():
        vr.error(f"Bundle file is a symlink, not a regular file: {bundle_file} (symlinks not allowed)")
        return
    if not primary_path.is_file():
        vr.error(f"Bundle file declared in manifest not found in PR: {bundle_file}")
        return

    _validate_manifest_provenance(manifest, primary_path, vr)

    actual_hash = _hash_file(primary_path)
    if actual_hash != expected_hash:
        vr.error(
            f"Bundle hash mismatch for {bundle_file}: manifest says "
            f"{expected_hash[:16]}..., computed {actual_hash[:16]}..."
        )

    companion_hashes = manifest.get("companion_hashes") or {}
    if not isinstance(companion_hashes, dict):
        vr.error("companion_hashes field must be an object (filename -> hash)")
        return

    for comp_name, comp_expected in companion_hashes.items():
        _validate_manifest_companion(comp_name, comp_expected, bundle_dir, vr)


def _validate_manifest_companion(
    comp_name: object,
    comp_expected: object,
    bundle_dir: Path,
    vr: ValidationResult,
) -> None:
    """Validate one manifest-declared companion without widening orchestration."""
    if not isinstance(comp_name, str) or not _is_safe_bundle_filename(comp_name):
        vr.error(f"Unsafe companion filename in manifest: {comp_name!r} (must be a plain filename)")
        return
    comp_path = bundle_dir / comp_name
    if comp_path.is_symlink():
        vr.error(f"Companion file is a symlink, not a regular file: {comp_name} (symlinks not allowed)")
        return
    if not comp_path.is_file():
        vr.error(f"Companion file declared in manifest not found in PR: {comp_name}")
        return
    if not isinstance(comp_expected, str) or not comp_expected:
        vr.error(f"Empty companion hash for {comp_name}")
        return
    if not _validate_applied_companion_limits(comp_path, vr):
        return
    comp_actual = _hash_file(comp_path)
    if comp_actual != comp_expected:
        vr.error(
            f"Companion hash mismatch for {comp_name}: manifest says "
            f"{comp_expected[:16]}..., computed {comp_actual[:16]}..."
        )


def _validate_applied_companion_limits(companion: Path, vr: ValidationResult) -> bool:
    """Reject an applied receipt that exceeds the public submission bounds."""
    if not companion.name.lower().endswith(".applied.json"):
        return True
    try:
        size = companion.stat().st_size
    except OSError as exc:
        vr.error(f"Cannot inspect applied companion {companion.name}: {exc}")
        return False
    if size > APPLIED_COMPANION_MAX_BYTES:
        vr.error(
            f"Applied companion {companion.name} exceeds the {APPLIED_COMPANION_MAX_BYTES}-byte limit ({size} bytes)"
        )
        return False
    try:
        payload = json.loads(companion.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Companion schema validation remains owned by its producer. This gate
        # only bounds inputs and must not broaden existing rejection semantics.
        return True
    if not isinstance(payload, dict):
        return True
    # Same array bounds the inlined copy gets. The file-size cap above stops the
    # multi-megabyte-string shape; these stop the many-tiny-entries shape, which
    # a byte cap alone lets through.
    oversized = _oversized_applied_ledger_arrays(payload)
    for label, count in oversized:
        vr.error(
            f"Applied receipt {companion.name} exceeds the {APPLIED_RECEIPT_MAX_ENTRIES}-entry limit "
            f"at {label} ({count} entries)"
        )
    return not oversized


def _oversized_applied_ledger_arrays(applied: dict) -> list[tuple[str, int]]:
    """Return every applied-ledger array that breaches the per-array entry cap.

    Shared by the companion gate and the inlined-block gate so one ledger shape
    cannot be bounded in one location and unbounded in the other.
    """
    receipt = applied.get("receipt") if isinstance(applied.get("receipt"), dict) else {}
    drift = applied.get("drift_check") if isinstance(applied.get("drift_check"), dict) else {}
    candidates = (
        ("statements", applied.get("statements")),
        ("dropped", applied.get("dropped")),
        ("receipt.entries", receipt.get("entries")),
        ("receipt.observed", receipt.get("observed")),
        ("receipt.dropped", receipt.get("dropped")),
        ("drift_check.errors", drift.get("errors")),
        ("drift_check.warnings", drift.get("warnings")),
        ("drift_check.configuration_mismatches", drift.get("configuration_mismatches")),
        ("drift_check.missing_tables", drift.get("missing_tables")),
        ("drift_check.extra_tables", drift.get("extra_tables")),
    )
    return [
        (label, len(value))
        for label, value in candidates
        if isinstance(value, list) and len(value) > APPLIED_RECEIPT_MAX_ENTRIES
    ]


def _validate_manifest_provenance(manifest: dict[str, Any], primary_path: Path, vr: ValidationResult) -> None:
    """Validate the optional provenance fields on a submission manifest.

    Runs on attacker-controlled PR JSON, so every value is checked against the
    canonical allowlists and unknown values are hard errors (not warnings).

    Governance: ``result_source == "vendor"`` (the ranking-eligible vendor tier)
    is only valid for a bundle whose immediate parent directory is ``vendor/``
    (``results-data/bundles/vendor/...``). The ENFORCED control is CODEOWNERS on
    that path on the submission branch — a community contributor cannot create a
    file under ``vendor/`` without maintainer review. This validator check is an
    advisory consistency guard: it rejects a community-located bundle that
    self-asserts the vendor label, but the authoritative label is derived from
    the (CODEOWNERS-gated) path by generate_corpus_inventory.py, not from this
    field.
    """
    funding = manifest.get("funding")
    if funding is not None and funding not in FUNDING_SOURCES:
        vr.error(f"Invalid manifest funding {funding!r}: must be one of {sorted(FUNDING_SOURCES)}")

    notes = manifest.get("submission_notes")
    if notes is not None:
        if not isinstance(notes, str):
            vr.error("Manifest submission_notes must be a string")
        elif len(notes) > SUBMISSION_NOTES_MAX_LEN:
            vr.error(f"Manifest submission_notes exceeds {SUBMISSION_NOTES_MAX_LEN} characters ({len(notes)})")

    result_source = manifest.get("result_source")
    if result_source is None:
        return
    if result_source not in RESULT_SOURCES:
        vr.error(f"Invalid manifest result_source {result_source!r}: must be one of {sorted(RESULT_SOURCES)}")
        return
    if result_source == "vendor" and primary_path.parent.name != "vendor":
        vr.error(
            "Manifest result_source 'vendor' is only valid for bundles directly "
            "under a maintainer-controlled results-data/bundles/vendor/ path; a "
            "community submission cannot self-assert the vendor-supplied label."
        )


# ---------------------------------------------------------------------------
# Discovery & orchestration
# ---------------------------------------------------------------------------


def discover_bundles(path: Path) -> list[Path]:
    """Find all primary bundle JSON files under a directory (excludes companions)."""
    return [candidate for candidate in sorted(path.rglob("*")) if is_primary_bundle_file(candidate)]


def is_primary_bundle_file(path: Path) -> bool:
    """Return whether *path* is a regular primary bundle, case-insensitively."""
    if not path.is_file():
        return False
    name = path.name.lower()
    if not name.endswith(".json"):
        return False
    if any(name.endswith(suffix) for suffix in COMPANION_SUFFIXES):
        return False
    if name == "corpus-inventory.json":
        return False
    return not _is_submission_manifest_path(path)


def _is_submission_manifest_path(path: Path) -> bool:
    """True for the legacy filename or any per-bundle ``<stem>.manifest.json``.

    The trailing-suffix match is intentionally broad. Any file ending in
    ``.manifest.json`` is treated as a sidecar regardless of stem so that
    co-located manifest variants (per-bundle, hashing tools, ad-hoc copies)
    are never validated as bundles. The submit CLI emits
    ``<bundle_stem>.manifest.json`` exclusively, and the published-results
    workflow filter mirrors this skip pattern.
    """
    name = path.name.lower()
    return name == SUBMISSION_MANIFEST_FILENAME or name.endswith(SUBMISSION_MANIFEST_SUFFIX)


def validate_bundles(
    paths: list[Path],
    require_manifest: bool = False,
    *,
    allow_partial_validation: bool = False,
) -> list[ValidationResult]:
    """Validate a list of bundle files. Returns one ValidationResult per file.

    When ``require_manifest`` is True, a primary bundle with no paired
    submission manifest is an error. This is the community-submission contract:
    the sidecar is what distinguishes a community submission from a
    maintainer-run bundle (whose absence of a sidecar is intentional), so CI
    passes this flag only for genuine contributor PRs — not for the maintainer
    mirror PRs that sync develop's corpus onto ``published-results``. Without
    it, a community bundle submitted without a sidecar would pass validation and
    then inherit the ``maintainer-run`` trust label (and ranking eligibility).

    When ``allow_partial_validation`` is True, ``summary.validation`` may be
    ``passed``, ``partial``, or the explicit ``not_run`` state. That is for
    the trusted maintainer mirror path only: the seed corpus intentionally
    retains partial and legacy unvalidated evidence. Community submissions
    must leave the flag off so every non-clean status remains refused.
    """
    results = []
    parsed: list[tuple[dict[str, Any], ValidationResult]] = []
    for bundle_path in paths:
        if _is_submission_manifest_path(bundle_path):
            continue

        vr = ValidationResult(str(bundle_path))

        if not bundle_path.exists():
            vr.error(f"File not found: {bundle_path}")
            results.append(vr)
            continue
        if not bundle_path.is_file():
            vr.error(f"Bundle path is not a regular file: {bundle_path}")
            results.append(vr)
            continue

        try:
            data = json.loads(bundle_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            vr.error(f"Invalid JSON: {exc}")
            results.append(vr)
            continue

        if not isinstance(data, dict):
            vr.error("Top-level value must be a JSON object")
            results.append(vr)
            continue

        _validate_bundle(data, vr, allow_partial_validation=allow_partial_validation)
        parsed.append((data, vr))

        # Bound an adjacent applied companion even if a hand-authored manifest
        # omitted it. The manifest hash contract is checked separately below;
        # resource bounds must not depend on honest companion enumeration.
        applied_name = f"{bundle_path.stem}.applied.json".lower()
        for companion in bundle_path.parent.iterdir():
            if companion.name.lower() != applied_name:
                continue
            if companion.is_symlink():
                vr.error(f"Companion file is a symlink, not a regular file: {companion.name} (symlinks not allowed)")
            elif companion.is_file():
                _validate_applied_companion_limits(companion, vr)

        # Check for submission manifest alongside the bundle.
        # Prefer per-bundle name (<stem>.manifest.json), fall back to legacy.
        per_bundle_manifest = bundle_path.parent / f"{bundle_path.stem}{SUBMISSION_MANIFEST_SUFFIX}"
        legacy_manifest = bundle_path.parent / SUBMISSION_MANIFEST_FILENAME
        manifest_path = (
            per_bundle_manifest
            if per_bundle_manifest.exists()
            else (legacy_manifest if legacy_manifest.exists() else None)
        )
        if manifest_path is not None:
            _validate_manifest_hash(manifest_path, bundle_path.parent, vr)
        elif require_manifest:
            vr.error(
                f"Submission manifest not found for {bundle_path.name}: expected "
                f"{bundle_path.stem}{SUBMISSION_MANIFEST_SUFFIX} alongside the bundle. "
                "Community submissions must include the manifest produced by "
                "`benchbox submit` (it carries the bundle-hash contract and the "
                "community-submission trust label)."
            )

        results.append(vr)

    # Cross-bundle timing plausibility over the validated set (e.g. one
    # submission PR). Warnings only; groups without scale span or peers
    # stay silent.
    _warn_cross_bundle_timing(parsed)
    return results


def format_summary(results: list[ValidationResult]) -> str:
    """Format validation results as a human-readable summary."""
    lines: list[str] = []
    total_errors = 0
    total_warnings = 0

    for vr in results:
        total_errors += len(vr.errors)
        total_warnings += len(vr.warnings)

        status = "PASS" if vr.ok else "FAIL"
        lines.append(f"  {status}  {vr.path}")
        for e in vr.errors:
            lines.append(f"        ERROR: {e}")
        for w in vr.warnings:
            lines.append(f"        WARN:  {w}")

    header = f"Validated {len(results)} bundle(s): {total_errors} error(s), {total_warnings} warning(s)"
    return header + "\n" + "\n".join(lines)


def format_pr_comment(results: list[ValidationResult]) -> str:
    """Format validation results as a GitHub PR comment (Markdown)."""
    lines: list[str] = []
    all_pass = all(vr.ok for vr in results)

    if all_pass:
        lines.append("## Submission Validation: PASSED")
    else:
        lines.append("## Submission Validation: FAILED")

    lines.append("")
    lines.append(f"Validated **{len(results)}** bundle(s).")
    lines.append("")

    # Summary table
    lines.append("| Bundle | Status | Benchmark | Platform | Scale |")
    lines.append("|--------|--------|-----------|----------|-------|")

    for vr in results:
        status = "PASS" if vr.ok else "FAIL"
        name = Path(vr.path).name.replace("|", "\\|")
        bm_id = vr.benchmark_id.replace("|", "\\|")
        pl_name = vr.platform_name.replace("|", "\\|")
        sf = vr.scale_factor.replace("|", "\\|")
        lines.append(f"| `{name}` | {status} | {bm_id} | {pl_name} | SF {sf} |")

    # Detail errors/warnings
    has_issues = any(vr.errors or vr.warnings for vr in results)
    if has_issues:
        lines.append("")
        lines.append("### Details")
        lines.append("")
        for vr in results:
            if not vr.errors and not vr.warnings:
                continue
            lines.append(f"**`{Path(vr.path).name}`**")
            for e in vr.errors:
                lines.append(f"- ERROR: {e}")
            for w in vr.warnings:
                lines.append(f"- WARN: {w}")
            lines.append("")

    return "\n".join(lines)
