#!/usr/bin/env python3
"""Validate the seed corpus meets depth and schema requirements."""

import collections
import json
import pathlib
import sys

bundles_dir = pathlib.Path(__file__).parent / "bundles"
bundles = [
    path
    for path in bundles_dir.rglob("*.json")
    if path.name != "submission-manifest.json"
    and not path.name.endswith(".manifest.json")
    and not path.name.endswith(".plans.json")
    and not path.name.endswith(".tuning.json")
]
print(f"Found {len(bundles)} bundles")

cohorts: collections.defaultdict[tuple[str, str], set[str]] = collections.defaultdict(set)
for b in bundles:
    try:
        with open(b, encoding="utf-8") as fh:
            d = json.load(fh)
        benchmark_id = d["benchmark"]["id"]
        scale_factor = str(d["benchmark"].get("scale_factor", ""))
        platform = d["platform"]["name"]
        cohorts[(benchmark_id, scale_factor)].add(platform)
    except Exception as e:
        print(f"ERROR reading {b}: {e}")
        sys.exit(1)

print("\nCohorts:")
for k, platforms in sorted(cohorts.items()):
    status = "OK" if len(platforms) >= 3 else "WARN (<3 platforms)"
    print(f"  {k[0]} SF={k[1]}: {len(platforms)} platforms ({sorted(platforms)}) [{status}]")

low = {k: v for k, v in cohorts.items() if len(v) < 3}
if low:
    print(f"\nWARN: {len(low)} cohort(s) have <3 platforms: { {k: len(v) for k, v in low.items()} }")
    sys.exit(1)
else:
    print(f"\nAll {len(cohorts)} cohort(s) meet the >=3-platform depth criterion.")
