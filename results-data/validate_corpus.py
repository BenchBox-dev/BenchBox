#!/usr/bin/env python3
"""Validate the seed corpus meets depth and schema requirements.

`SEED_CORPUS_SPEC.md` states the hard requirement this enforces: every
committed cohort must have at least 3 distinct comparison identities. A
one-identity cohort is not a comparison, so publishing it would put a row on
the public leaderboard that nothing can be read against.

This script also prints a recency/staleness report derived from each bundle's
``run.timestamp``. Age is informational only: it never fails the depth gate and
never implies ranking exclusion or automatic withdrawal.

Structured into functions so `tests/unit/scripts/test_corpus_cohort_depth.py`
can import and assert the same rule instead of restating it. Before that, the
script ran in no CI lane at all -- every workflow reference to it is a path
list for mirroring -- so a corpus PR could violate the requirement, pass
pr-preflight green, and merge. That is exactly what PR #1854 did.

Kept deliberately stdlib-only and free of `benchbox` imports: this file is
vendored onto the slim `published-results` branch, where the package is not
installed.
"""

from __future__ import annotations

import collections
import datetime as _dt
import json
import pathlib
import re
import sys
from typing import NamedTuple

#: Companion suffixes that are not primary result bundles.
COMPANION_SUFFIXES = (".manifest.json", ".plans.json", ".tuning.json", ".applied.json", ".override.json")
LEGACY_MANIFEST_NAME = "submission-manifest.json"

#: A cohort below this many distinct comparison identities is not a comparison.
MINIMUM_PLATFORMS_PER_COHORT = 3
NON_CLEAN_VALIDATION_STATUSES = frozenset(
    {"failed", "interrupted", "partial", "error", "not_run", "not_validated", "uncertain", "unknown"}
)
NON_CLEAN_TRANSLATION_STATUSES = frozenset({"fallback", "failed"})
UNOFFICIAL_COMPLIANCE_CLASSES = frozenset({"unofficial_nonstandard", "unofficial_subscale"})
PHASE_ALIASES = {"standard": "power"}
UTC = _dt.timezone.utc
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
TIMESTAMP_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:\d{2})?$")

CohortKey = tuple[str, str]


class CorpusReadError(Exception):
    """A bundle could not be read or lacks the fields a cohort key needs."""


class RecencyStats(NamedTuple):
    """Oldest/newest run dates and ages for one cohort or the whole corpus."""

    oldest: _dt.date
    newest: _dt.date
    oldest_age_days: int
    newest_age_days: int
    bundle_count: int


def discover_bundles(bundles_dir: pathlib.Path) -> list[pathlib.Path]:
    """Primary result bundles under *bundles_dir*, companions excluded."""
    return sorted(
        path
        for path in bundles_dir.rglob("*.json")
        if path.name != LEGACY_MANIFEST_NAME and not path.name.endswith(COMPANION_SUFFIXES)
    )


