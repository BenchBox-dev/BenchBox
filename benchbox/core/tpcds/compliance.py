"""TPC-DS compliance classification.

Single source of truth for classifying a TPC-DS run's methodology compliance.
All scale-factor validation logic that was previously duplicated across
benchmark_registry.py, runner.py, and generator/manager.py routes through here.
"""

from enum import Enum


class TpcdsComplianceClass(str, Enum):
    """Methodology compliance classification for a TPC-DS run.

    - OFFICIAL: scale factor is one of the TPC-DS specification-approved values
      and the run was invoked with ``--official`` mode.
    - UNOFFICIAL_NONSTANDARD: scale factor >= 1.0 but not an official scale point,
      or an official scale point run without ``--official`` mode.  No TPC-DS
      official metrics (QphDS) may be published.
    - UNOFFICIAL_SUBSCALE: scale factor < 1.0 (development convenience only).
      These runs are allowed by default, but remain unofficial. Official TPC-DS
      metrics must never be computed or displayed.
    """

    OFFICIAL = "official"
    UNOFFICIAL_NONSTANDARD = "unofficial_nonstandard"
    UNOFFICIAL_SUBSCALE = "unofficial_subscale"


# Official TPC-DS scale points per the TPC-DS specification.
OFFICIAL_SCALE_POINTS: frozenset[float] = frozenset(
    {1.0, 10.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0}
)

# Minimum allowed subscale value (below this the patch provides no guarantee).
TPCDS_MIN_SUBSCALE: float = 0.001


def classify_tpcds_run(scale_factor: float, *, official: bool = False) -> TpcdsComplianceClass:
    """Return the compliance class for a TPC-DS run at *scale_factor*.

    Args:
        scale_factor: The requested TPC-DS scale factor (> 0).
        official: True when the caller is running in ``--official`` mode.

    Returns:
        The appropriate :class:`TpcdsComplianceClass` value.
    """
    if scale_factor < 1.0:
        return TpcdsComplianceClass.UNOFFICIAL_SUBSCALE
    if official and scale_factor in OFFICIAL_SCALE_POINTS:
        return TpcdsComplianceClass.OFFICIAL
    return TpcdsComplianceClass.UNOFFICIAL_NONSTANDARD


def validate_tpcds_scale(
    scale_factor: float,
) -> TpcdsComplianceClass:
    """Validate *scale_factor* and return its compliance class.

    Raises :class:`ValueError` if the scale factor is not positive, exceeds
    the maximum, or is below the supported subscale floor.

    Args:
        scale_factor: The requested TPC-DS scale factor.

    Returns:
        The :class:`TpcdsComplianceClass` for the run.

    Raises:
        ValueError: If the scale factor is invalid.
    """
    if scale_factor <= 0:
        raise ValueError(f"TPC-DS scale factor must be positive, got {scale_factor}")
    if scale_factor > 100000:
        raise ValueError(f"TPC-DS scale factor {scale_factor} exceeds maximum (100000)")

    compliance = classify_tpcds_run(scale_factor)

    if compliance is TpcdsComplianceClass.UNOFFICIAL_SUBSCALE and scale_factor < TPCDS_MIN_SUBSCALE:
        raise ValueError(
            f"TPC-DS scale_factor {scale_factor} is below the minimum subscale "
            f"({TPCDS_MIN_SUBSCALE}). The patched dsdgen provides no row-count "
            "guarantees below this threshold."
        )

    return compliance
