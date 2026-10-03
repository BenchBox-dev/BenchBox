from __future__ import annotations

from benchbox.core.hooks.platform_hooks import (
    PlatformHookRegistry,
    PlatformOptionError,
    PlatformOptionSpec,
    parse_bool,  # noqa: F401 - re-exported for old-path callers
)

__all__ = [
    "PlatformHookRegistry",
    "PlatformOptionError",
    "PlatformOptionSpec",
]
