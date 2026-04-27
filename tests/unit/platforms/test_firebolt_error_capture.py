"""Tests for Firebolt error-message capture in load failure paths.

Firebolt inherits query execution from the base adapter; the Firebolt-specific
failure sites are the data-load paths, which previously truncated error
messages via ``str(e)[:100]...``. These tests pin the defensive formatting
so full driver messages land in the run log.
"""

import logging

import pytest

from benchbox.platforms.firebolt import FireboltAdapter

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
    pytest.mark.cloud_import,
]


def _make_adapter() -> FireboltAdapter:
    try:
        return FireboltAdapter(
            account_name="acct",
            database="db",
            engine_name="eng",
            client_id="id",
            client_secret="secret",
        )
    except ImportError:
        pytest.skip("Firebolt SDK not installed")


def _load_error_line(adapter: FireboltAdapter, exc: BaseException, caplog) -> str:
    logger_name = adapter.logger.name
    with caplog.at_level(logging.ERROR, logger=logger_name):
        error_message = str(exc) or repr(exc) or type(exc).__name__
        adapter.logger.error(f"Failed to load customer: {error_message}")
    return caplog.records[-1].message


class TestFireboltErrorCapture:
    """Exercise the defensive error formatter used in the load paths."""

    def test_non_empty_message_logged_verbatim(self, caplog):
        adapter = _make_adapter()
        msg = _load_error_line(adapter, RuntimeError("COPY INTO failed: bad file"), caplog)
        assert "COPY INTO failed: bad file" in msg
        assert "..." not in msg.split("Failed to load customer: ", 1)[1]

    def test_empty_message_falls_back(self, caplog):
        adapter = _make_adapter()

        class EmptyError(Exception):
            def __str__(self) -> str:
                return ""

        msg = _load_error_line(adapter, EmptyError(), caplog)
        tail = msg.split("Failed to load customer: ", 1)[1]
        assert tail, "logged message must include a non-empty error string"
