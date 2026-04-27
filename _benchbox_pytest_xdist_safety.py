"""Early pytest plugin that caps unsafe xdist worker counts on developer Macs."""

from __future__ import annotations

import os
import sys
from typing import Optional


def _safe_worker_count() -> int:
    """Return a safe pytest-xdist worker count for local development."""
    override = os.environ.get("BENCHBOX_MAX_XDIST_WORKERS")
    if override:
        try:
            return max(1, int(override))
        except ValueError:
            pass

    ncpu = os.cpu_count() or 4
    platform_cap = 8 if sys.platform == "darwin" else 4
    cpu_cap = min(platform_cap, max(2, ncpu // 2))

    try:
        import psutil

        avail_mb = psutil.virtual_memory().available / (1024 * 1024)
        worker_mb = 200
        mem_cap = max(2, int(avail_mb / worker_mb) - 1)
    except (ImportError, Exception):
        mem_cap = cpu_cap

    return min(cpu_cap, mem_cap)


def _requested_numprocesses(raw: str) -> Optional[int]:
    if raw in {"auto", "logical"}:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _rewrite_numprocesses_args(args: list[str], safe: int) -> str | None:
    """Mutate ``args`` in place when ``-n`` requests exceed the safe cap."""
    candidate: tuple[int, int, str, bool] | None = None

    for idx, arg in enumerate(args):
        value: str | None = None
        value_idx: int | None = None
        compact = False

        if arg in {"-n", "--numprocesses"} and idx + 1 < len(args):
            value = args[idx + 1]
            value_idx = idx + 1
        elif arg.startswith("--numprocesses="):
            value = arg.split("=", 1)[1]
            value_idx = idx
        elif arg.startswith("-n") and arg != "-n":
            value = arg[2:]
            value_idx = idx
            compact = True

        if value is not None and value_idx is not None:
            candidate = (idx, value_idx, value, compact)

    if candidate is None:
        return None

    idx, value_idx, value, compact = candidate
    requested = _requested_numprocesses(value)
    if value not in {"auto", "logical"} and requested is not None and requested <= safe:
        return None

    if value_idx == idx and compact:
        args[idx] = f"-n{safe}"
    elif value_idx == idx:
        args[idx] = f"--numprocesses={safe}"
    else:
        args[value_idx] = str(safe)
    return value


def pytest_load_initial_conftests(early_config, parser, args: list[str]) -> None:
    """Cap xdist workers before pytest/xdist creates any worker plan."""
    safe = _safe_worker_count()
    requested = _rewrite_numprocesses_args(args, safe)
    if requested is None:
        return

    os.environ["BENCHBOX_XDIST_CAP_REQUESTED"] = requested
    os.environ["BENCHBOX_XDIST_CAP_EFFECTIVE"] = str(safe)


def pytest_xdist_auto_num_workers(config) -> int:
    """Fallback hook for environments where xdist still asks for auto workers."""
    return _safe_worker_count()


def pytest_configure(config) -> None:
    if hasattr(config, "workerinput"):
        return

    requested = os.environ.pop("BENCHBOX_XDIST_CAP_REQUESTED", None)
    effective = os.environ.pop("BENCHBOX_XDIST_CAP_EFFECTIVE", None)
    if requested and effective:
        sys.stderr.write(
            f"[benchbox] Capped pytest-xdist workers from {requested} to {effective} "
            f"(set BENCHBOX_MAX_XDIST_WORKERS to override).\n"
        )
        sys.stderr.flush()
