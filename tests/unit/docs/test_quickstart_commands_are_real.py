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
        joined = block.replace("\\\n", " ")
        for line in joined.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = shlex.split(line)
            if "benchbox" not in parts:
                continue
            index = parts.index("benchbox")
            invoked = index == 0 or (index >= 1 and parts[index - 1] == "--")
            if not invoked:
                continue
            parts = parts[index + 1 :]
            if any("<" in p or ">" in p for p in parts):
                continue
            if parts:
                commands.append(parts)
    return commands


def test_quickstart_contains_benchbox_commands() -> None:
    assert _benchbox_invocations(), "no benchbox commands found - did the fence format change?"


@pytest.mark.parametrize("argv", _benchbox_invocations(), ids=lambda a: " ".join(a))
def test_each_documented_command_resolves(argv: list[str]) -> None:
    result = CliRunner().invoke(cli, [*argv, "--help"], catch_exceptions=False)
    assert result.exit_code == 0, f"`benchbox {' '.join(argv)}` is not a valid command:\n{result.output}"


def test_step_one_pins_the_duckdb_extra() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    step_one = text.split("## Step 1")[1].split("## Step 2")[0]
    assert "--extra duckdb" in step_one or "benchbox[duckdb]" in step_one


def test_no_reference_to_the_platforms_setup_variant_that_rejects_platform() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "platforms setup" not in text


def test_stated_step_count_is_not_contradicted() -> None:
    text = QUICKSTART.read_text(encoding="utf-8")
    assert "four steps" not in text.lower()


def test_tpcdi_deployment_guide_uses_real_config_symbols() -> None:
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "guides" / "tpc" / "tpc-di-deployment-guide.md"
    content = doc_path.read_text(encoding="utf-8")

    assert "ParallelBenchmarkConfig" not in content
    assert "ParallelExecutionMode" not in content
    assert "ParallelWorkloadType" not in content
    assert "run_parallel_" not in content
    assert "get_parallel_status" not in content
    assert "parallel_config" not in content
    assert "from benchbox.core.tpcdi.config import TPCDIConfig" in content
    assert "TPCDIConfig(" in content
    assert "TPCDIBenchmark(config=config)" in content


def test_databend_platform_doc_uses_platform_options() -> None:
    doc_path = Path(__file__).resolve().parents[3] / "docs" / "platforms" / "databend.md"
    content = doc_path.read_text(encoding="utf-8")

    assert "`--warehouse`" not in content
    assert "--databend-no-ssl" not in content
    assert "--disable-result-cache" not in content

    assert "## Platform Options" in content
    assert "--platform-option ssl=false" in content


def test_databend_documented_boolean_options_are_registered() -> None:
    import benchbox.platforms  # noqa: F401 - registers the platform option specs
    from benchbox.core.hooks.platform_hooks import PlatformHookRegistry

    parsed = PlatformHookRegistry.parse_options("databend", [("ssl", "false"), ("disable_result_cache", "false")])
    assert parsed["ssl"] is False
    assert parsed["disable_result_cache"] is False
