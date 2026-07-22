"""Explicit tuning-policy generation marker (ADR-3 seam).

ADR-3 (``docs/development/tuning-adr-003-baseline-and-single-renderer.md``)
redefined what ``notuning`` means (platform defaults + engine-mandatory schema
only) and made ``core/tuning/generators/*`` the single tuning-DDL renderer.
That decision is a *generation seam*: tuned results produced under the
post-ADR-3 policy are not directly comparable to results produced by the older,
pre-seam tuning behavior (curated OLAP packs firing on the ``notuning`` path,
three divergent renderers, unrecorded session ``SET`` statements). Comparing a
tuned run from one side of the seam against a tuned run from the other is
apples-to-oranges.

``TUNING_POLICY_GENERATION`` is the *explicit* marker every tuned bundle stamps
so a later reader (the results explorer) can tell which generation a result was
produced under, and warn -- never block -- on a cross-generation comparison.

Explicit by design: the seam signal MUST come from this named constant, never
from parsing ``benchbox_version``. Version strings move for reasons unrelated to
tuning policy (any release), so a version-derived signal would fire spuriously
and miss real policy seams that land without a version bump. Bundles predating
this marker carry no value at all; the explorer treats that absence as the
"pre-seam" generation (see the results-explorer ComparabilityReceipt).

Bump this ONLY at a genuine future tuning-policy seam (a new ADR that changes
what tuned/notuning means or how tuning is rendered), pointing the value at that
ADR. Do not bump it for unrelated schema or code churn.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

# The current tuning-policy generation, established by ADR-3's baseline
# redefinition and single-renderer consolidation. Stamped verbatim into every
# tuned bundle's tuning summary / .tuning.json companion.
TUNING_POLICY_GENERATION = "adr-003"

__all__ = ["TUNING_POLICY_GENERATION"]
