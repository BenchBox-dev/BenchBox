"""CoffeeShop data generator aligned with the reference order line model.

This implementation discards the legacy 6-table schema and now emits the exact
three-table layout expected by the reference CoffeeShop generator:

* ``dim_locations`` - static seed data describing each store and its region
* ``dim_products`` - reference product catalog with seasonal pricing windows
* ``order_lines`` - exploded fact table with 1-5 lines per order and realistic
  temporal, regional, and product weighting

The generator follows the approved mapping of scale factor → order count where
``SF=1.0`` produces 8.5 million orders (≈13.3 million order lines). Smaller
scale factors remain practical for development and unit tests while the
weighting logic mirrors the seasonal, regional, and growth dynamics of the
reference implementation.
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, time, timedelta
from itertools import cycle
from pathlib import Path
from typing import TypeVar

from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.coffeeshop_seed_loader import (
    LocationSeed,
    ProductSeed,
    load_location_seeds,
    load_product_seeds,
)
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.datagen_manifest import DataGenerationManifest, resolve_compression_metadata
from benchbox.utils.path_utils import get_benchmark_runs_datagen_path


@dataclass(frozen=True)
class _ProductWindow:
    """Bucket of product seeds that share the same availability window."""

    start: date
    end: date
    seeds_by_subcategory: dict[str, list[ProductSeed]]


T = TypeVar("T")


class CoffeeShopDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generate CoffeeShop benchmark data that matches the reference schema."""

    SF1_ORDER_COUNT = 8_500_000

    MONTH_WEIGHTS: dict[int, float] = {
        1: 0.82,
        2: 0.85,
        3: 0.95,
        4: 1.00,
        5: 1.05,
        6: 0.98,
        7: 0.90,
        8: 0.92,
        9: 1.08,
        10: 1.15,
        11: 1.22,
        12: 1.38,
    }

    REGION_WEIGHTS: dict[str, float] = {
        "South": 1.25,
        "Southeast": 1.10,
        "West": 0.90,
    }

    ORDER_LINE_PATTERN: Sequence[tuple[int, int]] = (
        (1, 60),
        (2, 30),
        (3, 5),
        (4, 4),
        (5, 1),
    )

    QUANTITY_PATTERN: Sequence[tuple[int, int]] = (
        (1, 55),
        (2, 30),
        (3, 10),
        (4, 4),
        (5, 1),
    )

    PRICE_MULTIPLIER_PATTERN: Sequence[tuple[float, int]] = (
        (0.97, 5),
        (0.99, 10),
        (1.00, 20),
        (1.02, 10),
        (1.04, 5),
    )

    SUBCATEGORY_PATTERN: Sequence[tuple[str, int]] = (
        ("Coffee", 60),
        ("Pastries", 25),
        ("Tea", 15),
    )

    TIME_PATTERN: Sequence[tuple[time, int]] = (
        (time(6, 45), 4),
        (time(7, 30), 14),
        (time(8, 15), 16),
        (time(9, 0), 8),
        (time(11, 0), 6),
        (time(12, 15), 10),
        (time(14, 0), 8),
        (time(16, 0), 12),
        (time(18, 30), 12),
        (time(20, 0), 6),
        (time(21, 15), 4),
    )

    TREND_START_WEIGHT: float = 0.85
    TREND_END_WEIGHT: float = 1.20

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | None = None,
        **kwargs,
    ) -> None:
        # Initialize compression mixin with all kwargs
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        if output_dir is None:
            output_dir = get_benchmark_runs_datagen_path("coffeeshop", scale_factor)
        self.output_dir = create_path_handler(output_dir)

        self.start_date = date(2023, 1, 1)
        self.end_date = date(2024, 12, 31)

        self._location_seeds: list[LocationSeed] = load_location_seeds()
        self._product_windows: list[_ProductWindow] = self._build_product_windows(load_product_seeds())

        self._order_line_sequence = self._expand_pattern(self.ORDER_LINE_PATTERN)
        self._quantity_sequence = self._expand_pattern(self.QUANTITY_PATTERN)
        self._price_multiplier_sequence = self._expand_pattern(self.PRICE_MULTIPLIER_PATTERN)
        self._subcategory_sequence = self._expand_pattern(self.SUBCATEGORY_PATTERN)
        self._time_sequence = self._expand_pattern(self.TIME_PATTERN)

        self._reset_generation_state()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def generate_data(self, tables: list[str] | None = None) -> dict[str, str]:
        """Generate CoffeeShop data for the requested tables."""
        self._reset_generation_state()

        def local_generator(output_path):
            return self._generate_data_local(output_path, tables)

        if self._is_cloud_output(self.output_dir):
            table_paths = self._handle_cloud_or_local_generation(self.output_dir, local_generator, False)
        else:
            table_paths = local_generator(self.output_dir)

        self._write_manifest(table_paths)
        return {name: str(path) for name, path in table_paths.items()}

    # ------------------------------------------------------------------
    # Core generation helpers
    # ------------------------------------------------------------------
    def _generate_data_local(self, output_dir: Path, tables: list[str] | None) -> dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)

        requested = {"dim_locations", "dim_products", "order_lines"} if tables is None else set(tables)

        if "order_lines" in requested:
            requested.update({"dim_locations", "dim_products"})

        ordered_tables = [t for t in ["dim_locations", "dim_products", "order_lines"] if t in requested]
        if not ordered_tables:
            return {}

        file_paths: dict[str, Path] = {}

        for table in ordered_tables:
            if table == "dim_locations":
                file_paths[table] = self._write_dim_locations(output_dir)
            elif table == "dim_products":
                file_paths[table] = self._write_dim_products(output_dir)
            elif table == "order_lines":
                file_paths[table] = self._write_order_lines(output_dir)

        return file_paths

    def _write_dim_locations(self, output_dir: Path) -> Path:
        filename = self.get_compressed_filename("dim_locations.csv")
        path = output_dir / filename

        with self.open_output_file(path, "wt") as handle:
            writer = csv.writer(handle)
            for seed in self._location_seeds:
                writer.writerow(
                    [
                        seed.record_id,
                        seed.location_id,
                        seed.city,
                        seed.state,
                        seed.country,
                        seed.region,
                    ]
                )

        self._table_row_counts["dim_locations"] = len(self._location_seeds)
        return path

    def _write_dim_products(self, output_dir: Path) -> Path:
        filename = self.get_compressed_filename("dim_products.csv")
        path = output_dir / filename

        with self.open_output_file(path, "wt") as handle:
            writer = csv.writer(handle)
            for seed in self._iter_product_seeds_in_order():
                writer.writerow(
                    [
                        seed.record_id,
                        seed.product_id,
                        seed.name,
                        seed.category,
                        seed.subcategory,
                        f"{seed.standard_cost:.2f}",
                        f"{seed.standard_price:.2f}",
                        seed.from_date,
                        seed.to_date,
                    ]
                )

        total_products = sum(
            len(window.seeds_by_subcategory[sub])
            for window in self._product_windows
            for sub in window.seeds_by_subcategory
        )
        self._table_row_counts["dim_products"] = total_products
        return path

    def _write_order_lines(self, output_dir: Path) -> Path:
        filename = self.get_compressed_filename("order_lines.csv")
        path = output_dir / filename

        order_count = self.calculate_order_count(self.scale_factor)
        daily_distribution = self._distribute_daily_orders(order_count)
        location_map = self._group_locations_by_region()

        order_id = 1
        total_lines = 0

        with self.open_output_file(path, "wt") as handle:
            writer = csv.writer(handle)

            for current_date in sorted(daily_distribution.keys()):
                orders_for_date = daily_distribution[current_date]
                if orders_for_date == 0:
                    continue

                region_counts = self._distribute_with_weights(
                    orders_for_date,
                    {region: self.REGION_WEIGHTS.get(region, 1.0) for region in location_map},
                )

                for region, count in region_counts.items():
                    if count == 0:
                        continue

                    locations = location_map[region]
                    location_weights = {seed.record_id: 1.0 for seed in locations}
                    location_counts = self._distribute_with_weights(count, location_weights)

                    for seed in locations:
                        orders_for_location = location_counts.get(seed.record_id, 0)
                        if orders_for_location == 0:
                            continue

                        for _ in range(orders_for_location):
                            line_total = next(self._order_line_cycle)
                            order_time = next(self._time_cycle)

                            for line_number in range(1, line_total + 1):
                                subcategory = next(self._subcategory_cycle)
                                product_seed = self._select_product_for_date(current_date, subcategory)
                                quantity = next(self._quantity_cycle)
                                base_price = product_seed.standard_price
                                price_multiplier = next(self._price_multiplier_cycle)
                                unit_price = round(base_price * price_multiplier, 2)
                                total_price = round(unit_price * quantity, 2)

                                writer.writerow(
                                    [
                                        order_id,
                                        line_number,
                                        seed.record_id,
                                        seed.location_id,
                                        product_seed.record_id,
                                        product_seed.product_id,
                                        current_date.isoformat(),
                                        order_time.strftime("%H:%M:%S"),
                                        quantity,
                                        f"{unit_price:.2f}",
                                        f"{total_price:.2f}",
                                        seed.region,
                                    ]
                                )
                                total_lines += 1

                            order_id += 1

        self._table_row_counts["order_lines"] = total_lines
        return path

    def _reset_generation_state(self) -> None:
        """Reset mutable state so repeated runs remain deterministic."""

        self._product_indices = [defaultdict(int) for _ in self._product_windows]
        self._order_line_cycle = cycle(self._order_line_sequence)
        self._quantity_cycle = cycle(self._quantity_sequence)
        self._price_multiplier_cycle = cycle(self._price_multiplier_sequence)
        self._subcategory_cycle = cycle(self._subcategory_sequence)
        self._time_cycle = cycle(self._time_sequence)
        self._table_row_counts: dict[str, int] = {}

    # ------------------------------------------------------------------
    # Helper utilities
    # ------------------------------------------------------------------
    @staticmethod
    def calculate_order_count(scale_factor: float) -> int:
        """Translate a scale factor into a number of orders."""
        base = CoffeeShopDataGenerator.SF1_ORDER_COUNT * scale_factor
        return max(1, int(round(base)))

    def _group_locations_by_region(self) -> dict[str, list[LocationSeed]]:
        grouped: dict[str, list[LocationSeed]] = defaultdict(list)
        for seed in sorted(self._location_seeds, key=lambda s: s.record_id):
            grouped[seed.region].append(seed)
        return grouped

    def _distribute_daily_orders(self, total_orders: int) -> dict[date, int]:
        days = (self.end_date - self.start_date).days + 1
        weights: dict[date, float] = {}
        for day_index in range(days):
            current_date = self.start_date + timedelta(days=day_index)
            month_weight = self.MONTH_WEIGHTS.get(current_date.month, 1.0)
            trend_weight = self._trend_weight(day_index, days)
            weights[current_date] = month_weight * trend_weight
        return self._distribute_with_weights(total_orders, weights)

    def _trend_weight(self, day_index: int, total_days: int) -> float:
        if total_days <= 1:
            return self.TREND_END_WEIGHT
        progress = day_index / (total_days - 1)
        return self.TREND_START_WEIGHT + (self.TREND_END_WEIGHT - self.TREND_START_WEIGHT) * progress

    def _select_product_for_date(self, order_date: date, subcategory: str) -> ProductSeed:
        for window_index, window in enumerate(self._product_windows):
            if window.start <= order_date <= window.end:
                seeds = window.seeds_by_subcategory.get(subcategory)
                if not seeds:
                    # Fallback: use whatever is available in this window
                    seeds = [seed for items in window.seeds_by_subcategory.values() for seed in items]
                cursor = self._product_indices[window_index]
                position = cursor[subcategory] % len(seeds)
                cursor[subcategory] = cursor[subcategory] + 1
                return seeds[position]
        raise ValueError(f"No product seeds available for date {order_date}")

    def _distribute_with_weights(self, total: int, weights: Mapping[T, float]) -> dict[T, int]:
        if total <= 0:
            return dict.fromkeys(weights, 0)

        normalized_keys = list(weights.keys())
        weight_values = [max(weights[key], 0.0) for key in normalized_keys]
        weight_sum = sum(weight_values)

        if math.isclose(weight_sum, 0.0):
            equal_share = total // len(normalized_keys)
            result = dict.fromkeys(normalized_keys, equal_share)
            for i in range(total - equal_share * len(normalized_keys)):
                result[normalized_keys[i]] += 1
            return result

        scaled = [total * w / weight_sum for w in weight_values]
        base_counts = [int(math.floor(value)) for value in scaled]
        remainder = total - sum(base_counts)

        remainders = [(scaled[i] - base_counts[i], i) for i in range(len(base_counts))]
        remainders.sort(reverse=True)

        for idx in range(remainder):
            _, position = remainders[idx % len(remainders)]
            base_counts[position] += 1

        return {normalized_keys[i]: base_counts[i] for i in range(len(normalized_keys))}

    def _build_product_windows(self, seeds: Iterable[ProductSeed]) -> list[_ProductWindow]:
        grouped: dict[tuple[str, str], list[ProductSeed]] = defaultdict(list)
        for seed in seeds:
            grouped[(seed.from_date, seed.to_date)].append(seed)

        windows: list[_ProductWindow] = []
        for (start_raw, end_raw), items in sorted(grouped.items()):
            start_date = date.fromisoformat(start_raw)
            end_date = date.fromisoformat(end_raw)
            seeds_by_subcategory: dict[str, list[ProductSeed]] = defaultdict(list)
            for seed in sorted(items, key=lambda s: (s.subcategory, s.product_id, s.record_id)):
                seeds_by_subcategory[seed.subcategory].append(seed)
            windows.append(
                _ProductWindow(start=start_date, end=end_date, seeds_by_subcategory=dict(seeds_by_subcategory))
            )
        return windows

    def _iter_product_seeds_in_order(self) -> Iterable[ProductSeed]:
        for window in self._product_windows:
            for subcategory in sorted(window.seeds_by_subcategory.keys()):
                yield from window.seeds_by_subcategory[subcategory]

    @staticmethod
    def _expand_pattern(pattern: Sequence[tuple[T, int]]) -> list[T]:
        expanded: list[T] = []
        for value, count in pattern:
            expanded.extend([value] * count)
        return expanded

    def _write_manifest(self, table_paths: dict[str, Path]) -> None:
        if not table_paths:
            return

        manifest = DataGenerationManifest(
            output_dir=self.output_dir,
            benchmark="coffeeshop",
            scale_factor=self.scale_factor,
            compression=resolve_compression_metadata(self),
            parallel=1,
            seed=None,
            formats=["csv"],
        )

        for table, path in table_paths.items():
            manifest.add_entry(table, path, row_count=self._table_row_counts.get(table, 0), format="csv")

        manifest.write()


__all__ = ["CoffeeShopDataGenerator"]
