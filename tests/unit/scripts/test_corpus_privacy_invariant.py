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
import subprocess
from pathlib import Path

import pytest

from benchbox.core.results.anonymization import AnonymizationManager, find_public_path_leaks
from benchbox.core.results.canonical_json import canonical_json_bytes

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DATA = REPO_ROOT / "results-data"
COMPANION_SUFFIXES = (".manifest.json", ".plans.json", ".tuning.json", ".applied.json")
MIGRATION_MANIFEST = "path-privacy-migration.manifest.json"


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


def _anonymize(payload: dict, path: Path, manager: AnonymizationManager) -> dict:
    """Route one corpus file through the entry point its publisher would use."""
    if path.name.endswith(".tuning.json"):
        return manager.anonymize_tuning_payload(payload)
    return manager.anonymize_result_payload(payload)


def test_anonymizing_the_corpus_twice_matches_anonymizing_it_once() -> None:
    """Publication must be a fixed point over every curated bundle.

    The corpus is stored already-anonymized, so the Explorer boundary
    anonymizes these payloads a second time. If that second pass re-hashes
    retained pseudonyms (``endpoint`` / ``database_name`` / ``submission_path``),
    a curated bundle and a fresh submission from the same source diverge after
    re-publication. Unread identifier fields (including ``machine_id``) are
    omitted at the public boundary — see ``adr-published-identifier-field-set``
    — so this gate is about retained-field fixed-point stability, not machine
    grouping. Nothing raises when this regresses; only published bytes change,
    so scan the real corpus rather than a fixture.
    """
    manager = AnonymizationManager()
    unstable: list[str] = []
    scanned = 0

    for path in _corpus_json_files():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            continue
        scanned += 1
        once = _anonymize(payload, path, manager)
        if _anonymize(once, path, manager) != once:
            unstable.append(str(path.relative_to(REPO_ROOT)))

    assert scanned, "no corpus mappings scanned - the fixed-point gate would be vacuous"
    assert not unstable, f"{len(unstable)} corpus file(s) change under a second anonymization pass:\n" + "\n".join(
        unstable[:20]
    )


def test_rederived_corpus_publishes_byte_identically_to_what_is_stored() -> None:
    """Stored bytes and published bytes must be the same bytes.

    Stronger than the fixed-point gate above, which only says publication
    stabilizes after one pass. This says the corpus is ALREADY at that fixed
    point, so publishing rewrites nothing: the stored file and the file the
    Explorer serves are byte-identical under the canonical encoder, and a
    result ID computed from either is the same ID.

    That is the property the re-derivation established. It also fails closed on
    the way a corpus most plausibly regresses - someone re-importing bundles
    that were never run through the public boundary, or run through a different
    one - because those would differ here while still passing the idempotence
    gate (anything already pseudonym-shaped is stable on a second pass whether
    or not it was correct on the first).

    What this canNOT check is how many passes produced the stored value: a
    once-hashed and a twice-hashed pseudonym are indistinguishable without the
    pre-anonymization original. That is inherently a one-time migration
    property, verified against the pre-#1467 originals in the PR that
    re-derived the corpus, not a recurring invariant.
    """
    manager = AnonymizationManager()
    drifted: list[str] = []
    scanned = 0

    for path in sorted((RESULTS_DATA / "bundles").rglob("*.json")):
        if path.name.endswith(COMPANION_SUFFIXES) or path.name == MIGRATION_MANIFEST:
            continue
        stored = path.read_bytes()
        payload = json.loads(stored.decode("utf-8"))
        if not isinstance(payload, dict):
            continue
        scanned += 1
        if canonical_json_bytes(manager.anonymize_result_payload(payload)) != stored:
            drifted.append(str(path.relative_to(REPO_ROOT)))

    assert scanned, "no primary bundles scanned - this gate would be vacuous"
    assert not drifted, (
        f"{len(drifted)} bundle(s) are not stored at the publication fixed point; "
        "publishing would rewrite them:\n" + "\n".join(drifted[:20])
    )


def test_corpus_checks_out_with_lf_on_every_platform() -> None:
    """The corpus must be exempt from git's end-of-line translation.

    The gate above compares stored bytes against published bytes, and the
    publisher always emits LF. So on a checkout where git translates line
    endings - ``core.autocrlf=true``, the Windows default - every multi-line
    bundle arrives as CRLF and disagrees with its own published form for
    reasons that have nothing to do with its content.

    That is not hypothetical: the byte-identity gate landed green and went red
    in the next nightly, failing all 207 primary bundles on windows-latest 3.10
    and 3.12 while the same commit passed on ubuntu. PR CI is Linux-only, so
    the nightly matrix is the first place it can show up.

    Pinning the attribute is the fix rather than comparing newline-insensitively,
    because the weaker test would go green while still letting a contributor on
    a translating checkout commit CRLF bundles that permanently disagree with
    what publication emits.
    """
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--", "results-data"],
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout
    paths = [name for name in tracked.split(b"\0") if name]
    assert paths, "no tracked corpus files - this gate would be vacuous"

    attrs = subprocess.run(
        ["git", "check-attr", "-z", "--stdin", "eol"],
        input=b"\0".join(paths),
        capture_output=True,
        check=True,
        cwd=REPO_ROOT,
    ).stdout

    # `check-attr -z` emits a flat NUL-separated stream of (path, attr, value).
    fields = attrs.split(b"\0")
    untranslated = [fields[index].decode() for index in range(0, len(fields) - 2, 3) if fields[index + 2] != b"lf"]
    assert not untranslated, (
        f"{len(untranslated)} corpus file(s) have no explicit `eol=lf` attribute, so their "
        "working-tree bytes depend on the platform that checked them out:\n" + "\n".join(untranslated[:20])
    )


def test_detector_still_flags_a_planted_leak() -> None:
    """The invariant above is only meaningful if the detector still fires.

    A clean corpus and a broken detector produce identical output, so pin the
    detector's behaviour here. Without this, silently neutering
    ``find_public_path_leaks`` would turn the whole-corpus gate green.
    """
    planted = {"metadata": {"working_dir": "/Users/someone/benchbox"}}
    assert find_public_path_leaks(planted), "detector no longer flags a private home path"


def test_detector_still_flags_a_leak_encoded_as_an_object_key() -> None:
    """The whole-file claim covers keys, not just values.

    A payload can carry a private path as a mapping key, and a value-only
    detector would report this corpus as clean while publishing the path.
    """
    planted = {"metadata": {"/Users/someone/benchbox": True}}
    leaks = find_public_path_leaks(planted)
    assert leaks, "detector no longer flags a private path encoded as an object key"
    assert "someone" not in " ".join(leaks), "key leaks must stay redacted in the report"
