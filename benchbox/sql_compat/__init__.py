"""sql_compat - phase-aware SQL compatibility decision engine for BenchBox.

Public API:

    from benchbox.sql_compat import (
        CompatibilityContext, Phase,
        CompatAction,
        CompatibilityDecision, SupportLevel, FailureMode,
        BlockBenchmarkPayload, SkipQueryPayload, SelectVariantPayload,
        RewriteQueryPayload, RewriteDDLPayload, SetSessionPolicyPayload,
        PostTranslatePayload,
        CompilationPlan, PhasedDecision,
        CompatibilityRegistry, CompatibilityRegistryConflict, REGISTRY,
        CompatibilityResolver,
    )

Rule files live under benchbox/sql_compat/rules/{phase}/ and register
decisions into the module-level REGISTRY singleton at import time.

See docs/development/adr/adr-sql-compat-phase-aware-pipeline.md for the full design.
"""

from benchbox.sql_compat.actions import CompatAction
from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import (
    BlockBenchmarkPayload,
    CompatibilityDecision,
    CompatPayload,
    FailureMode,
    PKCapabilityPayload,
    PostTranslatePayload,
    RewriteDDLPayload,
    RewriteQueryPayload,
    SelectVariantPayload,
    SetSessionPolicyPayload,
    SkipQueryPayload,
    SupportLevel,
)
from benchbox.sql_compat.plan import CompilationPlan, PhasedDecision
from benchbox.sql_compat.registry import (
    REGISTRY,
    CompatibilityRegistry,
    CompatibilityRegistryConflict,
)
from benchbox.sql_compat.resolver import CompatibilityResolver

__all__ = [
    "CompatAction",
    "CompatibilityContext",
    "Phase",
    "BlockBenchmarkPayload",
    "CompatibilityDecision",
    "CompatPayload",
    "FailureMode",
    "PKCapabilityPayload",
    "PostTranslatePayload",
    "RewriteDDLPayload",
    "RewriteQueryPayload",
    "SelectVariantPayload",
    "SetSessionPolicyPayload",
    "SkipQueryPayload",
    "SupportLevel",
    "CompilationPlan",
    "PhasedDecision",
    "CompatibilityRegistry",
    "CompatibilityRegistryConflict",
    "REGISTRY",
    "CompatibilityResolver",
]
