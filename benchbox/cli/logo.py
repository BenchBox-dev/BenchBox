# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, TextIO

import click

if TYPE_CHECKING:
    from rich.text import Text

LOGO = "\n".join(
    [
        "█                   █    █",
        "█▀▀▄ █▀▀█ █▀▀▄ █▀▀▀ █▀▀▄ █▀▀▄ ▄▀▀▄ ▀▄▄▀",
        "█▄▄▀ █▄▄▄ █  █ █▄▄▄ █  █ █▄▄▀ ▀▄▄▀ ▄▀▀▄",
    ]
)

LOGO_STYLE = "bold cyan"


def logo_supported(stream: TextIO | None = None) -> bool:
    encoding = getattr(stream if stream is not None else sys.stdout, "encoding", None)
    if not encoding:
        return False
    try:
        LOGO.encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def styled_logo() -> str:
    if not logo_supported():
        return ""
    return click.style(LOGO, fg="cyan", bold=True)


def rich_logo() -> Text | None:
    if not logo_supported():
        return None
    from rich.text import Text

    return Text(LOGO, style=LOGO_STYLE)
