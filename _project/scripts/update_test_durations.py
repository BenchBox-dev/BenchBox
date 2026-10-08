from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tests.duration_policy import collect_junit_durations, write_duration_file

CLI_DESCRIPTION = "Regenerate the committed per-test p95 artifact from T3 JUnit reports."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=CLI_DESCRIPTION)
    parser.add_argument("--input", type=Path, action="append", required=True, help="JUnit XML report to merge")
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "tests" / "fixtures" / "test_durations.json",
        help="Committed duration artifact to write",
    )
    parser.add_argument("--source", default="T3 nightly JUnit reports", help="Provenance label for the artifact")
    args = parser.parse_args(argv)

    durations = collect_junit_durations(args.input)
    write_duration_file(args.output, durations, source=args.source)
    print(f"wrote {len(durations)} test durations to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
