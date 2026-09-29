"""Generation ordering for the serialized site writer.

A deploy run may replace the live site only with a candidate that is not older
than what is already deployed. The decisions here are pure functions of facts the
caller has already gathered (git ancestry, release tag versions, the previous
receipt), so delayed and overlapping runs can be tested in either order.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class Relation(str, Enum):
    """How a candidate commit relates to the commit currently deployed."""

    SAME = "same"
    DESCENDANT = "descendant"  # candidate is newer: the deployed commit is its ancestor
    ANCESTOR = "ancestor"  # candidate is older
    DIVERGED = "diverged"  # neither contains the other, or ancestry is unknown


class Verdict(str, Enum):
    DEPLOY = "deploy"
    FIRST_DEPLOY = "first-deploy"
    NOOP = "noop"
    REFUSE = "refuse"


def release_version(tag: str) -> tuple[int, int, int]:
    """Parse ``vX.Y.Z``; anything else is not a release tag."""
    match = RELEASE_TAG_RE.match(tag)
    if match is None:
        raise ValueError(f"not a release tag: {tag!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


@dataclass(frozen=True)
class Generation:
    """The pinned identity of one site build."""

    trunk_sha: str
    trunk_index: int  # first-parent commit count of trunk at trunk_sha
    release_tag: str
    corpus_sha: str

    def __post_init__(self) -> None:
        for label, value in (("trunk_sha", self.trunk_sha), ("corpus_sha", self.corpus_sha)):
            if not SHA_RE.match(value):
                raise ValueError(f"{label} must be a 40-hex commit, got {value!r}")
        release_version(self.release_tag)
        if self.trunk_index < 0:
            raise ValueError("trunk_index must not be negative")

    @property
    def release_version(self) -> tuple[int, int, int]:
        return release_version(self.release_tag)

    def to_dict(self) -> dict[str, object]:
        return {
            "trunk_sha": self.trunk_sha,
            "trunk_index": self.trunk_index,
            "release_tag": self.release_tag,
            "corpus_sha": self.corpus_sha,
        }

    @classmethod
    def from_dict(cls, data: object) -> Generation:
        if not isinstance(data, dict):
            raise ValueError("generation must be a mapping")
        try:
            return cls(
                trunk_sha=str(data["trunk_sha"]),
                trunk_index=int(data["trunk_index"]),
                release_tag=str(data["release_tag"]),
                corpus_sha=str(data["corpus_sha"]),
            )
        except KeyError as exc:
            raise ValueError(f"generation is missing {exc.args[0]!r}") from exc


@dataclass(frozen=True)
class DeployedState:
    """What the previous receipt says is live."""

    generation: Generation
    receipt_id: str
    artifact_sha256: str
    quarantined_trunk_shas: frozenset[str] = frozenset()
    quarantined_release_tags: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Relations:
    """Ancestry facts between a candidate and the deployed generation."""

    trunk: Relation
    corpus: Relation


@dataclass
class Decision:
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)

    @property
    def allowed(self) -> bool:
        return self.verdict in (Verdict.DEPLOY, Verdict.FIRST_DEPLOY)

    def to_dict(self) -> dict[str, object]:
        return {"verdict": self.verdict.value, "allowed": self.allowed, "reasons": list(self.reasons)}


def _ancestry_refusals(candidate: Generation, deployed: Generation, relations: Relations) -> list[str]:
    refusals: list[str] = []
    if relations.trunk is Relation.ANCESTOR:
        refusals.append(
            f"candidate trunk {candidate.trunk_sha[:12]} (index {candidate.trunk_index}) is older than deployed "
            f"{deployed.trunk_sha[:12]} (index {deployed.trunk_index})"
        )
    elif relations.trunk is Relation.DIVERGED:
        refusals.append(
            f"candidate trunk {candidate.trunk_sha[:12]} does not descend from deployed {deployed.trunk_sha[:12]}"
        )
    if candidate.release_version < deployed.release_version:
        refusals.append(f"candidate release tag {candidate.release_tag} is older than deployed {deployed.release_tag}")
    if relations.corpus is Relation.ANCESTOR:
        refusals.append(
            f"candidate corpus {candidate.corpus_sha[:12]} is older than deployed corpus {deployed.corpus_sha[:12]}"
        )
    elif relations.corpus is Relation.DIVERGED:
        refusals.append(
            f"candidate corpus {candidate.corpus_sha[:12]} does not descend from deployed corpus "
            f"{deployed.corpus_sha[:12]}"
        )
    return refusals


def decide_deploy(candidate: Generation, deployed: DeployedState | None, relations: Relations | None) -> Decision:
    """Decide whether a candidate may replace the deployed site.

    A candidate is refused when it is older than, or unrelated to, the deployed
    generation on any pin, or when it names a quarantined commit or tag. Equal pins
    are a no-op. ``relations`` may be ``None`` only when nothing is deployed.
    """
    if deployed is None:
        return Decision(Verdict.FIRST_DEPLOY, ["no previous site-deploy receipt: nothing to order against"])
    if relations is None:
        raise ValueError("relations are required when a deployed state exists")

    refusals: list[str] = []
    if candidate.trunk_sha in deployed.quarantined_trunk_shas:
        refusals.append(f"trunk {candidate.trunk_sha[:12]} was rolled back and is quarantined")
    if candidate.release_tag in deployed.quarantined_release_tags:
        refusals.append(f"release tag {candidate.release_tag} was rolled back and is quarantined")
    refusals.extend(_ancestry_refusals(candidate, deployed.generation, relations))
    if refusals:
        return Decision(Verdict.REFUSE, refusals)

    current = deployed.generation
    unchanged = (
        relations.trunk is Relation.SAME
        and candidate.release_tag == current.release_tag
        and relations.corpus is Relation.SAME
    )
    if unchanged:
        return Decision(Verdict.NOOP, ["candidate pins equal the deployed generation"])
    return Decision(Verdict.DEPLOY, ["candidate is newer than the deployed generation"])


@dataclass(frozen=True)
class RollbackTarget:
    """A prior receipt offered as the rollback destination."""

    receipt_id: str
    generation: Generation
    artifact_sha256: str
    target: str
    status: str
    probes_ok: bool
    deployment_confirmed: bool


def last_known_good_problems(target: RollbackTarget) -> list[str]:
    """Reasons a receipt cannot serve as a rollback destination."""
    problems: list[str] = []
    if target.target != "production":
        problems.append(f"receipt targets {target.target!r}, not production")
    if target.status != "live-verified":
        problems.append(f"receipt status is {target.status!r}, not 'live-verified'")
    if not target.probes_ok:
        problems.append("receipt records failing post-deploy probes")
    if not target.deployment_confirmed:
        problems.append("receipt does not record a confirmed Pages deployment")
    if not re.fullmatch(r"[0-9a-f]{64}", target.artifact_sha256):
        problems.append("receipt has no valid artifact sha256")
    return problems


def decide_rollback(
    target: RollbackTarget,
    deployed: DeployedState | None,
    relations: Relations | None,
    *,
    live_unconfirmed: bool = False,
) -> Decision:
    """Decide whether a prior receipt may be redeployed over the live site.

    Only a receipt that was probed green in production, that is not newer than the
    live generation, and that was not itself rolled back may be restored.
    ``live_unconfirmed`` means the recorded receipt may not describe what is live
    (another writer deployed since); the already-deployed shortcut is then skipped.
    """
    problems = last_known_good_problems(target)
    if deployed is None:
        problems.append("no deployed site-deploy receipt to roll back from")
    if problems:
        return Decision(Verdict.REFUSE, problems)
    assert deployed is not None
    if relations is None:
        raise ValueError("relations are required for rollback")

    refusals: list[str] = []
    generation = target.generation
    if generation.trunk_sha in deployed.quarantined_trunk_shas:
        refusals.append(f"trunk {generation.trunk_sha[:12]} was rolled back before and is quarantined")
    if generation.release_tag in deployed.quarantined_release_tags:
        refusals.append(f"release tag {generation.release_tag} was rolled back before and is quarantined")
    if relations.trunk is Relation.DESCENDANT:
        refusals.append("rollback target is newer than the deployed generation; use a normal deploy")
    elif relations.trunk is Relation.DIVERGED:
        refusals.append("rollback target is not an ancestor of the deployed generation")
    if generation.release_version > deployed.generation.release_version:
        refusals.append("rollback target release tag is newer than the deployed release tag")
    if relations.corpus is Relation.DESCENDANT:
        refusals.append("rollback target corpus is newer than the deployed corpus")
    elif relations.corpus is Relation.DIVERGED:
        refusals.append("rollback target corpus is not an ancestor of the deployed corpus")
    if refusals:
        return Decision(Verdict.REFUSE, refusals)

    if not live_unconfirmed and (
        target.receipt_id == deployed.receipt_id or target.artifact_sha256 == deployed.artifact_sha256
    ):
        return Decision(Verdict.NOOP, ["rollback target is already the deployed artifact"])
    return Decision(Verdict.DEPLOY, ["rollback target is a probed-green, older generation"])


def quarantine_after_rollback(deployed: DeployedState, restored: Generation) -> tuple[frozenset[str], frozenset[str]]:
    """Commits and tags to block from redeployment once ``deployed`` is rolled back."""
    trunk = set(deployed.quarantined_trunk_shas)
    tags = set(deployed.quarantined_release_tags)
    if deployed.generation.trunk_sha != restored.trunk_sha:
        trunk.add(deployed.generation.trunk_sha)
    if deployed.generation.release_tag != restored.release_tag:
        tags.add(deployed.generation.release_tag)
    return frozenset(trunk), frozenset(tags)


# ---------------------------------------------------------------------------
# Git facts
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], check=False, capture_output=True, text=True)


def git_relation(repo: Path, candidate: str, deployed: str) -> Relation:
    """Ancestry of ``candidate`` relative to ``deployed``; unknown commits are DIVERGED (fail closed)."""
    if candidate == deployed:
        return Relation.SAME
    for sha in (candidate, deployed):
        if _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
            return Relation.DIVERGED
    if _git(repo, "merge-base", "--is-ancestor", deployed, candidate).returncode == 0:
        return Relation.DESCENDANT
    if _git(repo, "merge-base", "--is-ancestor", candidate, deployed).returncode == 0:
        return Relation.ANCESTOR
    return Relation.DIVERGED


def trunk_index(repo: Path, sha: str) -> int:
    """Monotonic position of ``sha`` along trunk: its first-parent commit count."""
    result = _git(repo, "rev-list", "--first-parent", "--count", sha)
    if result.returncode != 0:
        raise ValueError(f"cannot count first-parent commits for {sha}: {result.stderr.strip()}")
    return int(result.stdout.strip())


def first_parent_shas(repo: Path, ref: str, limit: int) -> list[str]:
    result = _git(repo, "rev-list", "--first-parent", f"--max-count={limit}", ref)
    if result.returncode != 0:
        raise ValueError(f"cannot list first-parent commits of {ref}: {result.stderr.strip()}")
    return result.stdout.split()


def relations_for(repo: Path, candidate: Generation, deployed: Generation) -> Relations:
    return Relations(
        trunk=git_relation(repo, candidate.trunk_sha, deployed.trunk_sha),
        corpus=git_relation(repo, candidate.corpus_sha, deployed.corpus_sha),
    )
