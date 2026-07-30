"""Shared fixtures for platform adapter unit tests.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util

import pytest


@pytest.fixture
def chdb_probe_satisfied(monkeypatch):
    """Let ClickHouse local-mode adapters be constructed without chDB installed.

    ``ClickHouseAdapter.__init__`` probes for chDB eagerly
    (``importlib.util.find_spec("chdb") is None`` -> ``ImportError``) even though
    nothing needs the package until a connection is opened. chDB ships no Windows
    wheels — ``pyproject.toml`` constrains it to ``sys_platform != 'win32'`` — so on
    the Windows runners that probe failed and took down every test in the modules
    that build a local-mode adapter, 17 in total, none of which touch chDB: they
    drive DDL rendering and plan/introspection logic against fake connections.

    Satisfy only the chDB lookup and delegate every other name to the real
    ``find_spec``, so an unrelated missing dependency still surfaces normally.
    Opt in per module with
    ``pytestmark = [..., pytest.mark.usefixtures("chdb_probe_satisfied")]``.

    Reproduce the Windows failure on any platform by making the probe return None:
    ``uv run -- python -m pytest -p nochdb ...`` with a plugin that patches
    ``importlib.util.find_spec``.
    """
    real_find_spec = importlib.util.find_spec

    def _find_spec(name, *args, **kwargs):
        if name == "chdb":
            # A loader-less spec is enough: the probe only checks for non-None.
            return importlib.machinery.ModuleSpec("chdb", loader=None)
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)
