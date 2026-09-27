"""Workflow expressions must name contexts GitHub can evaluate where they appear.

GitHub rejects the whole workflow file when an expression names an unknown
context or a context unavailable at that level, and reports every triggering
event as an instant "workflow file issue" failure. Expressions inside `run:`
shell comments are still evaluated, so comments are not exempt.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

WORKFLOWS = sorted((Path(__file__).resolve().parents[3] / ".github" / "workflows").glob("*.yml"))

KNOWN_CONTEXTS = {
    "github",
    "env",
    "vars",
    "job",
    "jobs",
    "steps",
    "runner",
    "secrets",
    "strategy",
    "matrix",
    "needs",
    "inputs",
}
# Functions and literals that may start an expression without being a context.
NON_CONTEXT_WORDS = {
    "always",
    "success",
    "failure",
    "cancelled",
    "contains",
    "startsWith",
    "endsWith",
    "format",
    "join",
    "toJSON",
    "fromJSON",
    "hashFiles",
    "true",
    "false",
    "null",
}
# Contexts GitHub does not provide in job-level `env` (evaluated before a runner
# is assigned).
JOB_ENV_FORBIDDEN = {"runner", "env", "steps", "job"}

EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
IDENTIFIER = re.compile(r"(?<![\w.'\"-])([A-Za-z_][A-Za-z0-9_-]*)")
STRING_LITERAL = re.compile(r"'(?:[^']|'')*'")


def _identifiers(expression: str) -> set[str]:
    return set(IDENTIFIER.findall(STRING_LITERAL.sub("''", expression)))


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_expressions_name_known_contexts(workflow: Path) -> None:
    text = workflow.read_text(encoding="utf-8")
    unknown = sorted(
        {
            name
            for expression in EXPRESSION.findall(text)
            for name in _identifiers(expression)
            if name not in KNOWN_CONTEXTS and name not in NON_CONTEXT_WORDS
        }
    )
    assert not unknown, f"{workflow.name}: expression names unknown context(s) {unknown}"


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_job_level_env_uses_only_available_contexts(workflow: Path) -> None:
    jobs: dict[str, Any] = yaml.safe_load(workflow.read_text(encoding="utf-8")).get("jobs") or {}
    offenders = []
    for job_id, job in jobs.items():
        for key, value in ((job or {}).get("env") or {}).items():
            for expression in EXPRESSION.findall(str(value)):
                bad = _identifiers(expression) & JOB_ENV_FORBIDDEN
                if bad:
                    offenders.append(f"jobs.{job_id}.env.{key} uses {sorted(bad)}")
    assert not offenders, f"{workflow.name}: " + "; ".join(offenders)


def test_detector_flags_the_known_failure_shapes() -> None:
    assert _identifiers("number") == {"number"}
    assert "runner" in _identifiers(" runner.temp ")
    assert _identifiers("github.event_name == 'merge_group' && '600' || '0'") == {"github"}
