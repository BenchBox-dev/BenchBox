"""Verbosity utilities and mixin shared across CLI, core, and adapters."""

from __future__ import annotations

import logging
from abc import ABC
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from benchbox.utils.version import check_version_consistency, format_version_report


@dataclass(frozen=True)
class VerbositySettings:
    """Normalized representation of CLI verbosity flags."""

    level: int = 0
    verbose_enabled: bool = False
    very_verbose: bool = False
    quiet: bool = False

    @property
    def verbose(self) -> bool:
        """Return True when verbose output should be emitted."""

        return self.verbose_enabled and not self.quiet

    def to_config(self) -> dict[str, Any]:
        """Convert settings to a flat dict suitable for config/options payloads."""

        return {
            "verbose_level": self.level,
            "verbose_enabled": self.verbose_enabled,
            "very_verbose": self.very_verbose,
            "quiet": self.quiet,
            "verbose": self.verbose,
        }

    @classmethod
    def from_flags(cls, verbose: int | bool | None, quiet: bool | None) -> VerbositySettings:
        """Create settings from CLI-style flags."""

        quiet_flag = bool(quiet) if quiet is not None else False
        level = (2 if verbose else 0) if isinstance(verbose, bool) else int(verbose or 0)

        if level < 0:
            level = 0

        if quiet_flag:
            level = 0

        verbose_enabled = level >= 1 and not quiet_flag
        very_verbose = level >= 2 and not quiet_flag

        return cls(level=level, verbose_enabled=verbose_enabled, very_verbose=very_verbose, quiet=quiet_flag)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> VerbositySettings:
        """Create settings from an options mapping if available."""

        if not data:
            return cls()

        quiet = bool(data.get("quiet", False))
        level = int(data.get("verbose_level", data.get("level", 0)) or 0)
        if quiet:
            level = 0

        verbose_enabled = bool(data.get("verbose_enabled", level >= 1 and not quiet))
        very_verbose = bool(data.get("very_verbose", level >= 2 and not quiet))

        return cls(level=level, verbose_enabled=verbose_enabled, very_verbose=very_verbose, quiet=quiet)

    @classmethod
    def default(cls) -> VerbositySettings:
        """Return default non-verbose settings."""

        return cls()


def compute_verbosity(verbose: int | bool | None, quiet: bool | None) -> VerbositySettings:
    """Normalize verbosity inputs to a consistent settings object."""

    return VerbositySettings.from_flags(verbose, quiet)


