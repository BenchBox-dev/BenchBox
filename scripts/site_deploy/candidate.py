"""Candidate identity: which commits may be deployed.

Only a commit that reached trunk through the merge queue is eligible. The proof is
a completed, successful ``merge_group`` run of ``ci.yml`` whose head commit is that
commit; the merge queue fast-forwards trunk to the merge-group head, so the two
SHAs are the same object.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from scripts.site_deploy.github import Api

CI_WORKFLOW_FILE = "ci.yml"
CI_WORKFLOW_PATH = f".github/workflows/{CI_WORKFLOW_FILE}"
MERGE_GROUP_EVENT = "merge_group"
DEFAULT_TRUNK_BRANCH = "develop"


@dataclass
class Eligibility:
    sha: str
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    run_id: int | None = None
    run_url: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sha": self.sha,
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "run_id": self.run_id,
            "run_url": self.run_url,
        }


def _workflow_path(run: dict) -> str:
    # Runs report their workflow as ``.github/workflows/ci.yml`` and, for some
    # events, with an ``@ref`` suffix.
    return str(run.get("path", "")).split("@", 1)[0]


def _is_merge_queue_branch(run: dict, trunk_branch: str) -> bool:
    return str(run.get("head_branch", "")).startswith(f"gh-readonly-queue/{trunk_branch}/")


def runs_for_sha(runs: Iterable[dict], sha: str, trunk_branch: str = DEFAULT_TRUNK_BRANCH) -> list[dict]:
    """``ci.yml`` merge-group runs for ``sha``, newest first."""
    matching = [
        run
        for run in runs
        if run.get("head_sha") == sha
        and run.get("event") == MERGE_GROUP_EVENT
        and _workflow_path(run) == CI_WORKFLOW_PATH
        and _is_merge_queue_branch(run, trunk_branch)
    ]
    return sorted(matching, key=lambda run: str(run.get("created_at", "")), reverse=True)


def check_candidate(
    sha: str,
    runs: Iterable[dict],
    trunk_first_parents: Sequence[str],
    trunk_branch: str = DEFAULT_TRUNK_BRANCH,
) -> Eligibility:
    """Decide whether ``sha`` is an eligible deployment candidate.

    The commit must be on trunk's first-parent history and its newest merge-group
    ``ci.yml`` run must have completed successfully. A red or unfinished newest run
    disqualifies the commit even if an older run for it was green.
    """
    if sha not in set(trunk_first_parents):
        return Eligibility(sha, False, [f"{sha[:12]} is not on the first-parent history of {trunk_branch}"])
    matching = runs_for_sha(runs, sha, trunk_branch)
    if not matching:
        return Eligibility(sha, False, [f"no {CI_WORKFLOW_FILE} {MERGE_GROUP_EVENT} run found for {sha[:12]}"])
    newest = matching[0]
    run_id = newest.get("id")
    url = newest.get("html_url")
    if newest.get("status") != "completed":
        return Eligibility(sha, False, [f"{CI_WORKFLOW_FILE} run {run_id} has not completed"], run_id, url)
    if newest.get("conclusion") != "success":
        return Eligibility(
            sha, False, [f"{CI_WORKFLOW_FILE} run {run_id} concluded {newest.get('conclusion')!r}"], run_id, url
        )
    return Eligibility(sha, True, [f"{CI_WORKFLOW_FILE} {MERGE_GROUP_EVENT} run {run_id} succeeded"], run_id, url)


def select_latest_eligible(
    runs: Sequence[dict],
    trunk_first_parents: Sequence[str],
    trunk_branch: str = DEFAULT_TRUNK_BRANCH,
) -> Eligibility | None:
    """Newest trunk commit (``trunk_first_parents`` is newest first) that is eligible."""
    for sha in trunk_first_parents:
        verdict = check_candidate(sha, runs, trunk_first_parents, trunk_branch)
        if verdict.eligible:
            return verdict
    return None


def fetch_merge_group_runs(repo: str, api: Api, pages: int = 3) -> list[dict]:
    """Recent ``ci.yml`` merge-group runs (all conclusions, newest first)."""
    collected: list[dict] = []
    for page in range(1, pages + 1):
        payload = api(
            f"repos/{repo}/actions/workflows/{CI_WORKFLOW_FILE}/runs?event={MERGE_GROUP_EVENT}&per_page=100&page={page}"
        )
        batch = list((payload or {}).get("workflow_runs", []))
        collected.extend(batch)
        if len(batch) < 100:
            break
    return collected


def fetch_runs_for_sha(repo: str, sha: str, api: Api) -> list[dict]:
    """``ci.yml`` merge-group runs whose head commit is ``sha``."""
    payload = api(
        f"repos/{repo}/actions/workflows/{CI_WORKFLOW_FILE}/runs?event={MERGE_GROUP_EVENT}&head_sha={sha}&per_page=100"
    )
    return list((payload or {}).get("workflow_runs", []))
