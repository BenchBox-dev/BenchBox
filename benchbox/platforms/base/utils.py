from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

from benchbox.utils.file_format import is_parquet_format, is_tpc_format


class FileFormatInfo(NamedTuple):
    format_type: str
    delimiter: str


def detect_file_format(file_paths: list[Path] | Path) -> FileFormatInfo:
    if isinstance(file_paths, Path):
        file_paths = [file_paths]

    if not file_paths:
        return FileFormatInfo(format_type="csv", delimiter=",")

    first_file = file_paths[0]

    if is_parquet_format(first_file):
        return FileFormatInfo(format_type="parquet", delimiter="")

    if is_tpc_format(first_file):
        return FileFormatInfo(format_type="tpc", delimiter="|")

    return FileFormatInfo(format_type="csv", delimiter=",")


def is_non_interactive() -> bool:
    if os.getenv("BENCHBOX_NON_INTERACTIVE", "").lower() in {"true", "1", "yes"}:
        return True

    if not sys.stdin.isatty():
        return True

    ci_env_vars = {
        "CI",
        "CONTINUOUS_INTEGRATION",
        "BUILD_NUMBER",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "TRAVIS",
        "JENKINS_URL",
        "TEAMCITY_VERSION",
        "BUILDKITE",
        "CIRCLECI",
    }
    if any(os.getenv(var) for var in ci_env_vars):
        return True

    return "pytest" in sys.modules


__all__ = ["is_non_interactive", "detect_file_format", "FileFormatInfo"]
