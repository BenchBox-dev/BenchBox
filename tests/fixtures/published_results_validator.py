#!/usr/bin/env python3
"""Validate submission bundles in results-data/bundles/.

Used by CI to check that PRs adding result bundles conform to schema-v2,
have sane timing data, valid platform/benchmark names, and (when a
submission manifest is present) matching SHA-256 hashes.

Exit codes:
    0 - all bundles valid
    1 - one or more validation errors

Usage:
    # Validate all bundles
    uv run -- python scripts/validate_submission.py results-data/bundles/

    # Validate specific files (e.g. only changed files from a PR)
    uv run -- python scripts/validate_submission.py path/to/bundle1.json path/to/bundle2.json
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Schema-v2 required top-level keys
# ---------------------------------------------------------------------------

REQUIRED_TOP_KEYS = {"version", "run", "benchmark", "platform", "summary", "queries"}
REQUIRED_RUN_KEYS = {"id", "timestamp", "total_duration_ms"}
REQUIRED_BENCHMARK_KEYS = {"id", "scale_factor"}
REQUIRED_PLATFORM_KEYS = {"name"}
REQUIRED_QUERY_KEYS = {"id", "ms"}

# Accepted schema version prefixes (2.x family).
ACCEPTED_VERSION_PREFIX = "2."

# Companion file suffixes - skipped during bundle discovery.
COMPANION_SUFFIXES = (".plans.json", ".tuning.json")
SUBMISSION_MANIFEST_FILENAME = "submission-manifest.json"
SUBMISSION_MANIFEST_SUFFIX = ".manifest.json"

# Known benchmarks and platforms - warn (not fail) on unknown values.
KNOWN_BENCHMARKS = {
    "tpch",
    "tpcds",
    "ssb",
    "star_schema",
    "clickbench",
    "nyctaxi",
    "flightdata",
    "tsbs-devops",
    "tsbs_devops",
    "h2odb",
    "amplab",
    "coffeeshop",
    "joinorder",
    "tpch_skew",
    "tpchavoc",
    "datavault",
    "tpcdi",
    "tpcds_obt",
    "read_primitives",
    "write_primitives",
    "metadata_primitives",
    "transaction_primitives",
    "ai_primitives",
    "vector_search",
}
KNOWN_PLATFORMS = {
    # Core
    "duckdb",
    "datafusion",
    "polars",
    "sqlite",
    "motherduck",
    # SQL - cloud & managed
    "clickhouse",
    "clickhouse-local",
    "clickhouse-server",
    "clickhouse-cloud",
    "snowflake",
    "databricks",
    "bigquery",
    "redshift",
    "athena",
    "firebolt",
    # SQL - self-hosted & extensions
    "postgresql",
    "timescaledb",
    "pg-duckdb",
    "pg-mooncake",
    "trino",
    "starburst",
    "presto",
    "influxdb",
    "questdb",
    "starrocks",
    "databend",
    "doris",
    # Spark-family
    "spark",
    "pyspark",
    "lakesail",
    # DataFrame
    "pandas",
    "modin",
    "cudf",
    "dask",
    # Microsoft Fabric / Synapse
    "synapse",
    "fabric_dw",
    "fabric-lakehouse",
    "fabric-spark",
}

# Sanity thresholds
MAX_QUERY_DURATION_MS = 7_200_000  # 2 hours per query
MAX_TOTAL_DURATION_MS = 86_400_000  # 24 hours total


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


class ValidationResult:
    """Collects errors and warnings for a single bundle."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.errors: list[str] = []
        self.warnings: list[str] = []
        # Metadata extracted during validation, used by format_pr_comment.
        self.benchmark_id: str = "-"
        self.platform_name: str = "-"
        self.scale_factor: str = "-"

    def error(self, msg: str) -> None:
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0


