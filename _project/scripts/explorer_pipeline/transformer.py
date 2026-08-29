"""Bundle-to-read-model transformer for the explorer static build pipeline.

Reads schema-v2 result bundle JSON files and converts them into the
ManifestEntry and DetailResult shapes consumed by the explorer frontend.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, cast

from _project.scripts.explorer_pipeline.models import (
    BasisAvailability,
    DetailResult,
    ManifestEntry,
    PercentileStats,
    QueryDisplayTiming,
    QueryTiming,
    _platform_id,
    ranking_exclusion_reason,
    timing_eligibility,
)
from benchbox.core.cost.models import CostScope, CostStatus, DeploymentMetadata, NormalizedCost
from benchbox.core.cost.pricing import PRICING_VERSION
from benchbox.core.results.anonymization import AnonymizationManager, find_public_path_leaks
from benchbox.core.results.canonical_json import canonical_json_bytes
from benchbox.core.results.schema_policy import EXPLORER_INPUT_SCHEMA_POLICY
from benchbox.core.results.status import bundle_failed_query_count, bundle_non_clean_reason, normalize_validation_status
from benchbox.core.tuning.modes import is_canonical_mode
from benchbox.validation.bundle import APPLIED_COMPANION_MAX_BYTES, APPLIED_RECEIPT_MAX_ENTRIES, COMPANION_SUFFIXES

logger = logging.getLogger(__name__)


class CompanionPrivacyError(Exception):
    """A companion remained private after the public anonymization boundary."""


def _companion_path(bundle_path: Path, suffix: str) -> Path:
    """Return the exact same-stem companion path for a primary bundle."""
    return bundle_path.with_name(f"{bundle_path.stem}{suffix}")


def _redact_applied_dropped(payload: dict[str, Any], key: str = "dropped") -> None:
    dropped = payload.get(key)
    if dropped:
        count = len(dropped) if isinstance(dropped, list) else 1
        payload[key] = [{"redacted": True} for _ in range(count)]


def _sanitize_applied_drift_check(drift_check: Any) -> None:
    if not isinstance(drift_check, dict):
        return
    removed = False
    for key in ("errors", "warnings", "configuration_mismatches", "missing_tables", "extra_tables"):
        if key in drift_check:
            drift_check.pop(key, None)
            removed = True
    if removed:
        drift_check["drift_redacted"] = True


# Stand-in for a receipt container whose shape none of the redaction rules
# below can reach. Publishing such a value verbatim is the failure this marker
# exists to prevent, so it carries no payload from the source document.
_REDACTED_APPLIED_SHAPE: dict[str, Any] = {"redacted": True, "reason": "unexpected_shape"}


def _sanitize_applied_entry(entry: dict[str, Any]) -> None:
    for key in ("statement", "diff", "detail", "evidence", "table", "name", "expected_columns", "observed_columns"):
        entry.pop(key, None)
    if "reason" in entry:
        entry.pop("reason", None)
        entry["reason_redacted"] = True
    entry["statement_redacted"] = True


def _sanitize_applied_observed(observed: dict[str, Any]) -> None:
    for key in ("table", "name", "columns", "evidence"):
        observed.pop(key, None)
    observed["redacted"] = True


def _sanitized_applied_container(value: Any, sanitize_item: Any) -> Any:
    """Sanitize a receipt sub-list, failing closed on an unexpected shape.

    A non-list here (or a non-object inside it) is free text no redaction rule
    matches. Iterating it would silently pass the original through - a string
    yields characters, none of which are dicts - so replace it with a marker.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        return dict(_REDACTED_APPLIED_SHAPE)
    sanitized: list[Any] = []
    for item in value:
        if not isinstance(item, dict):
            sanitized.append(dict(_REDACTED_APPLIED_SHAPE))
            continue
        sanitize_item(item)
        sanitized.append(item)
    return sanitized


def _sanitize_applied_receipt(receipt: Any) -> Any:
    """Sanitize the introspection receipt, redacting shapes it cannot inspect.

    Returning an unexpected shape untouched published it verbatim: a companion
    such as ``{"receipt": "private_customer_catalog"}`` parses, survives the
    generic anonymizer, and carries no absolute path for the leak detector to
    catch, so the free text reached the public sidecar intact.
    """
    if receipt is None:
        return None
    if not isinstance(receipt, dict):
        return dict(_REDACTED_APPLIED_SHAPE)
    if "error" in receipt:
        receipt.pop("error", None)
        receipt["error_redacted"] = True
    # Keyed on presence, not truthiness, so an absent key is never introduced.
    if "entries" in receipt:
        receipt["entries"] = _sanitized_applied_container(receipt["entries"], _sanitize_applied_entry)
    if "observed" in receipt:
        receipt["observed"] = _sanitized_applied_container(receipt["observed"], _sanitize_applied_observed)
    _redact_applied_dropped(receipt)
    return receipt


