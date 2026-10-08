# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

import math
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


def _require_at_least(name: str, value: float, minimum: float, expectation: str) -> None:
    if value < minimum:
        raise ValueError(f"{name} must be {expectation}")


@dataclass
class WorkloadPhase:
    concurrency: int
    duration_seconds: float
    phase_name: str = ""
    roles: dict[str, int] | None = None


class WorkloadPattern(ABC):
    @abstractmethod
    def get_phases(self) -> list[WorkloadPhase]: ...

    @abstractmethod
    def get_concurrency_at(self, elapsed_seconds: float) -> int: ...

    @property
    @abstractmethod
    def total_duration(self) -> float: ...

    @property
    @abstractmethod
    def max_concurrency(self) -> int: ...

    def iter_phases(self) -> Iterator[WorkloadPhase]:
        yield from self.get_phases()


class SteadyPattern(WorkloadPattern):
    def __init__(self, concurrency: int, duration_seconds: float):
        if concurrency < 1:
            raise ValueError("concurrency must be at least 1")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")

        self._concurrency = concurrency
        self._duration = duration_seconds

    def get_phases(self) -> list[WorkloadPhase]:
        return [
            WorkloadPhase(
                concurrency=self._concurrency,
                duration_seconds=self._duration,
                phase_name="steady",
            )
        ]

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0 or elapsed_seconds > self._duration:
            return 0
        return self._concurrency

    @property
    def total_duration(self) -> float:
        return self._duration

    @property
    def max_concurrency(self) -> int:
        return self._concurrency


class BurstPattern(WorkloadPattern):
    def __init__(
        self,
        base_concurrency: int,
        burst_concurrency: int,
        burst_duration_seconds: float,
        quiet_duration_seconds: float,
        num_bursts: int,
    ):
        if base_concurrency < 1:
            raise ValueError("base_concurrency must be at least 1")
        if burst_concurrency < base_concurrency:
            raise ValueError("burst_concurrency must be >= base_concurrency")
        if burst_duration_seconds <= 0:
            raise ValueError("burst_duration_seconds must be positive")
        if quiet_duration_seconds < 0:
            raise ValueError("quiet_duration_seconds must be non-negative")
        if num_bursts < 1:
            raise ValueError("num_bursts must be at least 1")

        self._base = base_concurrency
        self._burst = burst_concurrency
        self._burst_duration = burst_duration_seconds
        self._quiet_duration = quiet_duration_seconds
        self._num_bursts = num_bursts

    def get_phases(self) -> list[WorkloadPhase]:
        phases = []
        for i in range(self._num_bursts):
            if i > 0 and self._quiet_duration > 0:
                phases.append(
                    WorkloadPhase(
                        concurrency=self._base,
                        duration_seconds=self._quiet_duration,
                        phase_name=f"quiet_{i}",
                    )
                )
            phases.append(
                WorkloadPhase(
                    concurrency=self._burst,
                    duration_seconds=self._burst_duration,
                    phase_name=f"burst_{i + 1}",
                )
            )
        return phases

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            return 0

        cycle_duration = self._burst_duration + self._quiet_duration
        total = self._num_bursts * self._burst_duration + (self._num_bursts - 1) * self._quiet_duration

        if elapsed_seconds >= total:
            return 0

        if elapsed_seconds < self._burst_duration:
            return self._burst

        remaining = elapsed_seconds - self._burst_duration
        cycle_index = int(remaining / cycle_duration) + 1

        if cycle_index >= self._num_bursts:
            (self._num_bursts - 1) * cycle_duration + self._burst_duration - cycle_duration
            if elapsed_seconds >= total - self._burst_duration:
                return self._burst
            return self._base

        position_in_cycle = remaining % cycle_duration
        if position_in_cycle < self._quiet_duration:
            return self._base
        return self._burst

    @property
    def total_duration(self) -> float:
        return self._num_bursts * self._burst_duration + (self._num_bursts - 1) * self._quiet_duration

    @property
    def max_concurrency(self) -> int:
        return self._burst


