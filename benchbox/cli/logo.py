"""BenchBox block-character logo for CLI output.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TextIO

import click

if TYPE_CHECKING:
    from rich.text import Text

# Must match the fenced block at the top of README.md.
LOGO = "\n".join(
    [
        "█                   █    █",
        "█▀▀▄ █▀▀█ █▀▀▄ █▀▀▀ █▀▀▄ █▀▀▄ ▄▀▀▄ ▀▄▄▀",
        "█▄▄▀ █▄▄▄ █  █ █▄▄▄ █  █ █▄▄▀ ▀▄▄▀ ▄▀▀▄",
    ]
)

LOGO_STYLE = "bold cyan"


def logo_supported(stream: TextIO | None = None) -> bool:
    """Return True if ``stream`` can encode the logo's block characters.

    Consoles with legacy code pages (for example cp1252 on Windows) would
    raise ``UnicodeEncodeError``, so callers skip the logo there.
    """
    encoding = getattr(stream if stream is not None else sys.stdout, "encoding", None)
    if not encoding:
        return False
    try:
        LOGO.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def styled_logo() -> str:
    """Return the logo styled for click output, or "" when unsupported."""
    if not logo_supported():
        return ""
    return click.style(LOGO, fg="cyan", bold=True)


def rich_logo() -> Text | None:
    """Return the logo as Rich ``Text``, or None when unsupported."""
    if not logo_supported():
        return None
    from rich.text import Text

    return Text(LOGO, style=LOGO_STYLE)
