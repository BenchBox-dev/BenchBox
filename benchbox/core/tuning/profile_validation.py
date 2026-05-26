"""Validation for workload tuning profiles and checked-in tuning templates."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from benchbox.core.results.builder import normalize_benchmark_id
from benchbox.core.tuning.platform_capabilities import (
    CLUSTERING,
    DISTRIBUTION,
    MAPPED,
    PARTITIONING,
    SORTING,
    UNSUPPORTED,
    WAIVED,
    PlatformTuningMapping,
    map_candidate_to_platform,
)
from benchbox.core.tuning.workload_profiles import (
    ACCEPTED,
    DROPPED_LOW_EVIDENCE,
    WorkloadTuningCandidate,
    WorkloadTuningProfile,
    load_tpc_tuning_profile,
)

TUNING_TYPES = (PARTITIONING, CLUSTERING, DISTRIBUTION, SORTING)
ERROR = "error"


@dataclass(frozen=True)
class TuningProfileValidationIssue:
    """One profile/template validation finding."""

    severity: str
    candidate_key: str
    message: str
    decision: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "severity": self.severity,
            "candidate": self.candidate_key,
            "message": self.message,
            "decision": self.decision,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class CandidateTemplateMapping:
    """How one logical candidate was represented for a platform template."""

    candidate: WorkloadTuningCandidate
    platform_mapping: PlatformTuningMapping
    mapped_tuning_types: tuple[str, ...]

    @property
    def candidate_key(self) -> str:
        return candidate_key(self.candidate)

    @property
    def mapped(self) -> bool:
        return self.platform_mapping.decision == MAPPED and not self.missing_tuning_types

    @property
    def missing_tuning_types(self) -> tuple[str, ...]:
        mapped = set(self.mapped_tuning_types)
        return tuple(tuning_type for tuning_type in self.platform_mapping.tuning_types if tuning_type not in mapped)

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate_key,
            "status": self.candidate.status,
            "logical_roles": list(self.candidate.roles),
            "decision": self.platform_mapping.decision,
            "mapped_tuning_types": list(self.mapped_tuning_types),
            "physical_mechanisms": list(self.platform_mapping.physical_mechanisms),
            "reason": self.platform_mapping.reason,
        }


@dataclass(frozen=True)
class TuningProfileValidationResult:
    """Profile/template validation result and compact metadata view."""

    profile_id: str
    profile_version: str
    benchmark: str
    platform: str
    template_hash: str
    mappings: tuple[CandidateTemplateMapping, ...]
    issues: tuple[TuningProfileValidationIssue, ...]
    accepted_count: int
    dropped_low_evidence_count: int

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == ERROR for issue in self.issues)

    @property
    def required_count(self) -> int:
        return len(self.mappings)

    @property
    def mapped_count(self) -> int:
        return sum(1 for mapping in self.mappings if mapping.mapped)

    @property
    def unsupported_count(self) -> int:
        return sum(1 for mapping in self.mappings if mapping.platform_mapping.decision == UNSUPPORTED)

    @property
    def waived_count(self) -> int:
        return sum(1 for mapping in self.mappings if mapping.platform_mapping.decision == WAIVED)

    @property
    def physical_mechanisms(self) -> tuple[str, ...]:
        mechanisms = {
            mechanism
            for mapping in self.mappings
            if mapping.mapped
            for mechanism in mapping.platform_mapping.physical_mechanisms
        }
        return tuple(sorted(mechanisms))

    @property
    def unmapped_logical_candidates(self) -> tuple[dict[str, Any], ...]:
        unmapped: list[dict[str, Any]] = []
        for mapping in self.mappings:
            if mapping.mapped:
                continue
            entry = {
                "candidate": mapping.candidate_key,
                "decision": mapping.platform_mapping.decision,
                "reason": mapping.platform_mapping.reason or "required candidate was not mapped to the template",
            }
            if mapping.missing_tuning_types:
                entry["missing_tuning_types"] = list(mapping.missing_tuning_types)
            unmapped.append(entry)
        return tuple(unmapped)

    def to_metadata(self, *, max_unmapped: int = 20) -> dict[str, Any]:
        return {
            "logical_tuning_profile_id": self.profile_id,
            "logical_tuning_profile_version": self.profile_version,
            "tuning_template_hash": self.template_hash,
            "platform_physical_tuning_mechanisms": list(self.physical_mechanisms),
            "logical_profile_coverage": {
                "accepted_count": self.accepted_count,
                "required_count": self.required_count,
                "mapped_count": self.mapped_count,
                "unsupported_count": self.unsupported_count,
                "waived_count": self.waived_count,
                "unmapped_count": len(self.unmapped_logical_candidates),
                "dropped_low_evidence_count": self.dropped_low_evidence_count,
            },
            "unmapped_logical_candidates": list(self.unmapped_logical_candidates[:max_unmapped]),
            "validation_status": "passed" if self.is_valid else "failed",
        }


def validate_tuning_template(
    *,
    profile: WorkloadTuningProfile,
    benchmark: str,
    platform: str,
    tuning_config: Any,
) -> TuningProfileValidationResult:
    """Validate a concrete tuning template against a logical workload profile."""
    benchmark_key = _normalize_profile_benchmark(benchmark)
    platform_key = platform.lower().replace("_", "-")
    template_columns = extract_template_columns(tuning_config)
    candidates = profile.candidates(benchmark_key)
    accepted_count = sum(1 for candidate in candidates if candidate.status == ACCEPTED)
    dropped_candidates = tuple(candidate for candidate in candidates if candidate.status == DROPPED_LOW_EVIDENCE)

    issues: list[TuningProfileValidationIssue] = []
    mappings: list[CandidateTemplateMapping] = []

    for candidate in candidates:
        if candidate.is_dropped:
            if _candidate_present(template_columns, candidate):
                issues.append(
                    TuningProfileValidationIssue(
                        severity=ERROR,
                        candidate_key=candidate_key(candidate),
                        message="dropped-low-evidence candidate appears in the tuning template",
                        decision=DROPPED_LOW_EVIDENCE,
                        reason=candidate.rationale,
                    )
                )
            continue

        if not candidate.is_required_for_mapping:
            continue

        platform_mapping = map_candidate_to_platform(platform_key, candidate)
        mapped_tuning_types = tuple(
            tuning_type
            for tuning_type in platform_mapping.tuning_types
            if candidate.column in template_columns.get(candidate.table, {}).get(tuning_type, set())
        )
        mappings.append(
            CandidateTemplateMapping(
                candidate=candidate,
                platform_mapping=platform_mapping,
                mapped_tuning_types=mapped_tuning_types,
            )
        )

        missing_tuning_types = mappings[-1].missing_tuning_types
        if platform_mapping.decision == MAPPED and missing_tuning_types:
            expected = ", ".join(missing_tuning_types) or "a mapped tuning type"
            issues.append(
                TuningProfileValidationIssue(
                    severity=ERROR,
                    candidate_key=candidate_key(candidate),
                    message=f"required logical candidate is missing template mapping for {expected}",
                    decision=platform_mapping.decision,
                    reason=platform_mapping.reason,
                )
            )

    return TuningProfileValidationResult(
        profile_id=profile.id,
        profile_version=profile.version,
        benchmark=benchmark_key,
        platform=platform_key,
        template_hash=hash_tuning_template(tuning_config),
        mappings=tuple(mappings),
        issues=tuple(issues),
        accepted_count=accepted_count,
        dropped_low_evidence_count=len(dropped_candidates),
    )


def build_tuning_profile_metadata(
    *,
    benchmark: str | None,
    platform: str | None,
    tuning_config: Any | None,
    profile: WorkloadTuningProfile | None = None,
) -> dict[str, Any] | None:
    """Build compact result metadata for TPC tuning profile coverage."""
    if not benchmark or not platform or tuning_config is None:
        return None
    if not _get_value(tuning_config, "table_tunings"):
        return None

    profile = profile or load_tpc_tuning_profile()
    benchmark_key = _normalize_profile_benchmark(benchmark)
    if not profile.candidates(benchmark_key):
        return None

    return validate_tuning_template(
        profile=profile,
        benchmark=benchmark_key,
        platform=platform,
        tuning_config=tuning_config,
    ).to_metadata()


def extract_template_columns(tuning_config: Any) -> dict[str, dict[str, set[str]]]:
    """Return table -> tuning type -> column names from a tuning configuration."""
    table_tunings = _get_value(tuning_config, "table_tunings") or {}
    extracted: dict[str, dict[str, set[str]]] = {}

    if not isinstance(table_tunings, Mapping):
        return extracted

    for table_name, table_tuning in table_tunings.items():
        table_key = str(_get_value(table_tuning, "table_name") or table_name).upper()
        by_type: dict[str, set[str]] = {}
        for tuning_type in TUNING_TYPES:
            by_type[tuning_type] = _extract_column_names(_get_value(table_tuning, tuning_type))
        extracted[table_key] = by_type

    return extracted


def hash_tuning_template(tuning_config: Any) -> str:
    """Return a stable compact hash for a tuning configuration."""
    if hasattr(tuning_config, "to_dict"):
        payload = tuning_config.to_dict()
    elif isinstance(tuning_config, Mapping):
        payload = dict(tuning_config)
    else:
        payload = repr(tuning_config)
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def candidate_key(candidate: WorkloadTuningCandidate) -> str:
    return f"{candidate.benchmark}.{candidate.table}.{candidate.column}"


def _normalize_profile_benchmark(benchmark: str) -> str:
    return normalize_benchmark_id(benchmark).replace("-", "_")


def _candidate_present(template_columns: dict[str, dict[str, set[str]]], candidate: WorkloadTuningCandidate) -> bool:
    return any(candidate.column in columns for columns in template_columns.get(candidate.table, {}).values())


def _extract_column_names(raw_columns: Any) -> set[str]:
    if not raw_columns:
        return set()
    names: set[str] = set()
    for column in raw_columns:
        name = _get_value(column, "name")
        if name:
            names.add(str(name).upper())
    return names


def _get_value(obj: Any, key: str) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(key)
    return getattr(obj, key, None)
