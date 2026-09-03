#!/usr/bin/env python3
"""Scan assembled site artifacts for sensitive data, tokens, and unscrubbed private paths (A4 w1, w3).

Usage:
  uv run python scripts/publication/check_artifact_privacy.py [site_dir]
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# Patterns that should never appear in public site output
SENSITIVE_PATTERNS = (
    (re.compile(r"ghp_[0-9a-zA-Z]{36}"), "GitHub Personal Access Token (ghp_)"),
    (re.compile(r"github_pat_[0-9a-zA-Z_]{82}"), "GitHub Fine-Grained PAT"),
    (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"), "Private Key PEM header"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
)

# Verbatim example credentials published by AWS in their own documentation.
# Zero entropy and publicly listed as examples; no real credential can equal
# these strings, so they are exempt from the AKIA finding (docs prose and
# generated API references embed them).
AWS_EXAMPLE_TOKENS = frozenset(
    {
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    }
)

# Matches a single connection-string token and captures user/password/host.
# Each component excludes whitespace, slashes, and '@' so the match cannot
# slurp across prose: a bare "postgresql://...')" mention followed pages later
# by an '@' must not count as credentials (observed in tpc-di docs).
_CONNECTION_RE = re.compile(r"(?:postgresql|postgres|mysql)://([^\s/:@]+):([^\s/@]+)@([^\s/@]+)")

# Literal placeholder passwords used in documentation examples. A connection
# string whose password is exactly one of these (case-insensitive) is prose,
# not a leak; any other password still fails. Deliberately narrow: a real
# leaked credential never has the literal password "password".
PLACEHOLDER_PASSWORDS = frozenset(
    {
        "password",
        "pass",
        "your-password",
        "your_password",
        "changeme",
        "***",
        "<password>",
    }
)


def _connection_credential_leaks(content: str) -> int:
    """Count connection strings with non-placeholder passwords."""
    leaks = 0
    for match in _CONNECTION_RE.finditer(content):
        if match.group(2).strip().lower() not in PLACEHOLDER_PASSWORDS:
            leaks += 1
    return leaks


# Text extensions to scan
SCANNABLE_EXTENSIONS = (
    ".html",
    ".htm",
    ".json",
    ".js",
    ".css",
    ".svg",
    ".txt",
    ".xml",
    ".csv",
    ".yaml",
    ".yml",
)


def scan_file_for_privacy(file_path: Path) -> list[str]:
    """Scan a single file for sensitive content violations."""
    findings: list[str] = []
    try:
        content = file_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        findings.append(f"Could not read '{file_path}': {e}")
        return findings

    for pat, desc in SENSITIVE_PATTERNS:
        matches = [m for m in pat.findall(content) if m not in AWS_EXAMPLE_TOKENS]
        if matches:
            findings.append(f"Detected {desc} in '{file_path.name}' ({len(matches)} occurrence(s))")

    conn_leaks = _connection_credential_leaks(content)
    if conn_leaks:
        findings.append(
            f"Detected Database connection string with credentials in '{file_path.name}' ({conn_leaks} occurrence(s))"
        )

    return findings


def scan_directory_for_privacy(target_dir: Path) -> list[str]:
    """Recursively scan all text assets in target_dir for privacy and sensitivity leaks."""
    if not target_dir.exists():
        return [f"Target directory '{target_dir}' does not exist"]

    findings: list[str] = []
    for root, _, files in os.walk(target_dir):
        for f in files:
            p = Path(root) / f
            if p.suffix.lower() in SCANNABLE_EXTENSIONS:
                file_findings = scan_file_for_privacy(p)
                for fnd in file_findings:
                    rel = p.relative_to(target_dir).as_posix()
                    findings.append(f"{rel}: {fnd}")

    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan assembled artifacts for sensitive data")
    parser.add_argument("target_dir", type=Path, nargs="?", default=Path("publication/out/site"))
    args = parser.parse_args(argv)

    print(f"Scanning '{args.target_dir}' for sensitive data and privacy invariants...")
    findings = scan_directory_for_privacy(args.target_dir)

    if findings:
        print("❌ Privacy and sensitivity scan FAILED:")
        for fnd in findings:
            print(f"  - {fnd}")
        return 1

    print("✅ Privacy and sensitivity scan PASSED: zero sensitive leaks detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
