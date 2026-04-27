"""Tests for TSBS DevOps data generator.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import csv
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from benchbox.core.tsbs_devops.generator import (
    ARCHITECTURES,
    DATACENTERS,
    DEFAULT_DURATION_DAYS,
    DEFAULT_HOSTS,
    DEFAULT_INTERVAL_SECONDS,
    ENVIRONMENTS,
    OS_TYPES,
    REGIONS,
    SERVICES,
    TEAMS,
    TSBSDevOpsDataGenerator,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGeneratorConfiguration:
    """Tests for generator initialization and configuration."""

    def test_default_configuration(self):
        """Should use default values when not specified."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(output_dir=tmpdir)
            assert gen.scale_factor == 1.0
            assert gen.num_hosts == DEFAULT_HOSTS
            assert gen.duration_days == DEFAULT_DURATION_DAYS
            assert gen.interval_seconds == DEFAULT_INTERVAL_SECONDS

    def test_scale_factor_affects_hosts(self):
        """Scale factor should affect number of hosts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(scale_factor=2.0, output_dir=tmpdir)
            assert gen.num_hosts == int(DEFAULT_HOSTS * 2.0)

    def test_duration_fixed_regardless_of_scale_factor(self):
        """Duration should be fixed at DEFAULT_DURATION_DAYS (only hosts scale)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(scale_factor=3.0, output_dir=tmpdir)
            assert gen.duration_days == DEFAULT_DURATION_DAYS

    def test_explicit_num_hosts_overrides_scale(self):
        """Explicit num_hosts should override scale factor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(scale_factor=10.0, num_hosts=50, output_dir=tmpdir)
            assert gen.num_hosts == 50

    def test_explicit_duration_overrides_scale(self):
        """Explicit duration should override scale factor."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(scale_factor=10.0, duration_days=5, output_dir=tmpdir)
            assert gen.duration_days == 5

    def test_minimum_hosts(self):
        """Should have minimum 10 hosts even with tiny scale."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(scale_factor=0.001, output_dir=tmpdir)
            assert gen.num_hosts >= 10

    def test_custom_start_time(self, start_time):
        """Should use custom start time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(start_time=start_time, output_dir=tmpdir)
            assert gen.start_time == start_time

    def test_custom_interval(self):
        """Should use custom interval."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(interval_seconds=60, output_dir=tmpdir)
            assert gen.interval_seconds == 60

    def test_seed_for_reproducibility(self, seed):
        """Should accept seed for reproducibility."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(seed=seed, output_dir=tmpdir)
            assert gen.seed == seed


