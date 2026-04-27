#!/usr/bin/env python3
"""Check all 7 Phase 1 launch criteria for the BenchBox results explorer.

Verifies that the seed corpus, built explorer site, and supporting
infrastructure meet the requirements defined in the strategy document
before public launch.

Usage:
    uv run -- python scripts/check_launch_criteria.py [OPTIONS]

Exit codes:
    0 - All 7 criteria PASS (SKIP does not count as failure)
    1 - One or more criteria FAIL, or an unexpected error occurred
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Status constants
# ---------------------------------------------------------------------------

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"

_SYMBOLS = {PASS: "\u2713", FAIL: "\u2717", SKIP: "~"}


# ---------------------------------------------------------------------------
# Corpus cohort depth (inline - scripts do not import each other)
# ---------------------------------------------------------------------------


def _load_manifest_results(data_dir: Path) -> list[dict] | None:
    """Return result entries from manifest.json, or None if the file is absent."""
    manifest_path = data_dir / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with manifest_path.open() as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        print(f"Error: {manifest_path} contains invalid JSON: {exc}", file=sys.stderr)
        return None
    results = data if isinstance(data, list) else data.get("results", [])
    return results if isinstance(results, list) else None


def _build_cohorts(results: list[dict]) -> dict[tuple[str, str], set[str]]:
    cohorts: dict[tuple[str, str], set[str]] = defaultdict(set)
    for entry in results:
        benchmark = entry.get("benchmark", "")
        scale_factor = entry.get("scale_factor")
        platform = entry.get("platform", "")
        if benchmark and scale_factor is not None and platform:
            cohorts[(benchmark, str(scale_factor))].add(platform)
    return dict(cohorts)


def _check_corpus_depth(data_dir: Path, min_platforms: int = 3) -> tuple[str, str]:
    """Check cohort depth. Returns (status, detail_message)."""
    results = _load_manifest_results(data_dir)
    if results is None:
        return FAIL, f"{data_dir}/manifest.json not found - run the static build pipeline first"

    if not results:
        return FAIL, "manifest.json contains no results"

    cohorts = _build_cohorts(results)
    if not cohorts:
        return FAIL, "no valid benchmark\u00d7scale cohorts found in manifest.json"

    shallow = {k: len(v) for k, v in cohorts.items() if len(v) < min_platforms}
    if shallow:
        detail = f"{len(cohorts)} cohorts total; {len(shallow)} below threshold: " + ", ".join(
            f"{b}/{s}={n}" for (b, s), n in sorted(shallow.items())
        )
        return FAIL, detail

    return PASS, f"{len(cohorts)} cohorts, all with \u2265{min_platforms} platforms"


# ---------------------------------------------------------------------------
# Individual criterion checks
# ---------------------------------------------------------------------------


def criterion_corpus_depth(data_dir: Path) -> tuple[str, str]:
    return _check_corpus_depth(data_dir, min_platforms=3)


def criterion_explorer_home(site_dir: Path) -> tuple[str, str]:
    index = site_dir / "results" / "index.html"
    if not index.exists():
        return FAIL, f"{index} not found (run: cd results-explorer && npm run build)"
    return PASS, f"{index} exists"


def criterion_result_pages(site_dir: Path) -> tuple[str, str]:
    r_dir = site_dir / "results" / "r"
    if not r_dir.exists():
        return FAIL, f"{r_dir}/ directory not found"
    return PASS, f"{r_dir}/ directory exists"


def criterion_duckdb_snapshot(data_dir: Path) -> tuple[str, str]:
    db_file = data_dir / "results.duckdb"
    if not db_file.exists():
        return FAIL, f"{db_file} not found"
    return PASS, f"{db_file} exists"


def criterion_site_deployment(site_dir: Path) -> tuple[str, str]:
    results_dir = site_dir / "results"
    if not results_dir.exists():
        return FAIL, f"{results_dir}/ not found - assemble the site first"
    return PASS, f"{results_dir}/ exists (GitHub Pages deployment is a manual step)"


def criterion_nav_link(site_dir: Path) -> tuple[str, str]:
    landing = site_dir / "index.html"
    if not landing.exists():
        return SKIP, f"{landing} not found (assemble site first)"
    try:
        content = landing.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return FAIL, f"Cannot read {landing}: {exc}"
    if "/results/" not in content:
        return FAIL, f"{landing} does not contain a /results/ link - add Results to site nav"
    return PASS, f"{landing} contains /results/ link"


def criterion_cname(repo_root: Path) -> tuple[str, str]:
    cname = repo_root / "docs" / "CNAME"
    if not cname.exists():
        return FAIL, f"{cname} not found - brand/domain not configured"
    return PASS, f"{cname} exists"


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def run_all_checks(
    data_dir: Path,
    site_dir: Path,
    repo_root: Path,
) -> list[tuple[str, str, str]]:
    """Run all 7 criteria and return list of (name, status, detail)."""
    return [
        ("Corpus depth (\u22653 platforms per benchmark\u00d7scale cohort)", *criterion_corpus_depth(data_dir)),
        ("Explorer home page present", *criterion_explorer_home(site_dir)),
        ("Explorer result pages present", *criterion_result_pages(site_dir)),
        ("DuckDB snapshot present", *criterion_duckdb_snapshot(data_dir)),
        ("Site deployment directory assembled", *criterion_site_deployment(site_dir)),
        ("Results nav link in landing page", *criterion_nav_link(site_dir)),
        ("Brand/domain configured (CNAME)", *criterion_cname(repo_root)),
    ]


def print_report(results: list[tuple[str, str, str]]) -> None:
    print("BenchBox Phase 1 Launch Criteria Check")
    print("======================================")
    print()
    for i, (name, status, detail) in enumerate(results, 1):
        sym = _SYMBOLS[status]
        print(f"[{i}] {name}")
        print(f"    {sym} {status} \u2014 {detail}")
        print()

    passed = sum(1 for _, s, _ in results if s == PASS)
    total = len(results)
    print(f"Summary: {passed}/{total} criteria met")
    if any(s == FAIL for _, s, _ in results):
        print("To launch: fix FAIL items above, then verify manually with cross-browser testing")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check all 7 Phase 1 launch criteria for the BenchBox results explorer.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--data-dir",
        default="results-explorer/public/data",
        metavar="PATH",
        help="Explorer public data directory [default: results-explorer/public/data]",
    )
    parser.add_argument(
        "--site-dir",
        default="site",
        metavar="PATH",
        help="Assembled site directory [default: site]",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    repo_root = Path(__file__).resolve().parent.parent

    def resolve(p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else repo_root / path

    data_dir = resolve(args.data_dir)
    site_dir = resolve(args.site_dir)

    check_results = run_all_checks(data_dir, site_dir, repo_root)
    print_report(check_results)

    any_fail = any(status == FAIL for _, status, _ in check_results)
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
