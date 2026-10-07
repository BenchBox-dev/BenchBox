"""Repository paths derived from this file's location.

This module imports only the standard library so tests can locate repository
files without depending on the process working directory or on importing
BenchBox itself.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT: Path = Path(__file__).resolve().parents[2]

__all__ = ["REPO_ROOT"]
