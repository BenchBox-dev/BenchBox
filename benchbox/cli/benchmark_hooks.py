"""Back-compat re-export shim for the relocated benchmark hook registry.

``benchbox.cli.benchmark_hooks`` moved to
``benchbox.core.hooks.benchmark_hooks`` (see
``_project/TODO/main/planning/relocate-cli-hook-registries.yaml``) so that
``benchbox.core`` benchmark modules no longer need to import "up" into
``benchbox.cli``. This module is kept as an internal-only courtesy shim for
callers still importing from the old path; it is not a documented public
contract (see docs/reference/backward-compatibility.md). New code should
import from ``benchbox.core.hooks.benchmark_hooks`` directly.
"""

from __future__ import annotations

from benchbox.core.hooks.benchmark_hooks import (
    BenchmarkHookRegistry,
    BenchmarkOptionError,
    BenchmarkOptionSpec,
    parse_bool,
    parse_datetime,
    parse_enum_list,
    parse_int,
    parse_int_list,
    parse_str_list,
)

__all__ = [
    "BenchmarkHookRegistry",
    "BenchmarkOptionError",
    "BenchmarkOptionSpec",
    "parse_bool",
    "parse_datetime",
    "parse_enum_list",
    "parse_int",
    "parse_int_list",
    "parse_str_list",
]