class RampUpPattern(WorkloadPattern):
    def __init__(
        self,
        start_concurrency: int,
        end_concurrency: int,
        ramp_duration_seconds: float,
        step_count: int | None = None,
        hold_duration_seconds: float = 0,
    ):
        if start_concurrency < 1:
            raise ValueError("start_concurrency must be at least 1")
        if end_concurrency < start_concurrency:
            raise ValueError("end_concurrency must be >= start_concurrency")
        if ramp_duration_seconds <= 0:
            raise ValueError("ramp_duration_seconds must be positive")
        if step_count is not None and step_count < 1:
            raise ValueError("step_count must be at least 1 if provided")
        if hold_duration_seconds < 0:
            raise ValueError("hold_duration_seconds must be non-negative")

        self._start = start_concurrency
        self._end = end_concurrency
        self._ramp_duration = ramp_duration_seconds
        self._step_count = step_count
        self._hold_duration = hold_duration_seconds

    def get_phases(self) -> list[WorkloadPhase]:
        if self._step_count is None:
            return [
                WorkloadPhase(
                    concurrency=self._end,
                    duration_seconds=self._ramp_duration + self._hold_duration,
                    phase_name="ramp_up",
                )
            ]

        phases = []
        concurrency_step = (self._end - self._start) / self._step_count
        time_per_step = self._ramp_duration / self._step_count

        for i in range(self._step_count):
            concurrency = self._start + int(concurrency_step * i)
            duration = time_per_step + (self._hold_duration if i == self._step_count - 1 else 0)
            phases.append(
                WorkloadPhase(
                    concurrency=concurrency,
                    duration_seconds=duration,
                    phase_name=f"step_{i + 1}",
                )
            )

        if phases[-1].concurrency != self._end:
            phases.append(
                WorkloadPhase(
                    concurrency=self._end,
                    duration_seconds=self._hold_duration,
                    phase_name="peak",
                )
            )

        return phases

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            return 0
        if elapsed_seconds >= self._ramp_duration + self._hold_duration:
            return 0

        if elapsed_seconds >= self._ramp_duration:
            return self._end

        if self._step_count is None:
            progress = elapsed_seconds / self._ramp_duration
            return self._start + int((self._end - self._start) * progress)

        time_per_step = self._ramp_duration / self._step_count
        step_index = min(int(elapsed_seconds / time_per_step), self._step_count - 1)
        concurrency_step = (self._end - self._start) / self._step_count
        return self._start + int(concurrency_step * step_index)

    @property
    def total_duration(self) -> float:
        return self._ramp_duration + self._hold_duration

    @property
    def max_concurrency(self) -> int:
        return self._end


class SpikePattern(WorkloadPattern):
    def __init__(
        self,
        baseline_concurrency: int,
        spike_concurrency: int,
        pre_spike_duration_seconds: float,
        spike_duration_seconds: float,
        post_spike_duration_seconds: float,
    ):
        if baseline_concurrency < 1:
            raise ValueError("baseline_concurrency must be at least 1")
        if spike_concurrency < baseline_concurrency:
            raise ValueError("spike_concurrency must be >= baseline_concurrency")
        if pre_spike_duration_seconds < 0:
            raise ValueError("pre_spike_duration_seconds must be non-negative")
        if spike_duration_seconds <= 0:
            raise ValueError("spike_duration_seconds must be positive")
        if post_spike_duration_seconds < 0:
            raise ValueError("post_spike_duration_seconds must be non-negative")

        self._baseline = baseline_concurrency
        self._spike = spike_concurrency
        self._pre_duration = pre_spike_duration_seconds
        self._spike_duration = spike_duration_seconds
        self._post_duration = post_spike_duration_seconds

    def get_phases(self) -> list[WorkloadPhase]:
        phases = []
        if self._pre_duration > 0:
            phases.append(
                WorkloadPhase(
                    concurrency=self._baseline,
                    duration_seconds=self._pre_duration,
                    phase_name="pre_spike",
                )
            )
        phases.append(
            WorkloadPhase(
                concurrency=self._spike,
                duration_seconds=self._spike_duration,
                phase_name="spike",
            )
        )
        if self._post_duration > 0:
            phases.append(
                WorkloadPhase(
                    concurrency=self._baseline,
                    duration_seconds=self._post_duration,
                    phase_name="post_spike",
                )
            )
        return phases

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            return 0

        total = self._pre_duration + self._spike_duration + self._post_duration
        if elapsed_seconds >= total:
            return 0

        if elapsed_seconds < self._pre_duration:
            return self._baseline
        if elapsed_seconds < self._pre_duration + self._spike_duration:
            return self._spike
        return self._baseline

    @property
    def total_duration(self) -> float:
        return self._pre_duration + self._spike_duration + self._post_duration

    @property
    def max_concurrency(self) -> int:
        return self._spike


