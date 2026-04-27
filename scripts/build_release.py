#!/usr/bin/env python3
"""Build release packages with normalized timestamps."""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from benchbox.release.workflow import compute_source_fingerprint


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file.

    Args:
        file_path: Path to file to hash

    Returns:
        Hexadecimal SHA256 hash string
    """
    sha256 = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def verify_wheel_timestamps(wheel_path: Path, expected_timestamp: int) -> bool:
    """Verify all files in a wheel have the expected timestamp.

    Args:
        wheel_path: Path to the wheel file
        expected_timestamp: Expected Unix timestamp

    Returns:
        True if all timestamps match, False otherwise
    """
    mismatches: list[tuple[str, int]] = []

    with zipfile.ZipFile(wheel_path, "r") as zf:
        for info in zf.infolist():
            # Convert date_time tuple to unix timestamp (interpret as UTC to match SOURCE_DATE_EPOCH)
            file_dt = datetime(*info.date_time, tzinfo=timezone.utc)
            file_ts = int(file_dt.timestamp())

            # Allow 1 second tolerance for rounding differences
            if abs(file_ts - expected_timestamp) > 1:
                mismatches.append((info.filename, file_ts))

    if mismatches:
        print(f"\n⚠️  Timestamp mismatches found in {wheel_path.name}:")
        for filename, ts in mismatches[:10]:  # Show first 10
            print(f"  - {filename}: {ts} (expected {expected_timestamp})")
        if len(mismatches) > 10:
            print(f"  ... and {len(mismatches) - 10} more")
        return False

    return True


def build_with_timestamp(target: Path, timestamp: int, verify: bool = True) -> tuple[Path, Path]:
    """Build wheel and sdist with normalized timestamp.

    Args:
        target: Directory containing pyproject.toml
        timestamp: Unix timestamp for SOURCE_DATE_EPOCH
        verify: Whether to verify timestamps in built artifacts

    Returns:
        tuple[Path, Path]: (wheel_path, sdist_path)

    Raises:
        RuntimeError: If build fails or artifacts not found
        ValueError: If timestamp verification fails
    """
    if not target.is_dir():
        raise ValueError(f"Target directory does not exist: {target}")

    pyproject = target / "pyproject.toml"
    if not pyproject.exists():
        raise ValueError(f"pyproject.toml not found in {target}")

    # Set SOURCE_DATE_EPOCH for reproducible builds
    env = os.environ.copy()
    env["SOURCE_DATE_EPOCH"] = str(timestamp)

    print(f"Building packages in {target}")
    print(f"SOURCE_DATE_EPOCH={timestamp}")

    # Run uv build
    try:
        subprocess.run(
            ["uv", "build"],
            cwd=target,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        print("Build failed:")
        print(e.stdout)
        print(e.stderr)
        raise RuntimeError("Build failed") from e

    # Find built artifacts
    dist_dir = target / "dist"
    if not dist_dir.exists():
        raise RuntimeError(f"dist/ directory not created in {target}")

    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))

    if not wheels:
        raise RuntimeError(f"No wheel found in {dist_dir}")
    if not sdists:
        raise RuntimeError(f"No sdist found in {dist_dir}")

    wheel_path = wheels[0]
    sdist_path = sdists[0]

    print(f"✓ Built: {wheel_path.name} ({wheel_path.stat().st_size:,} bytes)")
    print(f"✓ Built: {sdist_path.name} ({sdist_path.stat().st_size:,} bytes)")

    # Verify timestamps in wheel if requested
    if verify:
        print("\nVerifying timestamps in wheel...")
        if verify_wheel_timestamps(wheel_path, timestamp):
            print("✓ All timestamps verified")
        else:
            raise ValueError("Timestamp verification failed")

    return wheel_path, sdist_path


def verify_build_fingerprint(target: Path, wheel_path: Path) -> str:
    """Verify that the built wheel matches the source tree.

    Computes a source fingerprint from the source tree, extracts the wheel,
    computes a fingerprint from the extracted package, and compares them.
    Writes the fingerprint to dist/.source_fingerprint for downstream verification.

    Args:
        target: Directory containing the source tree (with benchbox/ subdirectory)
        wheel_path: Path to the built wheel file

    Returns:
        The verified fingerprint string

    Raises:
        ValueError: If the source and wheel fingerprints don't match
    """
    print("\nVerifying source fingerprint...")

    # Compute fingerprint from source tree
    source_fp = compute_source_fingerprint(target / "benchbox")
    print(f"  Source fingerprint: {source_fp[:16]}...")

    # Extract wheel to temp dir and compute fingerprint
    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            zf.extractall(tmpdir)
        wheel_pkg_dir = Path(tmpdir) / "benchbox"
        if not wheel_pkg_dir.is_dir():
            raise ValueError(f"benchbox/ directory not found in wheel: {wheel_path.name}")
        wheel_fp = compute_source_fingerprint(wheel_pkg_dir)

    print(f"  Wheel fingerprint: {wheel_fp[:16]}...")

    if source_fp != wheel_fp:
        raise ValueError(
            f"Source/wheel fingerprint mismatch!\n"
            f"  Source: {source_fp}\n"
            f"  Wheel:  {wheel_fp}\n"
            f"The wheel does not match the current source tree."
        )

    # Write fingerprint for downstream verification
    fp_file = target / "dist" / ".source_fingerprint"
    fp_file.write_text(source_fp + "\n", encoding="utf-8")
    print(f"✓ Fingerprint verified and written to {fp_file.relative_to(target)}")

    return source_fp


def format_bytes(num_bytes: int | float) -> str:
    """Format byte count as human-readable string."""
    value: float = float(num_bytes)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024:
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} TB"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="Directory containing pyproject.toml to build",
    )
    parser.add_argument(
        "--timestamp",
        type=int,
        required=True,
        help="Unix timestamp for SOURCE_DATE_EPOCH",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip timestamp verification",
    )
    parser.add_argument(
        "--hash-only",
        action="store_true",
        help="Only calculate hashes (skip build)",
    )

    args = parser.parse_args()

    if args.hash_only:
        # Just calculate hashes of existing artifacts
        dist_dir = args.target / "dist"
        if not dist_dir.exists():
            print(f"❌ dist/ directory not found in {args.target}")
            return

        for artifact in dist_dir.glob("*"):
            if artifact.suffix in (".whl", ".gz"):
                sha = calculate_sha256(artifact)
                size = format_bytes(artifact.stat().st_size)
                print(f"{artifact.name}")
                print(f"  Size: {size}")
                print(f"  SHA256: {sha}")
    else:
        # Build and calculate hashes
        wheel_path, sdist_path = build_with_timestamp(
            target=args.target,
            timestamp=args.timestamp,
            verify=not args.no_verify,
        )

        # Verify source fingerprint (source tree vs wheel contents)
        verify_build_fingerprint(args.target, wheel_path)

        # Calculate hashes
        print("\nCalculating SHA256 hashes...")
        wheel_hash = calculate_sha256(wheel_path)
        sdist_hash = calculate_sha256(sdist_path)

        print(f"\n{'=' * 60}")
        print("Release Artifacts")
        print(f"{'=' * 60}")
        print(f"\nWheel: {wheel_path.name}")
        print(f"  Size: {format_bytes(wheel_path.stat().st_size)}")
        print(f"  SHA256: {wheel_hash}")
        print(f"\nSdist: {sdist_path.name}")
        print(f"  Size: {format_bytes(sdist_path.stat().st_size)}")
        print(f"  SHA256: {sdist_hash}")
        print(f"\n{'=' * 60}")


if __name__ == "__main__":
    main()
