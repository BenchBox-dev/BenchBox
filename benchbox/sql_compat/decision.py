"""CompatibilityDecision and typed payload dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Union

from benchbox.sql_compat.actions import CompatAction


class SupportLevel(str, Enum):
    NATIVE = "NATIVE"
    TRANSLATED = "TRANSLATED"
    REWRITTEN = "REWRITTEN"
    INFORMATIONAL = "INFORMATIONAL"
    SKIPPED_QUERY = "SKIPPED_QUERY"
    SKIPPED_DDL_FRAGMENT = "SKIPPED_DDL_FRAGMENT"
    BLOCKED = "BLOCKED"


class FailureMode(str, Enum):
    NONE = "NONE"
    SYNTAX_ERROR = "SYNTAX_ERROR"
    SILENT_CORRUPTION = "SILENT_CORRUPTION"
    UNSUPPORTED_FEATURE = "UNSUPPORTED_FEATURE"
    PERFORMANCE_REGRESSION = "PERFORMANCE_REGRESSION"


# ---------------------------------------------------------------------------
# Typed payload dataclasses (frozen + hashable so CompatibilityDecision can
# be frozen=True)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BlockBenchmarkPayload:
    reason: str


@dataclass(frozen=True)
class SkipQueryPayload:
    reason: str
    query_id: str


@dataclass(frozen=True)
class SelectVariantPayload:
    variant_key: str
    variant_sql: str


@dataclass(frozen=True)
class RewriteQueryPayload:
    transformer_id: str
    description: str


@dataclass(frozen=True)
class RewriteDDLPayload:
    transformer_id: str  # method name on the adapter when governance_only=False; documentary otherwise
    description: str
    # When True, BaseDdlOptimizer skips this rule at dispatch time (the adapter performs
    # the rewrite via a different code path; the rule exists only to satisfy compat_lint
    # governance). transformer_id need not name a real method on the adapter in that case.
    governance_only: bool = False


@dataclass(frozen=True)
class SetSessionPolicyPayload:
    settings: tuple[tuple[str, str], ...]
    issue_url: str | None


@dataclass(frozen=True)
class PostTranslatePayload:
    transformer_id: str
    description: str


@dataclass(frozen=True)
class PKCapabilityPayload:
    """Structured PRIMARY KEY capability record - typed fields, not a bare boolean."""

    ddl_accepted: bool
    uniqueness_enforced: bool
    conditions: str | None  # e.g. "first N columns only" for StarRocks/Doris
    failure_mode_detail: str | None


CompatPayload = Union[
    BlockBenchmarkPayload,
    SkipQueryPayload,
    SelectVariantPayload,
    RewriteQueryPayload,
    RewriteDDLPayload,
    SetSessionPolicyPayload,
    PostTranslatePayload,
    PKCapabilityPayload,
    None,  # NATIVE carries no payload
]


@dataclass(frozen=True)
class CompatibilityDecision:
    rule_id: str
    action: CompatAction
    support_level: SupportLevel
    failure_mode: FailureMode
    payload: CompatPayload
    reason: str