def _load_bundle(bundle: pathlib.Path) -> dict:
    """Read one primary bundle; any failure is fatal for corpus gates."""
    try:
        with open(bundle, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception as exc:  # noqa: BLE001 - any read failure is fatal here
        raise CorpusReadError(f"ERROR reading {bundle}: {exc}") from exc


def _phase_executed(phase: object) -> bool:
    if not isinstance(phase, dict) or not phase:
        return False
    return str(phase.get("status") or "").upper() != "NOT_RUN"


def bundle_phase(payload: dict) -> str:
    benchmark = payload.get("benchmark")
    declared = benchmark.get("test_type") if isinstance(benchmark, dict) else None
    if declared:
        normalized = str(declared).strip().lower()
        return PHASE_ALIASES.get(normalized, normalized) or "unknown"
    phases = payload.get("phases")
    if not isinstance(phases, dict):
        return "unknown"
    if _phase_executed(phases.get("power_test")):
        return "power"
    if _phase_executed(phases.get("throughput_test")):
        return "throughput"
    return "unknown"


def _stream_count(payload: dict) -> int | None:
    phases = payload.get("phases")
    throughput = phases.get("throughput_test") if isinstance(phases, dict) else None
    streams = throughput.get("stream_results") if isinstance(throughput, dict) else None
    return len(streams) if isinstance(streams, list) and streams else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _query_row_failed(query: object) -> bool:
    if not isinstance(query, dict):
        return False
    if str(query.get("run_type") or "measurement").strip().lower() != "measurement":
        return False
    status = query.get("status")
    return status is not None and str(status).upper() not in {"SUCCESS", "SKIPPED"}


def failed_query_count(payload: dict) -> int:
    summary = payload.get("summary")
    if isinstance(summary, dict):
        queries = summary.get("queries")
        if isinstance(queries, dict):
            failed = _int_or_none(queries.get("failed"))
            if failed is not None and failed > 0:
                return failed
            total = _int_or_none(queries.get("total"))
            passed = _int_or_none(queries.get("passed"))
            skipped = _int_or_none(queries.get("skipped")) or 0
            if total is not None and passed is not None and total > passed + skipped:
                return total - passed - skipped
    rows = payload.get("queries")
    if isinstance(rows, list):
        return sum(1 for row in rows if _query_row_failed(row))
    return 0


def _status_text(value: object) -> str | None:
    if isinstance(value, dict):
        value = value.get("status")
    if value is None:
        return None
    return str(value).strip().lower() or None


def _query_validation_failed(payload: dict) -> bool:
    rows = payload.get("queries")
    if not isinstance(rows, list):
        return False
    return any(
        isinstance(row, dict)
        and isinstance(evidence := row.get("row_count_validation"), dict)
        and str(evidence.get("status") or "").strip().upper() == "FAILED"
        for row in rows
    )


def _translation_status(payload: dict) -> str | None:
    execution = payload.get("execution")
    return _status_text(execution.get("translation")) if isinstance(execution, dict) else None


def bundle_validation_status(payload: dict) -> str | None:
    summary = payload.get("summary")
    if summary is not None and not isinstance(summary, dict):
        return None
    recorded = summary.get("validation") if isinstance(summary, dict) else None
    failed = failed_query_count(payload)
    if not isinstance(recorded, (str, dict)):
        return "partial" if failed else None
    status = _status_text(recorded)
    if status in {None, "passed"}:
        if failed:
            return "partial"
        if not _query_validation_failed(payload) and _translation_status(payload) in NON_CLEAN_TRANSLATION_STATUSES:
            return "uncertain"
    return status


def bundle_rankable(payload: dict) -> bool:
    benchmark = payload.get("benchmark")
    compliance = benchmark.get("compliance_class") if isinstance(benchmark, dict) else None
    if compliance is not None and str(compliance) in UNOFFICIAL_COMPLIANCE_CLASSES:
        return False
    if failed_query_count(payload):
        return False
    return bundle_validation_status(payload) not in NON_CLEAN_VALIDATION_STATUSES


def _cohort_key(payload: dict) -> CohortKey:
    try:
        benchmark_id = payload["benchmark"]["id"]
        scale_factor = str(payload["benchmark"].get("scale_factor", ""))
    except Exception as exc:  # noqa: BLE001
        raise CorpusReadError(f"ERROR missing cohort fields: {exc}") from exc
    phase = bundle_phase(payload)
    if phase != "power":
        scale_factor = f"{scale_factor}#{phase}"
        streams = _stream_count(payload) if phase == "throughput" else None
        if streams is not None:
            scale_factor = f"{scale_factor}#{streams}streams"
    return (benchmark_id, scale_factor)


def _comparison_identity(bundle: pathlib.Path, payload: dict) -> str:
    try:
        platform_section = payload["platform"]
        platform = platform_section["name"]
        version = None
        if bundle.parent.name == "duckdb-version-matrix":
            version = platform_section.get("version") or platform_section.get("client_version")
            execution = payload.get("execution", {})
            if isinstance(execution, dict):
                for key in (
                    "driver_version_resolved",
                    "driver_version_requested",
                    "driver_resolved_version",
                    "driver_requested_version",
                ):
                    candidate = execution.get(key)
                    if candidate and str(candidate) != "unknown":
                        version = candidate
                        break
    except Exception as exc:  # noqa: BLE001
        raise CorpusReadError(f"ERROR reading platform identity from {bundle}: {exc}") from exc
    identity = str(platform)
    if version and str(version) != "unknown":
        identity = f"{identity} v{str(version)[:120]}"
    return identity


def parse_run_date(payload: dict, *, bundle: pathlib.Path | None = None) -> _dt.date:
    """Extract the calendar run date from ``run.timestamp``.

    ``YYYY-MM-DD`` is an explicit UTC calendar date. A complete ISO timestamp
    with ``Z`` or an offset is converted to its UTC calendar date. Legacy
    complete timestamps without an offset are interpreted as UTC. Prefixes,
    malformed times, and trailing text are rejected. Callers that treat age as
    informational (``cohort_recency``) catch errors and omit the bad value.
    """
    label = f" in {bundle}" if bundle is not None else ""
    try:
        timestamp = payload["run"]["timestamp"]
    except Exception as exc:  # noqa: BLE001
        raise CorpusReadError(f"ERROR missing run.timestamp{label}: {exc}") from exc
    if not isinstance(timestamp, str):
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}")

    if DATE_RE.fullmatch(timestamp):
        try:
            return _dt.date.fromisoformat(timestamp)
        except ValueError as exc:
            raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}") from exc

    if not TIMESTAMP_RE.fullmatch(timestamp):
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}")
    try:
        parsed = _dt.datetime.fromisoformat(f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp)
    except ValueError as exc:
        raise CorpusReadError(f"ERROR unparseable run.timestamp{label}: {timestamp!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).date()


def utc_today() -> _dt.date:
    """Current calendar date in UTC for informational recency calculations."""
    return _dt.datetime.now(UTC).date()


def age_days(run_date: _dt.date, *, as_of: _dt.date | None = None) -> int:
    """Whole days between *run_date* and *as_of* (default: current UTC day).

    Informational only. Age does not fail the depth gate and does not affect
    ranking eligibility (see ``ranking_exclusion_reason`` in explorer_pipeline).
    """
    as_of = as_of or utc_today()
    return (as_of - run_date).days


def _stats_from_dates(dates: list[_dt.date], *, as_of: _dt.date) -> RecencyStats:
    oldest = min(dates)
    newest = max(dates)
    return RecencyStats(
        oldest=oldest,
        newest=newest,
        oldest_age_days=age_days(oldest, as_of=as_of),
        newest_age_days=age_days(newest, as_of=as_of),
        bundle_count=len(dates),
    )


def cohort_platforms(bundles: list[pathlib.Path]) -> dict[CohortKey, set[str]]:
    """Map a cohort to distinct platform/version comparison identities.

    Cohorts are keyed by benchmark, scale and measured phase, and only bundles
    the explorer can rank contribute an identity. A cohort whose bundles are all
    unrankable stays in the map with no identities so the depth gate reports it.

    An explicitly segregated version-over-version corpus legitimately repeats
    one platform name. Only bundles under ``duckdb-version-matrix/`` therefore
    include a reported version in their identity. Ordinary cohorts retain the
    historical platform-only identity so three versions of one engine cannot
    weaken the cross-platform admission floor.

    Raises:
        CorpusReadError: if any bundle is unreadable or missing a key field.
            Fail closed -- an unparseable bundle is exactly the state a
            truncated or unreviewed one would be in, and skipping it would let
            the corpus regress while this gate stayed green.
    """
    cohorts: collections.defaultdict[CohortKey, set[str]] = collections.defaultdict(set)
    for bundle in bundles:
        payload = _load_bundle(bundle)
        identities = cohorts[_cohort_key(payload)]
        if bundle_rankable(payload):
            identities.add(_comparison_identity(bundle, payload))
    return dict(cohorts)


def cohort_recency(
    bundles: list[pathlib.Path],
    *,
    as_of: _dt.date | None = None,
) -> tuple[RecencyStats | None, dict[CohortKey, RecencyStats], list[str]]:
    """Per-cohort and overall oldest/newest run ages from bundle timestamps.

    Returns ``(overall, per_cohort, warnings)``. *overall* is ``None`` when no
    parseable timestamps remain. Bundles with a missing or unparseable
    ``run.timestamp`` are omitted from the report and listed in *warnings*.
    Age never participates in the depth-gate exit code.
    """
    as_of = as_of or utc_today()
    by_cohort: collections.defaultdict[CohortKey, list[_dt.date]] = collections.defaultdict(list)
    all_dates: list[_dt.date] = []
    warnings: list[str] = []
    for bundle in bundles:
        payload = _load_bundle(bundle)
        try:
            run_date = parse_run_date(payload, bundle=bundle)
        except CorpusReadError as exc:
            # Age is informational: omit, warn, and leave the depth exit alone.
            warnings.append(str(exc).replace("ERROR", "WARN", 1))
            continue
        key = _cohort_key(payload)
        by_cohort[key].append(run_date)
        all_dates.append(run_date)
    per_cohort = {key: _stats_from_dates(dates, as_of=as_of) for key, dates in by_cohort.items()}
    overall = _stats_from_dates(all_dates, as_of=as_of) if all_dates else None
    return overall, per_cohort, warnings


def format_recency_report(
    overall: RecencyStats | None,
    per_cohort: dict[CohortKey, RecencyStats],
    *,
    as_of: _dt.date,
) -> str:
    """Human-readable recency report; does not encode a pass/fail decision."""
    lines = [
        "Recency (from run.timestamp; informational only — age does not fail "
        "the depth gate and does not affect ranking eligibility):",
        f"  as_of={as_of.isoformat()}",
    ]
    if overall is None:
        lines.append("  Overall: no parseable run timestamps")
        return "\n".join(lines)
    lines.append(
        "  Overall: "
        f"oldest={overall.oldest.isoformat()} ({overall.oldest_age_days} days), "
        f"newest={overall.newest.isoformat()} ({overall.newest_age_days} days), "
        f"{overall.bundle_count} bundles"
    )
    lines.append("  Cohorts:")
    for key, stats in sorted(per_cohort.items()):
        lines.append(
            f"    {key[0]} SF={key[1]}: "
            f"oldest={stats.oldest.isoformat()} ({stats.oldest_age_days} days), "
            f"newest={stats.newest.isoformat()} ({stats.newest_age_days} days), "
            f"{stats.bundle_count} bundles"
        )
    return "\n".join(lines)


def shallow_cohorts(cohorts: dict[CohortKey, set[str]]) -> dict[CohortKey, set[str]]:
    """Cohorts with some rankable identities but fewer than the required number.

    A cohort with no rankable identity publishes no ranking, so it is reported
    by ``unranked_cohorts`` instead of failing the gate.
    """
    return {key: platforms for key, platforms in cohorts.items() if 0 < len(platforms) < MINIMUM_PLATFORMS_PER_COHORT}


def unranked_cohorts(cohorts: dict[CohortKey, set[str]]) -> list[CohortKey]:
    return sorted(key for key, platforms in cohorts.items() if not platforms)


def main(bundles_dir: pathlib.Path | None = None, *, as_of: _dt.date | None = None) -> int:
    """Print the cohort and recency reports; exit code reflects depth only."""
    bundles_dir = bundles_dir or pathlib.Path(__file__).parent / "bundles"
    as_of = as_of or utc_today()
    bundles = discover_bundles(bundles_dir)
    print(f"Found {len(bundles)} bundles")

    try:
        cohorts = cohort_platforms(bundles)
    except CorpusReadError as exc:
        print(exc)
        return 1

    print("\nCohorts:")
    for key, platforms in sorted(cohorts.items()):
        if not platforms:
            status = "UNRANKED (no rankable bundles; no ranking published)"
        elif len(platforms) >= MINIMUM_PLATFORMS_PER_COHORT:
            status = "OK"
        else:
            status = "WARN (<3 identities)"
        print(f"  {key[0]} SF={key[1]}: {len(platforms)} identities ({sorted(platforms)}) [{status}]")

    # Recency is informational: timestamp parse failures warn and omit, and
    # never override the depth exit code computed below.
    try:
        overall, per_cohort, recency_warnings = cohort_recency(bundles, as_of=as_of)
    except CorpusReadError as exc:
        # Unreadable payload after a successful depth pass is unexpected; warn
        # and continue with an empty recency report rather than flipping depth.
        print(f"WARN recency skipped: {exc}")
        overall, per_cohort, recency_warnings = None, {}, []
    for warning in recency_warnings:
        print(warning)

    print()
    print(format_recency_report(overall, per_cohort, as_of=as_of))

    low = shallow_cohorts(cohorts)
    if low:
        print(f"\nWARN: {len(low)} cohort(s) have <3 comparison identities: { {k: len(v) for k, v in low.items()} }")
        return 1

    unranked = unranked_cohorts(cohorts)
    if unranked:
        print(f"\nUNRANKED: {len(unranked)} cohort(s) have no rankable bundle and publish no ranking: {unranked}")
    ranked = len(cohorts) - len(unranked)
    print(f"\nAll {ranked} ranked cohort(s) meet the >={MINIMUM_PLATFORMS_PER_COHORT}-identity depth criterion.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
