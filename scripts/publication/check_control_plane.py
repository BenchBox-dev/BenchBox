#!/usr/bin/env python3
"""Check publication control-plane contracts, token permissions, and branch rules.

Verifies:
1. CODEOWNERS protection for publication files.
2. Publication metadata ref existence and branch protection rules (no force-push, no deletion).
3. Role-scoped permissions:
   - 'journal' role requires only 'contents' write (least privilege for metadata ref updates).
   - 'legacy_app' role requires 'contents', 'pull_requests', and 'workflows'.

Usage:
  uv run python scripts/publication/check_control_plane.py [--live] [--strict] [--role {journal,legacy_app}]
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

# Journal updates require contents write only; PR/workflow writes are not required
REQUIRED_JOURNAL_PERMISSIONS = {"contents": "write"}
REQUIRED_LEGACY_APP_PERMISSIONS = {"contents": "write", "pull_requests": "write", "workflows": "write"}
REQUIRED_APP_PERMISSIONS = REQUIRED_JOURNAL_PERMISSIONS


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


def check_permissions(perms: dict[str, str], role: str = "journal") -> list[str]:
    """Check that token/app permissions satisfy the least-privilege contract for the given role."""
    errors: list[str] = []
    required = REQUIRED_JOURNAL_PERMISSIONS if role == "journal" else REQUIRED_LEGACY_APP_PERMISSIONS
    for name, level in required.items():
        if perms.get(name) != level:
            errors.append(f"Permission {name!r} must be {level!r}, got {perms.get(name)!r}")
    excess = set(perms) - set(required) - {"metadata"}
    if excess:
        errors.append(f"Excess permissions for {role} role: {sorted(excess)}")
    return errors


def check_branch_protection(
    repo: str = REPO,
    branch: str = PUBLICATION_BRANCH,
    *,
    gh_output: str | None = None,
) -> list[str]:
    """Verify that the publication metadata ref has branch protection blocking force-push and deletion."""
    errors: list[str] = []
    try:
        if gh_output is None:
            gh_output = run("gh", "api", f"repos/{repo}/branches/{branch}/protection")
        data = json.loads(gh_output)
    except Exception as e:
        return [f"Branch '{branch}' lacks verified protection rules on {repo}: {e}"]

    allow_force = data.get("allow_force_pushes", {}).get("enabled", False)
    if allow_force:
        errors.append(f"Branch '{branch}' permits force pushes (must be blocked for journal integrity)")

    allow_deletions = data.get("allow_deletions", {}).get("enabled", False)
    if allow_deletions:
        errors.append(f"Branch '{branch}' permits deletions (must be blocked for journal integrity)")

    enforce_admins = data.get("enforce_admins", {}).get("enabled", False)
    if not enforce_admins:
        errors.append(
            f"Branch '{branch}' does not enforce protection rules on administrators (enforce_admins must be enabled)"
        )

    return errors


def check_live_app_and_branch(role: str = "journal", strict: bool = False) -> list[str]:
    """Verify live GitHub App installation, token minting, and publication branch protection."""
    errors: list[str] = []

    # 1. Check publication branch on origin
    try:
        remote_heads = run("git", "ls-remote", "--heads", "origin", PUBLICATION_BRANCH)
        if not remote_heads:
            errors.append(f"Live check: branch '{PUBLICATION_BRANCH}' does not exist on origin")
        else:
            # Check branch protection rules
            protection_errors = check_branch_protection(REPO, PUBLICATION_BRANCH)
            errors.extend(protection_errors)
    except Exception as e:
        errors.append(f"Live check git ls-remote error: {e}")

    # 2. Check GitHub App credentials and installation
    app_id = os.environ.get("PUBLICATION_APP_ID")
    pem_content = os.environ.get("PUBLICATION_APP_PRIVATE_KEY")

    if not app_id:
        try:
            secrets_out = run("gh", "secret", "list", "-R", REPO)
            if "PUBLICATION_APP_ID" not in secrets_out:
                errors.append("Live check: PUBLICATION_APP_ID secret not found in repository secrets")
            if "PUBLICATION_APP_PRIVATE_KEY" not in secrets_out:
                errors.append("Live check: PUBLICATION_APP_PRIVATE_KEY secret not found in repository secrets")
        except Exception as e:
            errors.append(f"Live check gh secret list error: {e}")

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
                    perms = matching[0].get("permissions", {})
                    perm_errors = check_permissions(perms, role=role)
                    errors.extend(perm_errors)
        except Exception as e:
            errors.append(f"Live check JWT validation error: {e}")
    elif strict:
        errors.append(
            "Live check: PUBLICATION_APP_ID and PUBLICATION_APP_PRIVATE_KEY credentials are required in environment "
            f"to verify app permissions for role {role!r} under --strict"
        )

    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check publication control plane contracts")
    parser.add_argument("--live", action="store_true", help="Perform live GitHub checks (branch, app, rules)")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Require live checks; fail when --live was not used or live checks were skipped",
    )
    parser.add_argument(
        "--role",
        choices=["journal", "legacy_app"],
        default="journal",
        help="Permission role to validate (journal: contents only; legacy_app: contents, pull_requests, workflows)",
    )
    args = parser.parse_args(argv)

    all_errors: list[str] = []
    live_checks_performed = False

    # Local contracts
    codeowner_errors = check_codeowners()
    all_errors.extend(codeowner_errors)

    if args.live:
        live_errors = check_live_app_and_branch(role=args.role, strict=args.strict)
        all_errors.extend(live_errors)
        live_checks_performed = True

    if args.strict and not live_checks_performed:
        all_errors.append("--strict requires --live and completed live checks; live checks were not performed")

    if all_errors:
        print("❌ Publication Control Plane Check FAILED:")
        for err in all_errors:
            print(f"  - {err}")
        return 1

    mode = f"live ({args.role}) + local" if args.live else "local"
    print(f"✅ Publication control plane check passed ({mode}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
