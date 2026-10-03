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
    transformer_id: str
    description: str
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
    ddl_accepted: bool
    uniqueness_enforced: bool
    conditions: str | None
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
    None,
]


@dataclass(frozen=True)
class CompatibilityDecision:
    rule_id: str
    action: CompatAction
    support_level: SupportLevel
    failure_mode: FailureMode
    payload: CompatPayload
    reason: str
