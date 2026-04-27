"""TSBS DevOps data generator.

Generates synthetic DevOps monitoring data with realistic patterns:
- Diurnal CPU patterns (higher during business hours)
- Memory pressure events
- Disk I/O bursts
- Network traffic patterns
- Seasonal variations

Based on TSBS data generation patterns:
https://github.com/timescale/tsbs/tree/master/cmd/tsbs_generate_data

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Union

import numpy as np

from benchbox.core.manifest_utils import write_generator_manifest
from benchbox.core.tsbs_devops.schema import (
    TABLE_ORDER,
    TSBS_DEVOPS_SCHEMA,
)
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity

# Default configuration
DEFAULT_HOSTS = 100
DEFAULT_DURATION_DAYS = 2
DEFAULT_INTERVAL_SECONDS = 10
REGIONS = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]
DATACENTERS = ["dc1", "dc2", "dc3"]
RACKS = ["rack-a", "rack-b", "rack-c", "rack-d"]
OS_TYPES = ["linux", "linux", "linux", "windows"]  # 75% Linux
ARCHITECTURES = ["x86_64", "x86_64", "arm64"]  # 67% x86
TEAMS = ["platform", "backend", "frontend", "data", "infra"]
SERVICES = ["api", "web", "worker", "cache", "db", "queue"]
ENVIRONMENTS = ["prod", "prod", "staging", "dev"]  # 50% prod


class TSBSDevOpsDataGenerator(CompressionMixin, VerbosityMixin):
    """Generates TSBS DevOps benchmark data.

    Creates synthetic time-series data simulating infrastructure
    monitoring metrics with realistic patterns and correlations.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Union[str, Path] | None = None,
        num_hosts: int | None = None,
        duration_days: int | None = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        start_time: datetime | None = None,
        seed: int | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        force_regenerate: bool = False,
        **kwargs,
    ) -> None:
        """Initialize data generator.

        Args:
            scale_factor: Scale factor that multiplies hosts and duration
            output_dir: Directory for output files
            num_hosts: Number of hosts (overrides scale_factor for hosts)
            duration_days: Duration in days (overrides scale_factor for duration)
            interval_seconds: Measurement interval in seconds
            start_time: Start timestamp for data
            seed: Random seed for reproducibility
            verbose: Verbosity level
            quiet: Suppress output
            force_regenerate: Force regeneration even if data exists
            **kwargs: Additional options
        """
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "tsbs_devops_data"

        # Calculate dimensions based on scale factor.
        # SF=1.0 uses 100 hosts over 2 days, which keeps the dataset close to
        # BenchBox's ~1GB baseline while preserving TSBS's host-driven scale semantics.
        # Only num_hosts scales with SF; duration_days is fixed to avoid quadratic
        # growth (hosts × days both scaling would produce SF² total rows).
        self.num_hosts = num_hosts or max(10, int(DEFAULT_HOSTS * scale_factor))
        self.duration_days = duration_days or DEFAULT_DURATION_DAYS
        self.interval_seconds = interval_seconds
        self.start_time = start_time or datetime(2024, 1, 1, 0, 0, 0)

        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self.force_regenerate = force_regenerate

        # Initialize verbosity
        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger("benchbox.core.tsbs_devops.generator")

        # Generate consistent host metadata
        self._generate_host_metadata()
        self._table_row_counts: dict[str, int] = {}

    def _generate_host_metadata(self) -> None:
        """Generate consistent host tags for all hosts."""
        self.hosts = []
        for i in range(self.num_hosts):
            host = {
                "hostname": f"host_{i}",
                "region": REGIONS[i % len(REGIONS)],
                "datacenter": DATACENTERS[i % len(DATACENTERS)],
                "rack": RACKS[i % len(RACKS)],
                "os": OS_TYPES[int(self.rng.integers(len(OS_TYPES)))],
                "arch": ARCHITECTURES[int(self.rng.integers(len(ARCHITECTURES)))],
                "team": TEAMS[int(self.rng.integers(len(TEAMS)))],
                "service": SERVICES[int(self.rng.integers(len(SERVICES)))],
                "service_version": f"1.{int(self.rng.integers(0, 10))}.{int(self.rng.integers(0, 100))}",
                "service_environment": ENVIRONMENTS[int(self.rng.integers(len(ENVIRONMENTS)))],
            }
            self.hosts.append(host)

    def generate(self) -> dict[str, Path]:
        """Generate all TSBS DevOps data files.

        Returns:
            Dictionary mapping table names to file paths

        Raises:
            RuntimeError: If generation fails
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if data already exists
        if not self.force_regenerate and self._check_existing_data():
            self.log_verbose("Valid TSBS DevOps data found, skipping generation")
            return self._collect_table_files()

        self.log_verbose("Generating TSBS DevOps data:")
        self.log_verbose(f"  Hosts: {self.num_hosts}")
        self.log_verbose(f"  Duration: {self.duration_days} days")
        self.log_verbose(f"  Interval: {self.interval_seconds} seconds")
        self.log_verbose(f"  Start time: {self.start_time}")

        # Calculate number of timestamps
        total_seconds = self.duration_days * 24 * 60 * 60
        num_timestamps = total_seconds // self.interval_seconds
        self.log_verbose(f"  Timestamps per host: {num_timestamps}")

        table_files = {}

        # Generate tags table
        table_files["tags"] = self._generate_tags()

        # Generate metric tables
        table_files["cpu"] = self._generate_cpu_metrics(num_timestamps)
        table_files["mem"] = self._generate_mem_metrics(num_timestamps)
        table_files["disk"] = self._generate_disk_metrics(num_timestamps)
        table_files["net"] = self._generate_net_metrics(num_timestamps)

        if self._table_row_counts:
            write_generator_manifest(
                self, "tsbs_devops", table_files, self._table_row_counts, metadata={"csv_has_header": True}
            )
        self.log_verbose("TSBS DevOps data generation complete")
        return table_files

    def _check_existing_data(self) -> bool:
        """Check if valid data files exist."""
        for table in TABLE_ORDER:
            filename = self.get_compressed_filename(f"{table}.csv")
            if not (self.output_dir / filename).exists():
                return False
        return True

    def _collect_table_files(self) -> dict[str, Path]:
        """Collect existing table file paths."""
        return {
            table: self.output_dir / self.get_compressed_filename(f"{table}.csv")
            for table in TABLE_ORDER
            if (self.output_dir / self.get_compressed_filename(f"{table}.csv")).exists()
        }

    def _generate_tags(self) -> Path:
        """Generate tags table with host metadata."""
        output_path = self.output_dir / self.get_compressed_filename("tags.csv")

        columns = list(TSBS_DEVOPS_SCHEMA["tags"]["columns"].keys())

        with self.open_output_file(output_path, "wt") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()

            for host in self.hosts:
                writer.writerow(host)

        self._table_row_counts["tags"] = len(self.hosts)
        self.log_verbose(f"  tags: {len(self.hosts)} rows")
        return output_path

    def _generate_cpu_metrics(self, num_timestamps: int) -> Path:
        """Generate CPU metrics with realistic patterns."""
        output_path = self.output_dir / self.get_compressed_filename("cpu.csv")
        columns = list(TSBS_DEVOPS_SCHEMA["cpu"]["columns"].keys())

        total_rows = 0
        with self.open_output_file(output_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerow(columns)

            for host in self.hosts:
                hostname = host["hostname"]
                # Each host has baseline patterns
                base_user = 10 + self.rng.random() * 20
                base_system = 5 + self.rng.random() * 10

                for t in range(num_timestamps):
                    timestamp = self.start_time + timedelta(seconds=t * self.interval_seconds)

                    # Add diurnal pattern (higher during business hours 9-17)
                    hour = timestamp.hour
                    diurnal_factor = 1.0 + 0.5 * np.sin((hour - 6) * np.pi / 12) if 6 <= hour <= 18 else 0.7

                    # Add some randomness
                    noise = self.rng.random() * 10

                    usage_user = min(100, max(0, base_user * diurnal_factor + noise))
                    usage_system = min(100, max(0, base_system * diurnal_factor + noise * 0.5))
                    usage_idle = max(0, 100 - usage_user - usage_system)
                    usage_nice = self.rng.random() * 2
                    usage_iowait = self.rng.random() * 5
                    usage_irq = self.rng.random() * 0.5
                    usage_softirq = self.rng.random() * 0.5
                    usage_steal = self.rng.random() * 0.1
                    usage_guest = self.rng.random() * 0.5
                    usage_guest_nice = self.rng.random() * 0.1

                    writer.writerow(
                        [
                            timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            hostname,
                            f"{usage_user:.2f}",
                            f"{usage_system:.2f}",
                            f"{usage_idle:.2f}",
                            f"{usage_nice:.2f}",
                            f"{usage_iowait:.2f}",
                            f"{usage_irq:.2f}",
                            f"{usage_softirq:.2f}",
                            f"{usage_steal:.2f}",
                            f"{usage_guest:.2f}",
                            f"{usage_guest_nice:.2f}",
                        ]
                    )
                    total_rows += 1

        self._table_row_counts["cpu"] = total_rows
        self.log_verbose(f"  cpu: {total_rows} rows")
        return output_path

    def _generate_mem_metrics(self, num_timestamps: int) -> Path:
        """Generate memory metrics with realistic patterns."""
        output_path = self.output_dir / self.get_compressed_filename("mem.csv")
        columns = list(TSBS_DEVOPS_SCHEMA["mem"]["columns"].keys())

        total_rows = 0
        with self.open_output_file(output_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerow(columns)

            for host in self.hosts:
                hostname = host["hostname"]
                # Each host has different total memory (8GB to 64GB)
                total_mem = int(self.rng.choice([8, 16, 32, 64])) * 1024 * 1024 * 1024
                base_used_pct = 40 + self.rng.random() * 30

                for t in range(num_timestamps):
                    timestamp = self.start_time + timedelta(seconds=t * self.interval_seconds)

                    # Memory tends to grow slowly over time with periodic drops (GC)
                    trend = (t / num_timestamps) * 10  # Slow growth
                    gc_drop = -15 if t % 360 == 0 else 0  # Periodic drops

                    used_pct = min(95, max(10, base_used_pct + trend + gc_drop + self.rng.random() * 5))
                    used = int(total_mem * used_pct / 100)
                    free = total_mem - used
                    cached = int(used * 0.3 * self.rng.random())
                    buffered = int(used * 0.1 * self.rng.random())
                    available = free + cached + buffered

                    writer.writerow(
                        [
                            timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            hostname,
                            total_mem,
                            available,
                            used,
                            free,
                            cached,
                            buffered,
                            f"{used_pct:.2f}",
                            f"{available * 100.0 / total_mem:.2f}",
                        ]
                    )
                    total_rows += 1

        self._table_row_counts["mem"] = total_rows
        self.log_verbose(f"  mem: {total_rows} rows")
        return output_path

    def _generate_disk_metrics(self, num_timestamps: int) -> Path:
        """Generate disk I/O metrics."""
        output_path = self.output_dir / self.get_compressed_filename("disk.csv")
        columns = list(TSBS_DEVOPS_SCHEMA["disk"]["columns"].keys())

        devices = ["sda", "sdb"]  # 2 disks per host
        total_rows = 0

        with self.open_output_file(output_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerow(columns)

            for host in self.hosts:
                hostname = host["hostname"]

                for device in devices:
                    cumulative_reads = 0
                    cumulative_writes = 0
                    cumulative_read_time = 0
                    cumulative_write_time = 0

                    for t in range(num_timestamps):
                        timestamp = self.start_time + timedelta(seconds=t * self.interval_seconds)

                        # Generate incremental I/O with occasional bursts
                        is_burst = self.rng.random() < 0.05  # 5% chance of burst
                        mult = 10 if is_burst else 1

                        reads = int(self.rng.integers(10, 100) * mult)
                        writes = int(self.rng.integers(5, 50) * mult)
                        read_time = int(reads * (0.5 + self.rng.random() * 2))
                        write_time = int(writes * (1 + self.rng.random() * 5))

                        cumulative_reads += reads
                        cumulative_writes += writes
                        cumulative_read_time += read_time
                        cumulative_write_time += write_time

                        writer.writerow(
                            [
                                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                                hostname,
                                device,
                                cumulative_reads,
                                int(reads * 0.1),  # merged
                                cumulative_reads * 8,  # sectors
                                cumulative_read_time,
                                cumulative_writes,
                                int(writes * 0.1),  # merged
                                cumulative_writes * 8,  # sectors
                                cumulative_write_time,
                                int(self.rng.integers(0, 5)),  # io_in_progress
                                cumulative_read_time + cumulative_write_time,
                                int((cumulative_read_time + cumulative_write_time) * 1.1),
                            ]
                        )
                        total_rows += 1

        self._table_row_counts["disk"] = total_rows
        self.log_verbose(f"  disk: {total_rows} rows")
        return output_path

    def _generate_net_metrics(self, num_timestamps: int) -> Path:
        """Generate network metrics."""
        output_path = self.output_dir / self.get_compressed_filename("net.csv")
        columns = list(TSBS_DEVOPS_SCHEMA["net"]["columns"].keys())

        interfaces = ["eth0", "lo"]
        total_rows = 0

        with self.open_output_file(output_path, "wt") as f:
            writer = csv.writer(f)
            writer.writerow(columns)

            for host in self.hosts:
                hostname = host["hostname"]

                for interface in interfaces:
                    cumulative_recv = 0
                    cumulative_sent = 0
                    cumulative_packets_recv = 0
                    cumulative_packets_sent = 0

                    for t in range(num_timestamps):
                        timestamp = self.start_time + timedelta(seconds=t * self.interval_seconds)

                        # lo has much less traffic
                        mult = 0.1 if interface == "lo" else 1.0

                        bytes_recv = int(self.rng.integers(1000, 100000) * mult)
                        bytes_sent = int(self.rng.integers(500, 50000) * mult)
                        packets_recv = int(bytes_recv / 1500)  # Avg packet size
                        packets_sent = int(bytes_sent / 1500)

                        cumulative_recv += bytes_recv
                        cumulative_sent += bytes_sent
                        cumulative_packets_recv += packets_recv
                        cumulative_packets_sent += packets_sent

                        # Errors are rare
                        err_in = 1 if self.rng.random() < 0.001 else 0
                        err_out = 1 if self.rng.random() < 0.001 else 0
                        drop_in = 1 if self.rng.random() < 0.002 else 0
                        drop_out = 1 if self.rng.random() < 0.002 else 0

                        writer.writerow(
                            [
                                timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                                hostname,
                                interface,
                                cumulative_recv,
                                cumulative_sent,
                                cumulative_packets_recv,
                                cumulative_packets_sent,
                                err_in,
                                err_out,
                                drop_in,
                                drop_out,
                            ]
                        )
                        total_rows += 1

        self._table_row_counts["net"] = total_rows
        self.log_verbose(f"  net: {total_rows} rows")
        return output_path

    def get_generation_stats(self) -> dict:
        """Get statistics about the generated data.

        Returns:
            Dictionary with generation statistics
        """
        total_seconds = self.duration_days * 24 * 60 * 60
        num_timestamps = total_seconds // self.interval_seconds

        # CPU: hosts * timestamps
        cpu_rows = self.num_hosts * num_timestamps
        # Mem: hosts * timestamps
        mem_rows = self.num_hosts * num_timestamps
        # Disk: hosts * devices(2) * timestamps
        disk_rows = self.num_hosts * 2 * num_timestamps
        # Net: hosts * interfaces(2) * timestamps
        net_rows = self.num_hosts * 2 * num_timestamps

        return {
            "num_hosts": self.num_hosts,
            "duration_days": self.duration_days,
            "interval_seconds": self.interval_seconds,
            "num_timestamps": num_timestamps,
            "rows": {
                "tags": self.num_hosts,
                "cpu": cpu_rows,
                "mem": mem_rows,
                "disk": disk_rows,
                "net": net_rows,
            },
            "total_rows": self.num_hosts + cpu_rows + mem_rows + disk_rows + net_rows,
        }
