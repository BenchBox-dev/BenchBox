"""Verifies the unreasoned-skip warn hook catches markers missing ``reason=``.

The hook itself runs from ``pytest_collection_finish`` in ``tests/conftest.py``
(NOT ``pytest_collection_modifyitems`` - that hook name is forbidden by the
no-collection-time-marker-rewrite policy in ``tests/unit/test_marker_strategy.py``).
This test exercises the hook's private helper directly with synthetic markers
so it doesn't depend on spawning pytest-in-pytest.
"""

from __future__ import annotations

import warnings

import pytest

from tests.conftest import _warn_on_unreasoned_skip_markers

pytestmark = pytest.mark.fast


class _FakeMarker:
    def __init__(self, name: str, args: tuple = (), kwargs: dict | None = None) -> None:
        self.name = name
        self.args = args
        self.kwargs = kwargs or {}


class _FakeItem:
    def __init__(self, nodeid: str, markers: list[_FakeMarker]) -> None:
        self.nodeid = nodeid
        self._markers = markers

    def iter_markers(self):
        return iter(self._markers)


def test_hook_warns_on_unreasoned_skip(monkeypatch) -> None:
    monkeypatch.delenv("BENCHBOX_SKIP_REASON_CHECK", raising=False)
    items = [
        _FakeItem("bad::skip", [_FakeMarker("skip")]),
        _FakeItem("bad::skipif_no_reason", [_FakeMarker("skipif", args=(True,))]),
        _FakeItem("bad::xfail", [_FakeMarker("xfail")]),
        _FakeItem("ok::skip_kwarg", [_FakeMarker("skip", kwargs={"reason": "r"})]),
        _FakeItem("ok::skip_positional", [_FakeMarker("skip", args=("because",))]),
        _FakeItem("ok::skipif_kwarg", [_FakeMarker("skipif", args=(True,), kwargs={"reason": "r"})]),
        _FakeItem("ok::other_marker", [_FakeMarker("fast")]),
    ]

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_on_unreasoned_skip_markers(items)

    messages = [str(w.message) for w in caught if issubclass(w.category, UserWarning)]
    assert any("bad::skip: @pytest.mark.skip without reason=" in m for m in messages)
    assert any("bad::skipif_no_reason: @pytest.mark.skipif without reason=" in m for m in messages)
    assert any("bad::xfail: @pytest.mark.xfail without reason=" in m for m in messages)
    # Reasoned markers: no warning emitted
    assert not any("ok::" in m for m in messages)


def test_hook_silent_when_env_override_set(monkeypatch) -> None:
    monkeypatch.setenv("BENCHBOX_SKIP_REASON_CHECK", "1")
    items = [_FakeItem("bad::skip", [_FakeMarker("skip")])]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_on_unreasoned_skip_markers(items)
    assert not any("@pytest.mark.skip without reason=" in str(w.message) for w in caught)
