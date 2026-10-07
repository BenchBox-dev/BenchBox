from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from typing import Any

from .verdict import Finding

# Only a marker that ends the comment counts, so text a reviewer wrote earlier in
# the comment cannot set the fingerprint.
_MARKER = re.compile(r"<!-- oracle-finding: (?P<print>[0-9a-f]{16}) -->\s*\Z")
_TITLE = re.compile(r"^\*\*(?:Critical|High|Medium|Low)\*\*: (?P<title>.+)$", re.MULTILINE)
_NOT_WORD = re.compile(r"[^a-z0-9]+")


def fingerprint(path: str, title: str) -> str:
    # Lines move between heads and reviewers cite them loosely, so a finding is
    # identified by its file and normalized title only.
    normal = _NOT_WORD.sub(" ", title.lower()).strip()
    return hashlib.sha256(f"{path}\0{normal}".encode()).hexdigest()[:16]


def marker(finding: Finding) -> str:
    return f"<!-- oracle-finding: {fingerprint(finding.file, finding.title)} -->"


def thread_fingerprint(path: str | None, body: str) -> str | None:
    match = _MARKER.search(body.rstrip())
    if match is not None:
        return match.group("print")
    title = _TITLE.search(body)
    return fingerprint(path, title.group("title").strip()) if path and title else None


def open_fingerprints(threads: Iterable[Mapping[str, Any]], login: str) -> list[str]:
    prints = {
        thread_fingerprint(thread.get("path"), thread.get("body") or "")
        for thread in threads
        if not thread.get("resolved") and (thread.get("author") or "").removesuffix("[bot]") == login
    }
    return sorted(item for item in prints if item is not None)


def split(findings: Iterable[Finding], already_open: Iterable[str]) -> tuple[tuple[Finding, ...], tuple[Finding, ...]]:
    known = set(already_open)
    fresh: list[Finding] = []
    repeated: list[Finding] = []
    for finding in findings:
        key = fingerprint(finding.file, finding.title)
        (repeated if key in known else fresh).append(finding)
        known.add(key)
    return tuple(fresh), tuple(repeated)
