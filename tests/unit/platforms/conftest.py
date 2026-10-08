# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import importlib.machinery
import importlib.util

import pytest


@pytest.fixture
def chdb_probe_satisfied(monkeypatch):

    real_find_spec = importlib.util.find_spec

    def _find_spec(name, *args, **kwargs):
        if name == "chdb":
            return importlib.machinery.ModuleSpec("chdb", loader=None)
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", _find_spec)
