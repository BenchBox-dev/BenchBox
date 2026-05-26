#!/usr/bin/env python3
"""Validate checked-in TPC tuned templates against the logical tuning profile."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from benchbox.cli.config import ConfigManager
from benchbox.core.tuning.profile_validation import validate_tuning_template
from benchbox.core.tuning.workload_profiles import load_tpc_tuning_profile

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmarks", default="tpch,tpcds", help="Comma-separated benchmark ids")
    parser.add_argument("--platforms", default="databricks,duckdb", help="Comma-separated platform ids")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any template validation fails")
    args = parser.parse_args(argv)

    benchmarks = _split_csv(args.benchmarks)
    platforms = _split_csv(args.platforms)
    profile = load_tpc_tuning_profile()
    config_manager = ConfigManager()
    failures = 0

    for platform in platforms:
        for benchmark in benchmarks:
            for label, template_path in _template_paths(platform, benchmark):
                if not template_path.exists():
                    print(f"{platform}/{benchmark}/{label}: missing template {template_path.relative_to(REPO_ROOT)}")
                    failures += 1
                    continue

                tuning_config = config_manager.load_unified_tuning_config(template_path, platform=platform)
                result = validate_tuning_template(
                    profile=profile,
                    benchmark=benchmark,
                    platform=platform,
                    tuning_config=tuning_config,
                )
                metadata = result.to_metadata()
                coverage = metadata["logical_profile_coverage"]
                mechanisms = ",".join(metadata["platform_physical_tuning_mechanisms"]) or "none"
                rendering = metadata.get("physical_rendering_id", "unknown")
                status = "ok" if result.is_valid else "failed"
                print(
                    f"{platform}/{benchmark}/{label}: {status}; "
                    f"mapped={coverage['mapped_count']}/{coverage['required_count']}; "
                    f"accepted={coverage['accepted_count']}; "
                    f"dropped={coverage['dropped_low_evidence_count']}; "
                    f"rendering={rendering}; mechanisms={mechanisms}; hash={metadata['tuning_template_hash']}"
                )
                for issue in result.issues:
                    print(f"  {issue.severity}: {issue.candidate_key}: {issue.message} ({issue.reason})")
                if not result.is_valid:
                    failures += 1

    return 1 if args.strict and failures else 0


def _split_csv(raw: str) -> list[str]:
    values = [value.strip().lower() for value in raw.split(",") if value.strip()]
    if not values:
        raise SystemExit("expected at least one comma-separated value")
    return values


def _template_paths(platform: str, benchmark: str) -> list[tuple[str, Path]]:
    tuning_dir = REPO_ROOT / "examples" / "tunings" / platform
    paths = [("tuned", tuning_dir / f"{benchmark}_tuned.yaml")]
    if platform == "databricks":
        paths.append(("liquid", tuning_dir / f"{benchmark}_liquid_tuned.yaml"))
    return paths


if __name__ == "__main__":
    sys.exit(main())
