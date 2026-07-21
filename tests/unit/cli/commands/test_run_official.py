"""Fast coverage for the deprecated ``run-official`` compatibility command."""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

import benchbox.cli.commands.run_official as run_official_module

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_run_official_accepts_and_forwards_platform_options(monkeypatch):
    """The throughput UAT command must accept credentials with ``--streams``."""
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(run_official_module, "run", click.Command("run", callback=fake_run))

    result = CliRunner().invoke(
        run_official_module.run_official,
        [
            "tpch",
            "--platform",
            "postgresql",
            "--scale",
            "1",
            "--phases",
            "throughput",
            "--streams",
            "3",
            "--platform-option",
            "username=benchbox",
            "--platform-option",
            "password=benchbox",
            "--seed",
            "42",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["platform"] == "postgresql"
    assert captured["platform_option_pairs"] == (("username", "benchbox"), ("password", "benchbox"))
