from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("comment_cleanup_scope", ROOT / "scripts/check_comment_cleanup_scope.py")
assert SPEC and SPEC.loader
scope = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scope
SPEC.loader.exec_module(scope)


@pytest.fixture
def policy() -> dict:
    return {
        "version": 1,
        "maintained_roots": [{"id": "source", "selector": {"prefix": "src/"}, "kind": "source"}],
        "ownership_rules": [
            {
                "id": "source-owner",
                "owner": "comment-cleanup-core-bootstrap",
                "state": "blocked",
                "blocking_disposition": "Await source-reader inventory.",
                "priority": 0,
                "selectors": [{"prefix": "src/"}],
            }
        ],
        "external_entries": [],
        "payloads": [],
        "derived_rules": [],
        "consumer_edges": [],
        "directives": [],
        "notices": [],
        "obligations": [],
        "review_dispositions": [
            {
                "id": f"R{number}",
                "disposition": "accepted",
                "original_verdict": "accepted",
                "requirements": ["requirement"],
                "rationale": "Fixture rationale.",
                "acceptance_refs": ["Fixture acceptance reference."],
                "owner": "comment-cleanup-scope-policy",
            }
            for number in range(1, 19)
        ],
    }


def test_owned_paths_reports_unclassified_as_blocked(policy: dict) -> None:
    roots = scope.validate_roots(policy)
    resolved, findings = scope.owned_paths(["src/a.py"], roots, [])
    assert [finding.code for finding in findings] == ["SCOPE001"]
    assert resolved == [
        {
            "path": "src/a.py",
            "kind": "source",
            "owner": None,
            "state": "blocked",
            "blocking_disposition": "Ownership is not frozen for this maintained path.",
            "rule": None,
        }
    ]


def test_high_priority_shared_override_selects_one_owner(policy: dict) -> None:
    override = {
        "id": "shared-test",
        "owner": "comment-cleanup-cross-module-unit-tests",
        "state": "blocked",
        "blocking_disposition": "Serialize shared test changes.",
        "priority": 1,
        "selectors": [{"path": "src/shared.py"}],
    }
    rules = scope.validate_rules({**policy, "ownership_rules": [*policy["ownership_rules"], override]})
    resolved, findings = scope.owned_paths(["src/shared.py"], scope.validate_roots(policy), rules)
    assert not findings
    assert resolved[0]["owner"] == "comment-cleanup-cross-module-unit-tests"
    assert resolved[0]["rule"] == "shared-test"


def test_equal_priority_rules_are_an_ownership_collision(policy: dict) -> None:
    conflicting = deepcopy(policy["ownership_rules"][0])
    conflicting["id"] = "other-owner"
    conflicting["owner"] = "comment-cleanup-core-catalogs"
    rules = scope.validate_rules({**policy, "ownership_rules": [*policy["ownership_rules"], conflicting]})
    resolved, findings = scope.owned_paths(["src/a.py"], scope.validate_roots(policy), rules)
    assert [finding.code for finding in findings] == ["SCOPE002"]
    assert resolved[0]["state"] == "blocked"
    assert resolved[0]["rule"] == ["other-owner", "source-owner"]


def test_more_specific_root_wins_over_repository_fallback(policy: dict) -> None:
    policy["maintained_roots"].append({"id": "repository", "selector": {"prefix": ""}, "kind": "unclassified"})
    root = scope.selected_root("src/a.py", scope.validate_roots(policy))
    assert root["id"] == "source"


def test_equally_specific_roots_are_rejected(policy: dict) -> None:
    policy["maintained_roots"].append({"id": "other-source", "selector": {"prefix": "src/"}, "kind": "other"})
    with pytest.raises(scope.PolicyError, match="maintained-root collision"):
        scope.selected_root("src/a.py", scope.validate_roots(policy))


def test_policy_requires_all_review_dispositions(policy: dict) -> None:
    policy["review_dispositions"].pop()
    with pytest.raises(scope.PolicyError, match="review dispositions"):
        scope.validate_dispositions(policy)


