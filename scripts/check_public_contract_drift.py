#!/usr/bin/env python3
"""Public contract drift guard.

Verifies that ``docs/reference/public-contracts.md`` has not drifted from the
source-of-truth registries it claims to describe, and that README.md has not
regressed to hand-maintained exact count claims that the contract doc is
supposed to own instead.

Extracted verbatim (logic byte-equivalent) from the "Public contract drift
check" inline heredoc step in the `code-lint` (pr.yml `lint` job) job so the
same guard can run both in CI and locally via `make ci-lint` /
`make pr-preflight` without drifting out of sync. See
docs/operations/ci-local-parity.md for the parity invariant this guard is
part of.

Note: this is intentionally narrower than the "Validate public contract
drift guard" step in the `content-guard` job (which also checks required
doc surfaces/support-status vocabulary and is gated on docs/markdown path
changes) — that step is untouched by this extraction.

Run locally:
    uv run -- python scripts/check_public_contract_drift.py
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    from benchbox.core.benchmark_registry import list_benchmark_ids, list_loader_benchmark_ids
    from benchbox.core.platform_registry import PlatformRegistry
    from benchbox.core.results.schema import SCHEMA_VERSION

    contract = (REPO_ROOT / "docs/reference/public-contracts.md").read_text(encoding="utf-8")
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    forbidden_readme_count_claims = [
        "Twenty-Two Benchmarks",
        "SQL Platforms (",
        "DataFrame Platforms (",
    ]
    offenders = [phrase for phrase in forbidden_readme_count_claims if phrase in readme]
    if offenders:
        print(
            "README.md has exact hand-maintained count claims; use registry-derived checks "
            f"or mark them non-authoritative: {offenders}",
            file=sys.stderr,
        )
        return 1

    platforms = PlatformRegistry.get_all_platform_metadata()
    sql_capable = sum(1 for item in platforms.values() if item.get("capabilities", {}).get("supports_sql"))
    dataframe_capable = sum(1 for item in platforms.values() if item.get("capabilities", {}).get("supports_dataframe"))
    dual_mode = sum(
        1
        for item in platforms.values()
        if item.get("capabilities", {}).get("supports_sql") and item.get("capabilities", {}).get("supports_dataframe")
    )

    source_fragments = [
        f"{len(list_benchmark_ids())} benchmark metadata entries",
        f"{len(list_loader_benchmark_ids())} loader-resolved IDs",
        f"{len(platforms)} platform metadata entries",
        f"{sql_capable} SQL-capable",
        f"{dataframe_capable} DataFrame-capable",
        f"{dual_mode} dual-mode",
        f"Current result schema version: `{SCHEMA_VERSION}`",
    ]
    missing_fragments = [fragment for fragment in source_fragments if fragment not in contract]
    if missing_fragments:
        print(f"public-contracts.md source-derived claims are stale: {missing_fragments}", file=sys.stderr)
        return 1

    print("OK: public-contracts.md matches source-derived registry claims.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
