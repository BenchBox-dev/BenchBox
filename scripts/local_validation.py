#!/usr/bin/env python3
"""Serialize local validation gates and coalesce duplicate same-input runs.

Two agents (or two worktrees) often invoke the same local gate against the
same tree within minutes of each other. The second invocation historically
collided on the shared test lock and retried in a lock-error loop. This tool
makes that case cheap and honest:

* Identical validated inputs reuse a completed receipt instead of executing.
* Anything else (unknown identity, changed files/ref/tool, incomplete or
  failed prior run, different gate) executes.
* Concurrent identical requests serialize on a store lock: the waiter
  re-checks after acquiring and reuses the winner's receipt, so simultaneous
  identical requests execute once.

Receipts never certify hosted required checks and never transfer across
changed integration trees: the worktree HEAD, status, base ref, and tool
versions are all part of the identity. A failed prior run leaves no receipt,
so failures always re-execute.

Usage:
  python scripts/local_validation.py run --gate pr-preflight-fast -- make pr-preflight-fast-tests
  python scripts/local_validation.py run --gate member-check --batch-id B --batch-member M --batch-role member -- pytest tests/unit -q
  python scripts/local_validation.py show --gate pr-preflight-fast
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

# Bounds keep identity computation cheap; exceeding them means "unknown",
# which forces execution (fail open to running, never to false reuse).
MAX_UNTRACKED_FILES = 200
MAX_UNTRACKED_BYTES = 50 * 1024 * 1024
LOCK_POLL_SECONDS = 0.25
DEFAULT_LOCK_WAIT_SECONDS = 3600.0


class IdentityUnknown(Exception):
    """The working-tree identity cannot be established exactly."""


def read_holder(lock_path: Path) -> str:
    """Best-effort holder description for wait/timeout messages."""
    try:
        return lock_path.read_text(encoding="utf-8").strip() or "(empty lock file)"
    except OSError:
        return "(could not read lock file)"


def wait_on_fd(fd: int, lock_path: Path, timeout_seconds: float) -> None:
    """Acquire an exclusive flock on open *fd*, waiting up to *timeout_seconds*.

    Raises TimeoutError carrying the last observed holder description without
    closing *fd*. KeyboardInterrupt cancels the wait. A held flock always
    means a live holder: the kernel releases locks on process death, so this
    never steals, deletes, or bypasses. Shared with tests/conftest.py.
    """
    import fcntl

    deadline = time.monotonic() + max(0.0, timeout_seconds)
    holder = read_holder(lock_path)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except (BlockingIOError, OSError):
            holder = read_holder(lock_path)
            if time.monotonic() >= deadline:
                raise TimeoutError(f"timed out waiting for {lock_path} (holder: {holder})") from None
            time.sleep(LOCK_POLL_SECONDS)


def wait_for_lock(lock_path: Path, timeout_seconds: float) -> int:
    """Open *lock_path* and acquire it via :func:`wait_on_fd`.

    Returns the open fd (caller must close it to release). Closes the fd
    before raising TimeoutError.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        wait_on_fd(fd, lock_path, timeout_seconds)
    except TimeoutError:
        os.close(fd)
        raise
    return fd


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True, timeout=60)
    return proc.stdout


def repo_toplevel(cwd: Path) -> Path:
    return Path(_git(cwd, "rev-parse", "--show-toplevel").strip())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_identity(repo: Path) -> dict:
    """Exact validated-input identity for *repo*. Raises IdentityUnknown."""
    try:
        head = _git(repo, "rev-parse", "HEAD").strip()
        base = _git(repo, "rev-parse", "origin/develop").strip()
        porcelain = _git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise IdentityUnknown(f"git identity failed: {exc}") from exc
    untracked = sorted(line[3:] for line in porcelain if line.startswith("?? "))
    if len(untracked) > MAX_UNTRACKED_FILES:
        raise IdentityUnknown(f"{len(untracked)} untracked files exceed bound")
    digests: dict[str, str] = {}
    total = 0
    for name in untracked:
        path = repo / name
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise IdentityUnknown(f"cannot stat untracked {name}: {exc}") from exc
        total += size
        if total > MAX_UNTRACKED_BYTES:
            raise IdentityUnknown("untracked bytes exceed bound")
        try:
            digests[name] = _sha256_file(path)
        except OSError as exc:
            raise IdentityUnknown(f"cannot hash untracked {name}: {exc}") from exc
    uv_lock = repo / "uv.lock"
    try:
        lock_digest: str | None = _sha256_file(uv_lock) if uv_lock.is_file() else None
    except OSError as exc:
        raise IdentityUnknown(f"cannot hash uv.lock: {exc}") from exc
    return {
        "head": head,
        "base": base,
        "porcelain": sorted(porcelain),
        "untracked_digests": digests,
        "python": sys.version.split()[0],
        "uv_lock": lock_digest,
    }


