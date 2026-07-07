"""Canonical result-provenance vocabulary: source, trust label, visibility, funding.

Single source of truth for two orthogonal provenance concepts attached to a
benchmark result:

1. ``result_source`` - who produced the result. This maps onto the trust-label
   spectrum surfaced by the results explorer:

   ==========  =====================  ========================
   source      trust label            visibility state
   ==========  =====================  ========================
   internal    maintainer-run         public-curated
   community   community-submission   public-self-reported
   vendor      vendor-supplied        public-vendor-reported
   ==========  =====================  ========================

   ``vendor-supplied`` marks a result produced by the platform vendor itself
   (a conflict of interest that is neither maintainer-run nor an arms-length
   community submission). It is ranking-eligible but carries a distinct badge.

2. ``funding`` - who/how the run was paid for. This is independent of source:
   a vendor-supplied result may be employer-funded, and a community result may
   be on a free trial.

This module is intentionally free of CLI/platform imports (same rule as
``benchbox.core.results.models``) so both the explorer pipeline and the CLI can
import it without cycles. Helpers are total: unknown source normalizes to
``internal`` and unknown funding to ``unspecified``. Strict rejection of
unknown values is the submission validator's job, not this module's.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Result source -> trust label -> visibility
# ---------------------------------------------------------------------------

RESULT_SOURCES: tuple[str, ...] = ("internal", "community", "vendor")
"""Producer categories. ``internal`` = BenchBox maintainers, ``community`` =
arms-length contributor, ``vendor`` = the platform vendor itself."""

DEFAULT_RESULT_SOURCE = "internal"

SOURCE_TO_TRUST_LABEL: dict[str, str] = {
    "internal": "maintainer-run",
    "community": "community-submission",
    "vendor": "vendor-supplied",
}

# Full trust-label vocabulary. ``verified`` is reserved for future third-party
# attestation and is not produced by any current path.
TRUST_LABELS: tuple[str, ...] = (
    "maintainer-run",
    "community-submission",
    "vendor-supplied",
    "verified",
)

TRUST_LABEL_DISPLAY: dict[str, str] = {
    "maintainer-run": "Maintainer Run",
    "community-submission": "Community Submission",
    "vendor-supplied": "Vendor Supplied",
    "verified": "Verified",
}

TRUST_LABEL_TO_VISIBILITY: dict[str, str] = {
    "maintainer-run": "public-curated",
    "community-submission": "public-self-reported",
    "vendor-supplied": "public-vendor-reported",
    "verified": "public-verified",
}

# Visibility states that may appear in ranked leaderboard tables. Vendor-reported
# joins curated and verified: vendor results are ranked (with a distinct badge)
# rather than demoted to browse-only. Self-reported community results are not
# ranking-eligible.
RANKING_ELIGIBLE_VISIBILITIES: frozenset[str] = frozenset(
    {"public-curated", "public-verified", "public-vendor-reported"}
)

# ---------------------------------------------------------------------------
# Funding
# ---------------------------------------------------------------------------

FUNDING_SOURCES: tuple[str, ...] = (
    "employer",
    "personal",
    "free-trial",
    "vendor-sponsored",
    "grant",
    "unspecified",
)
"""How the run was paid for. ``unspecified`` is the default when a producer does
not declare funding."""

DEFAULT_FUNDING = "unspecified"


# ---------------------------------------------------------------------------
# Helpers (total: never raise on unknown input)
# ---------------------------------------------------------------------------


def _normalize_token(value: object) -> str:
    return str(value).strip().lower() if value is not None else ""


def normalize_source(value: object) -> str:
    """Return a valid result_source, defaulting unknown/empty to ``internal``."""
    token = _normalize_token(value)
    return token if token in SOURCE_TO_TRUST_LABEL else DEFAULT_RESULT_SOURCE


def is_valid_source(value: object) -> bool:
    """Return True only for an exact known result_source token."""
    return _normalize_token(value) in SOURCE_TO_TRUST_LABEL


def normalize_funding(value: object) -> str:
    """Return a valid funding value, defaulting unknown/empty to ``unspecified``."""
    token = _normalize_token(value)
    return token if token in FUNDING_SOURCES else DEFAULT_FUNDING


def is_valid_funding(value: object) -> bool:
    """Return True only for an exact known funding token."""
    return _normalize_token(value) in FUNDING_SOURCES


def trust_label_for_source(source: object) -> str:
    """Map a result_source to its trust label (unknown -> maintainer-run)."""
    return SOURCE_TO_TRUST_LABEL[normalize_source(source)]


def visibility_for_label(trust_label: object) -> str:
    """Map a trust label to its visibility state.

    An unrecognized label fails *safe* to ``public-self-reported`` (visible but
    NOT ranking-eligible) rather than being silently promoted to the ranked
    ``public-curated`` tier. Real labels are validated strictly upstream (e.g.
    ``BundlePublisher``), so this default only guards against corruption or a
    not-yet-known future label. Note this is deliberately different from the
    ``result_source`` default (:func:`normalize_source` -> ``internal``), where
    an undeclared source genuinely means a maintainer run.
    """
    token = _normalize_token(trust_label)
    return TRUST_LABEL_TO_VISIBILITY.get(token, "public-self-reported")


def display_for_label(trust_label: object) -> str:
    """Human-readable badge text for a trust label (unknown -> normalized token)."""
    token = _normalize_token(trust_label)
    return TRUST_LABEL_DISPLAY.get(token, token)


def is_ranking_eligible_visibility(visibility: object) -> bool:
    """Return True when a visibility state may appear in ranked tables."""
    return _normalize_token(visibility) in RANKING_ELIGIBLE_VISIBILITIES


__all__ = [
    "RESULT_SOURCES",
    "DEFAULT_RESULT_SOURCE",
    "SOURCE_TO_TRUST_LABEL",
    "TRUST_LABELS",
    "TRUST_LABEL_DISPLAY",
    "TRUST_LABEL_TO_VISIBILITY",
    "RANKING_ELIGIBLE_VISIBILITIES",
    "FUNDING_SOURCES",
    "DEFAULT_FUNDING",
    "normalize_source",
    "is_valid_source",
    "normalize_funding",
    "is_valid_funding",
    "trust_label_for_source",
    "visibility_for_label",
    "display_for_label",
    "is_ranking_eligible_visibility",
]
