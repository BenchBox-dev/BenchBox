from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Iterator


def mono_time() -> float:

    return perf_counter()


def elapsed_seconds(start: float, end: float | None = None) -> float:

    end_time = mono_time() if end is None else end
    return end_time - start


def utc_now() -> datetime:

    return datetime.now(timezone.utc)


@dataclass
class Stopwatch:
    start_mono: float
    start_utc: datetime

    @classmethod
    def start(cls) -> Stopwatch:

        return cls(start_mono=mono_time(), start_utc=utc_now())

    def elapsed_seconds(self) -> float:

        return elapsed_seconds(self.start_mono)

    def elapsed_ms(self) -> float:

        return self.elapsed_seconds() * 1000.0

    def finish(self) -> tuple[datetime, float]:

        return utc_now(), self.elapsed_seconds()


@contextmanager
def measure_elapsed() -> Iterator[Stopwatch]:

    stopwatch = Stopwatch.start()
    yield stopwatch