class TestHostMetadataGeneration:
    """Tests for host metadata generation."""

    @pytest.fixture
    def generator(self, seed):
        """Create generator with fixed seed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(
                num_hosts=20,
                output_dir=tmpdir,
                seed=seed,
            )
            yield gen

    def test_generates_correct_number_of_hosts(self, generator):
        """Should generate specified number of hosts."""
        assert len(generator.hosts) == 20

    def test_hostname_format(self, generator):
        """Hostnames should follow format 'host_N'."""
        for i, host in enumerate(generator.hosts):
            assert host["hostname"] == f"host_{i}"

    def test_regions_are_distributed(self, generator):
        """Regions should be distributed round-robin."""
        for i, host in enumerate(generator.hosts):
            expected_region = REGIONS[i % len(REGIONS)]
            assert host["region"] == expected_region

    def test_datacenters_are_distributed(self, generator):
        """Datacenters should be distributed round-robin."""
        for i, host in enumerate(generator.hosts):
            expected_dc = DATACENTERS[i % len(DATACENTERS)]
            assert host["datacenter"] == expected_dc

    def test_os_is_from_valid_set(self, generator):
        """OS should be from valid OS types."""
        for host in generator.hosts:
            assert host["os"] in OS_TYPES

    def test_arch_is_from_valid_set(self, generator):
        """Architecture should be from valid set."""
        for host in generator.hosts:
            assert host["arch"] in ARCHITECTURES

    def test_team_is_from_valid_set(self, generator):
        """Team should be from valid set."""
        for host in generator.hosts:
            assert host["team"] in TEAMS

    def test_service_is_from_valid_set(self, generator):
        """Service should be from valid set."""
        for host in generator.hosts:
            assert host["service"] in SERVICES

    def test_service_version_format(self, generator):
        """Service version should follow semver-like format."""
        for host in generator.hosts:
            version = host["service_version"]
            parts = version.split(".")
            assert len(parts) == 3
            assert parts[0] == "1"
            assert parts[1].isdigit()
            assert parts[2].isdigit()

    def test_environment_is_from_valid_set(self, generator):
        """Environment should be from valid set."""
        for host in generator.hosts:
            assert host["service_environment"] in ENVIRONMENTS


class TestDataGeneration:
    """Tests for data file generation."""

    @pytest.fixture
    def small_generator(self, seed, start_time):
        """Create generator with minimal settings for fast tests."""
        tmpdir = tempfile.mkdtemp()
        gen = TSBSDevOpsDataGenerator(
            num_hosts=3,
            duration_days=1,
            interval_seconds=3600,  # 1 hour = 24 points per day
            output_dir=tmpdir,
            start_time=start_time,
            seed=seed,
            force_regenerate=True,
        )
        yield gen
        # Cleanup
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_generate_returns_table_files(self, small_generator):
        """generate() should return dict of table paths."""
        result = small_generator.generate()
        assert isinstance(result, dict)
        assert set(result.keys()) == {"tags", "cpu", "mem", "disk", "net"}

    def test_generate_creates_files(self, small_generator):
        """generate() should create actual files."""
        result = small_generator.generate()
        for table_name, path in result.items():
            assert Path(path).exists(), f"File for {table_name} not created"

    def test_tags_csv_content(self, small_generator):
        """Tags CSV should have correct content."""
        result = small_generator.generate()
        tags_path = result["tags"]

        with open(tags_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 3  # 3 hosts
        assert rows[0]["hostname"] == "host_0"
        assert rows[1]["hostname"] == "host_1"
        assert rows[2]["hostname"] == "host_2"

    def test_cpu_csv_has_headers(self, small_generator):
        """CPU CSV should have correct headers."""
        result = small_generator.generate()

        with open(result["cpu"], newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            headers = next(reader)

        expected = [
            "time",
            "hostname",
            "usage_user",
            "usage_system",
            "usage_idle",
            "usage_nice",
            "usage_iowait",
            "usage_irq",
            "usage_softirq",
            "usage_steal",
            "usage_guest",
            "usage_guest_nice",
        ]
        assert headers == expected

    def test_cpu_csv_row_count(self, small_generator):
        """CPU CSV should have correct number of rows."""
        result = small_generator.generate()

        with open(result["cpu"], newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            rows = list(reader)

        # 3 hosts * 24 hours = 72 rows
        assert len(rows) == 72

    def test_cpu_values_in_range(self, small_generator):
        """CPU usage values should be in valid range [0, 100]."""
        result = small_generator.generate()

        with open(result["cpu"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for col in ["usage_user", "usage_system", "usage_idle"]:
                    value = float(row[col])
                    assert 0 <= value <= 100, f"{col} out of range: {value}"

    def test_mem_csv_content(self, small_generator):
        """Memory CSV should have valid content."""
        result = small_generator.generate()

        with open(result["mem"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # 3 hosts * 24 hours = 72 rows
        assert len(rows) == 72

        # Check first row values are valid
        row = rows[0]
        total = int(row["total"])
        used = int(row["used"])
        free = int(row["free"])

        assert total > 0
        assert used >= 0
        assert free >= 0
        # Memory accounting should be reasonable
        assert used + free <= total * 1.1  # Allow some slack for cached/buffered

    def test_disk_csv_has_device_column(self, small_generator):
        """Disk CSV should include device column."""
        result = small_generator.generate()

        with open(result["disk"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert "device" in row
        assert row["device"] in ["sda", "sdb"]

    def test_disk_csv_row_count(self, small_generator):
        """Disk CSV should have rows for each host * device * timestamp."""
        result = small_generator.generate()

        with open(result["disk"], newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            rows = list(reader)

        # 3 hosts * 2 devices * 24 hours = 144 rows
        assert len(rows) == 144

    def test_net_csv_has_interface_column(self, small_generator):
        """Network CSV should include interface column."""
        result = small_generator.generate()

        with open(result["net"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)

        assert "interface" in row
        assert row["interface"] in ["eth0", "lo"]

    def test_net_csv_row_count(self, small_generator):
        """Network CSV should have rows for each host * interface * timestamp."""
        result = small_generator.generate()

        with open(result["net"], newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            rows = list(reader)

        # 3 hosts * 2 interfaces * 24 hours = 144 rows
        assert len(rows) == 144


class TestDataPatterns:
    """Tests for realistic data patterns."""

    @pytest.fixture
    def generator(self, seed, start_time):
        """Create generator for pattern tests."""
        tmpdir = tempfile.mkdtemp()
        gen = TSBSDevOpsDataGenerator(
            num_hosts=1,
            duration_days=1,
            interval_seconds=3600,
            output_dir=tmpdir,
            start_time=start_time,
            seed=seed,
            force_regenerate=True,
        )
        yield gen
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)

    def test_timestamps_are_chronological(self, generator):
        """Timestamps should increase chronologically."""
        result = generator.generate()

        with open(result["cpu"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            prev_time = None
            for row in reader:
                curr_time = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
                if prev_time:
                    assert curr_time > prev_time
                prev_time = curr_time

    def test_cumulative_counters_increase(self, generator):
        """Cumulative counters should only increase within each host-device group."""
        result = generator.generate()

        with open(result["disk"], newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            # Track previous reads per (hostname, device) combination
            prev_reads_by_key: dict[tuple[str, str], int] = {}
            for row in reader:
                key = (row["hostname"], row["device"])
                curr_reads = int(row["reads_completed"])
                if key in prev_reads_by_key:
                    assert curr_reads >= prev_reads_by_key[key], (
                        f"Reads decreased for {key}: {prev_reads_by_key[key]} -> {curr_reads}"
                    )
                prev_reads_by_key[key] = curr_reads


class TestGenerationStats:
    """Tests for get_generation_stats."""

    def test_stats_structure(self, seed):
        """Stats should have expected structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(
                num_hosts=10,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                seed=seed,
            )
            stats = gen.get_generation_stats()

        assert "num_hosts" in stats
        assert "duration_days" in stats
        assert "interval_seconds" in stats
        assert "num_timestamps" in stats
        assert "rows" in stats
        assert "total_rows" in stats

    def test_stats_row_counts(self, seed):
        """Stats should have correct row counts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(
                num_hosts=10,
                duration_days=1,
                interval_seconds=3600,  # 24 timestamps
                output_dir=tmpdir,
                seed=seed,
            )
            stats = gen.get_generation_stats()

        assert stats["num_hosts"] == 10
        assert stats["num_timestamps"] == 24
        assert stats["rows"]["tags"] == 10
        assert stats["rows"]["cpu"] == 10 * 24  # hosts * timestamps
        assert stats["rows"]["mem"] == 10 * 24
        assert stats["rows"]["disk"] == 10 * 2 * 24  # hosts * devices * timestamps
        assert stats["rows"]["net"] == 10 * 2 * 24  # hosts * interfaces * timestamps

    def test_total_rows_is_sum(self, seed):
        """Total rows should be sum of all tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen = TSBSDevOpsDataGenerator(
                num_hosts=5,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                seed=seed,
            )
            stats = gen.get_generation_stats()

        expected_total = sum(stats["rows"].values())
        assert stats["total_rows"] == expected_total


