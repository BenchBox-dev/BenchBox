#!/usr/bin/env python3
"""Verify release artifacts and run smoke tests."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from benchbox.release.workflow import compute_source_fingerprint


def run_smoke_tests(wheel_path: Path, verbose: bool = False) -> bool:
    """Run smoke tests in an isolated environment.

    Args:
        wheel_path: Path to the wheel file to test
        verbose: Show detailed output

    Returns:
        True if all tests pass, False otherwise
    """
    # Find uv executable (required for creating venv and installing packages)
    uv_path = shutil.which("uv")
    if not uv_path:
        print("❌ uv executable not found in PATH")
        return False

    print("\n" + "=" * 60)
    print("Running Smoke Tests")
    print("=" * 60)

    with tempfile.TemporaryDirectory() as tmpdir:
        venv_dir = Path(tmpdir) / "benchbox-test-venv"

        # Create virtual environment
        print(f"\n1. Creating temporary venv at {venv_dir}")
        result = subprocess.run(
            [uv_path, "venv", str(venv_dir), "--python", "3.12"],
            capture_output=not verbose,
            text=True,
        )
        if result.returncode != 0:
            print("❌ Failed to create venv")
            if not verbose and result.stderr:
                print(result.stderr)
            return False
        print("✓ Venv created")

        # Install wheel
        print(f"\n2. Installing {wheel_path.name}")
        result = subprocess.run(
            [uv_path, "pip", "install", str(wheel_path)],
            env={"VIRTUAL_ENV": str(venv_dir)},
            capture_output=not verbose,
            text=True,
        )
        if result.returncode != 0:
            print("❌ Failed to install wheel")
            if not verbose and result.stderr:
                print(result.stderr)
            return False
        print("✓ Wheel installed")

        benchbox_exe = venv_dir / "bin" / "benchbox"
        if not benchbox_exe.exists():
            print(f"❌ benchbox executable not found at {benchbox_exe}")
            return False

        # Test 1: Version check
        print("\n3. Testing: benchbox --version")
        result = subprocess.run(
            [str(benchbox_exe), "--version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("❌ Version check failed")
            print(result.stderr)
            return False
        print(f"✓ Version: {result.stdout.strip()}")

        # Test 2: Dry-run
        print("\n4. Testing: benchbox run --dry-run (TPC-H on DuckDB)")
        dry_run_dir = Path(tmpdir) / "dry-run-preview"
        result = subprocess.run(
            [
                str(benchbox_exe),
                "run",
                "--dry-run",
                str(dry_run_dir),
                "--platform",
                "duckdb",
                "--benchmark",
                "tpch",
                "--scale",
                "0.01",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("❌ Dry-run failed")
            print(result.stderr)
            return False
        print("✓ Dry-run successful")

        # Test 3: Check dependencies
        print("\n5. Testing: benchbox check-deps")
        result = subprocess.run(
            [str(benchbox_exe), "check-deps"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("❌ check-deps failed")
            print(result.stderr)
            return False
        print("✓ Dependency check successful")

    print("\n" + "=" * 60)
    print("✅ All smoke tests passed!")
    print("=" * 60)
    return True


def verify_wheel_fingerprint(wheel_path: Path, expected_fingerprint: str) -> bool:
    """Verify that a wheel's contents match an expected source fingerprint.

    Extracts the wheel to a temporary directory, computes the fingerprint
    over the benchbox/ package within it, and compares against the expected value.

    Args:
        wheel_path: Path to the wheel file
        expected_fingerprint: Expected hex-encoded SHA256 fingerprint

    Returns:
        True if fingerprint matches, False otherwise
    """
    print(f"\nVerifying wheel fingerprint: {wheel_path.name}")

    with tempfile.TemporaryDirectory() as tmpdir:
        with zipfile.ZipFile(wheel_path, "r") as zf:
            zf.extractall(tmpdir)

        pkg_dir = Path(tmpdir) / "benchbox"
        if not pkg_dir.is_dir():
            print("❌ benchbox/ directory not found in wheel")
            return False

        actual = compute_source_fingerprint(pkg_dir)

    if actual != expected_fingerprint:
        print("❌ Fingerprint mismatch!")
        print(f"  Expected: {expected_fingerprint}")
        print(f"  Actual:   {actual}")
        return False

    print(f"✓ Fingerprint verified: {actual[:16]}...")
    return True


def verify_artifacts_exist(target: Path) -> tuple[Path | None, Path | None]:
    """Verify that wheel and sdist artifacts exist.

    Args:
        target: Directory containing dist/ folder

    Returns:
        tuple[Path | None, Path | None]: (wheel_path, sdist_path)
    """
    dist_dir = target / "dist"
    if not dist_dir.exists():
        print(f"❌ dist/ directory not found in {target}")
        return None, None

    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))

    if not wheels:
        print(f"❌ No wheel found in {dist_dir}")
        return None, None

    if not sdists:
        print(f"❌ No sdist found in {dist_dir}")
        return None, None

    wheel_path = wheels[0]
    sdist_path = sdists[0]

    print("\n" + "=" * 60)
    print("Artifacts Found")
    print("=" * 60)
    print(f"Wheel: {wheel_path.name}")
    print(f"  Size: {wheel_path.stat().st_size:,} bytes")
    print(f"Sdist: {sdist_path.name}")
    print(f"  Size: {sdist_path.stat().st_size:,} bytes")

    return wheel_path, sdist_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "target",
        type=Path,
        help="Directory containing dist/ folder with built artifacts",
    )
    parser.add_argument(
        "--skip-smoke-tests",
        action="store_true",
        help="Skip smoke tests (only verify artifacts exist)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed output from tests",
    )
    parser.add_argument(
        "--fingerprint",
        type=str,
        default=None,
        help="Expected source fingerprint (hex string) to verify against wheel contents",
    )

    args = parser.parse_args()

    # Verify artifacts exist
    wheel_path, sdist_path = verify_artifacts_exist(args.target)
    if wheel_path is None or sdist_path is None:
        return 1

    # Verify fingerprint if provided
    if args.fingerprint:
        if not verify_wheel_fingerprint(wheel_path, args.fingerprint):
            print("\n❌ Fingerprint verification failed")
            return 1

    # Run smoke tests unless skipped
    if not args.skip_smoke_tests:
        if not run_smoke_tests(wheel_path, verbose=args.verbose):
            print("\n❌ Smoke tests failed")
            return 1
    else:
        print("\n⚠️  Smoke tests skipped")

    print("\n✅ Verification complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