def _capture_metadata(data: dict, vr: ValidationResult) -> None:
    """Pull benchmark/platform identifiers out of the bundle for PR-comment formatting."""
    bm = data.get("benchmark")
    if isinstance(bm, dict):
        vr.benchmark_id = bm.get("id", "-")
        sf = bm.get("scale_factor")
        if sf is not None:
            vr.scale_factor = str(sf)
    pl = data.get("platform")
    if isinstance(pl, dict):
        vr.platform_name = pl.get("name", "-")


def _validate_version(version: Any, vr: ValidationResult) -> None:
    if not isinstance(version, str) or not version.startswith(ACCEPTED_VERSION_PREFIX):
        vr.error(f"Unsupported schema version: {version!r} (expected 2.x)")


def _validate_run_section(run: Any, vr: ValidationResult) -> None:
    if not isinstance(run, dict):
        vr.error("'run' must be a dict")
        return
    missing_run = REQUIRED_RUN_KEYS - set(run.keys())
    if missing_run:
        vr.error(f"Missing keys in 'run': {sorted(missing_run)}")

    total_ms = run.get("total_duration_ms")
    if total_ms is None:
        return
    try:
        total_ms_f = float(total_ms)
    except (TypeError, ValueError):
        vr.error(f"Invalid total_duration_ms: {total_ms!r}")
        return
    if total_ms_f < 0:
        vr.error(f"Negative total_duration_ms: {total_ms_f}")
    elif total_ms_f > MAX_TOTAL_DURATION_MS:
        vr.warn(f"Unusually long total_duration_ms: {total_ms_f:.0f} (>{MAX_TOTAL_DURATION_MS})")


def _validate_benchmark_section(benchmark: Any, vr: ValidationResult) -> None:
    if not isinstance(benchmark, dict):
        vr.error("'benchmark' must be a dict")
        return
    missing_bm = REQUIRED_BENCHMARK_KEYS - set(benchmark.keys())
    if missing_bm:
        vr.error(f"Missing keys in 'benchmark': {sorted(missing_bm)}")

    bm_id = benchmark.get("id", "")
    if isinstance(bm_id, str) and bm_id and bm_id not in KNOWN_BENCHMARKS:
        vr.warn(f"Unknown benchmark id: {bm_id!r}")

    sf = benchmark.get("scale_factor")
    if sf is None:
        return
    try:
        sf_f = float(sf)
    except (TypeError, ValueError):
        vr.error(f"Invalid scale_factor: {sf!r}")
        return
    if sf_f <= 0:
        vr.error(f"scale_factor must be positive: {sf_f}")


def _validate_platform_section(platform: Any, vr: ValidationResult) -> None:
    if not isinstance(platform, dict):
        vr.error("'platform' must be a dict")
        return
    missing_pl = REQUIRED_PLATFORM_KEYS - set(platform.keys())
    if missing_pl:
        vr.error(f"Missing keys in 'platform': {sorted(missing_pl)}")

    pl_name = platform.get("name", "")
    if isinstance(pl_name, str) and pl_name:
        normalized = pl_name.lower().replace(" ", "-")
        if normalized not in KNOWN_PLATFORMS:
            vr.warn(f"Unknown platform name: {pl_name!r}")


def _validate_summary_section(summary: Any, vr: ValidationResult) -> None:
    if not isinstance(summary, dict):
        vr.error("'summary' must be a dict")
        return
    queries_summary = summary.get("queries", {})
    if isinstance(queries_summary, dict):
        total_q = queries_summary.get("total", 0)
        if isinstance(total_q, (int, float)) and total_q == 0:
            vr.warn("summary.queries.total is 0 - empty result?")