def test_evidence_requires_immutable_base_paths(policy: dict) -> None:
    policy["notices"] = [
        {
            "path": "missing.py",
            "blob_sha256": "a" * 64,
            "byte_start": 0,
            "byte_end": 1,
            "retained_sha256": "a" * 64,
            "governing_requirement": "required notice",
            "source_identity": "upstream source",
            "owner": "comment-cleanup-scope-policy",
            "blocking_disposition": "Await provenance proof.",
        }
    ]
    with pytest.raises(scope.PolicyError, match="not tracked"):
        scope.validate_evidence(policy, ROOT, "0" * 40, {"src/a.py"})


def test_consumer_edge_rejects_unknown_endpoint(policy: dict) -> None:
    policy["consumer_edges"] = [
        {
            "producer": "src/a.py",
            "consumer": "unknown",
            "owner": "comment-cleanup-core-bootstrap",
            "state": "blocked",
            "blocking_disposition": "Await consumer mapping.",
            "proof": "source proof",
        }
    ]
    with pytest.raises(scope.PolicyError, match="endpoint"):
        scope.validate_payloads_and_edges(policy, {"src/a.py"})


def test_duplicate_consumer_edge_is_rejected(policy: dict) -> None:
    edge = {
        "producer": "src/a.py",
        "consumer": "src/consumer.py",
        "owner": "comment-cleanup-core-bootstrap",
        "state": "blocked",
        "blocking_disposition": "Await consumer migration.",
        "proof": "source proof",
    }
    policy["consumer_edges"] = [edge, deepcopy(edge)]
    with pytest.raises(scope.PolicyError, match="duplicate consumer edge"):
        scope.validate_payloads_and_edges(policy, {"src/a.py", "src/consumer.py"})


def test_cyclic_consumer_edges_are_rejected(policy: dict) -> None:
    policy["consumer_edges"] = [
        {
            "producer": "src/a.py",
            "consumer": "src/b.py",
            "owner": "comment-cleanup-core-bootstrap",
            "state": "blocked",
            "blocking_disposition": "Await consumer migration.",
            "proof": "source proof",
        },
        {
            "producer": "src/b.py",
            "consumer": "src/a.py",
            "owner": "comment-cleanup-core-bootstrap",
            "state": "blocked",
            "blocking_disposition": "Await consumer migration.",
            "proof": "source proof",
        },
    ]
    with pytest.raises(scope.PolicyError, match="cyclic consumer edge"):
        scope.validate_payloads_and_edges(policy, {"src/a.py", "src/b.py"})


def test_blocked_consumer_prevents_ready_producer(policy: dict) -> None:
    policy["ownership_rules"][0]["state"] = "ready"
    policy["consumer_edges"] = [
        {
            "producer": "src/a.py",
            "consumer": "src/consumer.py",
            "owner": "comment-cleanup-core-bootstrap",
            "state": "blocked",
            "blocking_disposition": "Await consumer migration.",
            "proof": "source proof",
        }
    ]
    resolved, _ = scope.owned_paths(
        ["src/a.py", "src/consumer.py"],
        scope.validate_roots(policy),
        scope.validate_rules(policy),
    )
    assert [finding.code for finding in scope.dependency_findings(policy, resolved)] == ["SCOPE003"]


def test_frozen_task_ids_rejects_unknown_owner(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".git/info/exclude").write_text(".todo-batch/\n", encoding="utf-8")
    (tmp_path / ".todo-batch").mkdir()
    (tmp_path / ".todo-batch/tasks.txt").write_text("TODO: comment-cleanup-known\n", encoding="utf-8")
    task_ids = scope.frozen_task_ids(tmp_path, ".todo-batch/tasks.txt")
    with pytest.raises(scope.PolicyError, match="frozen task set"):
        scope.check_owner("comment-cleanup-unknown", "owner", task_ids)


