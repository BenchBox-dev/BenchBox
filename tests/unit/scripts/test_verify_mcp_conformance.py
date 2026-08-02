"""Fail-closed coverage for the MCP conformance evidence generator."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.mcp.readiness import CURRENT_PROTOCOL_VERSION
from scripts import verify_mcp_conformance

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_certifying_protocol_gate_has_no_expected_failure_baseline(monkeypatch, tmp_path: Path) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(verify_mcp_conformance, "_prepare_conformance", lambda _checkout: tmp_path / "runner.js")
    monkeypatch.setattr(verify_mcp_conformance, "_run", lambda command, **_kwargs: commands.append(command))

    verify_mcp_conformance._run_protocol_gate("http://127.0.0.1:8000/mcp", CURRENT_PROTOCOL_VERSION, tmp_path)

    assert commands
    assert all("--expected-failures" not in command for command in commands)


def test_generated_evidence_does_not_certify_local_multiworker_tests(monkeypatch, tmp_path: Path) -> None:
    def fake_check_output(command: list[str], **_kwargs: object) -> str:
        if command[1] == "status":
            return ""
        if command[1] == "rev-parse":
            return "a" * 40 + "\n"
        raise AssertionError(command)

    monkeypatch.setattr(verify_mcp_conformance.subprocess, "check_output", fake_check_output)
    evidence = tmp_path / "evidence.json"

    verify_mcp_conformance._write_evidence(evidence, CURRENT_PROTOCOL_VERSION)

    payload = json.loads(evidence.read_text(encoding="utf-8"))
    assert payload["automated"]["conformance"] is True
    assert payload["automated"]["multiworker"] is False