def _validate_single_query(index: int, q: Any, vr: ValidationResult) -> bool:
    """Validate one queries[i] entry. Returns True if ms>0 was seen (non-zero signal)."""
    if not isinstance(q, dict):
        vr.error(f"queries[{index}] is not a dict")
        return False

    missing_qk = REQUIRED_QUERY_KEYS - set(q.keys())
    if missing_qk:
        vr.error(f"queries[{index}] missing keys: {sorted(missing_qk)}")
        return False

    ms = q.get("ms")
    if ms is None:
        return False
    try:
        ms_f = float(ms)
    except (TypeError, ValueError):
        vr.error(f"queries[{index}] invalid ms value: {ms!r}")
        return False
    if ms_f < 0:
        vr.error(f"queries[{index}] negative duration: {ms_f}")
    elif ms_f > MAX_QUERY_DURATION_MS:
        vr.warn(f"queries[{index}] unusually long: {ms_f:.0f}ms")
    return ms_f > 0


def _validate_queries_section(queries: Any, vr: ValidationResult) -> None:
    if not isinstance(queries, list):
        vr.error("'queries' must be a list")
        return
    if len(queries) == 0:
        vr.warn("queries array is empty")
        return

    any_nonzero = False
    for i, q in enumerate(queries):
        if _validate_single_query(i, q, vr):
            any_nonzero = True

    if not any_nonzero:
        vr.error("All query timings are 0ms - likely invalid data")


def _validate_bundle(data: dict, vr: ValidationResult) -> None:
    """Run all validation checks on a parsed bundle dict."""
    _capture_metadata(data, vr)

    missing_top = REQUIRED_TOP_KEYS - set(data.keys())
    if missing_top:
        vr.error(f"Missing required top-level keys: {sorted(missing_top)}")
        return  # Can't continue without structure

    _validate_version(data.get("version", ""), vr)
    _validate_run_section(data.get("run", {}), vr)
    _validate_benchmark_section(data.get("benchmark", {}), vr)
    _validate_platform_section(data.get("platform", {}), vr)
    _validate_summary_section(data.get("summary", {}), vr)
    _validate_queries_section(data.get("queries", []), vr)


def _hash_file(file_path: Path) -> str:
    """SHA-256 of a single file's contents."""
    h = hashlib.sha256()
    h.update(file_path.read_bytes())
    return h.hexdigest()


def _is_safe_bundle_filename(name: str) -> bool:
    """Reject filenames that could escape the bundle directory.

    The validator runs in CI on attacker-controlled PR JSON, so manifest-
    supplied filenames must be plain leaf names, not paths.
    """
    if not name or name in (".", ".."):
        return False
    if "/" in name or "\\" in name or "\x00" in name:
        return False
    parts = Path(name).parts
    if Path(name).is_absolute() or ".." in parts or len(parts) != 1:
        return False
    return True