class VerbosityMixin(ABC):
    """Mixin providing standardized verbose/very-verbose logging helpers.

    Expects the consumer to define:
      - self.logger: logging.Logger
      - self.verbose_enabled: bool
      - self.very_verbose: bool
      - self.quiet: bool
    """

    _logger: logging.Logger | None = None
    verbose_level: int = 0
    verbose_enabled: bool = False
    very_verbose: bool = False
    quiet: bool = False
    verbose: bool = False

    @property
    def logger(self) -> logging.Logger:
        """Return the logger configured for the verbosity mixin consumer."""

        if self._logger is None:
            raise AttributeError("VerbosityMixin requires 'logger' to be set before use")
        return self._logger

    @logger.setter
    def logger(self, value: logging.Logger) -> None:
        if not isinstance(value, logging.Logger):
            raise TypeError("logger must be an instance of logging.Logger")
        self._logger = value

    def apply_verbosity(self, settings: VerbositySettings) -> None:
        """Apply verbosity settings to the mixin consumer."""

        self.verbose_level = settings.level
        self.verbose_enabled = settings.verbose_enabled
        self.very_verbose = settings.very_verbose
        self.quiet = settings.quiet
        # Maintain legacy attribute expected by older helpers
        self.verbose = settings.verbose

    @property
    def verbosity_settings(self) -> VerbositySettings:
        """Return the current verbosity settings."""

        return VerbositySettings(
            level=self.verbose_level,
            verbose_enabled=self.verbose_enabled,
            very_verbose=self.very_verbose,
            quiet=self.quiet,
        )

    def log_verbose(self, message: str) -> None:
        """Log only when verbose mode is enabled."""
        if self.quiet:
            return
        if self.verbose_enabled:
            self.logger.info(message)

    def log_notice(self, message: str) -> None:
        """Log a default-visible operational notice while respecting quiet mode."""
        if self.quiet:
            return
        self.logger.info(message)

    def log_very_verbose(self, message: str) -> None:
        """Log only when very-verbose mode is enabled."""
        if self.quiet:
            return
        if self.very_verbose:
            self.logger.debug(message)

    def log_operation_start(self, operation: str, details: str = "") -> None:
        if self.quiet:
            return
        if self.very_verbose and details:
            self.logger.debug(f"Starting {operation}: {details}")
        elif self.verbose_enabled:
            self.logger.info(f"Starting {operation}")

    def log_operation_complete(self, operation: str, duration: float | None = None, details: str = "") -> None:
        if self.quiet:
            return
        if self.very_verbose:
            msg = f"Completed {operation} in {duration:.2f}s" if duration is not None else f"Completed {operation}"
            if details:
                msg += f": {details}"
            self.logger.debug(msg)
        elif self.verbose_enabled:
            if duration is not None:
                self.logger.info(f"\u2713 {operation} completed in {duration:.2f}s")
            else:
                self.logger.info(f"\u2713 {operation} completed")

    def log_debug_info(self, context: str = "Debug") -> None:
        """Log comprehensive debug information including version details."""
        if self.quiet or not self.very_verbose:
            return

        self.logger.debug(f"=== {context} Information ===")

        # Version information
        if format_version_report:
            try:
                version_info = format_version_report()
                for line in version_info.split("\n"):
                    if line.strip():
                        self.logger.debug(f"  {line.strip()}")
            except Exception:
                try:
                    import benchbox

                    self.logger.debug(f"  BenchBox Version: {benchbox.__version__}")
                    self.logger.debug(f"  Release: v{benchbox.__version__}")
                except Exception:
                    self.logger.debug("  Version information unavailable")

        # System information
        import platform
        import sys

        self.logger.debug(f"  Python: {sys.version}")
        self.logger.debug(f"  Platform: {platform.platform()}")

    def log_error_with_debug_info(self, error: Exception, context: str = "Error") -> None:
        """Log an error with comprehensive debug information."""
        if self.quiet:
            return

        self.logger.error(f"{context}: {str(error)}")

        if self.very_verbose:
            self.log_debug_info(f"{context} Debug")

            # Log traceback in very verbose mode
            import traceback

            self.logger.debug("Traceback:")
            for line in traceback.format_exc().split("\n"):
                if line.strip():
                    self.logger.debug(f"  {line}")

    def log_version_warning(self) -> None:
        """Log version consistency warnings if any exist."""
        if self.quiet or not check_version_consistency:
            return

        try:
            result = check_version_consistency()
            if not result.consistent:
                self.logger.warning(f"Version inconsistency detected: {result.message}")
                if self.very_verbose:
                    for key, value in result.sources.items():
                        self.logger.debug(f"  {key}: {value}")
        except Exception:
            # Gracefully handle any issues with version checking
            pass


def create_debug_logger(name: str, verbose_level: int = 0, quiet: bool = False) -> logging.Logger:
    """Create a logger with debug-friendly configuration including version information."""
    logger = logging.getLogger(name)

    # Configure logging level based on verbosity
    if quiet:
        logger.setLevel(logging.ERROR)
    elif verbose_level >= 2:
        logger.setLevel(logging.DEBUG)
    elif verbose_level >= 1:
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)

    # Version information for logger context if available
    if check_version_consistency and verbose_level >= 2:
        try:
            result = check_version_consistency()
            if not result.consistent:
                logger.warning(f"Version inconsistency detected: {result.message}")
        except Exception:
            pass

    return logger


def log_debug_context(logger: logging.Logger, context: dict[str, Any], title: str = "Debug Context") -> None:
    """Log debug context information in a structured format."""
    logger.debug(f"=== {title} ===")
    for key, value in context.items():
        logger.debug(f"  {key}: {value}")


def log_import_debug(logger: logging.Logger, module_name: str, error: Exception | None = None) -> None:
    """Log debug information about module imports."""
    if error:
        logger.debug(f"Failed to import {module_name}: {error}")
        if format_version_report:
            try:
                version_info = format_version_report()
                logger.debug("Version context for import failure:")
                for line in version_info.split("\n"):
                    if line.strip() and ("Version:" in line or "Python:" in line):
                        logger.debug(f"  {line.strip()}")
            except Exception:
                pass
    else:
        logger.debug(f"Successfully imported {module_name}")
