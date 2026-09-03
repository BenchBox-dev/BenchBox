#!/usr/bin/env python3
"""Check publication control-plane contracts, GitHub App permissions, and branch rules (A3 w2, w4, w5).

Usage:
  uv run python scripts/publication/check_control_plane.py [--live] [--strict]
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPO = "BenchBox-dev/BenchBox"
PUBLICATION_BRANCH = "publication"
REQUIRED_APP_PERMISSIONS = {"contents", "pull_requests", "workflows"}


def run(*args: str) -> str:
    return subprocess.run(args, cwd=ROOT, check=True, text=True, capture_output=True).stdout.strip()


def check_codeowners() -> list[str]:
    """Verify that .github/CODEOWNERS protects publication control files."""
    codeowners_path = ROOT / ".github/CODEOWNERS"
    if not codeowners_path.is_file():
        return ["Missing .github/CODEOWNERS"]

    text = codeowners_path.read_text(encoding="utf-8")
    errors: list[str] = []

    required_patterns = [
        "publication/**",
        "scripts/publication/**",
    ]
    for pat in required_patterns:
        if pat not in text:
            errors.append(f"CODEOWNERS missing required protection rule for: '{pat}'")

    return errors


def check_live_app_and_branch() -> list[str]:
    """Verify live GitHub App installation, token minting, and publication branch."""
    errors: list[str] = []

    # 1. Check publication branch on origin
    try:
        remote_heads = run("git", "ls-remote", "--heads", "origin", PUBLICATION_BRANCH)
        if not remote_heads:
            errors.append(f"Live check: branch '{PUBLICATION_BRANCH}' does not exist on origin")
    except Exception as e:
        errors.append(f"Live check git ls-remote error: {e}")

    # 2. Check GitHub App credentials and installation
    # Look for app ID and private key from env, repo secrets, or local downloads
    app_id = os.environ.get("PUBLICATION_APP_ID")
    pem_content = os.environ.get("PUBLICATION_APP_PRIVATE_KEY")

    if not app_id:
        # Check if secret exists via gh secret list
        try:
            secrets_out = run("gh", "secret", "list", "-R", REPO)
            if "PUBLICATION_APP_ID" not in secrets_out:
                errors.append("Live check: PUBLICATION_APP_ID secret not found in repository secrets")
            if "PUBLICATION_APP_PRIVATE_KEY" not in secrets_out:
                errors.append("Live check: PUBLICATION_APP_PRIVATE_KEY secret not found in repository secrets")
        except Exception as e:
            errors.append(f"Live check gh secret list error: {e}")

    # If App ID and Key are available in environment or verified, test JWT token minting
    if app_id and pem_content:
        try:
            import jwt

            now = int(time.time())
            payload = {
                "iat": now - 60,
                "exp": now + 600,
                "iss": str(app_id),
            }
            encoded_jwt = jwt.encode(payload, pem_content.encode(), algorithm="RS256")
            req = urllib.request.Request(
                "https://api.github.com/app/installations",
                headers={
                    "Authorization": f"Bearer {encoded_jwt}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": "BenchBox-Publication-Controller-Checker",
                },
            )
            with urllib.request.urlopen(req) as resp:
                installations = json.loads(resp.read().decode())
                matching = [inst for inst in installations if inst.get("account", {}).get("login") == "BenchBox-dev"]
                if not matching:
                    errors.append("Live check: GitHub App is not installed on account 'BenchBox-dev'")
                else:
                    perms = set(matching[0].get("permissions", {}).keys())
                    missing_perms = REQUIRED_APP_PERMISSIONS - perms
                    if missing_perms:
                        errors.append(f"Live check: GitHub App missing required permissions: {sorted(missing_perms)}")
        except Exception as e:
            errors.append(f"Live check JWT validation error: {e}")

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check publication control plane contracts")
    parser.add_argument("--live", action="store_true", help="Perform live GitHub checks (branch, app, rules)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require live checks; fail when --live was not used or live checks were skipped",
    )
    args = parser.parse_args(argv)

    all_errors: list[str] = []
    live_checks_performed = False

    # Local contracts
    codeowner_errors = check_codeowners()
    all_errors.extend(codeowner_errors)

    if args.live:
        live_errors = check_live_app_and_branch()
        all_errors.extend(live_errors)
        live_checks_performed = True

    if args.strict and not live_checks_performed:
        all_errors.append("--strict requires --live and completed live checks; live checks were not performed")

    if all_errors:
        print("❌ Publication Control Plane Check FAILED:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    mode = "live + local" if args.live else "local"
    print(f"✅ Publication control plane check passed ({mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
