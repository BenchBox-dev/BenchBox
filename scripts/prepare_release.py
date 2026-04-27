#!/usr/bin/env python3
"""Prepare a sanitized copy of the repository for public release."""

from __future__ import annotations

import argparse
from pathlib import Path

from benchbox.release.workflow import calculate_release_timestamp, prepare_public_release


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="Destination directory for the curated release tree.",
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Source repository root (default: current working directory).",
    )
    parser.add_argument(
        "--version",
        type=str,
        default="0.1.0",
        help="Version string to embed in the release metadata.",
    )
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Do not delete the target directory before copying.",
    )
    parser.add_argument(
        "--init-git",
        action="store_true",
        help="Initialise a git repository in the target directory and stage files.",
    )
    parser.add_argument(
        "--include",
        action="append",
        dest="includes",
        default=[],
        metavar="PATH",
        help=(
            "Additional files or directories (relative to the source root) to "
            "include in the public snapshot. May be provided multiple times."
        ),
    )
    parser.add_argument(
        "--timestamp",
        type=int,
        default=None,
        help=(
            "Unix timestamp for normalizing file modification times. "
            "If not provided, uses the most recent whole hour UTC."
        ),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Calculate timestamp if not provided
    timestamp = args.timestamp
    if timestamp is None:
        timestamp, iso_fmt, _ = calculate_release_timestamp()
        print(f"Using most recent whole hour: {iso_fmt} (timestamp: {timestamp})")
    else:
        print(f"Using provided timestamp: {timestamp}")

    prepare_public_release(
        source=args.source.resolve(),
        target=args.target.resolve(),
        version=args.version,
        clean=not args.no_clean,
        init_git=args.init_git,
        extra_root_files=args.includes or None,
        timestamp=timestamp,
    )


if __name__ == "__main__":
    main()