class TestExistingDataCheck:
    """Tests for existing data detection."""

    def test_skips_generation_if_data_exists(self, seed, start_time):
        """Should skip generation if valid data exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            gen1 = TSBSDevOpsDataGenerator(
                num_hosts=3,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
                force_regenerate=True,
            )
            result1 = gen1.generate()

            # Create second generator without force_regenerate
            gen2 = TSBSDevOpsDataGenerator(
                num_hosts=3,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
                force_regenerate=False,
            )
            result2 = gen2.generate()

            # Should return same files
            assert set(result1.keys()) == set(result2.keys())

    def test_force_regenerate_overwrites(self, seed, start_time):
        """force_regenerate should overwrite existing data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # First generation
            gen1 = TSBSDevOpsDataGenerator(
                num_hosts=3,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
            )
            gen1.generate()

            # Get modification time
            cpu_path = Path(tmpdir) / "cpu.csv"
            mtime1 = cpu_path.stat().st_mtime

            import time

            time.sleep(0.1)  # Ensure different mtime

            # Second generation with force
            gen2 = TSBSDevOpsDataGenerator(
                num_hosts=3,
                duration_days=1,
                interval_seconds=3600,
                output_dir=tmpdir,
                start_time=start_time,
                seed=seed,
                force_regenerate=True,
            )
            gen2.generate()

            # Should have new mtime
            mtime2 = cpu_path.stat().st_mtime
            assert mtime2 > mtime1
