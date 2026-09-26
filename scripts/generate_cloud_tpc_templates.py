#!/usr/bin/env python3
"""Generate cloud TPC tuned templates from the logical tuning profile.

Renders one `<benchmark>_tuned.yaml` per platform/benchmark from the
required candidates in `benchbox/core/tuning/profiles/tpc.yaml`, using each
platform's logical-to-physical mapping
(`benchbox.core.tuning.platform_capabilities.map_candidate_to_platform`).

Platform rules honored here (mirroring the mappers, not reimplementing them):

- BigQuery: at most 4 clustering columns per table; partitioning first.
- Redshift: single DISTKEY per table (first distribution candidate);
  remaining locality roles become compound sortkey entries.
- Snowflake: everything the mapper accepts becomes clustering.

Only platforms whose mapped tuning types reach the physical layout at
execution time are generated here. BigQuery partitioning/clustering and
Redshift distribution/sorting are preview-only or inspect-and-log in the
current adapters (see benchbox/core/tuning/capability_registry.py), so they
stay out of the certified set until the adapters render them for real;
Snowflake clustering renders post-load via ALTER TABLE ... CLUSTER BY and
is the one certified platform in this generator today.

Usage:
    uv run -- python scripts/generate_cloud_tpc_templates.py --write
    uv run -- python scripts/generate_cloud_tpc_templates.py --check
    uv run -- python scripts/generate_cloud_tpc_templates.py --write --output-root examples/tunings
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import yaml

CHECKOUT_ROOT = Path(__file__).resolve().parents[1]
if str(CHECKOUT_ROOT) not in sys.path:
    sys.path.insert(0, str(CHECKOUT_ROOT))

from benchbox.core.tuning.platform_capabilities import (  # noqa: E402
    map_candidate_to_platform,
)
from benchbox.core.tuning.workload_profiles import (  # noqa: E402
    load_tpc_tuning_profile,
)

PLATFORMS = ("snowflake",)
BENCHMARKS = ("tpch", "tpcds")

PLATFORM_TITLES = {
    "bigquery": "BigQuery",
    "redshift": "Redshift",
    "snowflake": "Snowflake",
}

HEADER = """# {platform_title} {benchmark_title} Tuned Configuration
# Generated from the logical tuning profile (benchbox/core/tuning/profiles/tpc.yaml)
# by scripts/generate_cloud_tpc_templates.py. Do not hand-edit: re-run the
# generator after changing the profile. Provides platform-native tuning for
# {benchmark_title} benchmark workloads.

primary_keys:
  enabled: true
  enforce_uniqueness: true
  nullable: false

foreign_keys:
  enabled: true
  enforce_referential_integrity: true
  on_delete_action: CASCADE
  on_update_action: RESTRICT

unique_constraints:
  enabled: true
  ignore_nulls: false

check_constraints:
  enabled: true
  enforce_on_insert: true
  enforce_on_update: true

platform_optimizations:
  z_ordering_enabled: false
  z_ordering_columns: []
  auto_optimize_enabled: false
  auto_compact_enabled: false
  bloom_filters_enabled: false
  bloom_filter_columns: []
  materialized_views_enabled: false

table_tunings:
"""


def _order_entries(entries: list[dict]) -> list[dict]:
    for position, entry in enumerate(entries, start=1):
        entry["order"] = position
    return entries


def render_table(
    platform: str,
    table: str,
    candidates: list,
) -> dict:
    """Render one table_tunings entry from mapped candidates."""
    partitioning: list[dict] = []
    clustering: list[dict] = []
    distribution: list[dict] = []
    sorting: list[dict] = []

    for candidate in candidates:
        mapping = map_candidate_to_platform(platform, candidate)
        if mapping.decision != "mapped":
            continue
        for tuning_type in mapping.tuning_types:
            entry = {"name": candidate.column, "type": candidate.type}
            if tuning_type == "partitioning":
                partitioning.append(entry)
            elif tuning_type == "clustering":
                if mapping.max_columns is not None and len(clustering) >= mapping.max_columns:
                    continue
                clustering.append(entry)
            elif tuning_type == "distribution":
                if not distribution:
                    distribution.append(entry)
            elif tuning_type == "sorting":
                sorting.append(entry)

    block: dict = {"table_name": table}
    if partitioning:
        block["partitioning"] = _order_entries(partitioning)
    if platform == "redshift":
        if distribution:
            block["distribution"] = _order_entries(distribution)
        if sorting:
            block["sorting"] = _order_entries(sorting)
    else:
        if clustering:
            block["clustering"] = _order_entries(clustering)
        if sorting and platform == "snowflake":
            # Snowflake folds sort hints into clustering; keep both only
            # when clustering did not already carry the column.
            extra = [e for e in sorting if e["name"] not in {c["name"] for c in clustering}]
            if extra:
                block["sorting"] = _order_entries(extra)
        elif sorting:
            block["sorting"] = _order_entries(sorting)
    return block


def render_template(platform: str, benchmark: str) -> str:
    """Render the full tuned YAML for one platform/benchmark."""
    profile = load_tpc_tuning_profile()
    by_table: dict[str, list] = defaultdict(list)
    for candidate in profile.required_candidates(benchmark):
        by_table[candidate.table].append(candidate)

    lines = [
        HEADER.format(
            platform_title=PLATFORM_TITLES[platform],
            benchmark_title=benchmark.upper(),
        ).rstrip()
    ]
    for table in sorted(by_table):
        block = render_table(platform, table, by_table[table])
        dumped = yaml.safe_dump({table: block}, sort_keys=False, default_flow_style=False)
        lines.append("  " + dumped.replace("\n", "\n  ").rstrip())
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def template_path(output_root: Path, platform: str, benchmark: str) -> Path:
    return output_root / platform / f"{benchmark}_tuned.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="Write generated templates.")
    parser.add_argument("--check", action="store_true", help="Fail when generated output differs.")
    parser.add_argument(
        "--output-root",
        default="examples/tunings",
        help="Template tree root (default: examples/tunings).",
    )
    args = parser.parse_args(argv)
    if not args.write and not args.check:
        parser.error("pass --write and/or --check")

    root = Path(args.output_root)
    if not args.write:
        root = CHECKOUT_ROOT / args.output_root
    failures: list[str] = []
    for platform in PLATFORMS:
        for benchmark in BENCHMARKS:
            expected = render_template(platform, benchmark)
            path = template_path(root if args.write else CHECKOUT_ROOT / args.output_root, platform, benchmark)
            if args.check and (not path.is_file() or path.read_text(encoding="utf-8") != expected):
                failures.append(str(path))
            if args.write:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(expected, encoding="utf-8")
                print(f"wrote {path}")
    if failures:
        print("FAIL: cloud TPC templates out of date:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        print("Run: uv run -- python scripts/generate_cloud_tpc_templates.py --write", file=sys.stderr)
        return 1
    if args.check:
        print(f"OK: cloud TPC templates up-to-date ({len(PLATFORMS) * len(BENCHMARKS)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
