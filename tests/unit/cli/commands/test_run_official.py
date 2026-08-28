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


def test_run_official_quiet_forwards_to_run_and_suppresses_banner(monkeypatch):
    """`run-official --quiet` must reuse the standard bare result-path contract."""
    captured: dict[str, object] = {}

    def fake_run(**kwargs):
        captured.update(kwargs)
        click.echo("/tmp/official-result.json")

    monkeypatch.setattr(run_official_module, "run", click.Command("run", callback=fake_run))

    result = CliRunner().invoke(
        run_official_module.run_official,
        [
            "tpch",
            "--platform",
            "duckdb",
            "--scale",
            "1",
            "--phases",
            "throughput",
            "--streams",
            "3",
            "--seed",
            "42",
            "--quiet",
        ],
    )

    assert result.exit_code == 0, result.output
    assert captured["quiet"] is True
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert lines[-1] == "/tmp/official-result.json"
    assert "TPC-Compliant Official Benchmark Run" not in result.output
    assert "Concurrency:" not in result.output