class StepPattern(WorkloadPattern):
    def __init__(self, steps: list[tuple[int, float]]):
        if not steps:
            raise ValueError("steps list cannot be empty")

        for i, (concurrency, duration) in enumerate(steps):
            if concurrency < 1:
                raise ValueError(f"step {i}: concurrency must be at least 1")
            if duration <= 0:
                raise ValueError(f"step {i}: duration must be positive")

        self._steps = steps

    def get_phases(self) -> list[WorkloadPhase]:
        return [
            WorkloadPhase(
                concurrency=concurrency,
                duration_seconds=duration,
                phase_name=f"step_{i + 1}",
            )
            for i, (concurrency, duration) in enumerate(self._steps)
        ]

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            return 0

        cumulative = 0.0
        for concurrency, duration in self._steps:
            if elapsed_seconds < cumulative + duration:
                return concurrency
            cumulative += duration

        return 0

    @property
    def total_duration(self) -> float:
        return sum(duration for _, duration in self._steps)

    @property
    def max_concurrency(self) -> int:
        return max(concurrency for concurrency, _ in self._steps)


class WavePattern(WorkloadPattern):
    def __init__(
        self,
        min_concurrency: int,
        max_concurrency: int,
        period_seconds: float,
        num_periods: int = 1,
    ):
        _require_at_least("min_concurrency", min_concurrency, 1, "at least 1")
        if max_concurrency < min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")
        _require_at_least("num_periods", num_periods, 1, "at least 1")

        self._min = min_concurrency
        self._max = max_concurrency
        self._period = period_seconds
        self._num_periods = num_periods

    def get_phases(self) -> list[WorkloadPhase]:
        return [
            WorkloadPhase(
                concurrency=self._max,
                duration_seconds=self._period * self._num_periods,
                phase_name="wave",
            )
        ]

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            return 0
        if elapsed_seconds >= self._period * self._num_periods:
            return 0

        amplitude = (self._max - self._min) / 2
        midpoint = (self._max + self._min) / 2

        position = (elapsed_seconds / self._period) * 2 * math.pi
        value = midpoint - amplitude * math.cos(position)

        return max(self._min, min(self._max, int(round(value))))

    @property
    def total_duration(self) -> float:
        return self._period * self._num_periods

    @property
    def max_concurrency(self) -> int:
        return self._max


class MultiWriterPattern(WorkloadPattern):
    def __init__(
        self,
        writers: int,
        readers: int,
        duration_seconds: float,
        drain_seconds: float = 5.0,
    ) -> None:
        _require_at_least("writers", writers, 1, "at least 1")
        _require_at_least("readers", readers, 1, "at least 1")
        if duration_seconds <= 0:
            raise ValueError("duration_seconds must be positive")
        _require_at_least("drain_seconds", drain_seconds, 0, "non-negative")

        self._writers = writers
        self._readers = readers
        self._duration = duration_seconds
        self._drain = drain_seconds

    def get_phases(self) -> list[WorkloadPhase]:
        phases = [
            WorkloadPhase(
                concurrency=self._writers + self._readers,
                duration_seconds=self._duration,
                phase_name="read-write",
                roles={"writer": self._writers, "reader": self._readers},
            )
        ]
        if self._drain > 0:
            phases.append(
                WorkloadPhase(
                    concurrency=self._writers,
                    duration_seconds=self._drain,
                    phase_name="write-drain",
                    roles={"writer": self._writers},
                )
            )
        return phases

    def writers_in_phase(self, phase_name: str) -> int:
        if phase_name == "read-write":
            return self._writers
        if phase_name == "write-drain":
            if self._drain <= 0:
                raise ValueError("write-drain phase is absent when drain_seconds is 0")
            return self._writers
        raise ValueError(f"unknown MultiWriterPattern phase: {phase_name!r}")

    def readers_in_phase(self, phase_name: str) -> int:
        if phase_name == "read-write":
            return self._readers
        if phase_name == "write-drain":
            if self._drain <= 0:
                raise ValueError("write-drain phase is absent when drain_seconds is 0")
            return 0
        raise ValueError(f"unknown MultiWriterPattern phase: {phase_name!r}")

    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        if elapsed_seconds < 0:
            return 0
        if elapsed_seconds <= self._duration:
            return self._writers + self._readers
        if elapsed_seconds <= self._duration + self._drain:
            return self._writers
        return 0

    @property
    def total_duration(self) -> float:
        return self._duration + self._drain

    @property
    def max_concurrency(self) -> int:
        return self._writers + self._readers

    @property
    def writer_count(self) -> int:
        return self._writers

    @property
    def reader_count(self) -> int:
        return self._readers
