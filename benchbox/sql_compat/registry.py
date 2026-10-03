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
        key: _RegistryKey = (phase, platform, benchmark, query_id)
        entries = self._rules.setdefault(key, [])
        for existing in entries:
            if existing.rule_id == decision.rule_id:
                if (
                    existing.decision == decision
                    and existing.min_version == min_version
                    and existing.max_version == max_version
                ):
                    return
                raise CompatibilityRegistryConflict(f"Duplicate rule_id '{decision.rule_id}' at key {key}")
        entries.append(_RuleEntry(decision.rule_id, decision, min_version, max_version))

    def resolve(self, ctx: CompatibilityContext) -> CompatibilityDecision | None:
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


REGISTRY = CompatibilityRegistry()
