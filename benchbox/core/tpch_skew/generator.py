"""Skewed data generator for TPC-H Skew benchmark.

Generates TPC-H data with configurable skew patterns by:
1. Generating standard TPC-H data using the official dbgen tool
2. Applying skew transformations to foreign keys and attributes

Based on the research: "Introducing Skew into the TPC-H Benchmark"
Reference: https://www.tpc.org/tpctc/tpctc2011/slides_and_papers/introducing_skew_into_the_tpc_h_benchmark.pdf

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import yaml

from benchbox.core.tpch.generator import TPCHDataGenerator
from benchbox.core.tpch_skew.distributions import (
    ExponentialDistribution,
    NormalDistribution,
    SkewDistribution,
    UniformDistribution,
    ZipfianDistribution,
)
from benchbox.utils.verbosity import VerbosityMixin, compute_verbosity

if TYPE_CHECKING:
    from benchbox.core.tpch_skew.skew_config import SkewConfiguration


def _load_generator_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("generator_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


_GENERATOR_SPECS = _load_generator_specs()

# TPC-H row counts at SF=1
_TPCH_BASE_ROW_COUNTS = dict(_GENERATOR_SPECS["base_row_counts"])

# Column indices for each TPC-H table (0-based)
_COLUMN_INDICES = _GENERATOR_SPECS["column_indices"]


class TPCHSkewDataGenerator(VerbosityMixin):
    """Generates TPC-H data with configurable skew patterns.

    This generator creates TPC-H benchmark data with realistic data
    distributions that deviate from the uniform distributions in
    standard TPC-H. It supports:

    - Attribute skew: Non-uniform value distributions
    - Join skew: Non-uniform foreign key relationships
    - Temporal skew: Date concentration patterns

    The generator uses the official dbgen tool for base data generation,
    then applies skew transformations to the generated data files.
    """

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: str | Path | None = None,
        skew_config: SkewConfiguration | None = None,
        verbose: int | bool = 0,
        quiet: bool = False,
        parallel: int = 1,
        force_regenerate: bool = False,
        **kwargs,
    ) -> None:
        """Initialize skewed data generator.

        Args:
            scale_factor: Scale factor (1.0 = ~1GB)
            output_dir: Directory for generated data
            skew_config: Skew configuration (None = moderate preset)
            verbose: Verbosity level
            quiet: Suppress output
            parallel: Parallel processes for base generation
            force_regenerate: Force regeneration even if data exists
            **kwargs: Additional arguments passed to base generator
        """
        self.scale_factor = scale_factor
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "tpch_skew_data"

        # Initialize verbosity
        verbosity_settings = compute_verbosity(verbose, quiet)
        self.apply_verbosity(verbosity_settings)
        self.logger = logging.getLogger("benchbox.core.tpch_skew.generator")

        self.parallel = parallel
        self.force_regenerate = force_regenerate

        # Import here to avoid circular dependency
        from benchbox.core.tpch_skew.skew_config import SkewPreset, get_preset_config

        # Use provided config or default to moderate skew
        self.skew_config = skew_config or get_preset_config(SkewPreset.MODERATE)

        # Initialize random generator with seed from config
        self.rng = np.random.default_rng(self.skew_config.seed)

        # Create distribution based on config
        self.distribution = self._create_distribution()

        # Store kwargs for base generator
        self._base_kwargs = kwargs

    def _create_distribution(self) -> SkewDistribution:
        """Create skew distribution based on configuration."""
        dist_type = self.skew_config.distribution_type.lower()
        skew_factor = self.skew_config.skew_factor

        if dist_type == "zipfian":
            # Map skew_factor [0,1] to Zipf s parameter [0,2]
            s = skew_factor * 2.0
            return ZipfianDistribution(s=s, num_elements=10000)
        elif dist_type == "normal":
            # Map skew_factor to std: high skew = low std
            std = max(0.05, 0.5 * (1 - skew_factor))
            return NormalDistribution(mean=0.5, std=std)
        elif dist_type == "exponential":
            # Map skew_factor to rate: high skew = high rate
            rate = 0.5 + skew_factor * 4.5
            return ExponentialDistribution(rate=rate)
        else:
            return UniformDistribution()

    def generate(self) -> dict[str, Path]:
        """Generate TPC-H data with skew applied.

        Returns:
            Dictionary mapping table names to data file paths

        Raises:
            RuntimeError: If data generation fails
        """
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Check if skewed data already exists
        if not self.force_regenerate and self._check_existing_data():
            self.log_verbose("✅ Valid skewed TPC-H data found, skipping generation")
            return self._collect_table_files()

        self.log_verbose(f"Generating TPC-H Skew data at scale factor {self.scale_factor}")
        self.log_verbose(f"Skew factor: {self.skew_config.skew_factor}")
        self.log_verbose(f"Distribution: {self.distribution.get_description()}")

        # Step 1: Generate base TPC-H data in a temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            self.log_verbose("Step 1/2: Generating base TPC-H data...")
            base_generator = TPCHDataGenerator(
                scale_factor=self.scale_factor,
                output_dir=temp_path,
                verbose=self.verbose,
                quiet=self.quiet,
                parallel=self.parallel,
                force_regenerate=True,
                **self._base_kwargs,
            )
            base_tables = base_generator.generate()
            self.log_verbose(f"Base data generated: {len(base_tables)} tables")

            # Step 2: Apply skew transformations
            self.log_verbose("Step 2/2: Applying skew transformations...")
            skewed_tables = self._apply_skew_to_tables(base_tables)

        self.log_verbose("✅ Skewed TPC-H data generation complete")
        return skewed_tables

    def _check_existing_data(self) -> bool:
        """Check if valid skewed data already exists."""
        expected_files = [
            "customer.tbl",
            "lineitem.tbl",
            "nation.tbl",
            "orders.tbl",
            "part.tbl",
            "partsupp.tbl",
            "region.tbl",
            "supplier.tbl",
        ]
        for filename in expected_files:
            if not (self.output_dir / filename).exists():
                return False
        return True

    def _collect_table_files(self) -> dict[str, Path]:
        """Collect existing table file paths."""
        table_files = {
            "customer": "customer.tbl",
            "lineitem": "lineitem.tbl",
            "nation": "nation.tbl",
            "orders": "orders.tbl",
            "part": "part.tbl",
            "partsupp": "partsupp.tbl",
            "region": "region.tbl",
            "supplier": "supplier.tbl",
        }
        return {
            table: self.output_dir / filename
            for table, filename in table_files.items()
            if (self.output_dir / filename).exists()
        }

    def _apply_skew_to_tables(self, base_tables: dict[str, Path | list[Path]]) -> dict[str, Path]:
        """Apply skew transformations to all tables.

        Args:
            base_tables: Dictionary of table names to base data file path(s).
                Values may be a single Path or a list of Paths (sharded generation).

        Returns:
            Dictionary of table names to skewed data file paths
        """
        skewed_tables = {}

        # Tables that don't need modification (reference data)
        unchanged = {"nation", "region"}

        for table_name, base_path_or_paths in base_tables.items():
            output_path = self.output_dir / f"{table_name}.tbl"

            # Normalize sharded files: concatenate into a single file for processing
            base_path = self._normalize_shards(base_path_or_paths, table_name)

            if table_name in unchanged:
                # Copy unchanged tables directly
                shutil.copy2(base_path, output_path)
                skewed_tables[table_name] = output_path
                self.log_verbose(f"  {table_name}: copied unchanged")
                continue

            # Apply appropriate skew transformations
            if table_name == "customer":
                self._transform_customer(base_path, output_path)
            elif table_name == "supplier":
                self._transform_supplier(base_path, output_path)
            elif table_name == "part":
                self._transform_part(base_path, output_path)
            elif table_name == "partsupp":
                self._transform_partsupp(base_path, output_path)
            elif table_name == "orders":
                self._transform_orders(base_path, output_path)
            elif table_name == "lineitem":
                self._transform_lineitem(base_path, output_path)
            else:
                # Unknown table - copy as-is
                shutil.copy2(base_path, output_path)

            skewed_tables[table_name] = output_path
            self.log_verbose(f"  {table_name}: skew applied")

        return skewed_tables

    @staticmethod
    def _normalize_shards(path_or_paths: Path | list[Path], table_name: str) -> Path:
        """Merge sharded files into a single path for processing.

        When TPCHDataGenerator runs with parallel > 1, it produces multiple
        shard files per table. This method concatenates them into a single
        temporary file so the skew transforms can process the table as a whole.

        Args:
            path_or_paths: Single path or list of shard paths.
            table_name: Table name (for logging context only).

        Returns:
            A single Path to the (possibly merged) data file.
        """
        if isinstance(path_or_paths, list):
            if len(path_or_paths) == 1:
                return path_or_paths[0]
            # Concatenate shards into first shard's directory
            merged = path_or_paths[0].parent / f"{table_name}_merged.tbl"
            with open(merged, "wb") as out:
                for shard in sorted(path_or_paths, key=lambda p: p.name):
                    with open(shard, "rb") as inp:
                        shutil.copyfileobj(inp, out)
            return merged
        return path_or_paths

    def _read_tbl_file(self, path: Path) -> list[list[str]]:
        """Read a .tbl file into list of rows.

        Args:
            path: Path to .tbl file

        Returns:
            List of rows, each row is a list of field values
        """
        rows = []
        with open(path, encoding="utf-8") as f:
            reader = csv.reader(f, delimiter="|")
            for row in reader:
                # Remove trailing empty element from TPC-H format
                if row and row[-1] == "":
                    row = row[:-1]
                if row:
                    rows.append(row)
        return rows

    def _write_tbl_file(self, rows: list[list[str]], path: Path) -> None:
        """Write rows to a .tbl file.

        Args:
            rows: List of rows to write
            path: Output path
        """
        with open(path, "w", encoding="utf-8", newline="") as f:
            for row in rows:
                # Match native dbgen output format: fields separated by |, NO trailing |
                f.write("|".join(row) + "\n")

    def _generate_skewed_values(
        self,
        num_values: int,
        min_val: int,
        max_val: int,
        skew_factor: float,
    ) -> np.ndarray:
        """Generate skewed integer values in a range.

        Args:
            num_values: Number of values to generate
            min_val: Minimum value (inclusive)
            max_val: Maximum value (inclusive)
            skew_factor: Skew intensity (0=uniform, 1=maximum)

        Returns:
            Array of skewed integer values
        """
        if skew_factor <= 0:
            # Uniform distribution
            return self.rng.integers(min_val, max_val + 1, size=num_values)

        # Create appropriate distribution for this skew factor
        if self.skew_config.distribution_type == "zipfian":
            num_elements = max_val - min_val + 1
            dist = ZipfianDistribution(s=skew_factor * 2.0, num_elements=num_elements)
        elif self.skew_config.distribution_type == "normal":
            std = max(0.05, 0.5 * (1 - skew_factor))
            dist = NormalDistribution(mean=0.5, std=std)
        elif self.skew_config.distribution_type == "exponential":
            rate = 0.5 + skew_factor * 4.5
            dist = ExponentialDistribution(rate=rate)
        else:
            dist = UniformDistribution()

        # Generate samples and map to range
        samples = dist.sample(num_values, self.rng)
        return dist.map_to_range(samples, min_val, max_val)

    def _transform_customer(self, input_path: Path, output_path: Path) -> None:
        """Apply skew to customer table.

        Skews applied:
        - c_nationkey: Customer nationality distribution
        - c_mktsegment: Market segment distribution
        """
        rows = self._read_tbl_file(input_path)
        attr_config = self.skew_config.attribute_skew

        if attr_config.customer_nation_skew > 0 or attr_config.customer_segment_skew > 0:
            num_rows = len(rows)
            nation_col = _COLUMN_INDICES["customer"]["c_nationkey"]
            segment_col = _COLUMN_INDICES["customer"]["c_mktsegment"]

            # Skew nationkey (0-24)
            if attr_config.customer_nation_skew > 0:
                skewed_nations = self._generate_skewed_values(num_rows, 0, 24, attr_config.customer_nation_skew)
                for i, row in enumerate(rows):
                    row[nation_col] = str(skewed_nations[i])

            # Skew market segment
            if attr_config.customer_segment_skew > 0:
                segments = ["AUTOMOBILE", "BUILDING", "FURNITURE", "HOUSEHOLD", "MACHINERY"]
                skewed_indices = self._generate_skewed_values(
                    num_rows, 0, len(segments) - 1, attr_config.customer_segment_skew
                )
                for i, row in enumerate(rows):
                    row[segment_col] = segments[skewed_indices[i]]

        self._write_tbl_file(rows, output_path)

    def _transform_supplier(self, input_path: Path, output_path: Path) -> None:
        """Apply skew to supplier table.

        Skews applied:
        - s_nationkey: Supplier nationality distribution
        """
        rows = self._read_tbl_file(input_path)
        attr_config = self.skew_config.attribute_skew

        if attr_config.supplier_nation_skew > 0:
            num_rows = len(rows)
            nation_col = _COLUMN_INDICES["supplier"]["s_nationkey"]

            skewed_nations = self._generate_skewed_values(num_rows, 0, 24, attr_config.supplier_nation_skew)
            for i, row in enumerate(rows):
                row[nation_col] = str(skewed_nations[i])

        self._write_tbl_file(rows, output_path)

    def _transform_part(self, input_path: Path, output_path: Path) -> None:
        """Apply skew to part table.

        Skews applied:
        - p_brand: Brand distribution (80/20 rule)
        - p_type: Part type distribution
        - p_container: Container type distribution
        """
        rows = self._read_tbl_file(input_path)
        attr_config = self.skew_config.attribute_skew

        num_rows = len(rows)
        brand_col = _COLUMN_INDICES["part"]["p_brand"]
        type_col = _COLUMN_INDICES["part"]["p_type"]
        container_col = _COLUMN_INDICES["part"]["p_container"]

        # Brands: Brand#11 through Brand#55
        if attr_config.part_brand_skew > 0:
            brands = [f"Brand#{i}{j}" for i in range(1, 6) for j in range(1, 6)]
            skewed_indices = self._generate_skewed_values(num_rows, 0, len(brands) - 1, attr_config.part_brand_skew)
            for i, row in enumerate(rows):
                row[brand_col] = brands[skewed_indices[i]]

        # Part types: combinations of type, metal, finish
        if attr_config.part_type_skew > 0:
            types = [
                "STANDARD ANODIZED TIN",
                "STANDARD ANODIZED NICKEL",
                "STANDARD ANODIZED BRASS",
                "STANDARD ANODIZED STEEL",
                "STANDARD ANODIZED COPPER",
                "SMALL ANODIZED TIN",
                "SMALL ANODIZED NICKEL",
                "SMALL ANODIZED BRASS",
                "MEDIUM POLISHED TIN",
                "MEDIUM POLISHED NICKEL",
                "MEDIUM POLISHED BRASS",
                "LARGE POLISHED TIN",
                "LARGE POLISHED NICKEL",
                "LARGE POLISHED STEEL",
                "ECONOMY BRUSHED BRASS",
                "ECONOMY BRUSHED COPPER",
                "ECONOMY BRUSHED STEEL",
                "PROMO PLATED TIN",
                "PROMO PLATED NICKEL",
                "PROMO PLATED BRASS",
            ]
            skewed_indices = self._generate_skewed_values(num_rows, 0, len(types) - 1, attr_config.part_type_skew)
            for i, row in enumerate(rows):
                row[type_col] = types[skewed_indices[i]]

        # Container types
        if attr_config.part_container_skew > 0:
            containers = [
                "SM CASE",
                "SM BOX",
                "SM BAG",
                "SM JAR",
                "SM PACK",
                "MED CASE",
                "MED BOX",
                "MED BAG",
                "MED JAR",
                "MED PACK",
                "LG CASE",
                "LG BOX",
                "LG BAG",
                "LG JAR",
                "LG PACK",
                "JUMBO CASE",
                "JUMBO BOX",
                "JUMBO BAG",
                "JUMBO JAR",
                "JUMBO PACK",
                "WRAP CASE",
                "WRAP BOX",
                "WRAP BAG",
                "WRAP JAR",
                "WRAP PACK",
            ]
            skewed_indices = self._generate_skewed_values(
                num_rows, 0, len(containers) - 1, attr_config.part_container_skew
            )
            for i, row in enumerate(rows):
                row[container_col] = containers[skewed_indices[i]]

        self._write_tbl_file(rows, output_path)

    def _transform_partsupp(self, input_path: Path, output_path: Path) -> None:
        """Apply skew to partsupp table.

        For partsupp, we typically don't apply direct skew as it's
        a cross-reference table. The skew comes from the skewed
        usage of parts and suppliers in lineitem.
        """
        # Copy unchanged - partsupp skew is derived from part/supplier usage
        shutil.copy2(input_path, output_path)

    def _transform_orders(self, input_path: Path, output_path: Path) -> None:
        """Apply skew to orders table.

        Skews applied:
        - o_custkey: Customer ordering frequency (join skew)
        - o_orderpriority: Order priority distribution
        - o_orderdate: Temporal skew (if enabled)
        """
        rows = self._read_tbl_file(input_path)
        attr_config = self.skew_config.attribute_skew
        join_config = self.skew_config.join_skew
        temporal_config = self.skew_config.temporal_skew

        num_rows = len(rows)
        custkey_col = _COLUMN_INDICES["orders"]["o_custkey"]
        priority_col = _COLUMN_INDICES["orders"]["o_orderpriority"]
        orderdate_col = _COLUMN_INDICES["orders"]["o_orderdate"]

        # Calculate max customer key
        max_custkey = int(150_000 * self.scale_factor)

        # Apply customer ordering frequency skew (join skew)
        if join_config.customer_order_skew > 0 and self.skew_config.enable_join_skew:
            skewed_custkeys = self._generate_skewed_values(num_rows, 1, max_custkey, join_config.customer_order_skew)
            for i, row in enumerate(rows):
                row[custkey_col] = str(skewed_custkeys[i])

        # Apply order priority skew
        if attr_config.order_priority_skew > 0 and self.skew_config.enable_attribute_skew:
            priorities = ["1-URGENT", "2-HIGH", "3-MEDIUM", "4-NOT SPECIFIED", "5-LOW"]
            skewed_indices = self._generate_skewed_values(
                num_rows, 0, len(priorities) - 1, attr_config.order_priority_skew
            )
            for i, row in enumerate(rows):
                row[priority_col] = priorities[skewed_indices[i]]

        # Apply temporal skew to order dates
        if temporal_config.order_date_skew > 0 and self.skew_config.enable_temporal_skew:
            self._apply_temporal_skew_to_dates(rows, orderdate_col, temporal_config.order_date_skew)

        self._write_tbl_file(rows, output_path)

    def _transform_lineitem(self, input_path: Path, output_path: Path) -> None:
        """Apply skew to lineitem table.

        Skews applied:
        - l_partkey: Part popularity (join skew)
        - l_suppkey: Supplier volume (join skew)
        - l_shipmode: Shipping mode distribution
        - l_returnflag: Return flag distribution
        - l_shipdate: Temporal skew (if enabled)
        """
        rows = self._read_tbl_file(input_path)
        attr_config = self.skew_config.attribute_skew
        join_config = self.skew_config.join_skew
        temporal_config = self.skew_config.temporal_skew

        num_rows = len(rows)
        partkey_col = _COLUMN_INDICES["lineitem"]["l_partkey"]
        suppkey_col = _COLUMN_INDICES["lineitem"]["l_suppkey"]
        shipmode_col = _COLUMN_INDICES["lineitem"]["l_shipmode"]
        returnflag_col = _COLUMN_INDICES["lineitem"]["l_returnflag"]
        shipdate_col = _COLUMN_INDICES["lineitem"]["l_shipdate"]

        # Calculate max keys
        max_partkey = int(200_000 * self.scale_factor)
        max_suppkey = int(10_000 * self.scale_factor)

        # Apply part popularity skew (join skew)
        if join_config.part_popularity_skew > 0 and self.skew_config.enable_join_skew:
            skewed_partkeys = self._generate_skewed_values(num_rows, 1, max_partkey, join_config.part_popularity_skew)
            for i, row in enumerate(rows):
                row[partkey_col] = str(skewed_partkeys[i])

        # Apply supplier volume skew (join skew)
        if join_config.supplier_volume_skew > 0 and self.skew_config.enable_join_skew:
            skewed_suppkeys = self._generate_skewed_values(num_rows, 1, max_suppkey, join_config.supplier_volume_skew)
            for i, row in enumerate(rows):
                row[suppkey_col] = str(skewed_suppkeys[i])

        # Apply ship mode skew
        if attr_config.shipmode_skew > 0 and self.skew_config.enable_attribute_skew:
            shipmodes = ["REG AIR", "AIR", "RAIL", "SHIP", "TRUCK", "MAIL", "FOB"]
            skewed_indices = self._generate_skewed_values(num_rows, 0, len(shipmodes) - 1, attr_config.shipmode_skew)
            for i, row in enumerate(rows):
                row[shipmode_col] = shipmodes[skewed_indices[i]]

        # Apply return flag skew (most items not returned)
        if attr_config.returnflag_skew > 0 and self.skew_config.enable_attribute_skew:
            # Return flags: N (not returned), R (returned), A (accepted)
            flags = ["N", "R", "A"]
            skewed_indices = self._generate_skewed_values(num_rows, 0, len(flags) - 1, attr_config.returnflag_skew)
            for i, row in enumerate(rows):
                row[returnflag_col] = flags[skewed_indices[i]]

        # Apply temporal skew to ship dates
        if temporal_config.ship_date_seasonality > 0 and self.skew_config.enable_temporal_skew:
            self._apply_temporal_skew_to_dates(rows, shipdate_col, temporal_config.ship_date_seasonality)

        self._write_tbl_file(rows, output_path)

    def _apply_temporal_skew_to_dates(self, rows: list[list[str]], date_col: int, skew_factor: float) -> None:
        """Apply temporal skew to date column.

        Concentrates dates toward more recent periods.

        Args:
            rows: Data rows to modify
            date_col: Index of date column
            skew_factor: Intensity of temporal skew
        """
        from datetime import datetime, timedelta

        # TPC-H date range: 1992-01-01 to 1998-12-31
        start_date = datetime(1992, 1, 1)
        end_date = datetime(1998, 12, 31)
        total_days = (end_date - start_date).days

        # Generate skewed day offsets
        num_rows = len(rows)
        dist = ExponentialDistribution(rate=0.5 + skew_factor * 4)
        samples = dist.sample(num_rows, self.rng)

        # Concentrate toward end of range (recent dates)
        # samples in [0,1] -> map to concentrate at high values
        concentrated = 1 - samples  # Flip to concentrate at 1
        day_offsets = (concentrated * total_days).astype(int)

        for i, row in enumerate(rows):
            new_date = start_date + timedelta(days=int(day_offsets[i]))
            row[date_col] = new_date.strftime("%Y-%m-%d")

    def get_skew_statistics(self) -> dict:
        """Get statistics about the applied skew.

        Returns:
            Dictionary with skew statistics
        """
        return {
            "scale_factor": self.scale_factor,
            "skew_factor": self.skew_config.skew_factor,
            "distribution": self.distribution.get_description(),
            "effective_skew": self.distribution.get_skew_factor(),
            "config_summary": self.skew_config.get_skew_summary(),
        }
