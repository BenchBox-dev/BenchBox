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


class TestInteractiveEngineResolution:
    @staticmethod
    def _state(execution_engine=None):
        import types
        from unittest.mock import MagicMock

        return types.SimpleNamespace(
            parsed_platform_options={},
            execution_engine=execution_engine,
            database_config=types.SimpleNamespace(type="polars-df", options={}, execution_engine="default"),
            ctx=MagicMock(),
            logger=None,
            benchmark_config=None,
        )

    def test_explicit_engine_skips_the_prompt(self):
        from benchbox.cli.commands.run import _interactive_prompt_platform_options

        s = self._state(execution_engine="streaming")
        with (
            patch("benchbox.cli.benchmarks.prompt_platform_options", return_value={}),
            patch("benchbox.cli.benchmarks.prompt_execution_engine") as prompt,
        ):
            _interactive_prompt_platform_options(s)

        prompt.assert_not_called()
        assert s.resolved_execution_engine == "streaming"
        assert s.database_config.execution_engine == "streaming"

    def test_prompted_engine_is_recorded(self):
        from benchbox.cli.commands.run import _interactive_prompt_platform_options

        s = self._state()
        with (
            patch("benchbox.cli.benchmarks.prompt_platform_options", return_value={}),
            patch("benchbox.cli.benchmarks.prompt_execution_engine", return_value="in-memory"),
        ):
            _interactive_prompt_platform_options(s)

        assert s.execution_engine == "in-memory"
        assert s.resolved_execution_engine == "in-memory"

    def test_invalid_explicit_engine_exits(self):
        from benchbox.cli.commands.run import _interactive_prompt_platform_options

        s = self._state(execution_engine="gpu")
        with (
            patch("benchbox.cli.benchmarks.prompt_platform_options", return_value={}),
            patch("benchbox.cli.benchmarks.prompt_execution_engine") as prompt,
        ):
            _interactive_prompt_platform_options(s)

        prompt.assert_not_called()
        assert s.ctx.exit.called
