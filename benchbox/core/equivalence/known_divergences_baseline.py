"""Editor for the cross-surface gate's ``--update-baseline`` affordance.

#903 (``cross-surface-known-divergence-baseline-hygiene``) made the gate FAIL when a
known-divergence entry no longer reproduces, telling the operator to "remove the
stale baseline entry in a reviewed change" -- but the promised ``--update-baseline``
maintenance flag was never built, so pruning a resolved entry stayed fully manual.

The plain-string ``known_divergences`` baseline lives in
``benchbox/core/equivalence/cross_surface_baseline.yaml``, one top-level section per
gate. This module prunes only the resolved keys from one gate's section, leaving
every other gate and every still-reproducing entry untouched, then rewrites the
whole file (plain data, so a full re-serialize is safe -- there is no risk of
corrupting an unrelated container the way editing Python source by AST position
would carry). Entries backed by executable acceptance logic (a
``ClassifiedDivergence`` with an ``accepts`` predicate) are not in this file at all --
they stay in ``cross_surface.py`` as code and are never touched here.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import yaml


class BaselineUpdateError(RuntimeError):
    """The baseline file could not be safely read or written; nothing was changed."""


def load_baseline(path: Path) -> dict[str, dict[str, str]]:
    """Read the baseline file at *path* as a gate -> {key: reason} mapping."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise BaselineUpdateError(f"{path} is not valid YAML: {exc}") from exc
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise BaselineUpdateError(f"{path} must contain a top-level mapping, got {type(payload).__name__}")
    return payload


def prune_known_divergences(
    data: dict[str, dict[str, str]], resolved_keys: Iterable[str], gate_name: str
) -> dict[str, dict[str, str]]:
    """Return a NEW mapping with ``resolved_keys`` removed from ``gate_name``'s own section.

    Keys not present in ``gate_name``'s section are ignored (idempotent: re-running
    after a key is already gone, or naming a key that only exists under a different
    gate, is a no-op). Every other gate's section, and every key not in
    ``resolved_keys``, is returned unchanged.
    """
    resolved = set(resolved_keys)
    section = data.get(gate_name)
    if not resolved or not section:
        return data
    updated_section = {key: reason for key, reason in section.items() if key not in resolved}
    if updated_section == section:
        return data
    updated = dict(data)
    updated[gate_name] = updated_section
    return updated


# Regenerated on every write rather than preserved through the YAML round-trip, so
# the file always documents itself even though a prune re-serializes the whole
# document (plain ``yaml.safe_load``/``safe_dump`` do not preserve comments).
_FILE_HEADER = """\
# Known-divergence baseline for the cross-surface SQL<->DataFrame equivalence
# gates (benchbox/core/equivalence/cross_surface.py). Each entry documents a
# deliberate, defensible presentational difference the gate tolerates for one
# specific "<query>_<backend>" cell - it is NOT a general-purpose ignore list.
# Adding an entry here mutes real regressions on that exact cell; do so only
# for a difference that is understood, verified, and non-discriminating.
#
# #903 made the gate FAIL when an entry's cell stops reproducing the divergence
# it documents (stale-baseline hygiene: an entry that no longer reproduces is
# no longer evidence the gap still exists, and silently keeping it risks
# masking a *different* future regression that happens to land on the same
# key). Prune resolved entries with:
#   make cross-surface-update-baseline BENCHMARK=<gate>
# which only removes entries that no longer reproduce, in a reviewed change,
# and refuses to write anything if the run has any OTHER failure.
#
# Only entries that tolerate ANY divergence on their key unconditionally
# belong here, as a plain "<gate>: {<key>: <reason>}" mapping. An entry that
# needs an executable acceptance predicate (a ClassifiedDivergence pinning the
# tolerated difference to an exact signature - column position, numeric
# bound, or execution-error text, so a genuinely wrong value on the same key
# is still reported as an unclassified gate failure) cannot be expressed as
# data and stays in cross_surface.py as code, next to its verification
# rationale. Each gate's section here is merged with its own in-code
# ClassifiedDivergence entries, so either source can carry part of a gate's
# baseline.
"""


def _dump(data: dict[str, dict[str, str]]) -> str:
    body = yaml.safe_dump(data, sort_keys=True, default_flow_style=False, allow_unicode=True, width=88)
    return _FILE_HEADER + "\n" + body


def update_baseline_file(path: Path, resolved_keys: Iterable[str], gate_name: str) -> list[str]:
    """Prune ``resolved_keys`` from ``gate_name``'s section of the baseline at *path*.

    Returns the sorted list of keys actually removed (empty when nothing changed).
    Writes only when the content changes, so a second run -- whose gate pass no
    longer reports the now-absent entries -- is a true no-op.
    """
    data = load_baseline(path)
    before = set(data.get(gate_name, {}))
    updated = prune_known_divergences(data, resolved_keys, gate_name)
    after = set(updated.get(gate_name, {}))
    removed = sorted(before - after)
    if not removed:
        return []
    path.write_text(_dump(updated), encoding="utf-8")
    return removed
