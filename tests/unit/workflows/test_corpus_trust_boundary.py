"""Corpus trust boundary - adversarial PR cannot execute code (A2 w2+w4)."""

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github/workflows/validate-submission.yml"


def test_corpus_trust_boundary():
    text = WORKFLOW.read_text()
    # must use pull_request_target, not pull_request, for trusted base
    data = yaml.safe_load(text)
    on = data[True]
    assert "pull_request_target" in on
    assert "pull_request" not in on
    # must use trusted base checkout
    assert "github.event.pull_request.base.sha" in text
    # must have allowlist
    assert "corpus_permit_rejections" in (REPO_ROOT / "scripts/validate_submission.py").read_text()
    # must have parity script
    assert (REPO_ROOT / "scripts/publication/validator_parity.py").is_file()
