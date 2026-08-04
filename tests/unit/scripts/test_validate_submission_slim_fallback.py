"""The slim-branch privacy detector must match the canonical one.

`scripts/validate_submission.py` carries an inline `find_public_path_leaks`
behind an `except ImportError`. That fallback is not dead code — it is the
implementation that actually runs on `published-results`, because the
slim-branch allowlist in `.github/workflows/sync-results-data-to-published.yml`
mirrors this script and `benchbox/validation/bundle.py` but *not*
`benchbox/core/results/anonymization.py`.

So the public-corpus privacy gate is only as strong as this copy. A detector
improvement made upstream and not mirrored here leaves the real gate blind,
which is exactly what happened with object-key scanning. These tests exercise
the fallback directly, with the canonical import forced to fail.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = "benchbox.core.results.anonymization"


@pytest.fixture(scope="module")
def slim_leak_detector():
    """Load the script with the canonical module unimportable.

    Binding `sys.modules[name] = None` makes `from name import ...` raise
    ImportError, which is the condition the slim branch is really in.
    """
    saved = sys.modules.get(CANONICAL, ...)
    sys.modules[CANONICAL] = None  # type: ignore[assignment]
    try:
        spec = importlib.util.spec_from_file_location(
            "_validate_submission_slim", ROOT / "scripts/validate_submission.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        if saved is ...:
            del sys.modules[CANONICAL]
        else:
            sys.modules[CANONICAL] = saved  # type: ignore[assignment]

    detector = module.find_public_path_leaks
    # Guard the guard: if the module ever imports the canonical function
    # despite the block, these tests would silently stop covering the fallback.
    assert detector.__module__ == "_validate_submission_slim", "fixture did not exercise the slim fallback"
    return detector


def _canonical():
    from benchbox.core.results.anonymization import find_public_path_leaks

    return find_public_path_leaks


PAYLOADS = [
    pytest.param({"metadata": {"working_dir": "/Users/alice/private"}}, id="value-leak"),
    pytest.param({"per_path_timings": {"/Users/alice/db": 1.2}}, id="key-leak"),
    pytest.param({"/Users/alice/db": 1}, id="root-key-leak"),
    pytest.param({"a": {"/Users/alice/x": {"working_dir": "/home/bob/private"}}}, id="nested-under-leaking-key"),
    pytest.param({"queries": [{"id": "q1"}, {"dir": "~/secret"}]}, id="list-leak"),
    pytest.param({"queries": {"q1": 1.0, "tpch/q2": 2.0}}, id="clean"),
]


@pytest.mark.parametrize("payload", PAYLOADS)
def test_slim_fallback_matches_canonical_detector(slim_leak_detector, payload) -> None:
    """Parity is the contract - the two copies must not drift."""
    assert sorted(slim_leak_detector(payload)) == sorted(_canonical()(payload))


def test_slim_fallback_flags_a_key_encoded_private_path(slim_leak_detector) -> None:
    """The gap this test file exists for: keys were not scanned at all."""
    assert slim_leak_detector({"per_path_timings": {"/Users/alice/db": 1.2}}) == ["per_path_timings.<key>"]


def test_slim_fallback_does_not_echo_a_leaking_key(slim_leak_detector) -> None:
    """Diagnostics reach PR comments, so a leaking key must never be named.

    The nested case is the trap: reporting the *child* leak used to splice the
    raw parent key into the field path.
    """
    leaks = slim_leak_detector({"/Users/alice/secret": {"working_dir": "/home/bob/private"}})
    joined = " ".join(leaks)
    assert leaks
    assert "alice" not in joined
    assert "secret" not in joined
    assert "bob" not in joined


def test_slim_fallback_still_reports_ordinary_value_leaks(slim_leak_detector) -> None:
    """Key scanning must not regress the original value behaviour."""
    assert slim_leak_detector({"nested": [{"working_dir": "/Users/alice/private"}]}) == ["nested.0.working_dir"]
