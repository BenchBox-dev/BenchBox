from __future__ import annotations

from unittest.mock import patch

import pytest

from benchbox.cli.benchmarks import prompt_execution_engine

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestPromptExecutionEngine:
    def test_platform_without_engines_returns_default_without_prompting(self):
        with patch("benchbox.cli.benchmarks.Prompt.ask") as ask:
            assert prompt_execution_engine("duckdb") == "default"
            ask.assert_not_called()

    def test_manifest_choices_are_offered_for_polars(self):
        with patch("benchbox.cli.benchmarks.Prompt.ask", return_value="streaming") as ask:
            assert prompt_execution_engine("polars-df") == "streaming"
            choices = ask.call_args.kwargs["choices"]
            assert choices == ["default", "auto", "in-memory", "streaming"]