def store_dir(repo: Path) -> Path:
    override = os.environ.get("BENCHBOX_VALIDATION_RECEIPTS_DIR")
    if override:
        return Path(override).expanduser()
    slug = hashlib.sha1(str(repo.resolve()).encode()).hexdigest()[:16]
    return Path.home() / ".benchbox" / "validation-receipts" / slug


def receipt_path(store: Path, gate: str, identity: dict, batch: dict | None) -> Path:
    canonical = json.dumps({"gate": gate, "identity": identity, "batch": batch}, sort_keys=True, separators=(",", ":"))
    return store / (hashlib.sha256(canonical.encode()).hexdigest() + ".json")


def read_receipt(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("exit") == 0 else None


def run_gate(
    gate: str,
    argv: list[str],
    batch: dict | None,
    lock_wait_seconds: float,
    repo: Path,
    store: Path,
) -> int:
    """Run *argv* under the singleflight receipt contract. Returns its exit code."""
    try:
        identity = content_identity(repo)
    except IdentityUnknown as exc:
        print(f"[local-validation] identity unknown ({exc}); executing without receipt")
        return subprocess.run(list(argv), cwd=repo, check=False).returncode
    receipt = receipt_path(store, gate, identity, batch)
    lock_fd = wait_for_lock(store / "store.lock", lock_wait_seconds)
    try:
        hit = read_receipt(receipt)
        if hit is not None:
            print(
                f"[local-validation] REUSED {gate} receipt "
                f"(head {identity['head'][:12]}, recorded {hit.get('recorded_at', '?')})"
            )
            return 0
        print(f"[local-validation] EXECUTING {gate}: {' '.join(argv)}")
        proc = subprocess.run(list(argv), cwd=repo, check=False)
        if proc.returncode == 0:
            tmp = receipt.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "gate": gate,
                        "identity": identity,
                        "batch": batch,
                        "exit": 0,
                        "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            tmp.replace(receipt)
        else:
            print(f"[local-validation] {gate} failed (exit {proc.returncode}); no receipt stored")
        return proc.returncode
    finally:
        os.close(lock_fd)


def show_gate(gate: str, batch: dict | None, repo: Path, store: Path) -> int:
    try:
        identity = content_identity(repo)
    except IdentityUnknown as exc:
        print(f"[local-validation] identity unknown ({exc})")
        return 2
    receipt = receipt_path(store, gate, identity, batch)
    hit = read_receipt(receipt)
    print(f"[local-validation] gate={gate} head={identity['head'][:12]} base={identity['base'][:12]}")
    print(f"[local-validation] receipt={'present' if hit is not None else 'absent'} ({receipt.name})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a gate unless an identical completed receipt exists")
    run.add_argument("--gate", required=True, help="exact gate name (receipt namespace)")
    run.add_argument("--batch-id", default=None)
    run.add_argument("--batch-member", default=None)
    run.add_argument("--batch-role", default=None, choices=["member", "integrator"])
    run.add_argument(
        "--lock-wait-seconds",
        type=float,
        default=DEFAULT_LOCK_WAIT_SECONDS,
        help="how long a contended identical request waits for the winner",
    )
    run.add_argument("argv", nargs=argparse.REMAINDER, help="gate command after --")
    show = sub.add_parser("show", help="report current identity and receipt status")
    show.add_argument("--gate", required=True)
    show.add_argument("--batch-id", default=None)
    show.add_argument("--batch-member", default=None)
    show.add_argument("--batch-role", default=None, choices=["member", "integrator"])
    return parser


def batch_block(args: argparse.Namespace) -> dict | None:
    if not args.batch_id and not args.batch_member and not args.batch_role:
        return None
    return {"batch_id": args.batch_id, "member": args.batch_member, "role": args.batch_role}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = repo_toplevel(Path.cwd())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("[local-validation] not inside a git repository", file=sys.stderr)
        return 2
    store = store_dir(repo)
    batch = batch_block(args)
    if args.command == "show":
        return show_gate(args.gate, batch, repo, store)
    cmd = list(args.argv)
    if cmd and cmd[0] == "--":
        cmd = cmd[1:]
    if not cmd:
        print("[local-validation] run requires a command after --", file=sys.stderr)
        return 2
    try:
        return run_gate(args.gate, cmd, batch, args.lock_wait_seconds, repo, store)
    except TimeoutError as exc:
        print(f"[local-validation] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
