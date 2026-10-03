#!/usr/bin/env python3
"""Delete old GitHub Actions workflow runs.

Usage:
    # Dry-run (default): show what would be deleted
    python scripts/cleanup_workflows.py --older-than 60

    # Actually delete workflows older than 60 minutes
    python scripts/cleanup_workflows.py --older-than 60 --delete

    # Delete all workflow runs (use with caution)
    python scripts/cleanup_workflows.py --older-than 0 --delete
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone

CLI_DESCRIPTION = (
    "Delete old GitHub Actions workflow runs.\n"
    "\n"
    "Usage:\n"
    "    # Dry-run (default): show what would be deleted\n"
    "    python scripts/cleanup_workflows.py --older-than 60\n"
    "\n"
    "    # Actually delete workflows older than 60 minutes\n"
    "    python scripts/cleanup_workflows.py --older-than 60 --delete\n"
    "\n"
    "    # Delete all workflow runs (use with caution)\n"
    "    python scripts/cleanup_workflows.py --older-than 0 --delete\n"
)


def get_workflow_runs(repo: str | None = None) -> list[dict]:
    """Fetch all workflow runs from GitHub.

    Args:
        repo: Repository in owner/repo format. If None, uses current repo.

    Returns:
        List of workflow run dictionaries.
    """
    cmd = ["gh", "run", "list", "--json", "databaseId,createdAt,status,name,conclusion", "--limit", "1000"]
    if repo:
        cmd.extend(["--repo", repo])

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Failed to fetch workflow runs: {result.stderr}")
        sys.exit(1)

    return json.loads(result.stdout)


def parse_timestamp(timestamp: str) -> datetime:
    """Parse GitHub timestamp to datetime."""
    # GitHub returns ISO 8601 format: 2024-01-15T10:30:00Z
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00"))


def delete_workflow_run(run_id: int, repo: str | None = None) -> bool:
    """Delete a specific workflow run.

    Args:
        run_id: The database ID of the workflow run.
        repo: Repository in owner/repo format. If None, uses current repo.

    Returns:
        True if deletion succeeded, False otherwise.
    """
    cmd = ["gh", "run", "delete", str(run_id)]
    if repo:
        cmd.extend(["--repo", repo])

    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=CLI_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--older-than",
        type=int,
        required=True,
        metavar="MINUTES",
        help="Delete workflow runs older than this many minutes",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="Actually delete the workflows (default is dry-run)",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Repository in owner/repo format (default: current repo)",
    )
    parser.add_argument(
        "--status",
        type=str,
        choices=["completed", "in_progress", "queued", "all"],
        default="all",
        help="Only delete runs with this status (default: all)",
    )

    args = parser.parse_args()

    # Check gh CLI is available
    if not shutil.which("gh"):
        print("❌ GitHub CLI (gh) not found in PATH")
        print("   Install: https://cli.github.com/")
        return 1

    # Fetch workflow runs
    print(f"Fetching workflow runs{f' from {args.repo}' if args.repo else ''}...")
    runs = get_workflow_runs(args.repo)

    if not runs:
        print("No workflow runs found.")
        return 0

    # Calculate cutoff time
    now = datetime.now(timezone.utc)
    cutoff_minutes = args.older_than

    # Filter runs to delete
    to_delete = []
    for run in runs:
        created_at = parse_timestamp(run["createdAt"])
        age_minutes = (now - created_at).total_seconds() / 60

        if age_minutes < cutoff_minutes:
            continue

        if args.status != "all" and run["status"].lower() != args.status:
            continue

        to_delete.append(
            {
                "id": run["databaseId"],
                "name": run["name"],
                "status": run["status"],
                "conclusion": run.get("conclusion", "N/A"),
                "created_at": run["createdAt"],
                "age_minutes": int(age_minutes),
            }
        )

    if not to_delete:
        print(f"No workflow runs older than {cutoff_minutes} minutes found.")
        return 0

    # Display what will be deleted
    print(f"\nFound {len(to_delete)} workflow run(s) older than {cutoff_minutes} minutes:\n")
    print(f"{'ID':<12} {'Age (min)':<10} {'Status':<12} {'Conclusion':<12} Name")
    print("-" * 80)
    for run in to_delete:
        print(f"{run['id']:<12} {run['age_minutes']:<10} {run['status']:<12} {run['conclusion']:<12} {run['name']}")

    if not args.delete:
        print("\n⚠️  Dry-run mode: No workflows deleted.")
        print(f"   Add --delete to actually delete these {len(to_delete)} workflow run(s).")
        return 0

    # Delete workflows
    print(f"\nDeleting {len(to_delete)} workflow run(s)...")
    deleted = 0
    failed = 0

    for run in to_delete:
        if delete_workflow_run(run["id"], args.repo):
            deleted += 1
            print(f"  ✓ Deleted {run['id']} ({run['name']})")
        else:
            failed += 1
            print(f"  ✗ Failed to delete {run['id']} ({run['name']})")

    print(f"\n{'✅' if failed == 0 else '⚠️ '} Deleted {deleted}/{len(to_delete)} workflow run(s)")
    if failed > 0:
        print(f"   {failed} deletion(s) failed")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