def _validate_manifest_hash(manifest_path: Path, bundle_dir: Path, vr: ValidationResult) -> None:
    """Verify the submission manifest hashes match the bundle file contents.

    Contract (see also benchbox/cli/commands/submit.py):
      - manifest.bundle_file: filename of the primary bundle JSON.
      - manifest.bundle_hash: SHA-256 of just that file's contents.
      - manifest.companion_hashes: optional dict of companion-file
        names mapped to their SHA-256s. Empty dict if no companions.

    The hash is per-file. Anything wider (a directory hash) does not
    survive the user copying the bundle files into a results-data/bundles/
    directory that already contains other bundles.
    """
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        vr.error(f"Cannot parse submission manifest JSON: {exc}")
        return
    except OSError as exc:
        vr.error(f"Cannot read submission manifest file: {exc}")
        return

    # Surface ALL missing required fields in one pass so a contributor
    # whose manifest is missing both `bundle_file` and `bundle_hash`
    # sees both warnings instead of having to fix-and-retry one at a time.
    bundle_file = manifest.get("bundle_file")
    expected_hash = manifest.get("bundle_hash")
    missing_fields: list[str] = []
    if not isinstance(bundle_file, str) or not bundle_file:
        missing_fields.append("bundle_file")
    if not isinstance(expected_hash, str) or not expected_hash:
        missing_fields.append("bundle_hash")
    if missing_fields:
        for field in missing_fields:
            vr.warn(f"Submission manifest has no {field} field")
        return

    if not _is_safe_bundle_filename(bundle_file):
        vr.error(f"Unsafe bundle_file in manifest: {bundle_file!r} (must be a plain filename)")
        return

    primary_path = bundle_dir / bundle_file
    # Symlink defense: the validator runs on PR-supplied content, so a
    # malicious symlink (committed via a crafted git tree) could redirect
    # the hash to attacker-chosen bytes outside the bundle. Reject before
    # is_file() — is_file() follows symlinks. The writer (benchbox submit)
    # uses shutil.copy2, which copies file contents not symlinks, so any
    # symlink in a submitted bundle is suspicious by construction.
    if primary_path.is_symlink():
        vr.error(f"Bundle file is a symlink, not a regular file: {bundle_file} (symlinks not allowed)")
        return
    if not primary_path.is_file():
        vr.error(f"Bundle file declared in manifest not found in PR: {bundle_file}")
        return

    actual_hash = _hash_file(primary_path)
    if actual_hash != expected_hash:
        vr.error(
            f"Bundle hash mismatch for {bundle_file}: manifest says "
            f"{expected_hash[:16]}..., computed {actual_hash[:16]}..."
        )

    companion_hashes = manifest.get("companion_hashes") or {}
    if not isinstance(companion_hashes, dict):
        vr.error("companion_hashes field must be an object (filename -> hash)")
        return

    for comp_name, comp_expected in companion_hashes.items():
        if not isinstance(comp_name, str) or not _is_safe_bundle_filename(comp_name):
            vr.error(f"Unsafe companion filename in manifest: {comp_name!r} (must be a plain filename)")
            continue
        comp_path = bundle_dir / comp_name
        if comp_path.is_symlink():
            vr.error(f"Companion file is a symlink, not a regular file: {comp_name} (symlinks not allowed)")
            continue
        if not comp_path.is_file():
            vr.error(f"Companion file declared in manifest not found in PR: {comp_name}")
            continue
        if not isinstance(comp_expected, str) or not comp_expected:
            vr.error(f"Empty companion hash for {comp_name}")
            continue
        comp_actual = _hash_file(comp_path)
        if comp_actual != comp_expected:
            vr.error(
                f"Companion hash mismatch for {comp_name}: manifest says "
                f"{comp_expected[:16]}..., computed {comp_actual[:16]}..."
            )


# ---------------------------------------------------------------------------
# Discovery & orchestration
# ---------------------------------------------------------------------------


def discover_bundles(path: Path) -> list[Path]:
    """Find all primary bundle JSON files under a directory (excludes companions)."""
    bundles = []
    for f in sorted(path.rglob("*.json")):
        if any(f.name.endswith(s) for s in COMPANION_SUFFIXES):
            continue
        if f.name == "corpus-inventory.json":
            continue
        if _is_submission_manifest_path(f):
            continue
        bundles.append(f)
    return bundles


def _is_submission_manifest_path(path: Path) -> bool:
    return path.name == SUBMISSION_MANIFEST_FILENAME or path.name.endswith(SUBMISSION_MANIFEST_SUFFIX)


