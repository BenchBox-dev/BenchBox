"""Shared config builder for Azure-compatible platform adapters.

.. deprecated::
    Import from ``benchbox.platforms.base.config_utils`` instead.
    This module is kept as a re-export shim for backward compatibility.
"""

from benchbox.platforms.base.config_utils import build_platform_config  # noqa: F401

__all__ = ["build_platform_config"]
