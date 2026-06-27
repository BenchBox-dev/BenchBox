"""Star Schema Benchmark (SSB) data generator.

This module generates synthetic data for the Star Schema Benchmark according
to the SSB specification. The data is based on TPC-H but with a denormalized
star schema structure.

The generator creates:
- DATE dimension (2556 rows for 7 years)
- CUSTOMER dimension (30,000 * scale_factor)
- SUPPLIER dimension (2,000 * scale_factor)
- PART dimension (200,000 * scale_factor)
- LINEORDER fact table (6,000,000 * scale_factor)

Copyright 2026 Joe Harris / BenchBox Project

This implementation is derived from TPC Benchmark™ H (TPC-H) - Copyright © Transaction Processing Performance Council

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import csv
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin, create_path_handler
from benchbox.utils.compression_mixin import CompressionMixin
from benchbox.utils.file_format import detect_compression, validate_tbl_compression_consistency


class SSBDataGenerator(CompressionMixin, CloudStorageGeneratorMixin):
    """Generator for Star Schema Benchmark data."""

    def __init__(
        self,
        scale_factor: float = 1.0,
        output_dir: Path | None = None,
        *,
        verbose: int | bool = 0,
        quiet: bool = False,
        **kwargs,
    ) -> None:
        """Initialize SSB data generator.

        Args:
            scale_factor: Scale factor for data generation (1.0 = standard size)
            output_dir: Directory to write generated data files
            **kwargs: Additional arguments including compression options
        """
        # Initialize compression mixin first
        super().__init__(**kwargs)

        self.scale_factor = scale_factor
        self.output_dir = create_path_handler(output_dir) if output_dir else Path.cwd()
        # Verbosity flags (stored for potential progress logging)
        if isinstance(verbose, bool):
            self.verbose_level = 1 if verbose else 0
        else:
            self.verbose_level = int(verbose or 0)
        self.verbose_enabled = self.verbose_level >= 1 and not quiet
        self.very_verbose = self.verbose_level >= 2 and not quiet
        self.quiet = bool(quiet)

        # Data size constants (base sizes for scale_factor = 1.0)
        self.base_customers = 30000
        self.base_suppliers = 2000
        self.base_parts = 200000
        self.base_lineorders = 6000000
        self.date_rows = 2556  # Fixed: 7 years of dates

        # Initialize random seed for reproducible data
        random.seed(42)

        # Data generation dictionaries
        self._nations = [
            "ALGERIA",
            "ARGENTINA",
            "BRAZIL",
            "CANADA",
            "EGYPT",
            "ETHIOPIA",
            "FRANCE",
            "GERMANY",
            "INDIA",
            "INDONESIA",
            "IRAN",
            "IRAQ",
            "JAPAN",
            "JORDAN",
            "KENYA",
            "MOROCCO",
            "MOZAMBIQUE",
            "PERU",
            "CHINA",
            "ROMANIA",
            "SAUDI ARABIA",
            "VIETNAM",
            "RUSSIA",
            "UNITED KINGDOM",
            "UNITED STATES",
        ]

        self._regions = ["AFRICA", "AMERICA", "ASIA", "EUROPE", "MIDDLE EAST"]

        self._segments = [
            "AUTOMOBILE",
            "BUILDING",
            "FURNITURE",
            "HOUSEHOLD",
            "MACHINERY",
        ]

        self._priorities = [
            "1-URGENT",
            "2-HIGH",
            "3-MEDIUM",
            "4-NOT SPECIFIED",
            "5-LOW",
        ]

        self._ship_modes = ["REG AIR", "AIR", "RAIL", "SHIP", "TRUCK", "MAIL", "FOB"]

    def generate_data(self, tables: list[str] | None = None) -> dict[str, str]:
        """Generate SSB data files.

        Args:
            tables: Optional list of table names to generate. If None, generates all.

        Returns:
            Dictionary mapping table names to file paths
        """

        # Use centralized cloud/local generation handler
        def local_generate_func(output_dir: Path) -> dict[str, Path]:
            return self._generate_data_local(output_dir, tables)

        result = self._handle_cloud_or_local_generation(
            self.output_dir,
            local_generate_func,
            verbose=True,  # SSB doesn't have self.verbose, so use True
        )

        # Convert Path objects to strings for compatibility
        return {k: str(v) for k, v in result.items()}

    def _generate_data_local(self, output_dir: Path, tables: list[str] | None = None) -> dict[str, Path]:
        """Generate SSB data files locally (original implementation)."""
        if tables is None:
            tables = ["date", "customer", "supplier", "part", "lineorder"]

        output_dir.mkdir(parents=True, exist_ok=True)

        # Temporarily update the output directory for internal methods
        original_output_dir = self.output_dir
        self.output_dir = output_dir

        try:
            file_paths: dict[str, Path] = {}

            if "date" in tables:
                file_paths["date"] = Path(self._generate_date_data())
            if "customer" in tables:
                file_paths["customer"] = Path(self._generate_customer_data())
            if "supplier" in tables:
                file_paths["supplier"] = Path(self._generate_supplier_data())
            if "part" in tables:
                file_paths["part"] = Path(self._generate_part_data())
            if "lineorder" in tables:
                file_paths["lineorder"] = Path(self._generate_lineorder_data())
            # Validate file format consistency: when compression enabled, no raw base files should remain
            self._validate_file_format_consistency(output_dir)

            # Write manifest with sizes and row counts
            self._write_manifest(output_dir, file_paths)

            return file_paths
        finally:
            # Restore original output directory
            self.output_dir = original_output_dir

    # DATE dimension spans 7 years; kept as a shared constant so the LINEORDER
    # generator can sample valid order dates from the same range.
    _DATE_START = datetime(1992, 1, 1)
    _DATE_END = datetime(1998, 12, 31)

    # Canonical SSB date strings are English month/day names. strftime("%A"/"%B"/"%b")
    # is LOCALE-dependent (e.g. 'Dec1997' becomes 'déc1997' under a French locale),
    # which would silently desync the canonical query literals (notably Q3.4's
    # d_yearmonth='Dec1997') from the generated data. Format these from fixed tables
    # so the output is identical on every machine/locale.
    _MONTH_NAMES = (
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    )
    _MONTH_ABBR = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    # Indexed by datetime.weekday() (Monday == 0).
    _DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

    def _date_objects(self) -> list[datetime]:
        """Return every DATE dimension day as a datetime, in chronological order.

        Single source of truth for the date range so the DATE dimension and the
        LINEORDER order/commit dates cannot drift apart.
        """
        days: list[datetime] = []
        current = self._DATE_START
        while current <= self._DATE_END:
            days.append(current)
            current += timedelta(days=1)
        return days

    def _generate_date_data(self) -> str:
        """Generate the DATE dimension data."""
        filename = self.get_compressed_filename("date.tbl")
        file_path = self.output_dir / filename

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for current_date in self._date_objects():
                d_datekey = int(current_date.strftime("%Y%m%d"))
                d_date = current_date.strftime("%Y-%m-%d")
                d_dayofweek = self._DAY_NAMES[current_date.weekday()]
                d_month = self._MONTH_NAMES[current_date.month - 1]
                d_year = current_date.year
                d_yearmonthnum = int(current_date.strftime("%Y%m"))
                d_yearmonth = f"{self._MONTH_ABBR[current_date.month - 1]}{current_date.year}"
                d_daynuminweek = current_date.weekday() + 1
                d_daynuminmonth = current_date.day
                d_daynuminyear = current_date.timetuple().tm_yday
                d_monthnuminyear = current_date.month
                d_weeknuminyear = current_date.isocalendar()[1]

                # Determine selling season
                month = current_date.month
                if month in [12, 1, 2]:
                    d_sellingseason = "Winter"
                elif month in [3, 4, 5]:
                    d_sellingseason = "Spring"
                elif month in [6, 7, 8]:
                    d_sellingseason = "Summer"
                else:
                    d_sellingseason = "Fall"

                # Flags
                d_lastdayinweekfl = 1 if current_date.weekday() == 6 else 0  # Sunday

                # Calculate last day of month properly handling December
                if current_date.month == 12:
                    next_month_first = current_date.replace(year=current_date.year + 1, month=1, day=1)
                else:
                    next_month_first = current_date.replace(month=current_date.month + 1, day=1)
                last_day_of_month = (next_month_first - timedelta(days=1)).day
                d_lastdayinmonthfl = 1 if current_date.day == last_day_of_month else 0
                d_holidayfl = (
                    1
                    if (current_date.month == 12 and current_date.day == 25)
                    or (current_date.month == 1 and current_date.day == 1)
                    else 0
                )
                d_weekdayfl = 1 if current_date.weekday() < 5 else 0

                row = [
                    d_datekey,
                    d_date,
                    d_dayofweek,
                    d_month,
                    d_year,
                    d_yearmonthnum,
                    d_yearmonth,
                    d_daynuminweek,
                    d_daynuminmonth,
                    d_daynuminyear,
                    d_monthnuminyear,
                    d_weeknuminyear,
                    d_sellingseason,
                    d_lastdayinweekfl,
                    d_lastdayinmonthfl,
                    d_holidayfl,
                    d_weekdayfl,
                ]

                writer.writerow(row)

        return str(file_path)

    def _validate_file_format_consistency(self, target_dir: Path) -> None:
        """Ensure no raw .tbl files exist when compression is enabled; ensure no empty compressed files."""
        if not self.should_use_compression():
            return
        validate_tbl_compression_consistency(target_dir, self.get_compressor().get_file_extension())

    def _write_manifest(self, output_dir: Path, table_paths: dict[str, Path]) -> None:
        import json
        from datetime import datetime

        manifest = {
            "benchmark": "ssb",
            "scale_factor": self.scale_factor,
            "compression": {
                "enabled": self.should_use_compression(),
                "type": getattr(self, "compression_type", None),
                "level": getattr(self, "compression_level", None),
            },
            "parallel": 1,
            "created_at": datetime.now(timezone.utc).isoformat() + "Z",
            "generator_version": "v1",
            "tables": {},
        }
        for table, path in table_paths.items():
            p = Path(path)
            size = p.stat().st_size if p.exists() else 0
            # Count rows efficiently
            rows = 0
            try:
                compression = detect_compression(p)
                if compression == "gzip":
                    import gzip

                    with gzip.open(p, "rt") as f:
                        rows = sum(1 for _ in f)
                elif compression == "zstd":
                    try:
                        import zstandard as zstd

                        dctx = zstd.ZstdDecompressor()
                        with open(p, "rb") as fh, dctx.stream_reader(fh) as reader:
                            import io

                            rows = sum(1 for _ in io.TextIOWrapper(reader, encoding="utf-8"))
                    except Exception:
                        rows = 0
                elif compression == "bzip2":
                    import bz2

                    with bz2.open(p, "rt") as f:
                        rows = sum(1 for _ in f)
                elif compression == "xz":
                    import lzma

                    with lzma.open(p, "rt") as f:
                        rows = sum(1 for _ in f)
                else:
                    with open(p, "rb") as f:
                        rows = sum(1 for _ in f)
            except Exception:
                rows = 0
            manifest["tables"].setdefault(table, []).append(
                {
                    "path": p.name,
                    "size_bytes": size,
                    "row_count": rows,
                }
            )
        out = output_dir / "_datagen_manifest.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _generate_customer_data(self) -> str:
        """Generate the CUSTOMER dimension data."""
        filename = self.get_compressed_filename("customer.tbl")
        file_path = self.output_dir / filename
        num_customers = int(self.base_customers * self.scale_factor)

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for i in range(1, num_customers + 1):
                c_custkey = i
                c_name = f"Customer#{i:09d}"
                c_address = f"Address {random.randint(1, 999)} Street"

                # Assign nation and region
                nation = random.choice(self._nations)
                if nation in [
                    "ALGERIA",
                    "EGYPT",
                    "ETHIOPIA",
                    "KENYA",
                    "MOROCCO",
                    "MOZAMBIQUE",
                ]:
                    region = "AFRICA"
                elif nation in [
                    "ARGENTINA",
                    "BRAZIL",
                    "CANADA",
                    "PERU",
                    "UNITED STATES",
                ]:
                    region = "AMERICA"
                elif nation in ["INDIA", "INDONESIA", "CHINA", "JAPAN", "VIETNAM"]:
                    region = "ASIA"
                elif nation in [
                    "FRANCE",
                    "GERMANY",
                    "ROMANIA",
                    "RUSSIA",
                    "UNITED KINGDOM",
                ]:
                    region = "EUROPE"
                else:
                    region = "MIDDLE EAST"

                # Canonical SSB c_city is the first 9 chars of the nation name plus a
                # city digit, e.g. 'UNITED KI1' (10 chars), not an 8-char truncation.
                c_city = f"{nation[:9]}{random.randint(0, 9)}"
                c_nation = nation
                c_region = region
                c_phone = f"{random.randint(10, 99)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
                c_mktsegment = random.choice(self._segments)

                row = [
                    c_custkey,
                    c_name,
                    c_address,
                    c_city,
                    c_nation,
                    c_region,
                    c_phone,
                    c_mktsegment,
                ]
                writer.writerow(row)

        return str(file_path)

    def _generate_supplier_data(self) -> str:
        """Generate the SUPPLIER dimension data."""
        filename = self.get_compressed_filename("supplier.tbl")
        file_path = self.output_dir / filename
        num_suppliers = int(self.base_suppliers * self.scale_factor)

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for i in range(1, num_suppliers + 1):
                s_suppkey = i
                s_name = f"Supplier#{i:09d}"
                s_address = f"Address {random.randint(1, 999)} Avenue"

                # Assign nation and region (same logic as customer)
                nation = random.choice(self._nations)
                if nation in [
                    "ALGERIA",
                    "EGYPT",
                    "ETHIOPIA",
                    "KENYA",
                    "MOROCCO",
                    "MOZAMBIQUE",
                ]:
                    region = "AFRICA"
                elif nation in [
                    "ARGENTINA",
                    "BRAZIL",
                    "CANADA",
                    "PERU",
                    "UNITED STATES",
                ]:
                    region = "AMERICA"
                elif nation in ["INDIA", "INDONESIA", "CHINA", "JAPAN", "VIETNAM"]:
                    region = "ASIA"
                elif nation in [
                    "FRANCE",
                    "GERMANY",
                    "ROMANIA",
                    "RUSSIA",
                    "UNITED KINGDOM",
                ]:
                    region = "EUROPE"
                else:
                    region = "MIDDLE EAST"

                # Canonical SSB s_city: first 9 chars of the nation name + a city digit,
                # e.g. 'UNITED KI1' (10 chars). Mirrors c_city in the customer table.
                s_city = f"{nation[:9]}{random.randint(0, 9)}"
                s_nation = nation
                s_region = region
                s_phone = f"{random.randint(10, 99)}-{random.randint(100, 999)}-{random.randint(1000, 9999)}"

                row = [
                    s_suppkey,
                    s_name,
                    s_address,
                    s_city,
                    s_nation,
                    s_region,
                    s_phone,
                ]
                writer.writerow(row)

        return str(file_path)

    def _generate_part_data(self) -> str:
        """Generate the PART dimension data."""
        filename = self.get_compressed_filename("part.tbl")
        file_path = self.output_dir / filename
        num_parts = int(self.base_parts * self.scale_factor)

        colors = [
            "almond",
            "antique",
            "aquamarine",
            "azure",
            "beige",
            "bisque",
            "black",
            "blanched",
            "blue",
            "blush",
            "brown",
            "burlywood",
            "burnished",
        ]

        types = ["STANDARD", "SMALL", "MEDIUM", "LARGE", "ECONOMY", "PROMO"]
        containers = [
            "SM CASE",
            "SM BOX",
            "SM PACK",
            "SM PKG",
            "MED BAG",
            "MED BOX",
            "MED PKG",
            "MED PACK",
            "LG CASE",
            "LG BOX",
            "LG PACK",
            "LG PKG",
        ]

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            for i in range(1, num_parts + 1):
                p_partkey = i
                p_name = f"Part {i}"

                # Manufacturer hierarchy (canonical SSB formats):
                #   p_mfgr     = 'MFGR#' + M                  -> 'MFGR#1'..'MFGR#5'
                #   p_category = 'MFGR#' + M + C              -> 'MFGR#11'..'MFGR#55'
                #   p_brand1   = 'MFGR#' + M + C + BB(01-40)  -> 'MFGR#1101'..'MFGR#5540'
                # where mfgr M and category C are single digits 1..5 and brand BB is
                # 01..40. The three dimensions are varied at different rates over the
                # full 1000-value brand space (5 mfgr * 5 categories * 40 brands):
                # mfgr fastest, then category, then brand. This is deterministic and
                # covers every (mfgr, category) pair within the first 25 parts -- so
                # all of p_mfgr/p_category appear even at tiny scales -- while every
                # canonical value (e.g. p_category 'MFGR#12', p_brand1 'MFGR#2221')
                # still appears once num_parts >= 1000.
                mfgr_num = (i - 1) % 5 + 1
                category_num = ((i - 1) // 5) % 5 + 1
                brand_num = ((i - 1) // 25) % 40 + 1

                p_mfgr = f"MFGR#{mfgr_num}"
                p_category = f"MFGR#{mfgr_num}{category_num}"
                p_brand1 = f"MFGR#{mfgr_num}{category_num}{brand_num:02d}"

                p_color = random.choice(colors)
                p_type = random.choice(types)
                p_size = random.randint(1, 50)
                p_container = random.choice(containers)

                row = [
                    p_partkey,
                    p_name,
                    p_mfgr,
                    p_category,
                    p_brand1,
                    p_color,
                    p_type,
                    p_size,
                    p_container,
                ]
                writer.writerow(row)

        return str(file_path)

    def _generate_lineorder_data(self) -> str:
        """Generate the LINEORDER fact table data."""
        filename = self.get_compressed_filename("lineorder.tbl")
        file_path = self.output_dir / filename
        num_lineorders = int(self.base_lineorders * self.scale_factor)

        num_customers = int(self.base_customers * self.scale_factor)
        num_suppliers = int(self.base_suppliers * self.scale_factor)
        num_parts = int(self.base_parts * self.scale_factor)

        # lo_orderdate is a foreign key into the DATE dimension, so it must be one of
        # the dimension's actual days. Drawing a raw random integer in
        # [19920101, 19981231] would mostly land on non-dates (e.g. 19920230), which
        # never join to DATE and silently orphan ~95% of the fact table. Sample from
        # the exact set of DATE dimension days instead (shared single source).
        valid_dates = self._date_objects()

        with self.open_output_file(file_path, "wt") as f:
            writer = csv.writer(f, delimiter="|")

            order_key = 1
            line_number = 0  # Initialize before loop to avoid undefined variable
            for i in range(1, num_lineorders + 1):
                # Generate new order key occasionally (simulate multi-line orders)
                if i == 1 or random.random() < 0.7:  # 70% chance of new order
                    order_key += 1
                    line_number = 1
                else:
                    line_number += 1

                lo_orderkey = order_key
                lo_linenumber = line_number
                lo_custkey = random.randint(1, num_customers)
                lo_partkey = random.randint(1, num_parts)
                lo_suppkey = random.randint(1, num_suppliers)

                # Pick a real date so the row joins to the DATE dimension.
                order_date = random.choice(valid_dates)
                lo_orderdate = int(order_date.strftime("%Y%m%d"))

                lo_orderpriority = random.choice(self._priorities)
                lo_shippriority = random.randint(0, 1)
                lo_quantity = random.randint(1, 50)

                # Price calculations (in cents to avoid decimals)
                unit_price = random.randint(90000, 200000)  # $900 to $2000
                lo_extendedprice = unit_price * lo_quantity
                lo_ordtotalprice = lo_extendedprice  # Simplified

                lo_discount = random.randint(0, 10)  # 0-10% discount
                lo_revenue = lo_extendedprice * (100 - lo_discount) // 100

                lo_supplycost = unit_price * random.randint(50, 80) // 100  # 50-80% of unit price
                lo_tax = random.randint(0, 8)  # 0-8% tax

                # Commit date is 1-121 days after the order date. Compute it as a real
                # calendar date so it stays a valid YYYYMMDD value -- plain integer
                # addition on the datekey would yield non-dates (e.g. 19971235).
                commit_date = order_date + timedelta(days=random.randint(1, 121))
                lo_commitdate = int(commit_date.strftime("%Y%m%d"))
                lo_shipmode = random.choice(self._ship_modes)

                row = [
                    lo_orderkey,
                    lo_linenumber,
                    lo_custkey,
                    lo_partkey,
                    lo_suppkey,
                    lo_orderdate,
                    lo_orderpriority,
                    lo_shippriority,
                    lo_quantity,
                    lo_extendedprice,
                    lo_ordtotalprice,
                    lo_discount,
                    lo_revenue,
                    lo_supplycost,
                    lo_tax,
                    lo_commitdate,
                    lo_shipmode,
                ]

                writer.writerow(row)

        return str(file_path)
