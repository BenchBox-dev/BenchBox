"""CompatibilityRegistry - rule storage and lookup.

Rules are registered at import time by rule files under
benchbox/sql_compat/rules/{phase}/. The registry is a singleton populated
during module import; no rules exist until individual rule modules are
imported.

Registration key: (phase, platform, benchmark | None, query_id | None)
Specificity tiers (highest → lowest):
  1. platform + benchmark + query_id
  2. platform + benchmark
  3. platform (benchmark=None, query_id=None)

Within a tier, version-gated rules (min_version/max_version set) take
precedence over unversioned rules when the context platform_version satisfies
the constraint. If platform_version is None, version-gated rules never fire.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterator

from packaging.version import InvalidVersion, Version

from benchbox.sql_compat.context import CompatibilityContext, Phase
from benchbox.sql_compat.decision import CompatibilityDecision


class CompatibilityRegistryConflict(Exception):
    pass


_VERSION_SUBSTRING_RE = re.compile(
    r"\d+(?:\.\d+)+(?:[-_.]?(?:a|b|rc|post|dev)\d*)?",
    re.IGNORECASE,
)


def _coerce_version(platform_version: str | None) -> Version | None:
    """Best-effort parse for adapter-reported platform versions.

    Some adapters return raw engine strings such as ``3.3.0-starrocks`` rather
    than strict PEP 440 versions. Version-gated compat rules should not crash on
    those values; we strip an engine suffix down to the leading semver-like
    portion when needed and otherwise treat the version as unknown.
    """
    if platform_version is None:
        return None
    try:
        return Version(platform_version)
    except InvalidVersion:
        match = _VERSION_SUBSTRING_RE.search(platform_version)
        if match is None:
            return None
        try:
            return Version(match.group(0))
        except InvalidVersion:
            return None


@dataclass
class _RuleEntry:
    rule_id: str
    decision: CompatibilityDecision
    min_version: str | None
    max_version: str | None

    def matches_version(self, platform_version: str | None) -> bool:
        if self.min_version is None and self.max_version is None:
            return True
        pv = _coerce_version(platform_version)
        if pv is None:
            return False
        if self.min_version is not None and pv < Version(self.min_version):
            return False
        if self.max_version is not None and pv > Version(self.max_version):
            return False
        return True


# Specificity key: (phase, platform, benchmark, query_id)
# benchmark=None → platform-wide; query_id=None → benchmark-wide
_RegistryKey = tuple[Phase, str, str | None, str | None]


class CompatibilityRegistry:
    def __init__(self) -> None:
        self._rules: dict[_RegistryKey, list[_RuleEntry]] = {}

    def register(
        self,
        decision: CompatibilityDecision,
        phase: Phase,
        platform: str,
        *,
        benchmark: str | None = None,
        query_id: str | None = None,
        min_version: str | None = None,
        max_version: str | None = None,
    ) -> None:
        """Register a compatibility rule.

        Multiple rules with *different* rule_ids at the same key are allowed;
        resolve() selects among them by specificity tier and version gate.

        Idempotent for exact duplicates (same rule_id + same semantics at the
        same key) so module re-imports in tests don't crash.

        Raises CompatibilityRegistryConflict if the same rule_id is registered
        at the same key with different semantics (payload, action, or version
        bounds differ).
        """
        key: _RegistryKey = (phase, platform, benchmark, query_id)
        entries = self._rules.setdefault(key, [])
        for existing in entries:
            if existing.rule_id == decision.rule_id:
                if (
                    existing.decision == decision
                    and existing.min_version == min_version
                    and existing.max_version == max_version
                ):
                    # Idempotent: module re-import (e.g. after sys.modules patch
                    # in tests) may re-execute module-level REGISTRY.register()
                    # on the same rule. Skip silently rather than crashing.
                    return
                raise CompatibilityRegistryConflict(f"Duplicate rule_id '{decision.rule_id}' at key {key}")
        entries.append(_RuleEntry(decision.rule_id, decision, min_version, max_version))

    def resolve(self, ctx: CompatibilityContext) -> CompatibilityDecision | None:
        """Return the winning decision for *ctx*, or None if no rule matches.

        Specificity tiers checked in order (most specific first). Within a tier,
        version-gated rules take precedence over unversioned ones when the
        context platform_version satisfies the constraint.

        Raises CompatibilityRegistryConflict if two rules at the same
        specificity level and version tier both match the same context.
        """
        tiers: list[_RegistryKey] = [
            (ctx.phase, ctx.platform, ctx.benchmark, ctx.query_id),
            (ctx.phase, ctx.platform, ctx.benchmark, None),
            (ctx.phase, ctx.platform, None, None),
        ]
        for key in tiers:
            entries = self._rules.get(key)
            if not entries:
                continue
            matching = [e for e in entries if e.matches_version(ctx.platform_version)]
            if not matching:
                continue
            versioned = [e for e in matching if e.min_version or e.max_version]
            unversioned = [e for e in matching if not e.min_version and not e.max_version]
            candidates = versioned if versioned else unversioned
            if len(candidates) > 1:
                ids = ", ".join(e.rule_id for e in candidates)
                raise CompatibilityRegistryConflict(f"Multiple rules match context {ctx}: {ids}")
            return candidates[0].decision
        return None

    def resolve_all(self, ctx: CompatibilityContext) -> list[CompatibilityDecision]:
        """Return all matching decisions for *ctx* across all specificity tiers.

        Unlike resolve(), this never raises CompatibilityRegistryConflict — it
        returns every decision that matches the context, ordered from most specific
        to least specific. Empty list when no rules match.

        Use this for governance/audit queries on platforms that register multiple
        rules at the same (phase, platform) key (e.g. SingleStore DDL_OPTIMIZE).

        Note: when ctx.query_id is None, tier 1 (platform+benchmark+query_id)
        and tier 2 (platform+benchmark) collapse to the same registry key.
        Duplicate lookups are skipped via ``seen`` so benchmark-level rules are
        never returned twice.
        """
        results: list[CompatibilityDecision] = []
        tiers: list[_RegistryKey] = [
            (ctx.phase, ctx.platform, ctx.benchmark, ctx.query_id),
            (ctx.phase, ctx.platform, ctx.benchmark, None),
            (ctx.phase, ctx.platform, None, None),
        ]
        seen: set[_RegistryKey] = set()
        for key in tiers:
            if key in seen:
                continue
            seen.add(key)
            entries = self._rules.get(key)
            if not entries:
                continue
            for entry in entries:
                if entry.matches_version(ctx.platform_version):
                    results.append(entry.decision)
        return results

    def resolve_platform_rules(
        self,
        phase: Phase,
        platform: str,
        platform_version: str | None = None,
    ) -> list[CompatibilityDecision]:
        """Return all platform-wide rules for *phase* / *platform* in registration order.

        Shortcut for governance contexts (e.g. BaseDdlOptimizer dispatch) that have
        no benchmark or query_id and only care about rules registered at the
        platform-wide tier (benchmark=None, query_id=None). Avoids constructing
        a synthetic ``CompatibilityContext`` with sentinel values and skips the
        always-empty benchmark/query_id tier lookups that resolve_all() would
        perform with ``benchmark=""``.
        """
        results: list[CompatibilityDecision] = []
        entries = self._rules.get((phase, platform, None, None))
        if not entries:
            return results
        for entry in entries:
            if entry.matches_version(platform_version):
                results.append(entry.decision)
        return results

    def all_rules(self) -> Iterator[tuple[_RegistryKey, _RuleEntry]]:
        for key, entries in self._rules.items():
            for entry in entries:
                yield key, entry

    def __len__(self) -> int:
        return sum(len(v) for v in self._rules.values())


# Module-level singleton - populated by rule files at import time
REGISTRY = CompatibilityRegistry()
