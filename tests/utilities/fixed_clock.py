# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

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
    def __instancecheck__(cls, obj: object) -> bool:
        return isinstance(obj, _RealDatetime)

    def __subclasscheck__(cls, sub: type) -> bool:
        return issubclass(sub, _RealDatetime)


def _instant(now: datetime, tz: tzinfo | None) -> datetime:
    instant = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    if tz is None:
        return instant.replace(tzinfo=None)
    return instant.astimezone(tz)


def fixed_datetime_class(now: datetime = FIXED_NOW) -> type[datetime]:

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
    target = getattr(module, attr)
    if not (isinstance(target, type) and issubclass(target, _RealDatetime)):
        raise TypeError(
            f"{module.__name__}.{attr} is {target!r}, not the datetime class; patch the name the module calls"
        )
    frozen = fixed_datetime_class(now)
    monkeypatch.setattr(module, attr, frozen)
    return frozen


def set_mtimes(files: Sequence[Path], *, newest: float = FIXED_EPOCH, spacing: float = 100.0) -> list[float]:
    if spacing <= 0:
        raise ValueError("spacing must be positive")
    last = len(files) - 1
    stamps = [newest - spacing * (last - index) for index in range(len(files))]
    for path, stamp in zip(files, stamps):
        os.utime(path, (stamp, stamp))
    return stamps
