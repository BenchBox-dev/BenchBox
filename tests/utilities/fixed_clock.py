"""Fixed-clock helpers for tests whose result must not depend on the time of day.

``freeze_datetime`` swaps the ``datetime`` name that one consumer module calls, so
only that module sees the fixed instant; the process-wide ``time`` and ``datetime``
modules keep running. ``set_mtimes`` gives files explicit modification times, so a
test that orders files by mtime does not rely on how fast the files were written.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime, timezone, tzinfo
from pathlib import Path
from types import ModuleType

import pytest

FIXED_NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
FIXED_EPOCH = FIXED_NOW.timestamp()

_RealDatetime = datetime


class _AcceptsRealDatetimes(type):
    """Make ``isinstance(value, datetime)`` in a consumer still accept real datetimes."""

    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, _RealDatetime)

    def __subclasscheck__(cls, sub: type) -> bool:
        return issubclass(sub, _RealDatetime)


def _instant(now: datetime, tz: tzinfo | None) -> datetime:
    """Return ``now`` as seen from ``tz``; a naive ``now`` is read as UTC.

    With no ``tz`` the result is naive and carries ``now``'s own wall-clock fields.
    """
    instant = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    if tz is None:
        return instant.replace(tzinfo=None)
    return instant.astimezone(tz)


def fixed_datetime_class(now: datetime = FIXED_NOW) -> type[datetime]:
    """Return a ``datetime`` subclass whose ``now``, ``utcnow`` and ``today`` report ``now``."""

    class FixedDatetime(_RealDatetime, metaclass=_AcceptsRealDatetimes):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            return _instant(now, tz)

        @classmethod
        def utcnow(cls) -> datetime:
            return _instant(now, timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls) -> datetime:
            return _instant(now, None)

    return FixedDatetime


def freeze_datetime(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    now: datetime = FIXED_NOW,
    *,
    attr: str = "datetime",
) -> type[datetime]:
    """Make ``module``'s ``datetime`` name report ``now``, restored when the test ends.

    Patch the consumer module's own binding, never a dotted path that goes through a
    module's ``time`` attribute: that path is the ``time`` module itself and would
    freeze every other caller in the process.
    """
    target = getattr(module, attr)
    if not (isinstance(target, type) and issubclass(target, _RealDatetime)):
        raise TypeError(
            f"{module.__name__}.{attr} is {target!r}, not the datetime class; patch the name the module calls"
        )
    frozen = fixed_datetime_class(now)
    monkeypatch.setattr(module, attr, frozen)
    return frozen


def set_mtimes(files: Sequence[Path], *, newest: float = FIXED_EPOCH, spacing: float = 100.0) -> list[float]:
    """Give each file an explicit mtime, oldest first; the last file gets ``newest``.

    Set a time on every competing file, including the newer ones, so the ordering
    never depends on the order or speed in which the files were created.
    """
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    last = len(files) - 1
    stamps = [newest - spacing * (last - index) for index in range(len(files))]
    for path, stamp in zip(files, stamps):
        os.utime(path, (stamp, stamp))
    return stamps
