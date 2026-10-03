#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from soundness_paths import (  # noqa: E402
    DATA_PATH,
    OVERRIDE_FILES_GLOB,
    SOUNDNESS_FILES,
    SOUNDNESS_GLOBS,
    SOUNDNESS_PREFIXES,
    SOUNDNESS_REGEXES,
    any_soundness_path,
    is_soundness_path,
    main,
    normalize_path,
    surface_invariant_violations,
)

__all__ = [
    "DATA_PATH",
    "OVERRIDE_FILES_GLOB",
    "SOUNDNESS_FILES",
    "SOUNDNESS_GLOBS",
    "SOUNDNESS_PREFIXES",
    "SOUNDNESS_REGEXES",
    "any_soundness_path",
    "is_soundness_path",
    "normalize_path",
    "surface_invariant_violations",
]


if __name__ == "__main__":
    raise SystemExit(main())
