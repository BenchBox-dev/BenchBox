"""Every `benchbox ...` command in the quickstart must be a real CLI route.

`docs/usage/getting-started.md` promised that `duckdb` would be "Ready
immediately" after `benchbox profile`, but Step 1 only linked out to the
installation guide. A reader who ran a plain `uv add benchbox` -- which ships
SQLite only -- hit a contradiction on their second command and could not
complete Step 3 at all. The same page also advertised
`benchbox platforms setup`, which rejects `--platform`.

This walks the fenced bash blocks in the quickstart and asserts each
`benchbox` invocation resolves to a real command with real options, so a
documented command that does not exist fails here instead of in a new user's
terminal.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest
from click.testing import CliRunner

from benchbox.cli.main import cli

pytestmark = [pytest.mark.unit, pytest.mark.fast]

QUICKSTART = Path(__file__).resolve().parents[3] / "docs" / "usage" / "getting-started.md"

FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _benchbox_invocations() -> list[list[str]]:
    text = QUICKSTART.read_text(encoding="utf-8")
    commands: list[list[str]] = []
    for block in FENCE.findall(text):
        # Join backslash continuations, then take one command per line.
        joined = block.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = shlex.split(line)
            if "benchbox" not in parts:
                continue
            # `uv add benchbox --extra duckdb` names benchbox as a PACKAGE, not
            # the CLI. Only `benchbox ...` and `uv run -- benchbox ...` invoke it.
            index = parts.index("benchbox")
            invoked = index == 0 or (index >= 1 and parts[index - 1] == "--")
            if not invoked:
                continue
            parts = parts[index + 1 :]
            # Drop placeholder-bearing invocations; they are illustrative.
            if any("<" in p or ">" in p for p in parts):
                continue
            if parts:
                commands.append(parts)
    return commands


def test_quickstart_contains_benchbox_commands() -> None:
    assert _benchbox_invocations(), "no benchbox commands found - did the fence format change?"


@pytest.mark.parametrize("argv", _benchbox_invocations(), ids=lambda a: " ".join(a))
def test_each_documented_command_resolves(argv: list[str]) -> None:
    """`--help` on the documented argv proves the route and its options exist.

    Click exits 2 with "No such option" / "No such command" when a documented
    flag or subcommand does not exist, which is exactly the defect class here.
    """
    result = CliRunner().invoke(cli, [*argv, "--help"], catch_exceptions=False)
    assert result.exit_code == 0, f"`benchbox {' '.join(argv)}` is not a valid command:\n{result.output}"


def test_step_one_pins_the_duckdb_extra() -> None:
    """Step 3 runs DuckDB, so Step 1 must install it.

    A plain `uv add benchbox` ships SQLite only.
    """
    text = QUICKSTART.read_text(encoding="utf-8")
    step_one = text.split("## Step 1")[1].split("## Step 2")[0]
    assert "--extra duckdb" in step_one or "benchbox[duckdb]" in step_one


def test_no_reference_to_the_platforms_setup_variant_that_rejects_platform() -> None:
    """`benchbox platforms setup` takes no --platform; `benchbox setup` does."""
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "platforms setup" not in text


def test_stated_step_count_is_not_contradicted() -> None:
    """The page said "four steps" and then listed Step 0 through Step 5."""
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "four steps" not in text.lower()
