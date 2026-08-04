"""Whole-corpus privacy invariant for the curated results corpus.

The submission workflow only scans the files a PR touched, so a bundle that
was already committed with a private path stays invisible to it forever. This
module closes that hole: it walks *every* JSON file under ``results-data/``
on every run, using the same canonical detector that guards the submission
boundary and the Explorer publication boundary.

Fail-closed is deliberate. A file that cannot be read or parsed is reported as
a failure rather than skipped, because "unparseable" is exactly the state an
unreviewed or truncated bundle would be in, and skipping it would let the
corpus regress while the gate stayed green.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchbox.core.results.anonymization import find_public_path_leaks

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DATA = REPO_ROOT / "results-data"


def _corpus_json_files() -> list[Path]:
    """Every JSON file in the corpus - bundles, companions, manifests, inventory."""
    return sorted(RESULTS_DATA.rglob("*.json"))


def test_corpus_directory_is_present() -> None:
    """Guard against the invariant silently passing on an empty scan.

    Without this, a rename or a partial checkout would make ``rglob`` return
    nothing and every assertion below would vacuously pass.
    """
    assert RESULTS_DATA.is_dir(), f"missing corpus directory: {RESULTS_DATA}"
    assert _corpus_json_files(), "corpus scan found no JSON files - the invariant would be vacuous"


def test_no_corpus_file_exposes_a_private_path() -> None:
    """Every corpus JSON file is free of private absolute paths.

    Reports the offending *field paths* only. ``find_public_path_leaks`` is
    value-redacting by design, so a failure message never echoes the home
    directory or machine-local material it detected.
    """
    offenders: list[str] = []
    unreadable: list[str] = []

    for path in _corpus_json_files():
        rel = path.relative_to(REPO_ROOT)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            # Fail closed: an unreadable file is a gate failure, never a skip.
            unreadable.append(f"{rel}: {type(exc).__name__}")
            continue
        leaks = find_public_path_leaks(payload)
        if leaks:
            offenders.append(f"{rel}: {', '.join(sorted(set(leaks))[:5])}")

    assert not unreadable, "corpus files could not be parsed (failing closed):\n" + "\n".join(unreadable)
    assert not offenders, f"{len(offenders)} corpus file(s) expose private paths:\n" + "\n".join(offenders[:20])


def test_corpus_only_change_routes_to_required_code_ci() -> None:
    """A results-data-only PR must still run the lane this invariant lives in.

    The gate above is marked ``fast``, so it runs inside the ``code-test`` job
    rather than a bespoke workflow. That is only sufficient while a corpus-only
    diff actually reaches ``code-test``. If ``results-data/**`` were ever added
    to the safe-content allowlist, this whole-corpus gate would stop running on
    exactly the PRs it exists to police, and every one of them would go green.
    """
    # scripts/ is importable here via the tests/unit/scripts/ conftest shim.
    from path_filter_decision import DEFAULT_RULES, classify_paths, load_rules

    rules = load_rules(REPO_ROOT / DEFAULT_RULES)
    for changed in (
        ["results-data/bundles/example.json"],
        ["results-data/bundles/example.manifest.json"],
        ["results-data/corpus-inventory.json"],
    ):
        decision = classify_paths(changed, rules)
        assert decision["needs_code_ci"] is True, f"{changed[0]} would skip the required code-test lane"


def test_code_test_is_gated_by_ci_required_result() -> None:
    """``code-test`` must remain a dependency of the one required check.

    develop's ruleset requires only ``ci-required-result``. A job that is not
    in its ``needs`` list cannot block a merge no matter what it reports, so
    this invariant's required-ness rests entirely on that edge.
    """
    import yaml

    workflow = yaml.safe_load((REPO_ROOT / ".github/workflows/pr.yml").read_text(encoding="utf-8"))
    needs = workflow["jobs"]["ci-required-result"]["needs"]
    assert "code-test" in needs, "ci-required-result no longer gates on code-test"


def test_detector_still_flags_a_planted_leak() -> None:
    """The invariant above is only meaningful if the detector still fires.

    A clean corpus and a broken detector produce identical output, so pin the
    detector's behaviour here. Without this, silently neutering
    ``find_public_path_leaks`` would turn the whole-corpus gate green.
    """
    planted = {"metadata": {"working_dir": "/Users/someone/benchbox"}}
    assert find_public_path_leaks(planted), "detector no longer flags a private home path"
