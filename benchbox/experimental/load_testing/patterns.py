"""Workload patterns for concurrent load testing.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import math
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass


@dataclass
class WorkloadPhase:
    """A phase in the workload pattern."""

    concurrency: int
    duration_seconds: float
    phase_name: str = ""


class WorkloadPattern(ABC):
    """Base class for workload patterns.

    Workload patterns define how concurrency changes over time during a test.
    """

    @abstractmethod
    def get_phases(self) -> list[WorkloadPhase]:
        """Get all phases in this workload pattern."""
        ...

    @abstractmethod
    def get_concurrency_at(self, elapsed_seconds: float) -> int:
        """Get target concurrency at a given point in time."""
        ...

    @property
    @abstractmethod
    def total_duration(self) -> float:
        """Total duration of the workload pattern in seconds."""
        ...

    @property
    @abstractmethod
    def max_concurrency(self) -> int:
        """Maximum concurrency level in this pattern."""
        ...

    def iter_phases(self) -> Iterator[WorkloadPhase]:
        """Iterate over phases."""
        yield from self.get_phases()


class SteadyPattern(WorkloadPattern):
    """Steady load pattern - constant concurrency throughout.

    Useful for baseline performance measurement and sustained load testing.
    """

    def __init__(self, concurrency: int, duration_seconds: float):
        """Initialize steady pattern.

        Args:
            concurrency: Number of concurrent streams
            duration_seconds: Duration to maintain the load
        """
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
    """Burst load pattern - alternating between low and high load.

    Useful for testing how systems handle sudden load increases and
    recover during quiet periods.
    """

    def __init__(
        self,
        base_concurrency: int,
        burst_concurrency: int,
        burst_duration_seconds: float,
        quiet_duration_seconds: float,
        num_bursts: int,
    ):
        """Initialize burst pattern.

        Args:
            base_concurrency: Concurrency during quiet periods
            burst_concurrency: Concurrency during burst periods
            burst_duration_seconds: Duration of each burst
            quiet_duration_seconds: Duration between bursts
            num_bursts: Number of burst cycles
        """
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
            # Quiet period (except before first burst)
            if i > 0 and self._quiet_duration > 0:
                phases.append(
                    WorkloadPhase(
                        concurrency=self._base,
                        duration_seconds=self._quiet_duration,
                        phase_name=f"quiet_{i}",
                    )
                )
            # Burst period
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

        # First burst has no quiet period before it
        if elapsed_seconds < self._burst_duration:
            return self._burst

        # Subsequent cycles
        remaining = elapsed_seconds - self._burst_duration
        cycle_index = int(remaining / cycle_duration) + 1

        if cycle_index >= self._num_bursts:
            # Check if in last burst
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
    """Ramp-up load pattern - gradually increasing concurrency.

    Useful for finding the breaking point of a system and understanding
    how performance degrades under increasing load.
    """

    def __init__(
        self,
        start_concurrency: int,
        end_concurrency: int,
        ramp_duration_seconds: float,
        step_count: int | None = None,
        hold_duration_seconds: float = 0,
    ):
        """Initialize ramp-up pattern.

        Args:
            start_concurrency: Starting concurrency level
            end_concurrency: Target concurrency level
            ramp_duration_seconds: Duration of the ramp-up period
            step_count: Number of discrete steps (None for smooth ramp)
            hold_duration_seconds: Duration to hold at each step
        """
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
            # Smooth ramp - single phase with interpolated concurrency
            return [
                WorkloadPhase(
                    concurrency=self._end,  # Max for resource estimation
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

        # Final step at end concurrency
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
            # Smooth interpolation
            progress = elapsed_seconds / self._ramp_duration
            return self._start + int((self._end - self._start) * progress)

        # Stepped ramp
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
    """Spike load pattern - sudden high load followed by return to baseline.

    Useful for testing system resilience to sudden load spikes
    and recovery behavior.
    """

    def __init__(
        self,
        baseline_concurrency: int,
        spike_concurrency: int,
        pre_spike_duration_seconds: float,
        spike_duration_seconds: float,
        post_spike_duration_seconds: float,
    ):
        """Initialize spike pattern.

        Args:
            baseline_concurrency: Normal concurrency level
            spike_concurrency: Spike concurrency level
            pre_spike_duration_seconds: Duration before the spike
            spike_duration_seconds: Duration of the spike
            post_spike_duration_seconds: Duration after the spike (recovery)
        """
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
    """Step load pattern - discrete concurrency levels held for fixed durations.

    Useful for systematic load testing at specific concurrency levels
    to gather metrics at each level.
    """

    def __init__(self, steps: list[tuple[int, float]]):
        """Initialize step pattern.

        Args:
            steps: List of (concurrency, duration_seconds) tuples
        """
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
    """Sinusoidal wave pattern - smooth oscillation between min and max concurrency.

    Useful for testing behavior under gradually changing load,
    simulating natural usage patterns.
    """

    def __init__(
        self,
        min_concurrency: int,
        max_concurrency: int,
        period_seconds: float,
        num_periods: int = 1,
    ):
        """Initialize wave pattern.

        Args:
            min_concurrency: Minimum concurrency level
            max_concurrency: Maximum concurrency level
            period_seconds: Duration of one complete wave cycle
            num_periods: Number of wave cycles to execute
        """
        if min_concurrency < 1:
            raise ValueError("min_concurrency must be at least 1")
        if max_concurrency < min_concurrency:
            raise ValueError("max_concurrency must be >= min_concurrency")
        if period_seconds <= 0:
            raise ValueError("period_seconds must be positive")
        if num_periods < 1:
            raise ValueError("num_periods must be at least 1")

        self._min = min_concurrency
        self._max = max_concurrency
        self._period = period_seconds
        self._num_periods = num_periods

    def get_phases(self) -> list[WorkloadPhase]:
        # Wave is continuous, represent as single phase with max for resource estimation
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

        # Sinusoidal oscillation: starts at min, peaks at max at period/2
        amplitude = (self._max - self._min) / 2
        midpoint = (self._max + self._min) / 2

        # Use cosine starting at -1 so we begin at min
        position = (elapsed_seconds / self._period) * 2 * math.pi
        value = midpoint - amplitude * math.cos(position)

        return max(self._min, min(self._max, int(round(value))))

    @property
    def total_duration(self) -> float:
        return self._period * self._num_periods

    @property
    def max_concurrency(self) -> int:
        return self._max
