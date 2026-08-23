"""A failed privacy check must stop the build, not drop the bundle.

`find_public_path_leaks` is the fail-closed boundary between the corpus and
what the Explorer publishes. Before the change these tests cover, every one of
its three call sites raised `ValueError`, and the publication loop catches
`ValueError` alongside `JSONDecodeError`, `KeyError` and `TypeError` and
downgrades all of them to `skipped_bundles += 1` plus a warning.

So the detector firing produced a green build with a quietly shorter corpus,
and the leaking bundle stayed in the repository, still leaking. That inverts
what the check is for: it fires precisely when a human needs to look.

The plans companion was quieter still. Its leak was caught by that block's own
handler, so the bundle published anyway with `plans_published` left false and
the corpus looked complete.

The leak shape used here is a private path as a *mapping key*, which the
detector's own docstring records as the one that occurs in practice, and which
survives `anonymize_result_payload` - the tests fail for the reason under test
rather than because the anonymizer declined to scrub a value.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from _project.scripts.explorer_pipeline.pipeline import (
    ExplorerPipeline,
    PrivacyRejectionError,
)
from _project.scripts.explorer_publish import explorer_publish
from tests.unit.scripts.explorer_pipeline.conftest import MINIMAL_BUNDLE

pytestmark = [pytest.mark.unit, pytest.mark.fast]

LEAKING_PATH = "/Users/alice/secret/db"


def _write_bundle(bundles_dir: Path, name: str, *, leaking: bool = False) -> Path:
    bundles_dir.mkdir(parents=True, exist_ok=True)
    payload = json.loads(json.dumps(MINIMAL_BUNDLE))
    if leaking:
        payload["config"] = {LEAKING_PATH: 1.2}
    path = bundles_dir / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_privacy_rejection_in_a_bundle_fails_the_build(tmp_path: Path) -> None:
    """A leaking bundle stops publication instead of vanishing from the corpus.

    This is the assertion that fails on the unfixed tree, where the rejection is
    a ValueError, the loop swallows it, and `run` returns normally having
    published nothing and reported only a warning.
    """
    data_dir = tmp_path / "data"
    _write_bundle(data_dir / "bundles", "leaky.json", leaking=True)

    with pytest.raises(PrivacyRejectionError) as excinfo:
        ExplorerPipeline().run(data_dir, tmp_path / "out")

    message = str(excinfo.value)
    assert "privacy check failed" in message
    # The detector is value-redacting by contract: the report names the field
    # path and must never echo the private path it found.
    assert LEAKING_PATH not in message


def test_privacy_rejection_error_escapes_the_per_bundle_handler() -> None:
    """The rejection must not be catchable by the loop's own error handling.

    The exception type *is* the fix. Reintroducing a ValueError base would
    restore the original defect without touching a line of the loop, and no
    other test here would notice.
    """
    assert not issubclass(PrivacyRejectionError, ValueError)
    assert not issubclass(PrivacyRejectionError, (json.JSONDecodeError, KeyError, TypeError))


def test_privacy_rejection_in_a_plans_companion_fails_the_build(tmp_path: Path) -> None:
    """A leaking plans sidecar stops the build too.

    This was the quietest case: the companion block has its own handler, so the
    rejection never even reached the per-bundle one. The bundle published, only
    `plans_published` stayed false, and nothing about the corpus looked short.
    """
    data_dir = tmp_path / "data"
    bundle = _write_bundle(data_dir / "bundles", "clean.json")
    bundle.with_name("clean.plans.json").write_text(
        json.dumps({"per_path_timings": {LEAKING_PATH: 1.2}}),
        encoding="utf-8",
    )

    with pytest.raises(PrivacyRejectionError) as excinfo:
        ExplorerPipeline().run(data_dir, tmp_path / "out")

    assert "plans privacy check failed" in str(excinfo.value)


def test_privacy_rejection_in_an_applied_receipt_fails_the_build(tmp_path: Path) -> None:
    """A leaking applied receipt stops the build.

    The receipt is taken verbatim from the companion and re-serialized, so it is
    the path most likely to carry machine-local material into publication.
    """
    data_dir = tmp_path / "data"
    bundle = _write_bundle(data_dir / "bundles", "clean.json")
    bundle.with_name("clean.applied.json").write_text(
        json.dumps({"receipt": {"per_path_timings": {LEAKING_PATH: 1.2}}}),
        encoding="utf-8",
    )

    with pytest.raises(PrivacyRejectionError) as excinfo:
        ExplorerPipeline().run(data_dir, tmp_path / "out")

    assert "applied receipt privacy check failed" in str(excinfo.value)


def test_privacy_rejection_leaves_a_clean_corpus_publishing(tmp_path: Path) -> None:
    """Must-preserve: a clean bundle still publishes.

    A guard that only ever raises is indistinguishable from a broken pipeline,
    and every assertion above would still pass.
    """
    data_dir = tmp_path / "data"
    _write_bundle(data_dir / "bundles", "first.json")

    output = tmp_path / "out"
    ExplorerPipeline().run(data_dir, output)

    assert list((output / "bundles").glob("*.json")), "clean corpus published nothing"


def test_privacy_rejection_still_tolerates_a_malformed_companion(tmp_path: Path) -> None:
    """Must-preserve: an unparseable plans companion is still only a warning.

    Only the *privacy* rejection was promoted. Broken input stays a skip, or
    this change would turn every corrupt sidecar into a build outage - a much
    wider blast radius than the decision covered.
    """
    data_dir = tmp_path / "data"
    bundle = _write_bundle(data_dir / "bundles", "clean.json")
    bundle.with_name("clean.plans.json").write_text("{not json", encoding="utf-8")

    output = tmp_path / "out"
    ExplorerPipeline().run(data_dir, output)

    assert list((output / "bundles").glob("*.json")), "a malformed companion should not stop publication"


def test_privacy_rejection_makes_the_publish_command_exit_non_zero(tmp_path: Path) -> None:
    """The exception type only matters if it reaches the exit code.

    `explorer_publish build` wraps the run in `except Exception` and converts it
    to `SystemExit(1)`. That handler is the last place this fix could be
    softened back into a warning without any test above noticing, so pin the
    end-to-end outcome a CI job actually observes.
    """
    data_dir = tmp_path / "data"
    _write_bundle(data_dir / "bundles", "leaky.json", leaking=True)

    result = CliRunner().invoke(
        explorer_publish,
        ["build", "--data-dir", str(data_dir), "--output", str(tmp_path / "out")],
    )

    assert result.exit_code != 0, "a leaking bundle produced a successful publish"
    # Rich wraps at the terminal width, so a long pytest temp path can put a
    # newline between adjacent words without changing the rendered message.
    normalized_output = " ".join(result.output.split())
    assert "privacy check failed" in normalized_output
    assert LEAKING_PATH not in result.output
