#!/usr/bin/env python3
"""Prepare and verify a release as an ordinary pull request on ``develop``.

Two subcommands, exposed as ``make release-prep`` and ``make release-check``:

``prep --version X.Y.Z``
    Bumps every version marker (``benchbox/__init__.py``, ``pyproject.toml``,
    the documentation release markers, the landing-page badge) with
    ``scripts/update_version.py``, refreshes ``uv.lock`` with ``uv lock``, and
    drafts the ``CHANGELOG.md`` section with
    ``scripts/generate_changelog_entry.py``. The result is one normal PR diff.
    The drafted changelog section still needs hand-curation; ``check`` fails
    until it is curated.

``check --version X.Y.Z``
    Verifies the complete pre-tag state and exits non-zero with every problem
    found:

    * ``pyproject.toml``, ``benchbox/__init__.py``, the documentation release
      markers, the landing-page badge, and the ``uv.lock`` package entry all
      carry the requested version;
    * ``CHANGELOG.md`` has a dated, hand-curated section for the version;
    * the ``uv.lock`` schema revision has not been downgraded;
    * every top-level path is accounted for in the release curation lists;
    * no capped dependency has reached its upper bound.

    ``check`` is meant to run on a clean checkout, locally and in CI, so a tag
    is only cut from a tree that already passed it.
"""

from __future__ import annotations

import argparse
import importlib.util
import re
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path

from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parent.parent

# A subprocess runner: (argv, cwd) -> (returncode, combined output). Injectable
# so tests can prove each delegated element fails the check on its own.
Runner = Callable[[Sequence[str], Path], tuple[int, str]]

_RELEASE_TAG_RE = re.compile(r"^v\d+\.\d+\.\d+$")