def validate_bundles(paths: list[Path]) -> list[ValidationResult]:
    """Validate a list of bundle files. Returns one ValidationResult per file."""
    results = []
    for bundle_path in paths:
        if _is_submission_manifest_path(bundle_path):
            continue

        vr = ValidationResult(str(bundle_path))

        if not bundle_path.exists():
            vr.error(f"File not found: {bundle_path}")
            results.append(vr)
            continue

        try:
            data = json.loads(bundle_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            vr.error(f"Invalid JSON: {exc}")
            results.append(vr)
            continue

        if not isinstance(data, dict):
            vr.error("Top-level value must be a JSON object")
            results.append(vr)
            continue

        _validate_bundle(data, vr)

        # Check for submission manifest alongside the bundle.
        # Prefer per-bundle name (<stem>.manifest.json), fall back to legacy.
        per_bundle_manifest = bundle_path.parent / f"{bundle_path.stem}{SUBMISSION_MANIFEST_SUFFIX}"
        legacy_manifest = bundle_path.parent / SUBMISSION_MANIFEST_FILENAME
        manifest_path = (
            per_bundle_manifest
            if per_bundle_manifest.exists()
            else (legacy_manifest if legacy_manifest.exists() else None)
        )
        if manifest_path is not None:
            _validate_manifest_hash(manifest_path, bundle_path.parent, vr)

        results.append(vr)
    return results


def format_summary(results: list[ValidationResult]) -> str:
    """Format validation results as a human-readable summary."""
    lines: list[str] = []
    total_errors = 0
    total_warnings = 0

    for vr in results:
        total_errors += len(vr.errors)
        total_warnings += len(vr.warnings)

        status = "PASS" if vr.ok else "FAIL"
        lines.append(f"  {status}  {vr.path}")
        for e in vr.errors:
            lines.append(f"        ERROR: {e}")
        for w in vr.warnings:
            lines.append(f"        WARN:  {w}")

    header = f"Validated {len(results)} bundle(s): {total_errors} error(s), {total_warnings} warning(s)"
    return header + "\n" + "\n".join(lines)


def format_pr_comment(results: list[ValidationResult]) -> str:
    """Format validation results as a GitHub PR comment (Markdown)."""
    lines: list[str] = []
    all_pass = all(vr.ok for vr in results)

    if all_pass:
        lines.append("## Submission Validation: PASSED")
    else:
        lines.append("## Submission Validation: FAILED")

    lines.append("")
    lines.append(f"Validated **{len(results)}** bundle(s).")
    lines.append("")

    # Summary table
    lines.append("| Bundle | Status | Benchmark | Platform | Scale |")
    lines.append("|--------|--------|-----------|----------|-------|")

    for vr in results:
        status = "PASS" if vr.ok else "FAIL"
        name = Path(vr.path).name.replace("|", "\\|")
        bm_id = vr.benchmark_id.replace("|", "\\|")
        pl_name = vr.platform_name.replace("|", "\\|")
        sf = vr.scale_factor.replace("|", "\\|")
        lines.append(f"| `{name}` | {status} | {bm_id} | {pl_name} | SF {sf} |")

    # Detail errors/warnings
    has_issues = any(vr.errors or vr.warnings for vr in results)
    if has_issues:
        lines.append("")
        lines.append("### Details")
        lines.append("")
        for vr in results:
            if not vr.errors and not vr.warnings:
                continue
            lines.append(f"**`{Path(vr.path).name}`**")
            for e in vr.errors:
                lines.append(f"- ERROR: {e}")
            for w in vr.warnings:
                lines.append(f"- WARN: {w}")
            lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]

    # Parse optional --pr-comment <path> flag.
    pr_comment_path: Path | None = None
    positional: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--pr-comment" and i + 1 < len(args):
            pr_comment_path = Path(args[i + 1])
            i += 2
        else:
            positional.append(args[i])
            i += 1

    if not positional:
        print("Usage: validate_submission.py [--pr-comment <path>] <dir-or-files...>", file=sys.stderr)
        return 1

    paths: list[Path] = []
    for arg in positional:
        p = Path(arg)
        if p.is_dir():
            paths.extend(discover_bundles(p))
        elif p.is_file():
            paths.append(p)
        else:
            print(f"Warning: {arg} does not exist, skipping", file=sys.stderr)

    if not paths:
        print("No bundle files found.", file=sys.stderr)
        return 1

    results = validate_bundles(paths)
    print(format_summary(results))

    if pr_comment_path is not None:
        try:
            pr_comment_path.write_text(format_pr_comment(results), encoding="utf-8")
        except OSError as exc:
            print(f"Warning: failed to write PR comment file: {exc}", file=sys.stderr)

    has_errors = any(not vr.ok for vr in results)
    return 1 if has_errors else 0


if __name__ == "__main__":
    sys.exit(main())
