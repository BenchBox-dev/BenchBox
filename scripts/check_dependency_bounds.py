"""Dependency upper-bound health check.

BenchBox caps a handful of high-risk dependencies in ``pyproject.toml``
(sqlglot, click, pydantic, pyarrow, duckdb today). Caps are enforced by
``uv lock`` at install time, but nothing blocks a release if a capped
dep has drifted into the last major before the ceiling. This script
surfaces that signal.

Two modes
---------
* ``--fail-on=cap-reached``  (blocking, offline)
    Exit non-zero if any locked version is at or past the full stated
    upper bound. This should not happen under normal flow; it's a safety
    net for lockfile-level drift.

* ``--report-only``  (non-blocking, offline)
    Emit a markdown report listing each capped dep, its locked version,
    the cap, and whether the locked major equals ``cap_major - 1`` (the
    "ceiling-minus-one" signal - the dep is one major away from
    requiring a bump/hold decision). Suitable for appending to release
    notes.

Parsing is intentionally restrained: PEP 508 with a single exclusive
upper bound of the form ``<N`` or ``<N.0`` or ``<N.0.0`` or a tighter
minor/patch cap such as ``<1.4.0`` (the forms we actually use). Exotic
specifiers fall through untracked rather than being misparsed.

Design notes
------------
* Offline by design - CI must not page on upstream outages.
* Single source of truth for bounds health; the quarterly review TODO
  invokes the same script so check logic never drifts.
* The "ceiling-minus-one" signal is warn-only (in --report-only) rather
  than blocking, because BenchBox's caps intentionally sit at
  current-major + 1, which means locked_major == cap_major - 1 is the
  steady state. The blocking signal is cap-reached - the case where
  bounds have already been violated.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License. See LICENSE file in the project root.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from packaging.version import InvalidVersion, Version

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

_UPPER_BOUND_RE = re.compile(r"<\s*(\d+(?:\.\d+)*)")
_REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class CappedDep:
    """A dependency with a stated upper bound."""

    name: str
    cap_major: int
    locked_version: str | None
    cap_version: Version | None = None
    cap_text: str | None = None

    @property
    def effective_cap_version(self) -> Version:
        """Full upper bound used for blocking comparisons."""
        if self.cap_version is not None:
            return self.cap_version
        if self.cap_text is not None:
            try:
                return Version(self.cap_text)
            except InvalidVersion:
                pass
        return Version(str(self.cap_major))

    @property
    def cap_display(self) -> str:
        """Compact upper-bound display for markdown reports."""
        if self._is_major_cap:
            return str(self.cap_major)
        return self.cap_text or str(self.effective_cap_version)

    @property
    def locked_parsed(self) -> Version | None:
        if not self.locked_version:
            return None
        try:
            return Version(self.locked_version)
        except InvalidVersion:
            return None

    @property
    def locked_major(self) -> int | None:
        locked = self.locked_parsed
        if locked is None:
            return None
        return locked.major

    @property
    def _is_major_cap(self) -> bool:
        release_tail = self.effective_cap_version.release[1:]
        return all(part == 0 for part in release_tail)

    @property
    def cap_reached(self) -> bool:
        """Locked version >= full upper bound - bounds violation."""
        locked = self.locked_parsed
        return locked is not None and locked >= self.effective_cap_version

    @property
    def ceiling_minus_one(self) -> bool:
        """Locked major == cap major - 1 - one bump from decision time."""
        return self._is_major_cap and self.locked_major is not None and self.locked_major == self.cap_major - 1


def _extract_cap_major(spec: str) -> int | None:
    """Return the upper-bound major from a PEP 508 specifier, or None."""
    parsed = _extract_upper_bound(spec)
    if parsed is None:
        return None
    return parsed[1].major


def _extract_upper_bound(spec: str) -> tuple[str, Version] | None:
    """Return the exclusive upper-bound text and parsed version, or None."""
    m = _UPPER_BOUND_RE.search(spec)
    if not m:
        return None
    text = m.group(1)
    try:
        return text, Version(text)
    except InvalidVersion:
        return None


def _iter_capped_requirements(pyproject: dict) -> list[tuple[str, str]]:
    """Flatten every dependency string in pyproject into (name, specifier) pairs."""
    out: list[tuple[str, str]] = []
    project = pyproject.get("project", {})
    for entry in project.get("dependencies", []):
        out.append(_split_requirement(entry))
    for _group, entries in project.get("optional-dependencies", {}).items():
        for entry in entries:
            out.append(_split_requirement(entry))
    for _group, entries in pyproject.get("dependency-groups", {}).items():
        for entry in entries:
            if isinstance(entry, str):
                out.append(_split_requirement(entry))
    return out


def _split_requirement(raw: str) -> tuple[str, str]:
    head = re.split(r"[<>=!~;\[]", raw, maxsplit=1)
    name = head[0].strip()
    spec = raw[len(name) :].strip()
    return name, spec


def _parse_lockfile(lock_path: Path) -> dict[str, str]:
    """Return {name: version} from a uv.lock file."""
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    result: dict[str, str] = {}
    for package in data.get("package", []):
        name = package.get("name")
        version = package.get("version")
        if name and version:
            result[name] = version
    return result


def collect_capped_deps(pyproject_path: Path, lock_path: Path) -> list[CappedDep]:
    """Parse pyproject + lockfile; return capped deps with locked versions."""
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    locked = _parse_lockfile(lock_path)

    seen: set[str] = set()
    capped: list[CappedDep] = []
    for name, spec in _iter_capped_requirements(pyproject):
        if name in seen:
            continue
        upper_bound = _extract_upper_bound(spec)
        if upper_bound is None:
            continue
        cap_text, cap_version = upper_bound
        seen.add(name)
        capped.append(
            CappedDep(
                name=name,
                cap_major=cap_version.major,
                locked_version=locked.get(name),
                cap_version=cap_version,
                cap_text=cap_text,
            )
        )
    return capped


def render_report(deps: list[CappedDep]) -> str:
    """Markdown report - suitable for appending to release notes."""
    lines = [
        "# Dependency Upper Bounds - Status",
        "",
        "| Dependency | Locked | Cap (`<`) | Status |",
        "|------------|--------|-----------|--------|",
    ]
    for dep in deps:
        locked = dep.locked_version or "(not locked)"
        if dep.cap_reached:
            status = "🛑 CAP REACHED - bounds violation"
        elif dep.ceiling_minus_one:
            status = "⚠️ ceiling-minus-one - one major from decision"
        else:
            status = "✅ healthy"
        lines.append(f"| `{dep.name}` | {locked} | <{dep.cap_display} | {status} |")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--fail-on",
        choices=["cap-reached", "ceiling-minus-one", "never"],
        default="never",
        help="Exit non-zero when the chosen condition is hit. Default 'never' "
        "(report-only run). Release workflow uses 'cap-reached'.",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Alias for --fail-on=never - prints the markdown report without failing.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write the markdown report to this path (in addition to stdout).",
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=_REPO_ROOT / "pyproject.toml",
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=_REPO_ROOT / "uv.lock",
    )
    args = parser.parse_args(argv)

    fail_on = "never" if args.report_only else args.fail_on

    deps = collect_capped_deps(args.pyproject, args.lock)
    if not deps:
        print("No upper-bounded dependencies found - nothing to check.", file=sys.stderr)
        return 0

    report = render_report(deps)
    print(report)
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")

    if fail_on == "cap-reached":
        offenders = [d for d in deps if d.cap_reached]
        if offenders:
            names = ", ".join(d.name for d in offenders)
            print(f"\nFAIL: cap reached for: {names}", file=sys.stderr)
            return 1
    elif fail_on == "ceiling-minus-one":
        offenders = [d for d in deps if d.ceiling_minus_one or d.cap_reached]
        if offenders:
            names = ", ".join(d.name for d in offenders)
            print(f"\nFAIL: ceiling-minus-one for: {names}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
