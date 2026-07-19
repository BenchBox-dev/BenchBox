"""Live integration test for the hosted (Turso/libsql) TODO tracker backend.

Everything else in the hosted suite runs against fakes that *encode* the real
client's observed quirks; this module is the checked-in counterpart of the
live acceptance protocol (`_project/audits/todo-db-hosted-acceptance-2026-07-18.md`),
so the claims stop being session testimony. It exercises, against a real
libsql primary: connect + sync, the claim path (cursor.rowcount semantics),
deferral creation (cursor.lastrowid semantics), cross-actor claim contention,
the deferral gate, and terminal cleanup — all through the shim, exactly as
agents use it.

Gated: runs only when TODO_TEST_DB_URL and TODO_DB_AUTH_TOKEN are set (a
dedicated test database, never the production tracker — see the spec's
Testing bullet). Deselected from the default lane by `live_integration`.
"""

from __future__ import annotations

import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.live_integration,
]

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "_project" / "scripts" / "todo"

TEST_URL = os.environ.get("TODO_TEST_DB_URL", "")
AUTH_TOKEN = os.environ.get("TODO_DB_AUTH_TOKEN", "")

requires_live_db = pytest.mark.skipif(
    not (TEST_URL and AUTH_TOKEN),
    reason="TODO_TEST_DB_URL and TODO_DB_AUTH_TOKEN not set (dedicated hosted test DB required)",
)


def _run(args: list[str], actor: str, replica_dir: Path) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(Path.home()),
        "TODO_DB_URL": TEST_URL,
        "TODO_DB_AUTH_TOKEN": AUTH_TOKEN,
        "TODO_DB_REPLICA": str(replica_dir / "replica.db"),
        "TODO_ACTOR": actor,
    }
    return subprocess.run(
        [str(SHIM), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env=env,
        check=False,
        timeout=180,
    )


@requires_live_db
class TestHostedLiveLifecycle:
    def test_two_actor_lifecycle_against_real_primary(self, tmp_path):
        item = f"live-uat-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"
        replica_a = tmp_path / "replica-a"
        replica_b = tmp_path / "replica-b"

        create = _run(
            [
                "create",
                item,
                "--title",
                "Live hosted integration item",
                "--worktree",
                "spike",
                "--priority",
                "low",
                "--description",
                "Checked-in live counterpart of the acceptance protocol.",
                "--work",
                "w1:live probe unit",
            ],
            "live-actor-a",
            replica_a,
        )
        assert create.returncode == 0, create.stderr

        # claim succeeds for A (real-client cursor.rowcount must be 1 here —
        # a rowcount-lying client would refuse even an uncontended claim)
        claim_a = _run(["claim", item], "live-actor-a", replica_a)
        assert claim_a.returncode == 0, claim_a.stderr

        # separate replica + actor: contention must refuse with exit 2
        claim_b = _run(["claim", item], "live-actor-b", replica_b)
        assert claim_b.returncode == 2
        assert "claimed by 'live-actor-a'" in claim_b.stderr

        done = _run(["done", item, "w1", "--evidence", "live integration run"], "live-actor-a", replica_a)
        assert done.returncode == 0, done.stderr

        # deferral id comes from cursor.lastrowid on the real client
        defer = _run(["defer", item, "--summary", "live gate probe", "--reason", "proof"], "live-actor-a", replica_a)
        assert defer.returncode == 0, defer.stderr
        assert "deferral #" in defer.stdout
        deferral_id = defer.stdout.split("#")[1].split()[0]

        # cross-replica deferral gate
        blocked = _run(["complete", item], "live-actor-b", replica_b)
        assert blocked.returncode == 2
        assert "unresolved deferrals" in blocked.stderr

        dismiss = _run(["dismiss", deferral_id, "--reason", "live probe artifact"], "live-actor-b", replica_b)
        assert dismiss.returncode == 0, dismiss.stderr
        complete = _run(["complete", item], "live-actor-a", replica_a)
        assert complete.returncode == 0, complete.stderr

        # terminal-defer guard, live
        late = _run(["defer", item, "--summary", "too late", "--reason", "nope"], "live-actor-a", replica_a)
        assert late.returncode == 2
        assert "terminal items" in late.stderr