def _load_script(name: str, root: Path):
    """Import ``scripts/<name>.py`` from ``root`` without requiring a package."""
    path = root / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_release_flow_{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def run_command(argv: Sequence[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(list(argv), cwd=cwd, capture_output=True, text=True, check=False)
    return result.returncode, (result.stdout + result.stderr).strip()


def normalize_version(value: str) -> str | None:
    """PEP 440 form of ``value`` (``0.4.2-rc.1`` -> ``0.4.2rc1``), or None."""
    try:
        return str(Version(value))
    except InvalidVersion:
        return None


# ---------------------------------------------------------------------------
# check
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError:
        return {}


def _pyproject_version(root: Path) -> str | None:
    path = root / "pyproject.toml"
    if not path.is_file():
        return None
    project = _load_toml(path).get("project", {})
    version = project.get("version")
    return version if isinstance(version, str) else None


def _init_version(root: Path) -> str | None:
    path = root / "benchbox" / "__init__.py"
    if not path.is_file():
        return None
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def _lock_version(root: Path) -> str | None:
    path = root / "uv.lock"
    if not path.is_file():
        return None
    lock = _load_toml(path)
    for package in lock.get("package", []):
        if package.get("name") == "benchbox":
            version = package.get("version")
            return version if isinstance(version, str) else None
    return None


def check_version_markers(root: Path, version: str) -> list[str]:
    """Every version marker must equal ``version`` (uv.lock is compared as PEP 440)."""
    update_version = _load_script("update_version", root)
    problems: list[str] = []

    def expect(label: str, found: str | None) -> None:
        if found is None:
            problems.append(f"{label}: no version marker found (expected {version})")
        elif found != version:
            problems.append(f"{label}: {found} != {version}")

    expect("pyproject.toml", _pyproject_version(root))
    expect("benchbox/__init__.py", _init_version(root))

    for doc in update_version.DOCUMENTATION_PATHS:
        path = root / doc
        found = None
        if path.is_file():
            match = update_version.DOC_RELEASE_PATTERN.search(path.read_text(encoding="utf-8"))
            # The marker pattern's pre-release class also matches a sentence-ending period.
            found = match.group("version").rstrip(".") if match else None
        expect(doc.as_posix(), found)

    landing = root / update_version.LANDING_PAGE_PATH
    found = None
    if landing.is_file():
        match = update_version.LANDING_VERSION_PATTERN.search(landing.read_text(encoding="utf-8"))
        found = match.group("version") if match else None
    expect("landing/index.html badge", found)

    lock_version = _lock_version(root)
    expected_lock = normalize_version(version)
    if lock_version is None:
        problems.append(f"uv.lock: no benchbox package entry found (expected {version})")
    elif normalize_version(lock_version) != expected_lock:
        problems.append(f"uv.lock: benchbox {lock_version} != {version}; run `uv lock`")
    return problems


def check_changelog(root: Path, version: str) -> list[str]:
    """A dated ``## [version]`` section must exist and look hand-curated."""
    changelog = _load_script("generate_changelog_entry", root)
    if not (root / "CHANGELOG.md").is_file():
        return ["CHANGELOG.md: file not found"]
    if not changelog.has_changelog_section(root, version):
        return [f"CHANGELOG.md: no '## [{version}] - <date>' section"]
    header = re.search(rf"^## \[{re.escape(version)}\] - (.+)$", (root / "CHANGELOG.md").read_text(), re.MULTILINE)
    try:
        if header is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", header[1]):
            raise ValueError("missing ISO date")
        date.fromisoformat(header[1])
    except ValueError:
        return [f"CHANGELOG.md [{version}]: release date must be a valid YYYY-MM-DD date"]
    _ok, problems = changelog.check_changelog_curation(root, version)
    return [f"CHANGELOG.md [{version}]: {problem}" for problem in problems]


def _delegated(label: str, argv: Sequence[str], root: Path, runner: Runner) -> list[str]:
    returncode, output = runner(argv, root)
    if returncode == 0:
        return []
    tail = "\n".join(output.splitlines()[-15:])
    return [f"{label}: `{' '.join(argv)}` exited {returncode}" + (f"\n{tail}" if tail else "")]


def check_uv_lock_revision(root: Path, runner: Runner, baseline_ref: str | None) -> list[str]:
    if baseline_ref is None:
        return ["uv.lock revision: no prior final release tag; provide --baseline-ref"]
    code, commit = run_command(["git", "rev-parse", "--verify", f"{baseline_ref}^{{commit}}"], root)
    if code != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        return [f"uv.lock revision: baseline {baseline_ref!r} cannot be resolved to a commit"]
    script = root / "_project" / "scripts" / "check_uv_lock_revision.py"
    return _delegated("uv.lock revision", [sys.executable, str(script), "--baseline-ref", commit], root, runner)


def check_release_curation(root: Path, runner: Runner) -> list[str]:
    script = root / "scripts" / "check_release_curation.py"
    return _delegated("release curation", [sys.executable, str(script)], root, runner)


def check_dependency_bounds(root: Path, runner: Runner) -> list[str]:
    script = root / "scripts" / "check_dependency_bounds.py"
    return _delegated("dependency bounds", [sys.executable, str(script), "--fail-on=cap-reached"], root, runner)


def run_checks(root: Path, version: str, runner: Runner = run_command, *, baseline_ref: str | None = None) -> list[str]:
    """Return every problem found; an empty list means the tree is ready to tag."""
    problems: list[str] = []
    if normalize_version(version) is None:
        return [f"version {version!r} is not a valid version"]
    problems += check_version_markers(root, version)
    problems += check_changelog(root, version)
    problems += check_uv_lock_revision(root, runner, baseline_ref or latest_release_tag(root, before_version=version))
    problems += check_release_curation(root, runner)
    problems += check_dependency_bounds(root, runner)
    return problems


# ---------------------------------------------------------------------------
# prep
# ---------------------------------------------------------------------------


def latest_release_tag(root: Path, *, before_version: str | None = None) -> str | None:
    """Newest final ``vX.Y.Z`` tag, as a full ref so a same-named branch cannot shadow it."""
    code, output = run_command(["git", "tag", "--list", "v[0-9]*", "--sort=-v:refname"], root)
    if code != 0:
        return None
    for tag in output.splitlines():
        if _RELEASE_TAG_RE.match(tag.strip()) and (
            before_version is None or Version(tag.strip()[1:]) < Version(before_version)
        ):
            return f"refs/tags/{tag.strip()}"
    return None


def prep(root: Path, version: str, since_ref: str | None, release_date: str | None, runner: Runner) -> int:
    update_version = root / "scripts" / "update_version.py"
    changelog = root / "scripts" / "generate_changelog_entry.py"
    if normalize_version(version) is None:
        print(f"release-prep: invalid version {version!r}", file=sys.stderr)
        return 1
    if release_date:
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", release_date):
                raise ValueError("date format")
            date.fromisoformat(release_date)
        except ValueError:
            print("release-prep: release date must be a valid YYYY-MM-DD date", file=sys.stderr)
            return 1
    ref = since_ref or latest_release_tag(root)
    if ref:
        code, output = runner(["git", "rev-parse", "--verify", f"{ref}^{{commit}}"], root)
        if code != 0:
            print(f"release-prep: changelog lower bound {ref!r} cannot be resolved: {output}", file=sys.stderr)
            return code

    steps: list[tuple[str, list[str]]] = [
        (
            "version marker validation",
            [sys.executable, str(update_version), "--version", version, "--update-pyproject", "--dry-run"],
        ),
        (
            "version markers",
            [sys.executable, str(update_version), "--version", version, "--update-pyproject"],
        ),
        ("uv.lock", ["uv", "lock"]),
    ]
    changelog_cmd = [sys.executable, str(changelog), "--version", version, "--source", str(root)]
    if release_date:
        changelog_cmd += ["--release-date", release_date]
    if ref:
        changelog_cmd += ["--since-ref", ref]
    steps.append(("CHANGELOG.md", changelog_cmd))

    for label, argv in steps:
        print(f"==> {label}")
        code, output = runner(argv, root)
        if output:
            print(output)
        if code != 0:
            print(f"release-prep failed at: {label}", file=sys.stderr)
            print("Inspect git diff before retrying; preparation may be partial.", file=sys.stderr)
            return code or 1

    print()
    print(f"Release {version} prepared. Next:")
    print(f"  1. Hand-curate the [{version}] section in CHANGELOG.md.")
    print(f"  2. make release-check VERSION={version}")
    print("  3. Commit the changed files and open a normal PR against develop.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("prep", "check"):
        command = sub.add_parser(name)
        command.add_argument("--version", required=True, help="Release version without the leading 'v'")
        command.add_argument("--root", type=Path, default=REPO_ROOT, help=argparse.SUPPRESS)
    sub.choices["prep"].add_argument("--since-ref", help="Changelog lower bound (default: newest final v* tag)")
    sub.choices["prep"].add_argument("--release-date", help="YYYY-MM-DD (default: today)")
    sub.choices["check"].add_argument(
        "--baseline-ref", help="Lock revision baseline (default: prior final release tag)"
    )

    args = parser.parse_args(argv)
    version = args.version.removeprefix("v")

    if args.command == "prep":
        return prep(args.root, version, args.since_ref, args.release_date, run_command)

    problems = run_checks(args.root, version, baseline_ref=args.baseline_ref)
    if problems:
        print(f"release-check FAILED for {version}:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"release-check OK: {version} is ready to tag")
    return 0


if __name__ == "__main__":
    sys.exit(main())
