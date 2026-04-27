"""Repository timing inventory and classification report."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

RE_TIME_TIME = re.compile(r"\btime\.time\(")
RE_DATETIME_NOW = re.compile(r"\bdatetime\.now\(")
RE_MONO = re.compile(r"\bmono_time\(")
RE_ELAPSED = re.compile(r"\belapsed_seconds\(")
RE_PERF = re.compile(r"\bperf_counter\(")
RE_WALLCLOCK_ARITH = re.compile(
    r"(time\.time\(\)\s*[-+*/]|[-+*/]\s*time\.time\(\)|datetime\.now\(\)\s*-\s*|-\s*datetime\.now\(\))"
)


@dataclass
class Finding:
    path: str
    line: int
    symbol: str
    classification: str
    text: str


def _classify(symbol: str, line: str) -> str:
    if symbol in {"mono_time", "elapsed_seconds", "perf_counter"}:
        return "monotonic"
    if RE_WALLCLOCK_ARITH.search(line):
        return "elapsed_or_timeout_wall_clock"
    lowered = line.lower()
    if any(token in lowered for token in ("timestamp", "isoformat", "st_mtime", "mtime", "created", "updated")):
        return "event_wall_clock"
    return "wall_clock_unknown"


def _iter_py_files(roots: list[Path]) -> list[Path]:
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file() and root.suffix == ".py":
            files.append(root)
            continue
        for path in root.rglob("*.py"):
            if any(part in {".git", ".venv", "site-packages", "__pycache__"} for part in path.parts):
                continue
            files.append(path)
    return sorted(set(files))


def collect_findings(repo_root: Path, roots: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for file_path in _iter_py_files([repo_root / root for root in roots]):
        rel = file_path.relative_to(repo_root).as_posix()
        for lineno, line in enumerate(file_path.read_text(encoding="utf-8").splitlines(), start=1):
            symbol = None
            if RE_TIME_TIME.search(line):
                symbol = "time.time"
            elif RE_DATETIME_NOW.search(line):
                symbol = "datetime.now"
            elif RE_MONO.search(line):
                symbol = "mono_time"
            elif RE_ELAPSED.search(line):
                symbol = "elapsed_seconds"
            elif RE_PERF.search(line):
                symbol = "perf_counter"
            if symbol is None:
                continue
            findings.append(
                Finding(
                    path=rel,
                    line=lineno,
                    symbol=symbol,
                    classification=_classify(symbol, line),
                    text=line.strip(),
                )
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory and classify timing callsites.")
    parser.add_argument(
        "--roots",
        nargs="+",
        default=[
            "benchbox",
            "scripts",
            "_project/scripts",
        ],
        help="Directories to scan (default: full benchbox tree)",
    )
    parser.add_argument("--report", action="store_true", help="Emit human-readable report")
    parser.add_argument("--json", action="store_true", help="Emit JSON report")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[2]
    findings = collect_findings(repo_root, args.roots)

    summary: dict[str, int] = {}
    for finding in findings:
        key = f"{finding.symbol}:{finding.classification}"
        summary[key] = summary.get(key, 0) + 1

    payload = {
        "roots": args.roots,
        "total_findings": len(findings),
        "summary": dict(sorted(summary.items())),
        "findings": [asdict(f) for f in findings],
    }

    if args.json or not args.report:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Timing audit findings: {len(findings)}")
        for key, count in sorted(summary.items()):
            print(f"- {key}: {count}")
        unresolved = [
            f
            for f in findings
            if f.classification in {"elapsed_or_timeout_wall_clock", "wall_clock_unknown"} and f.symbol in {"time.time", "datetime.now"}
        ]
        print(f"\nPotential policy violations: {len(unresolved)}")
        for finding in unresolved[:200]:
            print(f"{finding.path}:{finding.line} [{finding.classification}] {finding.text}")
        if len(unresolved) > 200:
            print(f"... truncated {len(unresolved) - 200} additional potential violations")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
