"""Gated applied-ledger trust helpers for DataFrame adapters.

The status-deriving and result-attaching logic moved here from
``TuningConfigurableMixin`` so the trust decision lives in a
soundness-manifest module; the mixin keeps one-line delegates so existing
entry points are unchanged. Behavior is identical: capture never breaks a
run, and every helper degrades to a no-op on error, mirroring
``AppliedTuningLedger``'s own guarantee.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def derive_applied_tuning_status(ledger: Any | None, config: Any | None) -> str | None:
    """Derive the honest execution-path tuning status, or ``None``.

    A run with an absent or all-default configuration that recorded no
    statement requested no tuning and derives ``not_applicable``. A run that
    requested tuning derives ``applied_unverified`` when at least one setting
    executed and ``noop`` when none did. Returns ``None`` when there is no
    ledger (a non-tuning stub adapter).
    """
    if ledger is None:
        return None
    has_config = bool(ledger.statements) or (config is not None and not config.is_default())
    return ledger.overall_status(tuning_enabled=has_config, has_config=has_config)


def write_applied_tuning_ledger(ledger: Any | None, config: Any | None, builder: Any) -> None:
    """Attach the applied-ledger status + companion payload + hash onto a
    result builder before it builds the ``BenchmarkResults``.

    Reuses ``ResultBuilder.set_tuning_info`` -- the same seam the SQL path
    feeds -- so the existing export path carries ``applied_tuning_ledger`` +
    ``applied_ledger_hash`` (companion ``.applied.json`` and the
    ``platform.tuning`` summary block the explorer ingests). Guarded end to
    end: any derive/serialize failure degrades to a debug log and leaves the
    builder's defaults.
    """
    if ledger is None:
        return
    try:
        status = derive_applied_tuning_status(ledger, config)
        if status is None:
            return
        # Only carry the companion when something was actually captured; an
        # empty ledger (default/untuned run) still records the honest status.
        payload = ledger.to_payload(status=status) if not ledger.is_empty() else None
        # Requested-config export (ADR-1): the DataFrame tuning config's
        # to_dict() is the requested tunings, mirroring the SQL side's
        # ``effective_tuning_config.to_dict()``. Populating it also lets the
        # shared ``_build_tuning_summary`` emit the ``platform.tuning`` block
        # that carries ``applied_ledger_hash`` for explorer ingest. Empty for
        # a default config (a no-op run needs no requested-config summary).
        tunings_applied = config.to_dict() if config is not None else None
        builder.set_tuning_info(
            tunings_applied=tunings_applied or None,
            validation_status=status,
            applied_tuning_ledger=payload,
            applied_ledger_hash=ledger.applied_ledger_hash(),
        )
    except Exception as exc:  # capture must never break a run
        logger.debug("dataframe applied-ledger wiring degraded: %s", exc)
