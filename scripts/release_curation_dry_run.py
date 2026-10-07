#!/usr/bin/env python3
"""Run tests on a simulated release tree to find tests that read curated-away paths.

`make release-cut` removes development-only paths with the `git rm` commands in
its recipe. A test that reads one of those paths passes on develop and fails the
release PR's required test job. This script runs those same commands, parsed
from the Makefile, in a detached scratch worktree at HEAD, then runs pytest there
with the release test job's marker selection.

Only committed content is checked. Run locally:

    uv run -- python scripts/release_curation_dry_run.py                # full fast selection
    uv run -- python scripts/release_curation_dry_run.py --changed-since origin/develop
    uv run -- python scripts/release_curation_dry_run.py tests/unit/test_example.py

Fix a failure by skipping the test when the specific file it reads is absent, or,
when the whole file tests development-only tooling, by adding it to the
release-cut strip list. docs/operations/release-guide.md describes both.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_release_curation import release_cut_rm_commands  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
# The marker selection of the release PR's required test job in .github/workflows/test.yml.
FAST_SELECTION = "fast and not (slow or stress or resource_heavy or live_integration)"
NO_TESTS_COLLECTED = 5


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def changed_test_files(root: Path, base: str) -> list[str]:
    """Return test modules added, modified or renamed since the merge base with ``base``."""
    out = _git(root, "diff", "--name-only", "--diff-filter=AMR", f"{base}...HEAD", "--", "tests")
    return [p for p in out.splitlines() if Path(p).name.startswith("test_") and p.endswith(".py")]


@contextmanager
def curated_tree(root: Path, commands: Sequence[Sequence[str]]) -> Iterator[Path]:
    """Yield a detached worktree of HEAD with the release-cut removals applied."""
    with tempfile.TemporaryDirectory(prefix="release-curation-") as tmp:
        tree = Path(tmp) / "tree"
        _git(root, "worktree", "add", "--detach", "--quiet", str(tree), "HEAD")
        try:
            for command in commands:
                subprocess.run(command, cwd=tree, check=True, capture_output=True, text=True)
            yield tree
        finally:
            _git(root, "worktree", "remove", "--force", str(tree))


def pytest_command(targets: Sequence[str], marker: str) -> list[str]:
    """Run in the scratch tree's own environment so imports resolve inside that tree."""
    parallel = [] if targets else ["-n", "auto"]
    return ["uv", "run", "--", "python", "-m", "pytest", *(targets or ["tests"]), "-m", marker, "-q", *parallel]


def run(
    root: Path,
    targets: Sequence[str],
    *,
    makefile: Path | None = None,
    marker: str = FAST_SELECTION,
    command: Sequence[str] | None = None,
) -> int:
    """Return 0 when the selected tests pass on the curated tree, 1 otherwise."""
    commands = release_cut_rm_commands(makefile or root / "Makefile")
    with curated_tree(root, commands) as tree:
        if targets:
            kept = [t for t in targets if (tree / t).exists()]
            for stripped in sorted(set(targets) - set(kept)):
                print(f"skipped (removed by release-cut): {stripped}")
            if not kept:
                print("release curation dry run: no selected test remains on the release tree")
                return 0
            targets = kept
        argv = [*command, *(targets or ["tests"])] if command else pytest_command(targets, marker)
        result = subprocess.run(argv, cwd=tree, check=False)
    if result.returncode in (0, NO_TESTS_COLLECTED):
        print("release curation dry run: OK")
        return 0
    print(
        "release curation dry run: FAILED. A test above fails on the release tree, usually because it reads a "
        "path that release-cut removes. Skip it when that specific file is absent, or add the test to the "
        "release-cut strip list; see 'Tests on the release tree' in docs/operations/release-guide.md.",
        file=sys.stderr,
    )
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tests", nargs="*", help="test paths to run; default: every test in the fast selection")
    parser.add_argument("--changed-since", metavar="REF", help="run only test modules changed since REF")
    args = parser.parse_args(argv)
    targets = list(args.tests)
    if args.changed_since:
        targets += changed_test_files(REPO_ROOT, args.changed_since)
        if not targets:
            print(f"release curation dry run: no test modules changed since {args.changed_since}")
            return 0
    return run(REPO_ROOT, targets)


if __name__ == "__main__":
    sys.exit(main())
