# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from benchbox.core.dataframe.tuning import (
    DataFrameTuningConfiguration,
    ValidationLevel,
    validate_dataframe_tuning,
)
from benchbox.core.tuning.applied_ledger import (
    EXECUTED,
    PHASE_POST_LOAD,
    PHASE_SESSION,
    AppliedTuningLedger,
)

if TYPE_CHECKING:
    from benchbox.core.dataframe.tuning.write_config import DataFrameWriteConfiguration

logger = logging.getLogger(__name__)

DATAFRAME_RUNTIME_MECHANISM = "dataframe_runtime"
DATAFRAME_WRITE_LAYOUT_MECHANISM = "dataframe_write_layout"


def _render_layout_value(value: Any) -> str:
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


class TuningConfigurableMixin(ABC):
    _tuning_config: DataFrameTuningConfiguration
    verbose: bool

    @property
    @abstractmethod
    def platform_name(self) -> str:
        pass

    @property
    @abstractmethod
    def family(self) -> str:
        pass

    def _init_tuning(
        self,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        self._tuning_config = tuning_config or DataFrameTuningConfiguration()
        self._applied_tuning_ledger: AppliedTuningLedger = AppliedTuningLedger()

    def _validate_and_apply_tuning(self) -> None:
        issues = validate_dataframe_tuning(self._tuning_config, self.platform_name)

        applied_settings: list[str] = []
        warnings_logged: list[str] = []

        for issue in issues:
            if issue.level == ValidationLevel.ERROR:
                raise ValueError(f"Tuning configuration error: {issue.message}")
            elif issue.level == ValidationLevel.WARNING:
                logger.warning(f"Tuning [{self.platform_name}]: {issue}")
                warnings_logged.append(str(issue))
            elif getattr(self, "verbose", False) and issue.level == ValidationLevel.INFO:
                logger.info(f"Tuning [{self.platform_name}]: {issue}")

        if not self._tuning_config.is_default():
            enabled = self._tuning_config.get_enabled_settings()
            applied_settings = [s.value for s in enabled]
            logger.debug(f"Applying tuning to {self.platform_name}: {applied_settings}")

        self._apply_tuning()

        if applied_settings:
            logger.debug(f"Tuning applied to {self.platform_name}: {len(applied_settings)} settings")

    def _apply_tuning(self) -> None:
        pass

    @property
    def tuning_config(self) -> DataFrameTuningConfiguration:
        return self._tuning_config

    def get_tuning_summary(self) -> dict[str, Any]:
        return {
            "platform": self.platform_name,
            "family": self.family,
            "config_summary": self._tuning_config.get_summary(),
            "is_default": self._tuning_config.is_default(),
        }

    def _record_runtime_tuning(
        self,
        statement: str,
        *,
        phase: str = PHASE_SESSION,
        status: str = EXECUTED,
        mechanism: str = DATAFRAME_RUNTIME_MECHANISM,
    ) -> None:
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None:
            return
        ledger.record(statement, phase, status=status, mechanism=mechanism)

    def _fold_write_layout_into_ledger(
        self,
        write_config: DataFrameWriteConfiguration | None,
    ) -> None:
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None or write_config is None:
            return
        try:
            if write_config.is_default():
                return
            ledger.statements = [
                s
                for s in ledger.statements
                if not (s.phase == PHASE_POST_LOAD and s.mechanism == DATAFRAME_WRITE_LAYOUT_MECHANISM)
            ]
            for key, value in write_config.to_dict().items():
                ledger.record(
                    f"{key}={_render_layout_value(value)}",
                    PHASE_POST_LOAD,
                    mechanism=DATAFRAME_WRITE_LAYOUT_MECHANISM,
                )
        except Exception as exc:
            logger.debug("dataframe write-layout ledger fold degraded: %s", exc)

    def _derive_applied_tuning_status(self) -> str | None:
        from benchbox.platforms.dataframe import tuning_trust

        return tuning_trust.derive_applied_tuning_status(
            getattr(self, "_applied_tuning_ledger", None),
            getattr(self, "_tuning_config", None),
        )

    def _write_applied_tuning_ledger(self, builder: Any) -> None:
        from benchbox.platforms.dataframe import tuning_trust

        tuning_trust.write_applied_tuning_ledger(
            getattr(self, "_applied_tuning_ledger", None),
            getattr(self, "_tuning_config", None),
            builder,
        )
