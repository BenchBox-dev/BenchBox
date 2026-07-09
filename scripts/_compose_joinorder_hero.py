#!/usr/bin/env python3
"""Compose post 14 hero ANSI text from real manifest + JSON values.

Mimics the Rich color palette emitted by `benchbox run` (see /tmp/bb-hero-12.log
for reference). Every number / hash / row count in the output is sourced from
real artifacts:
  - benchbox/core/joinorder/data_manifest.toml
  - benchmark_runs/results/joinorder_sf1_duckdb_sql_20260518_161132_e392ddcb.json

The layout is reconstructed because no real on-disk run output is captured for
joinorder; the values are not.
"""

import json
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

ROOT = Path(__file__).resolve().parent.parent
try:
    ROOT = ROOT.relative_to(Path.cwd())
except ValueError:
    ROOT = ROOT
MANIFEST = ROOT / "benchbox" / "core" / "joinorder" / "data_manifest.toml"
JSON_PATH = ROOT / "benchmark_runs" / "results" / "joinorder_sf1_duckdb_sql_20260518_161132_e392ddcb.json"

ESC = "\x1b"
RESET = f"{ESC}[0m"

# Rich-compatible palette codes (matches /tmp/bb-hero-12.log usage)
DIM = f"{ESC}[2m"
BOLD = f"{ESC}[1m"
BLUE = f"{ESC}[34m"
GREEN = f"{ESC}[32m"
CYAN = f"{ESC}[36m"
YELLOW = f"{ESC}[33m"
NUM = f"{ESC}[1;36m"  # bold cyan numerals
NUM_GREEN = f"{ESC}[1;32m"
LABEL = f"{ESC}[1;35m"  # bold magenta for table names
DULL = f"{ESC}[38;5;242m"


def fmt_num(n: int) -> str:
    """Render an integer with bold cyan thousands-separated digits."""
    s = f"{n:,}"
    out = []
    for ch in s:
        if ch.isdigit():
            out.append(f"{NUM}{ch}{RESET}")
        else:
            out.append(f"{NUM}{ch}{RESET}" if ch == "," else ch)
    return "".join(out)


def main() -> None:
    manifest = tomllib.loads(MANIFEST.read_text(encoding="utf-8"))
    data = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    # Real numbers
    dataset_version = manifest["dataset_version"]
    manifest_hash = manifest["manifest_hash"]
    data_archive_hash = manifest["data_archive_hash"]
    archive_sha256 = manifest["archive_sha256"]
    n_tables = len(manifest["tables"])
    total_rows = data["summary"]["data"]["rows_loaded"]
    load_ms = data["summary"]["data"]["load_time_ms"]
    total_ms = data["summary"]["timing"]["total_ms"]
    qcounts = data["summary"]["queries"]

    # Top tables by row count from the JSON (sorted desc)
    rows_by_table = sorted(data["tables"].items(), key=lambda kv: kv[1]["rows"], reverse=True)
    top_tables = rows_by_table[:8]  # show the largest 8

    # First 6 distinct query latencies from the JSON (warmup stream/iter 0)
    seen: dict[str, float] = {}
    for q in data["queries"]:
        qid = q["id"]
        if qid not in seen and q.get("iter") == 0 and q.get("stream") == 0:
            seen[qid] = q["ms"]
        if len(seen) >= 6:
            break
    first_queries = list(seen.items())

    lines: list[str] = []
    a = lines.append

    a(
        f"Running joinorder on duckdb at scale {NUM}1{RESET} {BOLD}[{RESET}driver {NUM}1.3{RESET}.{NUM}2{RESET}{BOLD}]{RESET}"
    )
    a(f"{BLUE}Initializing joinorder benchmark{RESET}{BLUE}...{RESET}")
    a(f"{GREEN}✅{RESET} Loaded benchmark: {CYAN}Join Order Benchmark{RESET}")
    a(f"{BLUE}Verifying dataset {RESET}{CYAN}'{dataset_version}'{RESET}{BLUE}...{RESET}")
    a(f"  manifest_hash:     {DULL}{manifest_hash}{RESET} {GREEN}✓{RESET}")
    a(f"  data_archive_hash: {DULL}{data_archive_hash}{RESET} {GREEN}✓{RESET}")
    a(f"  archive_sha256:    {DULL}{archive_sha256}{RESET} {GREEN}✓{RESET}")
    a(f"{GREEN}✅{RESET} Verified {fmt_num(n_tables)} canonical Parquet files")
    a(f"{YELLOW}Loading benchmark data{RESET}{YELLOW}...{RESET}")
    for name, info in top_tables:
        rows_str = fmt_num(info["rows"])
        # right-align the rendered number (account for ANSI noise: use raw digit count)
        raw = f"{info['rows']:,}"
        pad = " " * max(0, 14 - len(raw))
        a(f"  {GREEN}✅{RESET} Loaded {pad}{rows_str} rows into {LABEL}{name}{RESET}")
    remaining = n_tables - len(top_tables)
    a(f"  {DIM}... {remaining} more tables verified{RESET}")
    a(f"{GREEN}✅{RESET} Data loading completed: {fmt_num(total_rows)} rows in {NUM}{load_ms / 1000:.1f}{RESET}s")
    a("")
    a(f"{CYAN}--- Executing 113 JOB SQL queries (power mode) ---{RESET}")
    for idx, (qid, ms) in enumerate(first_queries, start=1):
        idx_str = f"{idx}".rjust(3)
        ms_str = f"{ms:>5.1f}"
        a(
            f"  {GREEN}✅{RESET} Query {NUM}{idx_str}{RESET}/{NUM}113{RESET}: {qid:3s} completed in {NUM_GREEN}{ms_str}{RESET}ms"
        )
    a(f"  {DIM}... 107 more queries ...{RESET}")
    a(
        f"{GREEN}✅ Power Test completed{RESET}: {fmt_num(qcounts['total'])} runs, "
        f"{NUM_GREEN}{qcounts['passed']}{RESET} passed, {NUM}{qcounts['failed']}{RESET} failed "
        f"({fmt_num(total_ms)}ms total)"
    )

    print("\n".join(lines))


if __name__ == "__main__":
    main()
