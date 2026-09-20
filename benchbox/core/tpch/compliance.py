"""TPC-H compliance classification.

Single source of truth for classifying a TPC-H run's methodology compliance,
mirroring :mod:`benchbox.core.tpcds.compliance` so the two TPC families share
one gate shape: official scale point plus ``--official`` mode, stamped as
``compliance_class`` and refused by ``benchbox submit``/``publish`` when
unofficial.
"""

from enum import Enum


class TpchComplianceClass(str, Enum):
    """Methodology compliance classification for a TPC-H run.

    - OFFICIAL: scale factor is one of the TPC-H specification-approved values
      and the run was invoked with ``--official`` mode.
    - UNOFFICIAL_NONSTANDARD: scale factor >= 1.0 but not an official scale point,
      or an official scale point run without ``--official`` mode. No official
      TPC-H metrics (QphH) may be published.
    - UNOFFICIAL_SUBSCALE: scale factor < 1.0 (development convenience only).
      These runs are allowed by default, but remain unofficial. Official TPC-H
      metrics must never be computed or displayed.
    """

    OFFICIAL = "official"
    UNOFFICIAL_NONSTANDARD = "unofficial_nonstandard"
    UNOFFICIAL_SUBSCALE = "unofficial_subscale"


# Official TPC-H scale points per the TPC-H specification (database sizes
# 1GB .. 100000GB).
OFFICIAL_SCALE_POINTS: frozenset[float] = frozenset(
    {1.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0, 10000.0, 30000.0, 100000.0}
)


def classify_tpch_run(scale_factor: float, *, official: bool = False) -> TpchComplianceClass:
    """Return the compliance class for a TPC-H run at *scale_factor*.

    Args:
        scale_factor: The requested TPC-H scale factor (> 0).
        official: True when the caller is running in ``--official`` mode.

    Returns:
        The appropriate :class:`TpchComplianceClass` value.
    """
    if scale_factor < 1.0:
        return TpchComplianceClass.UNOFFICIAL_SUBSCALE
    if official and scale_factor in OFFICIAL_SCALE_POINTS:
        return TpchComplianceClass.OFFICIAL
    return TpchComplianceClass.UNOFFICIAL_NONSTANDARD


def validate_tpch_scale(
    scale_factor: float,
    *,
    official: bool = False,
) -> TpchComplianceClass:
    """Validate *scale_factor* and return its compliance class.

    Raises :class:`ValueError` if the scale factor is not positive or exceeds
    the maximum.

    Args:
        scale_factor: The requested TPC-H scale factor.
        official: True when the run was invoked in ``--official`` mode. This
            must be forwarded from the run configuration: without it every run
            classifies as ``UNOFFICIAL_NONSTANDARD`` and can never be submitted.

    Returns:
        The :class:`TpchComplianceClass` for the run.

    Raises:
        ValueError: If the scale factor is invalid.
    """
    if scale_factor <= 0:
        raise ValueError(f"TPC-H scale factor must be positive, got {scale_factor}")
    if scale_factor > 100000:
        raise ValueError(f"TPC-H scale factor {scale_factor} exceeds maximum (100000)")

    return classify_tpch_run(scale_factor, official=official)