def _sanitize_applied_companion(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove free-text and user identifiers from an applied-ledger payload.

    Applied statements, dropped-intent reasons, and introspection evidence are
    execution-path text and may contain paths, DSNs, or user-chosen catalog
    names. Preserve only the structural/status evidence needed by the public
    companion; this mirrors the exporter boundary for already-exported inputs.
    """
    sanitized = copy.deepcopy(payload)
    statements = sanitized.get("statements")
    if isinstance(statements, list):
        for entry in statements:
            if not isinstance(entry, dict):
                continue
            entry.pop("statement", None)
            entry.pop("error", None)
            entry.pop("table", None)
            entry["statement_redacted"] = True
    _redact_applied_dropped(sanitized)
    _sanitize_applied_drift_check(sanitized.get("drift_check"))
    if "receipt" in sanitized:
        sanitized["receipt"] = _sanitize_applied_receipt(sanitized["receipt"])
    return sanitized


def _public_companion_bytes(
    bundle_path: Path,
    suffix: str,
    anonymizer: AnonymizationManager,
) -> bytes | None:
    """Load, validate, anonymize, and canonicalize one optional companion.

    Missing, malformed, oversized, or non-regular companions are ignored so a
    bad sidecar cannot be advertised or copied. A companion that still contains
    a private path after anonymization is different: that is a publication
    boundary violation and must fail the build rather than silently publish a
    partial public artifact.
    """
    if suffix not in COMPANION_SUFFIXES:
        raise ValueError(f"unsupported explorer companion suffix: {suffix}")

    source = _companion_path(bundle_path, suffix)
    if not source.exists():
        return None
    if source.is_symlink() or not source.is_file():
        logger.warning("Skipping non-regular companion %s", source)
        return None
    try:
        if suffix == ".applied.json" and source.stat().st_size > APPLIED_COMPANION_MAX_BYTES:
            logger.warning("Skipping oversized applied companion %s", source)
            return None
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Skipping malformed companion %s - %s: %s", source, type(exc).__name__, exc)
        return None

    if not isinstance(payload, dict):
        logger.warning("Skipping non-object companion %s", source)
        return None

    if suffix == ".tuning.json":
        public_payload = anonymizer.anonymize_tuning_payload(payload)
    elif suffix == ".applied.json":
        public_payload = _sanitize_applied_companion(anonymizer.anonymize_result_payload(payload))
    else:
        public_payload = anonymizer.anonymize_result_payload(payload)

    leaks = find_public_path_leaks(public_payload)
    if leaks:
        raise CompanionPrivacyError(
            f"public {suffix.removesuffix('.json').lstrip('.')} privacy check failed for fields: "
            + ", ".join(sorted(set(leaks)))
        )
    return canonical_json_bytes(public_payload)


# Status values that are considered passing for the query timing status field.
_PASS_STATUSES = {"SUCCESS", "PASS", "pass", "success"}
# Allowed run_type values for query execution rows ingested into query_executions.
# Narrows the ingest filter to execution timings only (measurement + warmup),
# explicitly excluding metadata and summary pseudo-rows.
_ALLOWED_EXECUTION_RUN_TYPES: frozenset[str] = frozenset({"measurement", "warmup"})
_COST_MODEL_SOURCE = "benchbox.core.cost.pricing"
_COST_SCOPES: frozenset[str] = frozenset({"compute_only", "compute_plus_storage"})
_COST_STATUSES: frozenset[str] = frozenset({"normalized", "not_applicable_local", "unavailable"})
_KNOWN_LOGICAL_QUERY_COUNTS: dict[str, int] = {
    "tpch": 22,
    "tpch_skew": 22,
    "tpchavoc": 22,
    "tpcds": 99,
    "ssb": 13,
    "star_schema": 13,
    "clickbench": 43,
}


def _load_bundle(bundle_path: Path) -> tuple[dict[str, Any], bytes]:
    """Load and parse a bundle JSON file.

    Returns both the parsed dict and the raw bytes so callers can compute
    a content hash without a second file read.
    """
    raw = bundle_path.read_bytes()
    data = json.loads(raw)
    _ensure_explorer_input_schema(data)
    return data, raw


def _ensure_explorer_input_schema(data: dict[str, Any]) -> None:
    """Reject unsupported bundles before explorer field projection starts."""
    decision = EXPLORER_INPUT_SCHEMA_POLICY.evaluate(data.get("version"))
    if not decision.accepted:
        raise ValueError(decision.error_message())


def _sha256_prefix(raw: bytes, length: int = 8) -> str:
    """Return the first *length* hex chars of the SHA-256 of *raw* bytes."""
    return hashlib.sha256(raw).hexdigest()[:length]


def _run_date_from_timestamp(timestamp: str) -> str:
    """Extract YYYYMMDD from an ISO timestamp string."""
    # Timestamp may be "2026-01-15T12:00:00" or "2026-01-15T12:00:00.123456"
    date_part = timestamp[:10]  # "YYYY-MM-DD"
    return date_part.replace("-", "")


def _driver_version(data: dict[str, Any]) -> str | None:
    """Extract the package version used to identify a DuckDB run.

    DuckDB development wheels can report an internal engine build string from
    ``SELECT version()`` that is unrelated to the wheel version (for example,
    ``1.6.0.dev365`` reports ``2.0.0-alpha...``). The resolved package version
    is the stable comparison identity; the raw bundle still retains the actual
    engine string for auditability.
    """
    execution = data.get("execution", {})
    if not isinstance(execution, dict):
        execution = {}
    platform = data.get("platform", {})
    is_duckdb = isinstance(platform, dict) and str(platform.get("name", "")).lower() == "duckdb"
    if is_duckdb:
        for key in (
            "driver_version_resolved",
            "driver_version_requested",
            "driver_resolved_version",
            "driver_requested_version",
        ):
            val = execution.get(key)
            if val and isinstance(val, str):
                return val
        client_version = platform.get("client_version") if isinstance(platform, dict) else None
        if client_version and isinstance(client_version, str) and client_version != "unknown":
            return client_version
    for key in (
        "driver_version_actual",
        "driver_version_resolved",
        "driver_version_requested",
        "driver_actual_version",
        "driver_resolved_version",
        "driver_requested_version",
    ):
        val = execution.get(key)
        if val and isinstance(val, str):
            return val
    return None


def _power_score(data: dict[str, Any]) -> float | None:
    """Extract TPC power@size metric from a schema-v2 bundle."""
    summary = data.get("summary", {})
    tpc = summary.get("tpc_metrics", {}) if isinstance(summary, dict) else {}
    if isinstance(tpc, dict):
        for key in ("power_at_size", "qphh_at_size", "qphds_at_size"):
            val = tpc.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    pass
    return None


def _geomean_ms(data: dict[str, Any]) -> float | None:
    """Compute geometric mean of measurement-query execution times in milliseconds.

    Uses only queries with run_type="measurement" (or all when run_type is absent).
    Returns None if no valid positive timings exist.
    """
    raw_queries: list[dict[str, Any]] = data.get("queries", [])
    values: list[float] = []
    for q in raw_queries:
        if not isinstance(q, dict):
            continue
        run_type = q.get("run_type")
        if run_type is not None and run_type != "measurement":
            continue
        ms_raw = q.get("ms")
        duration_ms_raw = ms_raw if ms_raw is not None else q.get("execution_time_ms")
        if duration_ms_raw is None:
            continue
        try:
            ms = float(duration_ms_raw)
        except (TypeError, ValueError):
            continue
        if ms > 0:
            values.append(ms)
    if not values:
        return None
    return math.exp(sum(math.log(v) for v in values) / len(values))


_FUNDING_SOURCES = ("employer", "personal", "free-trial", "vendor-sponsored", "grant", "unspecified")


def _funding(data: dict[str, Any]) -> str:
    """Extract the funding disclosure from a bundle's provenance block.

    Returns the normalized funding value, defaulting to "unspecified" when the
    bundle declares no provenance or an unrecognized value. Kept in lockstep with
    benchbox/core/results/provenance.py::FUNDING_SOURCES.
    """
    provenance = data.get("provenance")
    if not isinstance(provenance, dict):
        return "unspecified"
    token = str(provenance.get("funding") or "").strip().lower()
    return token if token in _FUNDING_SOURCES else "unspecified"


def _platform_version(data: dict[str, Any]) -> str | None:
    """Extract platform version from schema-v2 bundle."""
    platform = data.get("platform", {})
    if not isinstance(platform, dict):
        return None
    if str(platform.get("name", "")).lower() == "duckdb":
        execution = data.get("execution", {})
        if isinstance(execution, dict):
            for key in (
                "driver_version_resolved",
                "driver_version_requested",
                "driver_resolved_version",
                "driver_requested_version",
            ):
                value = execution.get(key)
                if value and isinstance(value, str):
                    return value
        client_version = platform.get("client_version")
        if client_version and client_version != "unknown":
            return str(client_version)
    val = platform.get("version")
    return str(val) if val and val != "unknown" else None


#: Ordered key paths consulted for a bundle's SQL-vs-DataFrame execution mode.
#:
#: Measured against all 207 published bundles on 2026-08-23:
#:   - ``config.execution_mode`` and ``execution.execution_mode`` are the
#:     documented schema locations but NO bundle writes either, which is why
#:     the facet was NULL for 207 of 207 rows.
#:   - ``platform.config.execution_mode`` is populated on every bundle,
#:     including ones produced by current develop.
#:   - ``config.mode`` agrees with it on all 207.
#:   - Both agree with the filename suffix (``_df_`` / ``_sql_``) wherever one
#:     exists: 105 df, 95 sql, 7 without a suffix.
#:
#: ``execution.mode`` is deliberately NOT consulted: it reads "sql" for 105
#: DataFrame runs, so using it would label more than half the corpus wrongly.
_EXECUTION_MODE_KEY_PATHS: tuple[tuple[str, ...], ...] = (
    ("config", "execution_mode"),
    ("platform", "config", "execution_mode"),
    ("config", "mode"),
    ("execution", "execution_mode"),
)

#: Values a bundle may legitimately carry for execution mode.
_EXECUTION_MODES = frozenset({"sql", "dataframe"})


def _execution_mode(data: dict[str, Any]) -> str | None:
    """Extract execution mode (sql/dataframe) from a schema-v2 bundle.

    Walks :data:`_EXECUTION_MODE_KEY_PATHS` in order and returns the first
    recognized value. A bundle that records no mode, or records something
    outside the known vocabulary, stays ``None`` rather than being guessed --
    an invented mode would label a DataFrame result as SQL, which is worse
    than an honestly empty facet.
    """
    for path in _EXECUTION_MODE_KEY_PATHS:
        node: Any = data
        for key in path:
            if not isinstance(node, dict):
                node = None
                break
            node = node.get(key)
        if node and str(node).lower() in _EXECUTION_MODES:
            return str(node).lower()
    return None


def _tuning_mode(data: dict[str, Any]) -> str | None:
    """Extract tuning mode from a schema-v2 bundle.

    Reads ``config.tuning_mode`` first (the current schema location), falling
    back to ``execution.tuning_mode`` for the seed-corpus generation that
    wrote the value there instead. When neither location carries a value the
    result stays ``None`` -- callers must not invent a mode for bundles that
    never recorded one (see explorer ingest tuning-mode-extraction TODO).

    ADR-2 (docs/development/tuning-adr-002-mode-vocabulary-fallback-facets.md)
    §2 pins the legal ``tuning_mode`` vocabulary to exactly
    ``{tuned, tuned-fallback, notuning, auto, custom}``. Older bundles
    predating that pin may carry a raw local tuning-file path (from before
    ``--tuning <path>`` runs were required to record ``custom``) or the
    wizard's old ``"balanced"`` flavor string. Per the ADR's consequences
    section, ingest does not guess which of the five buckets an
    unrecognized legacy value belongs in -- it is treated as not-recorded
    (``None`` here; the explorer surfaces that as the "Not Recorded" state)
    rather than silently reclassified.
    """
    config = data.get("config", {})
    if isinstance(config, dict):
        val = config.get("tuning_mode")
        if val and is_canonical_mode(str(val)):
            return str(val)
    execution = data.get("execution", {})
    if isinstance(execution, dict):
        val = execution.get("tuning_mode")
        if val and is_canonical_mode(str(val)):
            return str(val)
    return None


def _tuning_hash(data: dict[str, Any]) -> str | None:
    """Compute a stable 8-char hash of the tuning configuration.

    Only machine-readable tuning detail is hashed: a dict is hashed
    canonically (``json.dumps(..., sort_keys=True)``), but a string value
    (e.g. a Python ``repr()`` of a dataclass, which is not canonical and
    varies cosmetically between otherwise-identical configs) is dropped
    rather than hashed. The resolved tuning mode (see ``_tuning_mode``, which
    includes the ``execution.tuning_mode`` fallback) may still be hashed on
    its own when no machine-readable detail is present. Returns None when
    there is neither a mode nor machine-readable detail to hash.
    """
    mode = _tuning_mode(data)
    config = data.get("config", {})
    tuning_detail: dict[str, Any] | None = None
    if isinstance(config, dict):
        raw_detail = config.get("tuning_config") or config.get("tuning")
        if isinstance(raw_detail, dict):
            tuning_detail = raw_detail
        # Non-dict detail (e.g. a repr() string) is intentionally not hashed:
        # it is not canonical, so cosmetic differences would change the hash
        # even when the underlying tuning configuration is identical.
    if mode is None and tuning_detail is None:
        return None
    payload = json.dumps({"mode": mode, "detail": tuning_detail}, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:8]


def _tuning_summary(data: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``platform.tuning`` summary block, or None when absent.

    This is the per-platform tuning summary emitted by
    ``benchbox/core/results/schema.py::_build_tuning_summary`` -- the same
    block that carries ``logical_profile`` (see ``_logical_profile``). None
    for legacy bundles that never recorded a tuning summary.
    """
    platform = data.get("platform", {})
    if not isinstance(platform, dict):
        return None
    tuning = platform.get("tuning", {})
    return tuning if isinstance(tuning, dict) else None


def _requested_config_hash(data: dict[str, Any]) -> str | None:
    """Ingest the ADR-1 canonical requested-config hash from the bundle.

    Read verbatim from ``platform.tuning.requested_config_hash`` (emitted by
    ``_build_tuning_summary``); never recomputed here. None for legacy bundles
    that predate the field. Display-only, like ``tuning_hash`` -- never a
    join/dedup/grouping key.
    """
    summary = _tuning_summary(data)
    if summary is None:
        return None
    val = summary.get("requested_config_hash")
    return str(val) if val else None


def _applied_ledger_hash(data: dict[str, Any]) -> str | None:
    """Ingest the ADR-1 physical applied-ledger hash from the bundle.

    Read verbatim from ``platform.tuning.applied_ledger_hash`` (emitted by
    ``_build_tuning_summary`` from the execution-path applied ledger); never
    recomputed here. None for legacy bundles, or new-generation bundles whose
    applied ledger recorded no executed statements. Display-only.
    """
    summary = _tuning_summary(data)
    if summary is None:
        return None
    val = summary.get("applied_ledger_hash")
    return str(val) if val else None


def _tuning_validation_status(data: dict[str, Any]) -> str | None:
    """Ingest the ADR-1 tuning verified-state from the bundle.

    Read verbatim from ``platform.tuning.validation_status`` (emitted by
    ``_build_tuning_summary`` from the execution-path applied ledger's honest
    ``tuning_validation_status``: not_applicable / noop / applied_unverified /
    applied_verified / failed). ``applied_verified`` means the post-load
    introspection receipt corroborated the applied ledger against the live
    catalog. ``None`` for legacy bundles predating the field -- the explorer
    treats absence as "unknown". Display-only; never a join/match key.
    """
    summary = _tuning_summary(data)
    if summary is None:
        return None
    val = summary.get("validation_status")
    return str(val) if val else None


def _applied_receipt(bundle_path: Path) -> str | None:
    """Ingest the per-statement introspection receipt from the applied companion.

    The ``{stem}.applied.json`` companion sits next to the bundle (published
    alongside it by ``benchbox.validation.bundle``). Its ``receipt`` sub-object
    is the post-load introspection receipt that earns the ``applied_verified``
    state: platform, corroboration verdict, summary, and one entry per applied
    statement. It is taken **verbatim** and re-serialized canonically
    (``sort_keys``, compact separators) so the stored string is deterministic;
    nothing here is recomputed or derived, and the explorer renders it read-only.

    ``None`` whenever the receipt is not available -- companion absent (the
    common case: introspection did not run, or a legacy bundle), unreadable,
    malformed JSON, not a JSON object, or carrying no ``receipt`` key. A broken
    companion must never fail the build, so every failure degrades to ``None``.
    Inputs beyond the public submission caps are the exception: already-published
    legacy data is bounded defensively and stored with an explicit truncation
    marker rather than being silently dropped.
    """
    companion = bundle_path.with_name(f"{bundle_path.stem}.applied.json")
    try:
        companion_size = companion.stat().st_size
    except (OSError, ValueError):
        return None
    if companion_size > APPLIED_COMPANION_MAX_BYTES:
        return json.dumps(
            {
                "entries": [],
                "original_byte_count": companion_size,
                "truncated": True,
                "truncation_reason": "byte_limit",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    try:
        payload = json.loads(companion.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    receipt = payload.get("receipt")
    if receipt is None:
        return None
    if isinstance(receipt, dict) and isinstance(receipt.get("entries"), list):
        entries = receipt["entries"]
        if len(entries) > APPLIED_RECEIPT_MAX_ENTRIES:
            receipt = {
                **receipt,
                "entries": entries[:APPLIED_RECEIPT_MAX_ENTRIES],
                "original_entry_count": len(entries),
                "truncated": True,
                "truncation_reason": "entry_limit",
            }
    try:
        return json.dumps(receipt, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError):
        return None


def _tuning_policy_generation(data: dict[str, Any]) -> str | None:
    """Ingest the ADR-3 explicit tuning-policy generation marker from the bundle.

    Read verbatim from ``platform.tuning.tuning_policy_generation`` (emitted by
    ``_build_tuning_summary``); never derived from ``benchbox_version`` or
    recomputed here. ``None`` for legacy bundles that predate the field -- the
    explorer treats that absence as the "pre-seam" generation. Display-only,
    like the tuning hashes: never a join/dedup/grouping/match key.
    """
    summary = _tuning_summary(data)
    if summary is None:
        return None
    val = summary.get("tuning_policy_generation")
    return str(val) if val else None


def _logical_profile(data: dict[str, Any]) -> dict[str, Any] | None:
    """Extract the `platform.tuning.logical_profile` block (ADR-2 §3).

    Returns `None` when no logical profile was recorded at all (unknown --
    e.g. a legacy bundle predating this field), distinct from an empty `{}`
    profile object, which -- were a bundle ever to emit one -- would mean a
    profile WAS recorded. Callers use this `None` vs "object present" split
    to distinguish "unknown" from "recorded, just empty" for fields like
    physical_mechanisms (see `_physical_mechanisms`).
    """
    platform = data.get("platform", {})
    if not isinstance(platform, dict):
        return None
    tuning = platform.get("tuning", {})
    if not isinstance(tuning, dict):
        return None
    profile = tuning.get("logical_profile")
    return profile if isinstance(profile, dict) else None


def _physical_mechanisms(data: dict[str, Any]) -> list[str] | None:
    """Extract the platform-rendered physical tuning mechanisms.

    Tri-state (see `DetailResult.physical_mechanisms`): `None` when no
    logical_profile was recorded at all (unknown), `[]` when a
    logical_profile IS present but recorded zero mechanisms (a genuine,
    comparable value -- the ADR-2 motivating case of a platform rendering
    zero mechanisms for a tuned template). Collapsing these would make an
    unknown/legacy bundle compared against a genuinely zero-mechanism bundle
    look like a real mismatch instead of "nothing to compare".
    """
    profile = _logical_profile(data)
    if profile is None:
        return None
    mechanisms = profile.get("physical_mechanisms", [])
    if not isinstance(mechanisms, list):
        return []
    return [str(item) for item in mechanisms]


def _physical_rendering_id(data: dict[str, Any]) -> str | None:
    """Extract the physical rendering strategy id (ADR-2 §3 secondary facet)."""
    profile = _logical_profile(data)
    if profile is None:
        return None
    val = profile.get("physical_rendering_id")
    return str(val) if val else None


def _test_type(data: dict[str, Any]) -> str | None:
    """Extract test type (power/throughput) from schema-v2 bundle."""
    benchmark = data.get("benchmark", {})
    if isinstance(benchmark, dict):
        val = benchmark.get("test_type")
        if val:
            return str(val)
    phases = data.get("phases", {})
    if isinstance(phases, dict):
        if phases.get("power_test"):
            return "power"
        if phases.get("throughput_test"):
            return "throughput"
    return None


def _validation_status(data: dict[str, Any]) -> str | None:
    """Extract validation status from schema-v2 bundle summary.

    Handles both string (``"passed"``) and dict (``{"status": "passed", ...}``)
    forms of ``summary.validation``.
    """
    summary = data.get("summary", {})
    if not isinstance(summary, dict):
        return None
    val = summary.get("validation")
    failed_queries = bundle_failed_query_count(data)
    if isinstance(val, str):
        normalized = normalize_validation_status(val)
        if failed_queries and normalized in {None, "passed"}:
            return "partial"
        if _translation_uncertain(data, normalized):
            return "uncertain"
        return normalized
    if isinstance(val, dict):
        s = val.get("status")
        normalized = normalize_validation_status(s)
        if failed_queries and normalized in {None, "passed"}:
            return "partial"
        if _translation_uncertain(data, normalized):
            return "uncertain"
        return normalized
    if failed_queries:
        return "partial"
    return None


def _translation_uncertain(data: dict[str, Any], validation_status: str | None) -> bool:
    if validation_status not in {None, "passed"}:
        return False
    reason = bundle_non_clean_reason(data)
    return bool(reason and reason.startswith("translation_status="))


def _unavailable_normalized_cost() -> NormalizedCost:
    """Return explicit normalized-cost-unavailable metadata for old bundles."""
    return NormalizedCost(
        normalized_cost_usd=None,
        cost_model_version=PRICING_VERSION,
        cost_model_source=_COST_MODEL_SOURCE,
        cost_scope="compute_only",
        cost_status="unavailable",
        billing_unit="unknown",
        pricing_region="unknown",
    )


def _raw_normalized_cost_block(data: dict[str, Any]) -> dict[str, Any] | None:
    """Find a normalized cost block in current or near-future bundle shapes."""
    raw = data.get("normalized_cost")
    if isinstance(raw, dict):
        return raw

    cost = data.get("cost", {})
    if not isinstance(cost, dict):
        return None

    for key in ("normalized_cost", "normalized"):
        raw = cost.get(key)
        if isinstance(raw, dict):
            return raw

    normalized_keys = {
        "normalized_cost_usd",
        "cost_model_version",
        "cost_model_source",
        "cost_scope",
        "cost_status",
    }
    if normalized_keys.intersection(cost):
        return cost

    return None


def _decimal_or_none(val: Any) -> Decimal | None:
    try:
        parsed = Decimal(str(val)) if val is not None else None
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid normalized_cost_usd value: {val!r}") from exc
    if parsed is not None and not parsed.is_finite():
        raise ValueError(f"Invalid normalized_cost_usd value: {val!r}")
    return parsed


def _deployment_metadata(raw: Any) -> DeploymentMetadata:
    if not isinstance(raw, dict):
        return DeploymentMetadata()
    node_count = raw.get("node_count")
    return DeploymentMetadata(
        cloud_provider=raw.get("cloud_provider"),
        cloud_region=raw.get("cloud_region"),
        instance_type=raw.get("instance_type"),
        warehouse_size=raw.get("warehouse_size"),
        node_count=int(node_count) if node_count is not None else None,
        cluster_size=raw.get("cluster_size"),
        storage_format=raw.get("storage_format"),
        storage_tier=raw.get("storage_tier"),
    )


def _require_cost_choice(raw: dict[str, Any], key: str, choices: frozenset[str]) -> str:
    value = raw.get(key)
    if value not in choices:
        raise ValueError(f"Normalized cost field {key!r} must be one of {sorted(choices)}; got {value!r}")
    return str(value)


def _require_cost_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Normalized cost field {key!r} must be a non-empty string")
    return value


def _normalized_cost_from_block(raw: dict[str, Any]) -> NormalizedCost:
    """Build a validated NormalizedCost from a bundle payload."""
    return NormalizedCost(
        normalized_cost_usd=_decimal_or_none(raw.get("normalized_cost_usd")),
        cost_model_version=_require_cost_string(raw, "cost_model_version"),
        cost_model_source=_require_cost_string(raw, "cost_model_source"),
        cost_scope=cast(CostScope, _require_cost_choice(raw, "cost_scope", _COST_SCOPES)),
        cost_status=cast(CostStatus, _require_cost_choice(raw, "cost_status", _COST_STATUSES)),
        billing_unit=_require_cost_string(raw, "billing_unit"),
        pricing_region=_require_cost_string(raw, "pricing_region"),
        deployment=_deployment_metadata(raw.get("deployment")),
    )


def _normalized_cost(data: dict[str, Any]) -> NormalizedCost:
    """Extract normalized BenchBox cost or explicit unavailable metadata."""
    raw = _raw_normalized_cost_block(data)
    if raw is None:
        return _unavailable_normalized_cost()
    return _normalized_cost_from_block(raw)


def _cost_usd_alias(cost: NormalizedCost) -> float | None:
    """Return the legacy compute-only cost alias for read-model compatibility."""
    if cost.cost_usd is None:
        return None
    return float(cost.cost_usd)


def _mapping_or_empty(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _string_or_none(raw: Any) -> str | None:
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def _first_string(*values: Any) -> str | None:
    for value in values:
        parsed = _string_or_none(value)
        if parsed is not None:
            return parsed
    return None


def _deployment_class_from_contract(data: dict[str, Any]) -> str | None:
    """Classify deployment from normalized runtime/deployment metadata only."""
    environment = _mapping_or_empty(data.get("environment"))
    runtime = _mapping_or_empty(environment.get("platform_runtime"))
    platform = _mapping_or_empty(data.get("platform"))
    deployment = _mapping_or_empty(platform.get("deployment"))

    runtime_type = _string_or_none(runtime.get("runtime_type"))
    deployment_type = _string_or_none(deployment.get("deployment_type"))
    endpoint_class = _string_or_none(deployment.get("endpoint_class"))

    runtime_key = runtime_type.lower() if runtime_type else None
    deployment_key = deployment_type.lower() if deployment_type else None
    endpoint_key = endpoint_class.lower() if endpoint_class else None

    if runtime_key in {"managed_cloud", "serverless"}:
        return "cloud"
    if deployment_key in {"managed_cloud", "serverless"} or endpoint_key == "cloud_endpoint":
        return "cloud"
    if runtime_key in {"local_process", "dataframe_process", "docker_container"}:
        return "local"
    if deployment_key == "embedded" or endpoint_key in {"embedded_process", "localhost_port"}:
        return "local"
    if runtime_key == "unknown" or deployment_key == "unknown" or endpoint_key == "unknown":
        return "unavailable"
    if runtime_key or deployment_key or endpoint_key:
        return "unavailable"
    return None


def _has_normalized_environment_contract(data: dict[str, Any]) -> bool:
    """Return true when the bundle carries normalized environment/platform facets."""
    environment = _mapping_or_empty(data.get("environment"))
    platform = _mapping_or_empty(data.get("platform"))
    return any(isinstance(environment.get(key), dict) for key in ("platform_runtime", "container")) or any(
        isinstance(platform.get(key), dict) for key in ("deployment", "cloud", "compute", "storage")
    )


def _legacy_environment_facets_from_cost(normalized_cost: NormalizedCost) -> dict[str, str | None]:
    """Recover explorer facets from pre-environment-contract normalized cost metadata."""
    deployment = normalized_cost.deployment
    cloud_provider = _string_or_none(deployment.cloud_provider)
    cloud_region = _string_or_none(deployment.cloud_region)
    instance_or_warehouse = _first_string(
        deployment.instance_type,
        deployment.warehouse_size,
        deployment.cluster_size,
        deployment.node_count,
    )
    storage_format = _string_or_none(deployment.storage_format)

    deployment_class: str | None = None
    if normalized_cost.cost_status == "not_applicable_local":
        deployment_class = "local"
    elif cloud_provider or cloud_region:
        deployment_class = "cloud"
    elif normalized_cost.cost_status == "unavailable":
        deployment_class = "unavailable"

    return {
        "deployment_class": deployment_class,
        "cloud_provider": cloud_provider,
        "cloud_region": cloud_region,
        "instance_or_warehouse": instance_or_warehouse,
        "storage_format": storage_format,
    }


def _environment_facets(
    data: dict[str, Any],
    *,
    normalized_cost: NormalizedCost | None = None,
) -> dict[str, str | None]:
    """Flatten normalized execution-environment facets for the browser store."""
    platform = _mapping_or_empty(data.get("platform"))
    cloud = _mapping_or_empty(platform.get("cloud"))
    compute = _mapping_or_empty(platform.get("compute"))
    storage = _mapping_or_empty(platform.get("storage"))

    facets = {
        "deployment_class": _deployment_class_from_contract(data),
        "cloud_provider": _string_or_none(cloud.get("provider")),
        "cloud_region": _first_string(cloud.get("region"), cloud.get("location")),
        "instance_or_warehouse": _first_string(
            compute.get("node_type"),
            compute.get("warehouse_size"),
            compute.get("warehouse"),
            compute.get("cluster_id"),
            compute.get("cluster_name"),
            compute.get("rpu"),
            compute.get("serverless_slots"),
            compute.get("worker_shape"),
            compute.get("driver_shape"),
        ),
        "storage_format": _string_or_none(storage.get("table_format")),
    }
    if _has_normalized_environment_contract(data) or normalized_cost is None:
        return facets
    return _legacy_environment_facets_from_cost(normalized_cost)


def _compliance_class(data: dict[str, Any]) -> str | None:
    """Extract compliance class from the benchmark block of a schema-v2 bundle."""
    benchmark = data.get("benchmark", {})
    if not isinstance(benchmark, dict):
        return None
    val = benchmark.get("compliance_class")
    return str(val) if val is not None else None


def _phase_durations(data: dict[str, Any]) -> dict[str, float] | None:
    """Extract per-phase durations (seconds) from a schema-v2 bundle phases block.

    Returns a dict keyed by phase name (e.g. "data_loading", "power_test") with
    values in seconds.  Returns None when no phase data is present.
    """
    phases = data.get("phases", {})
    if not isinstance(phases, dict):
        return None
    result: dict[str, float] = {}
    for phase_name, phase_data in phases.items():
        if isinstance(phase_data, dict):
            duration_ms = phase_data.get("duration_ms")
            if duration_ms is not None:
                try:
                    result[str(phase_name)] = float(duration_ms) / 1000.0
                except (TypeError, ValueError):
                    pass
    return result if result else None


def _compute_percentile(values: list[float], p: float) -> float:
    """Compute the p-th percentile using linear interpolation.

    Mirrors ``textcharts.percentile_ladder.compute_percentile`` exactly so
    that pipeline-emitted values match CLI chart output within floating-point
    precision.

    Args:
        values: Non-empty list of numeric values (will be sorted internally).
        p:      Percentile in range [0, 100].
    """
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    k = (p / 100.0) * (n - 1)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (c - k) + sorted_vals[c] * (k - f)


def _platform_percentile_stats(display_timings: list[QueryDisplayTiming]) -> PercentileStats | None:
    """Compute P50/P90/P95/P99 over the per-query display_ms medians.

    Returns None when fewer than 1 non-null display_ms value is available.
    """
    # Exclude zero values: sub-millisecond queries round to 0 in some runners
    # and 0ms is not a valid timing (would skew percentiles); genuine sub-ms
    # timings appear as a small non-zero display_ms from the rounding formula.
    values = [dt.display_ms for dt in display_timings if dt.display_ms is not None and dt.display_ms > 0]
    if not values:
        return None
    return PercentileStats(
        p50=_compute_percentile(values, 50),
        p90=_compute_percentile(values, 90),
        p95=_compute_percentile(values, 95),
        p99=_compute_percentile(values, 99),
    )


def _query_timings(data: dict[str, Any]) -> list[QueryTiming]:
    """Extract per-query timings from the queries list in a schema-v2 bundle.

    Includes measurement and warmup execution queries (or those without a run_type).
    Explicitly filters out non-execution pseudo-rows (metadata, summary).
    Preserves run_type, iter, and stream fields for provenance.
    """
    raw_queries: list[dict[str, Any]] = data.get("queries", [])
    timings: list[QueryTiming] = []
    for q in raw_queries:
        if not isinstance(q, dict):
            continue
        run_type = q.get("run_type")
        # Ingest both measurement and warmup executions. Narrow the filter to an
        # explicit allow-list; do not remove the check entirely, because the corpus
        # carries "metadata" and "summary" pseudo-rows (ms=0, status=SKIPPED) that
        # are not execution timings.
        if run_type is not None and run_type not in _ALLOWED_EXECUTION_RUN_TYPES:
            continue
        query_id = q.get("id") or q.get("query_id", "")
        ms_raw = q.get("ms")
        duration_ms_raw = ms_raw if ms_raw is not None else (q.get("execution_time_ms") or 0.0)
        try:
            duration_ms = float(duration_ms_raw)
        except (TypeError, ValueError):
            duration_ms = 0.0
        raw_status = q.get("status", "pass")
        status = "pass" if raw_status in _PASS_STATUSES else "fail"
        iter_val = q.get("iter")
        stream_val = q.get("stream")
        timings.append(
            QueryTiming(
                query_id=str(query_id),
                duration_ms=duration_ms,
                status=status,
                run_type=run_type,
                iter=int(iter_val) if iter_val is not None else None,
                stream=int(stream_val) if stream_val is not None else None,
            )
        )
    return timings


def _query_display_ms(query_timings: list[QueryTiming]) -> tuple[float | None, int]:
    """Compute canonical display value and sample count for a single logical query.

    ``query_timings`` must be pre-filtered to a single query_id.

    ``query_timings`` is expected to be pre-filtered to a single query_id by
    the caller (as ``_build_display_timings`` does via ``_query_timings``).

    Algorithm:
      1. Filter to passing (status == "pass") rows.
      2. Prefer run_type == "measurement" rows; fall back to unlabelled legacy rows
         (run_type is None) when no explicit measurement rows exist. Warmup rows
         (run_type == "warmup") are NEVER used for display_ms or sample_count.
      3. Return (median duration_ms, sample_count).
      4. Return (None, 0) when no passing rows exist.

    Median is chosen over mean so that a single cold-cache outlier (common in
    power-test runs that include one warmup iteration) does not dominate.
    """
    passing = [t for t in query_timings if t.status == "pass"]
    if not passing:
        return None, 0
    measurement = [t for t in passing if t.run_type == "measurement"]
    # DECISION: Fall back to unlabelled legacy rows (run_type is None) only when
    # no explicit measurement rows exist. Warmup rows (run_type == "warmup")
    # must NEVER be picked up by the fallback branch; doing so would let warmup
    # rows feed display_ms for bundles that recorded warmup without measurement
    # or whose measurement executions failed.
    legacy_unlabelled = [t for t in passing if t.run_type is None]
    candidates = measurement if measurement else legacy_unlabelled
    if not candidates:
        return None, 0
    durations = sorted(t.duration_ms for t in candidates)
    mid = len(durations) // 2
    if len(durations) % 2 == 1:
        return durations[mid], len(candidates)
    return (durations[mid - 1] + durations[mid]) / 2.0, len(candidates)


def _build_display_timings(timings: list[QueryTiming]) -> list[QueryDisplayTiming]:
    """Build per-query canonical display timings from all QueryTiming rows."""
    seen: dict[str, list[QueryTiming]] = {}
    for t in timings:
        seen.setdefault(t.query_id, []).append(t)
    result: list[QueryDisplayTiming] = []
    for qid, qid_timings in seen.items():
        display_ms, sample_count = _query_display_ms(qid_timings)
        result.append(QueryDisplayTiming(query_id=qid, display_ms=display_ms, sample_count=sample_count))
    return result


def _compute_basis_availability(queries: list[QueryTiming]) -> BasisAvailability:
    """Derive basis availability from query timings for a result bundle.

    Surfaces whether warmup exists, measurement pass count, available bases,
    and per-query pass count where it varies.
    """
    warmup_passing = [q for q in queries if q.run_type == "warmup" and q.status == "pass"]
    has_warmup = len(warmup_passing) > 0
    warmup_status = "available" if has_warmup else "no_warmup_recorded"

    # Pre-initialize every attempted measurement query with 0 so completely failed queries
    # are not silently dropped from varying_pass_queries
    measurement_queries = [q for q in queries if q.run_type == "measurement" or q.run_type is None]
    query_pass_counts: dict[str, int] = {q.query_id: 0 for q in measurement_queries}
    for q in measurement_queries:
        if q.status == "pass":
            query_pass_counts[q.query_id] += 1

    if query_pass_counts:
        counts = list(query_pass_counts.values())
        count_freq = Counter(counts)
        nominal_count = sorted(count_freq.items(), key=lambda x: (x[1], x[0]), reverse=True)[0][0]
        varying_pass_queries = {qid: cnt for qid, cnt in sorted(query_pass_counts.items()) if cnt != nominal_count}
    else:
        nominal_count = 0
        varying_pass_queries = {}

    available_bases: list[str] = ["default"]
    unavailable_bases: dict[str, str] = {}

    if has_warmup:
        available_bases.append("warmup")
    else:
        unavailable_bases["warmup"] = "no_warmup_recorded"

    if nominal_count > 0:
        available_bases.append("all_warm")
        for p in range(1, nominal_count + 1):
            available_bases.append(f"warm_pass_{p}")
    else:
        unavailable_bases["all_warm"] = "no_measurement_executions"

    return BasisAvailability(
        has_warmup=has_warmup,
        measurement_pass_count=nominal_count,
        warmup_status=warmup_status,
        available_bases=available_bases,
        unavailable_bases=unavailable_bases,
        query_pass_counts=query_pass_counts,
        varying_pass_queries=varying_pass_queries,
    )


def _display_geomean_ms(display_timings: list[QueryDisplayTiming]) -> float | None:
    """Compute geometric mean of non-None display_ms values across all queries."""
    values = [dt.display_ms for dt in display_timings if dt.display_ms is not None and dt.display_ms > 0]
    if not values:
        return None
    return math.exp(sum(math.log(v) for v in values) / len(values))


def _summary_query_count(data: dict[str, Any]) -> int:
    summary = data.get("summary", {})
    if not isinstance(summary, dict):
        return 0
    queries = summary.get("queries", {})
    if not isinstance(queries, dict):
        return 0
    try:
        return int(queries.get("total", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _logical_query_count(data: dict[str, Any], display_timings: list[QueryDisplayTiming]) -> int:
    """Infer the logical query denominator without treating repeats as misses.

    ``summary.queries.total`` is retained as the raw sample count. For repeated
    benchmark runs it can be 3x/4x the logical benchmark query count, while
    ``display_timings`` has one row per logical query ID.
    """
    dataframe_skip_total = _dataframe_skip_logical_query_count(data)
    if dataframe_skip_total is not None:
        return dataframe_skip_total

    raw_query_count = _summary_query_count(data)
    observed_query_count = len({timing.query_id for timing in display_timings if timing.query_id})
    if observed_query_count <= 0:
        return raw_query_count
    if raw_query_count <= observed_query_count:
        return raw_query_count or observed_query_count

    benchmark = str(data.get("benchmark", {}).get("id", "unknown"))
    known_count = _KNOWN_LOGICAL_QUERY_COUNTS.get(benchmark)
    if known_count and observed_query_count <= known_count and raw_query_count % known_count == 0:
        return known_count

    if raw_query_count % observed_query_count == 0 and any(timing.sample_count > 1 for timing in display_timings):
        return observed_query_count

    return raw_query_count


def _dataframe_skip_logical_query_count(data: dict[str, Any]) -> int | None:
    """Return executed+skipped logical query count for DataFrame partial runs."""
    raw_queries = data.get("queries", [])
    if not isinstance(raw_queries, list):
        return None

    best_total: int | None = None
    for query in raw_queries:
        if not isinstance(query, dict):
            continue
        summary = query.get("dataframe_skip_summary")
        if not isinstance(summary, dict):
            continue
        executed = _int_or_none(summary.get("executed_total"))
        skipped = _int_or_none(summary.get("skipped_total"))
        if executed is None or skipped is None:
            continue
        total = executed + skipped
        if total > 0 and (best_total is None or total > best_total):
            best_total = total
    return best_total


def _int_or_none(value: Any) -> int | None:
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


class BundleTransformer:
    """Transforms a schema-v2 result bundle into explorer read model artifacts."""

    def load_bundle(self, bundle_path: Path) -> dict[str, Any]:
        """Load a schema-v2 bundle from disk, returning parsed data only."""
        data, _ = _load_bundle(bundle_path)
        return data

    def load_bundle_full(self, bundle_path: Path) -> tuple[dict[str, Any], bytes]:
        """Load a bundle and return ``(parsed_data, raw_bytes)``.

        Use this in pipelines that need both the parsed data and a content
        hash without incurring a second file read.
        """
        return _load_bundle(bundle_path)

    def result_id_from_bundle(
        self,
        bundle_path: Path,
        data: dict[str, Any] | None = None,
        *,
        raw: bytes | None = None,
    ) -> str:
        """Generate a stable result_id from bundle content.

        Format: ``{benchmark}-{platform}-sf{scale_factor}-{yyyymmdd}-{sha8}``

        Args:
            bundle_path: Path to the bundle file (used to load data/raw if not provided).
            data: Pre-loaded parsed bundle dict.  If omitted, the file is read.
            raw: Pre-read raw file bytes for SHA computation.  When both *data*
                and *raw* are supplied, no file I/O occurs (zero disk reads).
        """
        if data is not None and raw is not None:
            _ensure_explorer_input_schema(data)
            bundle_data, file_raw = data, raw
        elif data is not None:
            _ensure_explorer_input_schema(data)
            bundle_data, file_raw = data, bundle_path.read_bytes()
        else:
            bundle_data, file_raw = _load_bundle(bundle_path)

        benchmark = bundle_data.get("benchmark", {}).get("id", "unknown")
        platform = str(bundle_data.get("platform", {}).get("name", "unknown")).lower().replace(" ", "-")
        scale_factor = bundle_data.get("benchmark", {}).get("scale_factor", 0.0)
        timestamp = bundle_data.get("run", {}).get("timestamp", "19700101T000000")
        run_date = _run_date_from_timestamp(timestamp)
        sha_prefix = _sha256_prefix(file_raw)
        return f"{benchmark}-{platform}-sf{scale_factor}-{run_date}-{sha_prefix}"

    def to_manifest_entry(
        self,
        bundle_path: Path,
        *,
        trust_label: str = "maintainer-run",
        visibility: str = "public-curated",
        result_id: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> ManifestEntry:
        """Extract manifest entry from a result bundle JSON file."""
        bundle_data = data if data is not None else self.load_bundle(bundle_path)
        _ensure_explorer_input_schema(bundle_data)
        rid = result_id or self.result_id_from_bundle(bundle_path, data=bundle_data)

        benchmark = bundle_data.get("benchmark", {}).get("id", "unknown")
        scale_factor = float(bundle_data.get("benchmark", {}).get("scale_factor", 0.0))
        platform = str(bundle_data.get("platform", {}).get("name", "unknown"))
        timestamp = bundle_data.get("run", {}).get("timestamp", "1970-01-01T00:00:00")
        run_date = timestamp[:10]
        total_duration_ms = bundle_data.get("run", {}).get("total_duration_ms", 0.0)
        total_duration_s = float(total_duration_ms) / 1000.0

        query_count = _summary_query_count(bundle_data)
        failed_query_count = bundle_failed_query_count(bundle_data)

        # Same _query_timings → _build_display_timings pass also runs in
        # to_detail_result; a shared intermediate could halve the work for
        # large bundles (≤99 queries makes this negligible today).
        timings = _query_timings(bundle_data)
        display_timings = _build_display_timings(timings)
        logical_query_count = _logical_query_count(bundle_data, display_timings)
        timing_contract = timing_eligibility(display_timings, logical_query_count)
        normalized_cost = _normalized_cost(bundle_data)
        environment_facets = _environment_facets(
            bundle_data,
            normalized_cost=normalized_cost if _raw_normalized_cost_block(bundle_data) is not None else None,
        )
        entry = ManifestEntry(
            result_id=rid,
            benchmark=benchmark,
            scale_factor=scale_factor,
            platform=platform,
            platform_id=_platform_id(platform),
            driver_version=_driver_version(bundle_data),
            run_date=run_date,
            power_score=_power_score(bundle_data),
            total_duration_s=total_duration_s,
            geomean_ms=_geomean_ms(bundle_data),
            display_geomean_ms=_display_geomean_ms(display_timings),
            query_count=int(query_count),
            logical_query_count=logical_query_count,
            has_display_timing=timing_contract.has_display_timing,
            valid_query_count=timing_contract.valid_query_count,
            missing_query_count=timing_contract.missing_query_count,
            zero_timing_count=timing_contract.zero_timing_count,
            display_exclusion_reason=timing_contract.display_exclusion_reason,
            comparison_exclusion_reason=timing_contract.comparison_exclusion_reason,
            trust_label=trust_label,
            visibility=visibility,
            funding=_funding(bundle_data),
            platform_version=_platform_version(bundle_data),
            execution_mode=_execution_mode(bundle_data),
            tuning_mode=_tuning_mode(bundle_data),
            tuning_hash=_tuning_hash(bundle_data),
            requested_config_hash=_requested_config_hash(bundle_data),
            applied_ledger_hash=_applied_ledger_hash(bundle_data),
            tuning_validation_status=_tuning_validation_status(bundle_data),
            applied_receipt=_applied_receipt(bundle_path),
            tuning_policy_generation=_tuning_policy_generation(bundle_data),
            test_type=_test_type(bundle_data),
            validation_status=_validation_status(bundle_data),
            failed_query_count=failed_query_count,
            cost_usd=_cost_usd_alias(normalized_cost),
            normalized_cost=normalized_cost.to_dict(),
            deployment_class=environment_facets["deployment_class"],
            cloud_provider=environment_facets["cloud_provider"],
            cloud_region=environment_facets["cloud_region"],
            instance_or_warehouse=environment_facets["instance_or_warehouse"],
            storage_format=environment_facets["storage_format"],
            compliance_class=_compliance_class(bundle_data),
            basis_availability=_compute_basis_availability(timings),
        )
        return entry.model_copy(update={"ranking_exclusion_reason": ranking_exclusion_reason(entry)})

    def to_detail_result(
        self,
        bundle_path: Path,
        result_id: str,
        *,
        trust_label: str = "maintainer-run",
        visibility: str = "public-curated",
        bundle_download_url: str = "",
        data: dict[str, Any] | None = None,
    ) -> DetailResult:
        """Extract full detail from a result bundle JSON file."""
        bundle_data = data if data is not None else self.load_bundle(bundle_path)
        _ensure_explorer_input_schema(bundle_data)

        benchmark = bundle_data.get("benchmark", {}).get("id", "unknown")
        scale_factor = float(bundle_data.get("benchmark", {}).get("scale_factor", 0.0))
        platform = str(bundle_data.get("platform", {}).get("name", "unknown"))
        timestamp = bundle_data.get("run", {}).get("timestamp", "1970-01-01T00:00:00")
        run_date = timestamp[:10]
        total_duration_ms = bundle_data.get("run", {}).get("total_duration_ms", 0.0)
        total_duration_s = float(total_duration_ms) / 1000.0

        environment: dict[str, Any] = {}
        if isinstance(bundle_data.get("environment"), dict):
            environment = bundle_data["environment"]

        # Detect companion files relative to bundle
        stem = bundle_path.stem
        has_plans = bundle_path.with_name(f"{stem}.plans.json").exists()
        has_tuning = bundle_path.with_name(f"{stem}.tuning.json").exists()

        timings = _query_timings(bundle_data)
        display_timings = _build_display_timings(timings)
        query_count = _summary_query_count(bundle_data)
        logical_query_count = _logical_query_count(bundle_data, display_timings)
        timing_contract = timing_eligibility(display_timings, logical_query_count)
        normalized_cost = _normalized_cost(bundle_data)
        detail = DetailResult(
            result_id=result_id,
            benchmark=benchmark,
            scale_factor=scale_factor,
            platform=platform,
            platform_id=_platform_id(platform),
            driver_version=_driver_version(bundle_data),
            run_date=run_date,
            total_duration_s=total_duration_s,
            geomean_ms=_geomean_ms(bundle_data),
            display_geomean_ms=_display_geomean_ms(display_timings),
            power_score=_power_score(bundle_data),
            has_display_timing=timing_contract.has_display_timing,
            logical_query_count=logical_query_count,
            valid_query_count=timing_contract.valid_query_count,
            missing_query_count=timing_contract.missing_query_count,
            zero_timing_count=timing_contract.zero_timing_count,
            display_exclusion_reason=timing_contract.display_exclusion_reason,
            comparison_exclusion_reason=timing_contract.comparison_exclusion_reason,
            environment=environment,
            queries=timings,
            display_timings=display_timings,
            has_plans=has_plans,
            has_tuning=has_tuning,
            bundle_download_url=bundle_download_url,
            trust_label=trust_label,
            visibility=visibility,
            platform_version=_platform_version(bundle_data),
            execution_mode=_execution_mode(bundle_data),
            tuning_mode=_tuning_mode(bundle_data),
            tuning_hash=_tuning_hash(bundle_data),
            requested_config_hash=_requested_config_hash(bundle_data),
            applied_ledger_hash=_applied_ledger_hash(bundle_data),
            tuning_validation_status=_tuning_validation_status(bundle_data),
            applied_receipt=_applied_receipt(bundle_path),
            tuning_policy_generation=_tuning_policy_generation(bundle_data),
            test_type=_test_type(bundle_data),
            validation_status=_validation_status(bundle_data),
            failed_query_count=bundle_failed_query_count(bundle_data),
            cost_usd=_cost_usd_alias(normalized_cost),
            normalized_cost=normalized_cost.to_dict(),
            compliance_class=_compliance_class(bundle_data),
            phase_durations=_phase_durations(bundle_data),
            physical_mechanisms=_physical_mechanisms(bundle_data),
            physical_rendering_id=_physical_rendering_id(bundle_data),
            basis_availability=_compute_basis_availability(timings),
        )
        manifest_peer = ManifestEntry(
            result_id=result_id,
            benchmark=benchmark,
            scale_factor=scale_factor,
            platform=platform,
            platform_id=_platform_id(platform),
            driver_version=_driver_version(bundle_data),
            run_date=run_date,
            power_score=detail.power_score,
            total_duration_s=total_duration_s,
            geomean_ms=detail.geomean_ms,
            display_geomean_ms=detail.display_geomean_ms,
            query_count=int(query_count),
            logical_query_count=logical_query_count,
            trust_label=trust_label,
            visibility=visibility,
            validation_status=detail.validation_status,
            failed_query_count=detail.failed_query_count,
        )
        return detail.model_copy(update={"ranking_exclusion_reason": ranking_exclusion_reason(manifest_peer)})


__all__ = ["BundleTransformer"]
