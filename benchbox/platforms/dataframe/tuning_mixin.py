"""Tuning configuration mixin for DataFrame adapters.

This module provides the TuningConfigurableMixin class that adds tuning
configuration support to DataFrame adapters. Both ExpressionFamilyAdapter
and PandasFamilyAdapter inherit from this mixin.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

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

# Reuse the shared applied-tuning ledger vocabulary from the SQL side (ADR-1,
# tuning-applied-ledger-and-validation-status-20260712) -- NOT a fork. DataFrame
# "tuning" is runtime settings (thread/memory) + write-layout, recorded as
# ledger statements with an honest DataFrame-runtime mechanism.
from benchbox.core.tuning.applied_ledger import (
    EXECUTED,
    PHASE_POST_LOAD,
    PHASE_SESSION,
    AppliedTuningLedger,
)

if TYPE_CHECKING:
    from benchbox.core.dataframe.tuning.write_config import DataFrameWriteConfiguration

logger = logging.getLogger(__name__)

#: mechanism tag for runtime settings the DataFrame path applies at construction
#: (thread count, streaming, chunk size, dtype backend). Phase = SESSION.
DATAFRAME_RUNTIME_MECHANISM = "dataframe_runtime"
#: mechanism tag for physical write-layout the DataFrame path applies during
#: data preparation (sort/partition/compression/row-group). Phase = POST_LOAD.
DATAFRAME_WRITE_LAYOUT_MECHANISM = "dataframe_write_layout"


def _render_layout_value(value: Any) -> str:
    """Render a write-config value compactly for a ledger statement string."""
    if isinstance(value, (list, dict)):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    return str(value)


class TuningConfigurableMixin(ABC):
    """Mixin providing tuning configuration support for DataFrame adapters.

    This mixin extracts the common tuning validation and application logic
    that was previously duplicated in ExpressionFamilyAdapter and
    PandasFamilyAdapter.

    Subclasses must implement:
    - platform_name: Property returning the platform identifier
    - family: Property returning the family identifier
    - _apply_tuning(): Method to apply platform-specific tuning settings

    Attributes:
        _tuning_config: The active tuning configuration
        verbose: Whether verbose logging is enabled
    """

    # These will be provided by the concrete adapter classes
    _tuning_config: DataFrameTuningConfiguration
    verbose: bool

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the human-readable platform name."""

    @property
    @abstractmethod
    def family(self) -> str:
        """Return the DataFrame family (expression or pandas)."""

    def _init_tuning(
        self,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the tuning configuration.

        This should be called during adapter __init__ before _validate_and_apply_tuning.

        Args:
            tuning_config: Optional tuning configuration. If None, uses defaults.
        """
        self._tuning_config = tuning_config or DataFrameTuningConfiguration()
        # Fresh applied-tuning ledger for this adapter. Populated BY the apply
        # path as runtime settings execute in ``_apply_tuning`` (SESSION) and as
        # write-layout is folded after data prep (POST_LOAD); read back once at
        # result construction for the honest status + applied-ledger hash. Never
        # reconstructed from config, mirroring the SQL-side invariant.
        self._applied_tuning_ledger: AppliedTuningLedger = AppliedTuningLedger()

    def _validate_and_apply_tuning(self) -> None:
        """Validate tuning configuration and apply settings.

        This method should be called by subclasses after their own initialization
        is complete (so platform_name is available).

        Raises:
            ValueError: If the tuning configuration contains errors
        """
        # Validate the configuration
        issues = validate_dataframe_tuning(self._tuning_config, self.platform_name)

        # Track what settings were validated
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

        # Log tuning application
        if not self._tuning_config.is_default():
            enabled = self._tuning_config.get_enabled_settings()
            applied_settings = [s.value for s in enabled]
            logger.debug(f"Applying tuning to {self.platform_name}: {applied_settings}")

        # Apply tuning settings (implemented by subclasses)
        self._apply_tuning()

        # Log completion
        if applied_settings:
            logger.debug(f"Tuning applied to {self.platform_name}: {len(applied_settings)} settings")

    def _apply_tuning(self) -> None:  # noqa: B027 - intentional hook pattern
        """Apply tuning configuration settings.

        Subclasses should override this method to implement platform-specific
        tuning application. The default implementation does nothing (hook pattern).
        """

    @property
    def tuning_config(self) -> DataFrameTuningConfiguration:
        """Get the active tuning configuration."""
        return self._tuning_config

    def get_tuning_summary(self) -> dict[str, Any]:
        """Get a summary of the applied tuning settings.

        Returns:
            Dictionary with tuning summary information including:
            - platform: The platform name
            - family: The DataFrame family
            - config_summary: Summary from the configuration
            - is_default: Whether using default configuration
        """
        return {
            "platform": self.platform_name,
            "family": self.family,
            "config_summary": self._tuning_config.get_summary(),
            "is_default": self._tuning_config.is_default(),
        }

    # -------------------------------------------------------------------------
    # Applied-tuning ledger (ADR-1 parity with the SQL execution path)
    #
    # The SQL side wraps its DB connection so every executed tuning statement is
    # recorded transparently. The DataFrame path has no such connection -- it
    # applies runtime settings via env vars / library config / attributes and
    # write-layout via the Parquet converter -- so it records explicitly at each
    # apply point instead. Capture never breaks a run: every helper degrades to
    # a no-op on error, mirroring ``AppliedTuningLedger``'s own guarantee.
    # -------------------------------------------------------------------------
    def _record_runtime_tuning(
        self,
        statement: str,
        *,
        phase: str = PHASE_SESSION,
        status: str = EXECUTED,
        mechanism: str = DATAFRAME_RUNTIME_MECHANISM,
    ) -> None:
        """Record one runtime tuning setting the apply path actually applied.

        Called from concrete ``_apply_tuning`` implementations right after a
        setting is applied (thread count, streaming, chunk size, dtype backend),
        so the ledger reflects what executed rather than what was requested.
        """
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None:
            return
        ledger.record(statement, phase, status=status, mechanism=mechanism)

    def _fold_write_layout_into_ledger(
        self,
        write_config: DataFrameWriteConfiguration | None,
    ) -> None:
        """Fold applied physical write-layout into the ledger as POST_LOAD.

        ``write_config`` is the layout the data loader actually applied when
        converting/caching the benchmark's Parquet (its ``applied_write_layout``
        signal) -- ``None`` or a default config records nothing. Each non-default
        layout option becomes one POST_LOAD statement, mirroring the SQL side's
        ``_fold_layout_operations_into_ledger``. Prior write-layout statements
        are pruned first so re-running the same adapter stays idempotent (the
        construction-time SESSION statements are left untouched).
        """
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
        except Exception as exc:  # capture must never break a run
            logger.debug("dataframe write-layout ledger fold degraded: %s", exc)

    def _derive_applied_tuning_status(self) -> str | None:
        """Derive the honest execution-path tuning status, or ``None``.

        The DataFrame path always runs its tuning-application step (even for a
        default config), so ``tuning_enabled``/``has_config`` are both true when
        a config is present: a default run that applied nothing derives ``noop``,
        a tuned run that applied >=1 setting derives ``applied_unverified``.
        Returns ``None`` when there is no ledger (a non-tuning stub adapter).
        """
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None:
            return None
        has_config = getattr(self, "_tuning_config", None) is not None
        return ledger.overall_status(tuning_enabled=has_config, has_config=has_config)

    def _write_applied_tuning_ledger(self, builder: Any) -> None:
        """Attach the applied-ledger status + companion payload + hash onto a
        result builder before it builds the ``BenchmarkResults``.

        Reuses ``ResultBuilder.set_tuning_info`` -- the same seam the SQL path
        feeds -- so the existing export path carries ``applied_tuning_ledger`` +
        ``applied_ledger_hash`` (companion ``.applied.json`` and the
        ``platform.tuning`` summary block the explorer ingests). Guarded end to
        end: any derive/serialize failure degrades to a debug log and leaves the
        builder's defaults.
        """
        ledger = getattr(self, "_applied_tuning_ledger", None)
        if ledger is None:
            return
        try:
            status = self._derive_applied_tuning_status()
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
            config = getattr(self, "_tuning_config", None)
            tunings_applied = config.to_dict() if config is not None else None
            builder.set_tuning_info(
                tunings_applied=tunings_applied or None,
                validation_status=status,
                applied_tuning_ledger=payload,
                applied_ledger_hash=ledger.applied_ledger_hash(),
            )
        except Exception as exc:  # capture must never break a run
            logger.debug("dataframe applied-ledger wiring degraded: %s", exc)
