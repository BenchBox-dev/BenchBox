"""Back-compat re-export shim for the relocated platform hook registry.

``benchbox.cli.platform_hooks`` moved to
``benchbox.core.hooks.platform_hooks`` (see
``_project/TODO/main/planning/relocate-cli-hook-registries.yaml``) so that
``benchbox.platforms`` no longer needs to import "up" into ``benchbox.cli``.
This module is kept as an internal-only courtesy shim for callers still
importing from the old path; it is not a documented public contract (see
docs/reference/backward-compatibility.md). New code should import from
``benchbox.core.hooks.platform_hooks`` directly.
"""

from __future__ import annotations

from benchbox.core.hooks.platform_hooks import (
    PlatformHookRegistry,
    PlatformOptionError,
    PlatformOptionSpec,
    parse_bool,  # noqa: F401 - re-exported for old-path callers
)

# NOTE: `parse_bool` is intentionally importable (some callers do
# `from benchbox.cli.platform_hooks import ..., parse_bool`) but omitted from
# __all__, matching the original module's behavior before the relocation.
__all__ = [
    "PlatformHookRegistry",
    "PlatformOptionError",
    "PlatformOptionSpec",
]
