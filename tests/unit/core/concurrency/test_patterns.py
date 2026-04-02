"""Tests for workload patterns module.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.experimental.concurrency.patterns import (
    BurstPattern,
    RampUpPattern,
    SpikePattern,
    SteadyPattern,
    StepPattern,
    WavePattern,
    WorkloadPhase,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSteadyPattern:
    """Tests for SteadyPattern."""

    def test_basic_configuration(self):
        """Should create steady pattern with specified concurrency and duration."""
        pattern = SteadyPattern(concurrency=10, duration_seconds=60)
        assert pattern.max_concurrency == 10
        assert pattern.total_duration == 60

    def test_single_phase(self):
        """Should produce a single phase."""
        pattern = SteadyPattern(concurrency=5, duration_seconds=30)
        phases = pattern.get_phases()
        assert len(phases) == 1
        assert phases[0].concurrency == 5
        assert phases[0].duration_seconds == 30
        assert phases[0].phase_name == "steady"

    def test_concurrency_at_time(self):
        """Should return constant concurrency within duration."""
        pattern = SteadyPattern(concurrency=10, duration_seconds=60)
        assert pattern.get_concurrency_at(0) == 10
        assert pattern.get_concurrency_at(30) == 10
        assert pattern.get_concurrency_at(60) == 10
        assert pattern.get_concurrency_at(61) == 0
        assert pattern.get_concurrency_at(-1) == 0

    def test_invalid_concurrency(self):
        """Should reject invalid concurrency."""
        with pytest.raises(ValueError, match="must be at least 1"):
            SteadyPattern(concurrency=0, duration_seconds=60)
        with pytest.raises(ValueError, match="must be at least 1"):
            SteadyPattern(concurrency=-1, duration_seconds=60)

    def test_invalid_duration(self):
        """Should reject invalid duration."""
        with pytest.raises(ValueError, match="must be positive"):
            SteadyPattern(concurrency=10, duration_seconds=0)
        with pytest.raises(ValueError, match="must be positive"):
            SteadyPattern(concurrency=10, duration_seconds=-10)


class TestBurstPattern:
    """Tests for BurstPattern."""

    def test_basic_configuration(self):
        """Should create burst pattern with correct parameters."""
        pattern = BurstPattern(
            base_concurrency=2,
            burst_concurrency=20,
            burst_duration_seconds=5,
            quiet_duration_seconds=10,
            num_bursts=3,
        )
        assert pattern.max_concurrency == 20

    def test_total_duration(self):
        """Should calculate correct total duration."""
        pattern = BurstPattern(
            base_concurrency=2,
            burst_concurrency=20,
            burst_duration_seconds=5,
            quiet_duration_seconds=10,
            num_bursts=3,
        )
        # 3 bursts of 5s + 2 quiet periods of 10s
        assert pattern.total_duration == 35

    def test_phases(self):
        """Should generate correct phases."""
        pattern = BurstPattern(
            base_concurrency=1,
            burst_concurrency=10,
            burst_duration_seconds=5,
            quiet_duration_seconds=5,
            num_bursts=2,
        )
        phases = pattern.get_phases()
        assert len(phases) == 3  # burst1, quiet, burst2
        assert phases[0].concurrency == 10
        assert phases[1].concurrency == 1
        assert phases[2].concurrency == 10

    def test_concurrency_at_time(self):
        """Should return correct concurrency during bursts and quiet periods."""
        pattern = BurstPattern(
            base_concurrency=1,
            burst_concurrency=10,
            burst_duration_seconds=5,
            quiet_duration_seconds=5,
            num_bursts=2,
        )
        # First burst: 0-5
        assert pattern.get_concurrency_at(2) == 10
        # Quiet: 5-10
        assert pattern.get_concurrency_at(7) == 1
        # Second burst: 10-15
        assert pattern.get_concurrency_at(12) == 10

    def test_invalid_parameters(self):
        """Should reject invalid parameters."""
        with pytest.raises(ValueError, match="base_concurrency"):
            BurstPattern(0, 10, 5, 5, 2)
        with pytest.raises(ValueError, match="burst_concurrency"):
            BurstPattern(10, 5, 5, 5, 2)  # burst < base
        with pytest.raises(ValueError, match="num_bursts"):
            BurstPattern(1, 10, 5, 5, 0)


class TestRampUpPattern:
    """Tests for RampUpPattern."""

    def test_basic_configuration(self):
        """Should create ramp pattern with correct parameters."""
        pattern = RampUpPattern(
            start_concurrency=1,
            end_concurrency=100,
            ramp_duration_seconds=60,
        )
        assert pattern.max_concurrency == 100
        assert pattern.total_duration == 60

    def test_with_hold_duration(self):
        """Should add hold duration to total."""
        pattern = RampUpPattern(
            start_concurrency=1,
            end_concurrency=10,
            ramp_duration_seconds=30,
            hold_duration_seconds=10,
        )
        assert pattern.total_duration == 40

    def test_smooth_ramp_concurrency(self):
        """Should interpolate concurrency smoothly."""
        pattern = RampUpPattern(
            start_concurrency=1,
            end_concurrency=101,
            ramp_duration_seconds=100,
        )
        assert pattern.get_concurrency_at(0) == 1
        assert pattern.get_concurrency_at(50) == 51
        # At ramp end, concurrency is at max
        assert pattern.get_concurrency_at(99.9) == 100

    def test_stepped_ramp(self):
        """Should produce discrete steps when step_count specified."""
        pattern = RampUpPattern(
            start_concurrency=1,
            end_concurrency=11,
            ramp_duration_seconds=10,
            step_count=5,
        )
        # Each step covers 2 seconds, increases by 2
        assert pattern.get_concurrency_at(0) == 1
        assert pattern.get_concurrency_at(2) == 3
        assert pattern.get_concurrency_at(4) == 5

    def test_invalid_parameters(self):
        """Should reject invalid parameters."""
        with pytest.raises(ValueError, match="start_concurrency"):
            RampUpPattern(0, 10, 60)
        with pytest.raises(ValueError, match="end_concurrency"):
            RampUpPattern(10, 5, 60)  # end < start
        with pytest.raises(ValueError, match="step_count"):
            RampUpPattern(1, 10, 60, step_count=0)


class TestSpikePattern:
    """Tests for SpikePattern."""

    def test_basic_configuration(self):
        """Should create spike pattern correctly."""
        pattern = SpikePattern(
            baseline_concurrency=5,
            spike_concurrency=50,
            pre_spike_duration_seconds=10,
            spike_duration_seconds=5,
            post_spike_duration_seconds=10,
        )
        assert pattern.max_concurrency == 50
        assert pattern.total_duration == 25

    def test_phases(self):
        """Should produce three phases."""
        pattern = SpikePattern(
            baseline_concurrency=1,
            spike_concurrency=10,
            pre_spike_duration_seconds=5,
            spike_duration_seconds=3,
            post_spike_duration_seconds=5,
        )
        phases = pattern.get_phases()
        assert len(phases) == 3
        assert phases[0].phase_name == "pre_spike"
        assert phases[1].phase_name == "spike"
        assert phases[2].phase_name == "post_spike"

    def test_concurrency_at_time(self):
        """Should return correct concurrency at each phase."""
        pattern = SpikePattern(
            baseline_concurrency=1,
            spike_concurrency=10,
            pre_spike_duration_seconds=5,
            spike_duration_seconds=3,
            post_spike_duration_seconds=5,
        )
        assert pattern.get_concurrency_at(2) == 1  # pre-spike
        assert pattern.get_concurrency_at(6) == 10  # spike
        assert pattern.get_concurrency_at(10) == 1  # post-spike

    def test_no_pre_spike(self):
        """Should handle zero pre-spike duration."""
        pattern = SpikePattern(
            baseline_concurrency=1,
            spike_concurrency=10,
            pre_spike_duration_seconds=0,
            spike_duration_seconds=5,
            post_spike_duration_seconds=5,
        )
        phases = pattern.get_phases()
        assert len(phases) == 2
        assert phases[0].phase_name == "spike"


class TestStepPattern:
    """Tests for StepPattern."""

    def test_basic_configuration(self):
        """Should create step pattern from tuples."""
        pattern = StepPattern([(5, 10), (10, 10), (15, 10)])
        assert pattern.max_concurrency == 15
        assert pattern.total_duration == 30

    def test_phases(self):
        """Should produce correct phases."""
        pattern = StepPattern([(1, 5), (5, 5), (10, 5)])
        phases = pattern.get_phases()
        assert len(phases) == 3
        assert phases[0].concurrency == 1
        assert phases[1].concurrency == 5
        assert phases[2].concurrency == 10

    def test_concurrency_at_time(self):
        """Should return correct concurrency at each step."""
        pattern = StepPattern([(1, 10), (5, 10), (10, 10)])
        assert pattern.get_concurrency_at(5) == 1
        assert pattern.get_concurrency_at(15) == 5
        assert pattern.get_concurrency_at(25) == 10
        assert pattern.get_concurrency_at(30) == 0  # After end

    def test_empty_steps(self):
        """Should reject empty steps list."""
        with pytest.raises(ValueError, match="cannot be empty"):
            StepPattern([])

    def test_invalid_step(self):
        """Should reject invalid step values."""
        with pytest.raises(ValueError, match="concurrency must be at least 1"):
            StepPattern([(0, 10)])
        with pytest.raises(ValueError, match="duration must be positive"):
            StepPattern([(5, 0)])


class TestWavePattern:
    """Tests for WavePattern."""

    def test_basic_configuration(self):
        """Should create wave pattern correctly."""
        pattern = WavePattern(
            min_concurrency=1,
            max_concurrency=10,
            period_seconds=60,
            num_periods=2,
        )
        assert pattern.max_concurrency == 10
        assert pattern.total_duration == 120

    def test_concurrency_oscillation(self):
        """Should oscillate between min and max."""
        pattern = WavePattern(
            min_concurrency=1,
            max_concurrency=11,
            period_seconds=4,
            num_periods=1,
        )
        # Starts at min, peaks at period/2
        assert pattern.get_concurrency_at(0) == 1
        assert pattern.get_concurrency_at(2) == 11  # Peak at half period
        # Just before end of period, back near min
        assert pattern.get_concurrency_at(3.9) <= 2

    def test_single_phase(self):
        """Should produce single phase for resource estimation."""
        pattern = WavePattern(
            min_concurrency=1,
            max_concurrency=10,
            period_seconds=30,
        )
        phases = pattern.get_phases()
        assert len(phases) == 1
        assert phases[0].concurrency == 10  # Max for resource estimation

    def test_invalid_parameters(self):
        """Should reject invalid parameters."""
        with pytest.raises(ValueError, match="min_concurrency"):
            WavePattern(0, 10, 60)
        with pytest.raises(ValueError, match="max_concurrency"):
            WavePattern(10, 5, 60)  # max < min
        with pytest.raises(ValueError, match="period_seconds"):
            WavePattern(1, 10, 0)
        with pytest.raises(ValueError, match="num_periods"):
            WavePattern(1, 10, 60, num_periods=0)


class TestWorkloadPhase:
    """Tests for WorkloadPhase dataclass."""

    def test_basic_creation(self):
        """Should create phase with basic attributes."""
        phase = WorkloadPhase(concurrency=10, duration_seconds=30, phase_name="test")
        assert phase.concurrency == 10
        assert phase.duration_seconds == 30
        assert phase.phase_name == "test"

    def test_default_phase_name(self):
        """Should default phase_name to empty string."""
        phase = WorkloadPhase(concurrency=5, duration_seconds=10)
        assert phase.phase_name == ""


class TestPatternIteration:
    """Tests for pattern iteration capabilities."""

    def test_iter_phases(self):
        """Should iterate over phases."""
        pattern = StepPattern([(1, 5), (5, 5)])
        phases = list(pattern.iter_phases())
        assert len(phases) == 2

    def test_phases_are_workload_phase(self):
        """All patterns should return WorkloadPhase objects."""
        patterns = [
            SteadyPattern(5, 10),
            BurstPattern(1, 10, 5, 5, 2),
            RampUpPattern(1, 10, 30),
            SpikePattern(1, 10, 5, 5, 5),
            StepPattern([(1, 5), (5, 5)]),
            WavePattern(1, 10, 30),
        ]
        for pattern in patterns:
            for phase in pattern.get_phases():
                assert isinstance(phase, WorkloadPhase)