def test_notice_digest_must_match_immutable_base_bytes(tmp_path: Path, policy: dict) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    (tmp_path / "src").mkdir()
    notice = b"required notice\n"
    (tmp_path / "src/a.py").write_bytes(notice)
    policy["notices"] = [
        {
            "path": "src/a.py",
            "blob_sha256": hashlib.sha256(notice).hexdigest(),
            "byte_start": 0,
            "byte_end": len(notice),
            "retained_sha256": hashlib.sha256(notice).hexdigest(),
            "governing_requirement": "fixture requirement",
            "source_identity": "fixture source",
            "owner": "comment-cleanup-core-bootstrap",
            "blocking_disposition": "Retain required notice.",
        }
    ]
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    scope.validate_evidence(policy, tmp_path, base, {"src/a.py"})
    policy["notices"][0]["retained_sha256"] = "0" * 64
    with pytest.raises(scope.PolicyError, match="retained-byte digest"):
        scope.validate_evidence(policy, tmp_path, base, {"src/a.py"})


def test_obligation_requires_exactly_one_destination_reference(tmp_path: Path, policy: dict) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("# TODO: follow up\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    entry = {
        "path": "src/a.py",
        "token": "TODO",
        "destination": "follow-up",
        "tracker_reference": "",
        "approved_destination": "",
        "owner": "comment-cleanup-core-bootstrap",
        "blocking_disposition": "Await approved follow-up.",
    }
    policy["obligations"] = [entry]
    with pytest.raises(scope.PolicyError, match="exactly one"):
        scope.validate_evidence(policy, tmp_path, base, {"src/a.py"})
    entry["tracker_reference"] = "comment-cleanup-follow-up"
    scope.validate_evidence(policy, tmp_path, base, {"src/a.py"})
    entry["approved_destination"] = "approved destination"
    with pytest.raises(scope.PolicyError, match="exactly one"):
        scope.validate_evidence(policy, tmp_path, base, {"src/a.py"})


def test_validator_writes_only_to_ignored_output(tmp_path: Path, policy: dict) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "quality").mkdir()
    (tmp_path / "quality/comment-cleanup-scope.json").write_text(json.dumps(policy), encoding="utf-8")
    (tmp_path / ".git/info/exclude").write_text(".todo-batch/\n", encoding="utf-8")
    (tmp_path / ".todo-batch").mkdir()
    owners = {rule["owner"] for rule in policy["ownership_rules"]}
    owners.update(item["owner"] for item in policy["review_dispositions"])
    (tmp_path / ".todo-batch/tasks.txt").write_text(
        "".join(f"TODO: {owner}\n" for owner in sorted(owners)), encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "fixture"], check=True)
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"], text=True).strip()
    assert (
        scope.main(
            [
                "--root",
                str(tmp_path),
                "--base",
                base,
                "--task-set",
                ".todo-batch/tasks.txt",
                "--output",
                ".todo-batch/manifest.json",
            ]
        )
        == 0
    )
    assert (tmp_path / ".todo-batch/manifest.json").is_file()
    assert (
        scope.main(
            [
                "--root",
                str(tmp_path),
                "--base",
                base,
                "--task-set",
                ".todo-batch/tasks.txt",
                "--output",
                "manifest.json",
            ]
        )
        == 2
    )


def test_verified_source_slices_have_distinct_blocked_owners() -> None:
    repository_policy = scope.load_policy(ROOT / "quality/comment-cleanup-scope.json")
    roots = scope.validate_roots(repository_policy)
    rules = scope.validate_rules(repository_policy)
    paths = [
        "benchbox/core/tpch/queries.py",
        "benchbox/core/tpcds/dataframe_queries/queries.py",
        "benchbox/core/tpcds/generator/runner.py",
        "benchbox/core/tpcdi/generator/data.py",
        "benchbox/core/tpchavoc/dataframe_queries/queries.py",
        "benchbox/core/ssb/queries.py",
        "benchbox/core/clickbench/queries.py",
        "benchbox/core/read_primitives/dataframe_queries.py",
    ]
    resolved, findings = scope.owned_paths(paths, roots, rules)
    assert not findings
    assert all(record["state"] == "blocked" for record in resolved)
    assert {record["owner"] for record in resolved} == {
        "comment-cleanup-tpch",
        "comment-cleanup-tpcds-dataframe",
        "comment-cleanup-tpcds-generation",
        "comment-cleanup-tpcdi-generation",
        "comment-cleanup-tpchavoc-dataframe",
        "comment-cleanup-ssb",
        "comment-cleanup-clickbench",
        "comment-cleanup-read-primitives",
    }


