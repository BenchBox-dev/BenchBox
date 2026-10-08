from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def derive_applied_tuning_status(ledger: Any | None, config: Any | None) -> str | None:
    if ledger is None:
        return None
    has_config = bool(ledger.statements) or (config is not None and not config.is_default())
    return ledger.overall_status(tuning_enabled=has_config, has_config=has_config)


def write_applied_tuning_ledger(ledger: Any | None, config: Any | None, builder: Any) -> None:
    if ledger is None:
        return
    try:
        status = derive_applied_tuning_status(ledger, config)
        if status is None:
            return
        payload = ledger.to_payload(status=status) if not ledger.is_empty() else None
        tunings_applied = config.to_dict() if config is not None else None
        builder.set_tuning_info(
            tunings_applied=tunings_applied or None,
            validation_status=status,
            applied_tuning_ledger=payload,
            applied_ledger_hash=ledger.applied_ledger_hash(),
        )
    except Exception as exc:
        logger.debug("dataframe applied-ledger wiring degraded: %s", exc)
