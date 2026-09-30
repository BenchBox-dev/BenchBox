"""Require an assigned pytest shard to be collected and executed completely."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.release_canary_sharding import read_node_ids


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption("--assigned-nodeids", type=Path, required=True)
    parser.addoption("--shard-evidence", type=Path, required=True)
    parser.addoption("--checked-sha", required=True)


class ShardEvidence:
    def __init__(self, config: pytest.Config) -> None:
        self.assigned = read_node_ids(config.getoption("assigned_nodeids"))
        self.output = config.getoption("shard_evidence")
        self.sha = config.getoption("checked_sha")
        self.observed: list[str] = []
        self.collections: list[list[str]] = []

    def pytest_collection_finish(self, session: pytest.Session) -> None:
        # xdist controllers delegate collection to workers. Capture each
        # worker's actual selection through the xdist collection hook below.
        if not session.config.getoption("numprocesses", default=0):
            self.collections.append(sorted(item.nodeid for item in session.items))

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: object, ids: list[str]) -> None:
        self.collections.append(sorted(ids))

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and report.outcome in {"failed", "skipped"}):
            self.observed.append(report.nodeid)

    @pytest.hookimpl(trylast=True)
    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        if hasattr(session.config, "workerinput"):
            return
        complete = bool(self.collections) and all(ids == self.assigned for ids in self.collections)
        complete = complete and sorted(self.observed) == self.assigned
        self.output.parent.mkdir(parents=True, exist_ok=True)
        self.output.write_text(
            json.dumps(
                {
                    "commit_sha": self.sha,
                    "assigned_node_ids": self.assigned,
                    "collected_node_ids": self.collections,
                    "executed_node_ids": sorted(self.observed),
                    "complete": complete,
                    "pytest_exit_status": int(exitstatus),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        if not complete and exitstatus == 0:
            session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_configure(config: pytest.Config) -> None:
    config.pluginmanager.register(ShardEvidence(config), "assigned-shard-evidence")
