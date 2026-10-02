"""Early pytest plugin that caps unsafe xdist worker counts on developer Macs."""

from __future__ import annotations

import os
import sys
from typing import Optional

import pytest

from tests.utilities import session_isolation


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


def _last_option_value(args: list[str], long_name: str, short_name: str) -> str | None:
    """Return the value of the last ``-x value``, ``-xvalue``, ``--long value`` or ``--long=value`` option."""
    value: str | None = None
    for idx, arg in enumerate(args):
        if arg in {short_name, long_name} and idx + 1 < len(args):
            value = args[idx + 1]
        elif arg.startswith(f"{long_name}="):
            value = arg.split("=", 1)[1]
        elif arg.startswith(short_name) and not arg.startswith("--") and len(arg) > len(short_name):
            value = arg[len(short_name) :]
    return value


def _wants_parallel_lock(args: list[str]) -> bool:
    """Whether this run competes for the shared lock: parallel workers and no explicit bypass."""
    if os.environ.get("BENCHBOX_SKIP_TEST_LOCK"):
        return False
    value = _last_option_value(args, "--numprocesses", "-n")
    if value is None:
        return False
    return value in {"auto", "logical"} or bool(_requested_numprocesses(value))


def _selects_live_tests(args: list[str]) -> bool:
    """Whether the effective ``-m`` expression selects a test marked only ``live_integration``.

    Live tests read the caller's real credential files, so a run that selects them keeps the real HOME.
    The default expression deselects them. An expression that does not parse is treated as not selecting.
    """
    expression = _last_option_value(args, "--markers-expression", "-m")
    if not expression:
        return False
    try:
        from _pytest.mark.expression import Expression

        return bool(Expression.compile(expression).evaluate(lambda name, **_: name == "live_integration"))
    except Exception:
        return False


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_load_initial_conftests(early_config, parser, args: list[str]):
    """Own lock and HOME before collection, then cap xdist's worker plan."""
    if not _selects_live_tests(args) and session_isolation.start(acquire_lock=_wants_parallel_lock(args)):
        early_config.add_cleanup(session_isolation.finish)
    safe = _safe_worker_count()
    requested = _rewrite_numprocesses_args(args, safe)
    if requested is not None:
        os.environ["BENCHBOX_XDIST_CAP_REQUESTED"] = requested
        os.environ["BENCHBOX_XDIST_CAP_EFFECTIVE"] = str(safe)
    return (yield)


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