def test_verified_source_slice_paths_remain_blocked_when_unmapped() -> None:
    repository_policy = scope.load_policy(ROOT / "quality/comment-cleanup-scope.json")
    roots = scope.validate_roots(repository_policy)
    rules = scope.validate_rules(repository_policy)
    resolved, findings = scope.owned_paths(["benchbox/core/tpchavoc_variants/new.py"], roots, rules)
    assert [finding.code for finding in findings] == ["SCOPE001"]
    assert resolved[0]["owner"] is None
    assert resolved[0]["state"] == "blocked"


def test_verified_source_slice_rule_ids_are_unique() -> None:
    policy = scope.load_policy(ROOT / "quality/comment-cleanup-scope.json")
    rules = scope.validate_rules(policy)
    ids = [rule["id"] for rule in rules if rule["id"].endswith("-source-slice")]
    assert len(ids) == 20
    assert len(ids) == len(set(ids))


def test_review_dispositions_preserve_original_verdict_and_rationale() -> None:
    policy = scope.load_policy(ROOT / "quality/comment-cleanup-scope.json")
    dispositions = policy["review_dispositions"]
    assert len(dispositions) == 18
    assert {item["id"] for item in dispositions} == {f"R{number}" for number in range(1, 19)}
    for item in dispositions:
        assert item["original_verdict"] == item["disposition"]
        assert item["rationale"]
        assert item["acceptance_refs"]


def test_every_tracked_eula_and_notice_file_has_a_notice_entry() -> None:
    policy = scope.load_policy(ROOT / "quality/comment-cleanup-scope.json")
    listed = {entry["path"] for entry in policy["notices"]}
    tracked = scope.git(ROOT, "ls-files", "-z", "--", "_binaries", "_sources").decode().split("\0")
    notice_files = {
        path for path in tracked if path and Path(path).name in {"EULA.txt", "NOTICE.txt"} and (ROOT / path).exists()
    }
    assert notice_files
    assert notice_files <= listed


def _derived_rule(priority: int = 20) -> dict:
    return {
        "id": "test-import-owner",
        "method": "python-imports",
        "state": "blocked",
        "blocking_disposition": "Derived from imports.",
        "priority": priority,
        "selectors": [{"prefix": "tests/"}],
    }


def _resolved(path: str, owner: str | None) -> dict:
    return {"path": path, "kind": "x", "owner": owner, "state": "blocked", "blocking_disposition": "b", "rule": "r"}


def _git_repo_with(tmp_path: Path, files: dict[str, str]) -> tuple[Path, str]:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "--", *files], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "x"],
        check=True,
    )
    base = subprocess.check_output(["git", "-C", str(tmp_path), "rev-parse", "HEAD"]).decode().strip()
    return tmp_path, base


def test_derived_rule_assigns_single_import_owner_and_falls_back_otherwise(tmp_path: Path) -> None:
    root, base = _git_repo_with(
        tmp_path,
        {
            "benchbox/__init__.py": "",
            "benchbox/a.py": "",
            "benchbox/b.py": "",
            "tests/test_a.py": "from benchbox.a import thing\n",
            "tests/test_ab.py": "import benchbox.a\nimport benchbox.b\n",
            "tests/test_facade.py": "from benchbox import thing\n",
            "tests/test_none.py": "import os\n",
            "tests/broken.py": "def (:\n",
        },
    )
    resolved = [
        _resolved("benchbox/a.py", "comment-cleanup-a"),
        _resolved("benchbox/b.py", "comment-cleanup-b"),
        _resolved("benchbox/__init__.py", "comment-cleanup-boot"),
        *(
            _resolved(f"tests/{n}.py", "comment-cleanup-fallback")
            for n in ("test_a", "test_ab", "test_facade", "test_none", "broken")
        ),
    ]
    scope.apply_derived_rules(resolved, [_derived_rule()], root, base, {})
    owners = {record["path"]: record["owner"] for record in resolved}
    assert owners["tests/test_a.py"] == "comment-cleanup-a"
    assert owners["tests/test_ab.py"] == "comment-cleanup-fallback"
    assert owners["tests/test_facade.py"] == "comment-cleanup-fallback"
    assert owners["tests/test_none.py"] == "comment-cleanup-fallback"
    assert owners["tests/broken.py"] == "comment-cleanup-fallback"


