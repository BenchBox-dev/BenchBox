from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _stub_psutil_cpu_count(monkeypatch: pytest.MonkeyPatch) -> None:

    monkeypatch.setattr("benchbox.core.tpcdi.generator.data.psutil.cpu_count", lambda: 2)
