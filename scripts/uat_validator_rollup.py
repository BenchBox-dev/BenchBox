#!/usr/bin/env python3
"""Roll up `scripts/validate_submission.py` outcomes for a sweep-shape UAT.

Walks a directory of result-JSON bundles, runs the bundle validator on each,
and emits a TSV roll-up plus per-platform / per-benchmark validator-clean
rates. The W7 author of any sweep-shape UAT consumes this directly instead of
reconciling `validate_submission.py` output against W3 success counts by
hand (see _project/handoffs/results-explorer-uat-retrospective-20260502.md).

Per-bundle status values:

    clean           validation produced 0 errors, 0 warnings
    warning_only    validation produced 0 errors, >=1 warning
    error           validation produced >=1 error
    refused-by-cli  bundle would be refused by `benchbox submit` (TPC-DS
                    compliance guardrail: benchmark.compliance_class in
                    {unofficial_subscale, unofficial_nonstandard}). The
                    actual bundle validator is not run on these because
                    they cannot be packaged for submission anyway.

Usage:

    uv run -- python scripts/uat_validator_rollup.py <results-dir> [--output <path>|-]
    uv run -- python scripts/uat_validator_rollup.py <results-dir> --newer <sentinel-file>

The TSV columns are:

    platform | benchmark | scale | result_path | validator_status |
    error_count | warning_count | first_error

Footer summary lines (prefixed with `#`) report overall, per-platform, and
per-benchmark validator-clean rates.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from benchbox.validation.bundle import CLI_REFUSED_COMPLIANCE_CLASSES, discover_bundles, validate_bundles

TSV_HEADER = "platform\tbenchmark\tscale\tresult_path\tvalidator_status\terror_count\twarning_count\tfirst_error"


@dataclass
class RollupRow:
    platform: str
    benchmark: str
    scale: str
    result_path: str
    validator_status: str
    error_count: int
    warning_count: int
    first_error: str

    def to_tsv(self) -> str:
        return "\t".join(
            [
                self.platform,
                self.benchmark,
                self.scale,
                self.result_path,
                self.validator_status,
                str(self.error_count),
                str(self.warning_count),
                self.first_error.replace("\t", " ").replace("\n", " "),
            ]
        )


def _read_bundle_metadata(bundle_path: Path) -> tuple[str, str, str, str | None]:
    """Return (platform, benchmark, scale, compliance_class) from a bundle JSON.

    Falls back to "-" for platform/benchmark/scale when the JSON is malformed
    or missing fields; compliance_class is None unless explicitly set.
    """
    try:
        data = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "-", "-", "-", None
    if not isinstance(data, dict):
        return "-", "-", "-", None

    platform = "-"
    pl = data.get("platform")
    if isinstance(pl, dict):
        name = pl.get("name")
        if isinstance(name, str) and name:
            platform = name

    benchmark = "-"
    scale = "-"
    compliance_class: str | None = None
    bm = data.get("benchmark")
    if isinstance(bm, dict):
        bm_id = bm.get("id")
        if isinstance(bm_id, str) and bm_id:
            benchmark = bm_id
        sf = bm.get("scale_factor")
        if sf is not None:
            scale = str(sf)
        cc = bm.get("compliance_class")
        if isinstance(cc, str):
            compliance_class = cc

    return platform, benchmark, scale, compliance_class


def _classify(error_count: int, warning_count: int) -> str:
    if error_count > 0:
        return "error"
    if warning_count > 0:
        return "warning_only"
    return "clean"


def _filter_newer(bundles: list[Path], sentinel: Path) -> list[Path]:
    cutoff = sentinel.stat().st_mtime
    return [b for b in bundles if b.stat().st_mtime >= cutoff]


def build_rows(bundles: Iterable[Path]) -> list[RollupRow]:
    rows: list[RollupRow] = []
    for bundle_path in bundles:
        platform, benchmark, scale, compliance_class = _read_bundle_metadata(bundle_path)

        if compliance_class in CLI_REFUSED_COMPLIANCE_CLASSES:
            rows.append(
                RollupRow(
                    platform=platform,
                    benchmark=benchmark,
                    scale=scale,
                    result_path=str(bundle_path),
                    validator_status="refused-by-cli",
                    error_count=0,
                    warning_count=0,
                    first_error=f"compliance_class={compliance_class}",
                )
            )
            continue

        results = validate_bundles([bundle_path])
        if not results:
            # validate_bundles skips files it treats as manifests; surface that
            # so the row is still accounted for.
            rows.append(
                RollupRow(
                    platform=platform,
                    benchmark=benchmark,
                    scale=scale,
                    result_path=str(bundle_path),
                    validator_status="error",
                    error_count=1,
                    warning_count=0,
                    first_error="validate_bundles returned no result (manifest sidecar?)",
                )
            )
            continue

        vr = results[0]
        first_error = vr.errors[0] if vr.errors else ""
        rows.append(
            RollupRow(
                platform=platform,
                benchmark=benchmark,
                scale=scale,
                result_path=str(bundle_path),
                validator_status=_classify(len(vr.errors), len(vr.warnings)),
                error_count=len(vr.errors),
                warning_count=len(vr.warnings),
                first_error=first_error,
            )
        )
    return rows


def _rate(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a"
    return f"{(100 * numerator / denominator):.1f}%"


def format_footer(rows: list[RollupRow]) -> list[str]:
    """Return footer lines (each prefixed with `#`) summarising clean rates.

    Per-platform and per-benchmark rates exclude `refused-by-cli` from the
    denominator: those bundles cannot be packaged for submission so they
    cannot meaningfully be "clean" or "error" — they are out of scope for
    the validator-clean rate. They remain visible in the per-row TSV.
    """
    total = len(rows)
    clean = sum(1 for r in rows if r.validator_status == "clean")
    error = sum(1 for r in rows if r.validator_status == "error")
    warning_only = sum(1 for r in rows if r.validator_status == "warning_only")
    refused = sum(1 for r in rows if r.validator_status == "refused-by-cli")
    submittable = total - refused

    lines = [
        f"# overall: total={total} submittable={submittable} clean={clean} "
        f"warning_only={warning_only} error={error} refused-by-cli={refused} "
        f"validator_clean_rate={_rate(clean, submittable)}"
    ]

    by_platform: dict[str, list[RollupRow]] = {}
    for r in rows:
        by_platform.setdefault(r.platform, []).append(r)
    for platform in sorted(by_platform):
        plist = by_platform[platform]
        sub = [r for r in plist if r.validator_status != "refused-by-cli"]
        c = sum(1 for r in sub if r.validator_status == "clean")
        lines.append(
            f"# platform={platform}: total={len(plist)} submittable={len(sub)} "
            f"clean={c} validator_clean_rate={_rate(c, len(sub))}"
        )

    by_benchmark: dict[str, list[RollupRow]] = {}
    for r in rows:
        by_benchmark.setdefault(r.benchmark, []).append(r)
    for benchmark in sorted(by_benchmark):
        blist = by_benchmark[benchmark]
        sub = [r for r in blist if r.validator_status != "refused-by-cli"]
        c = sum(1 for r in sub if r.validator_status == "clean")
        lines.append(
            f"# benchmark={benchmark}: total={len(blist)} submittable={len(sub)} "
            f"clean={c} validator_clean_rate={_rate(c, len(sub))}"
        )

    return lines


def render_tsv(rows: list[RollupRow]) -> str:
    body = [TSV_HEADER]
    body.extend(r.to_tsv() for r in rows)
    body.extend(format_footer(rows))
    return "\n".join(body) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Roll up validate_submission.py outcomes across a sweep results directory.",
    )
    parser.add_argument(
        "path",
        type=Path,
        help="Directory containing result-JSON bundles (or a single file).",
    )
    parser.add_argument(
        "--output",
        default="-",
        help="Output TSV path. Use '-' (default) for stdout.",
    )
    parser.add_argument(
        "--newer",
        type=Path,
        default=None,
        help="Optional sentinel file. Only bundles modified at or after the "
        "sentinel's mtime are included (mirrors the sweep_start sentinel "
        "pattern in benchmark_runs/logs/uat_*/).",
    )
    args = parser.parse_args(argv)

    if not args.path.exists():
        print(f"error: {args.path} does not exist", file=sys.stderr)
        return 2

    if args.path.is_dir():
        bundles = discover_bundles(args.path)
    else:
        bundles = [args.path]

    if args.newer is not None:
        if not args.newer.exists():
            print(f"error: --newer sentinel {args.newer} does not exist", file=sys.stderr)
            return 2
        bundles = _filter_newer(bundles, args.newer)

    rows = build_rows(bundles)
    output = render_tsv(rows)

    if args.output == "-":
        sys.stdout.write(output)
    else:
        Path(args.output).write_text(output, encoding="utf-8")

    return 0


if __name__ == "__main__":
    sys.exit(main())