def test_derived_rule_does_not_override_a_higher_priority_rule(tmp_path: Path) -> None:
    root, base = _git_repo_with(tmp_path, {"benchbox/a.py": "", "tests/test_a.py": "import benchbox.a\n"})
    resolved = [_resolved("benchbox/a.py", "comment-cleanup-a"), _resolved("tests/test_a.py", "comment-cleanup-exact")]
    scope.apply_derived_rules(resolved, [_derived_rule()], root, base, {"tests/test_a.py": 30})
    assert resolved[1]["owner"] == "comment-cleanup-exact"


def test_derived_rule_rejects_unknown_method(policy: dict) -> None:
    policy["derived_rules"] = [{**_derived_rule(), "method": "guess-from-names"}]
    with pytest.raises(scope.PolicyError):
        scope.validate_derived_rules(policy)


def test_derived_rule_skips_ownership_collisions(tmp_path: Path) -> None:
    root, base = _git_repo_with(tmp_path, {"benchbox/a.py": "", "tests/t.py": "import benchbox.a\n"})
    collision = {**_resolved("tests/t.py", None), "rule": ["rule-a", "rule-b"], "competing_owners": ["a", "b"]}
    resolved = [_resolved("benchbox/a.py", "comment-cleanup-a"), collision]
    scope.apply_derived_rules(resolved, [_derived_rule()], root, base, {})
    assert resolved[1]["owner"] is None
    assert resolved[1]["rule"] == ["rule-a", "rule-b"]


def test_derived_rule_counts_module_literals_and_rejects_unowned_modules(tmp_path: Path) -> None:
    root, base = _git_repo_with(
        tmp_path,
        {
            "benchbox/a.py": "",
            "benchbox/b.py": "",
            "benchbox/loose.py": "",
            "tests/test_patch.py": 'import benchbox.a\npatch("benchbox.b.Thing")\n',
            "tests/test_dynamic.py": 'importlib.import_module("benchbox.a")\n',
            "tests/test_unowned.py": "import benchbox.a\nimport benchbox.loose\n",
        },
    )
    resolved = [
        _resolved("benchbox/a.py", "comment-cleanup-a"),
        _resolved("benchbox/b.py", "comment-cleanup-b"),
        _resolved("benchbox/loose.py", None),
        *(
            _resolved(f"tests/{n}.py", "comment-cleanup-fallback")
            for n in ("test_patch", "test_dynamic", "test_unowned")
        ),
    ]
    scope.apply_derived_rules(resolved, [_derived_rule()], root, base, {})
    owners = {record["path"]: record["owner"] for record in resolved}
    assert owners["tests/test_patch.py"] == "comment-cleanup-fallback"
    assert owners["tests/test_dynamic.py"] == "comment-cleanup-a"
    assert owners["tests/test_unowned.py"] == "comment-cleanup-fallback"


def test_notice_owner_claims_an_unowned_path_and_reports_conflicts() -> None:
    notices = [
        {"path": "LICENSE", "owner": "comment-cleanup-scope-policy", "blocking_disposition": "Retain exact bytes."},
        {"path": "NOTICE", "owner": "comment-cleanup-scope-policy", "blocking_disposition": "Retain exact bytes."},
    ]
    resolved = [_resolved("LICENSE", None), _resolved("NOTICE", "comment-cleanup-other")]
    resolved[0]["rule"] = None
    findings = scope.apply_notice_owners(resolved, notices)
    assert resolved[0]["owner"] == "comment-cleanup-scope-policy"
    assert resolved[0]["rule"] == "notice"
    assert resolved[1]["owner"] == "comment-cleanup-other"
    assert [finding.code for finding in findings] == ["SCOPE005"]
