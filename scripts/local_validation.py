#!/usr/bin/env python3
"""Serialize local validation gates and coalesce duplicate same-input runs.

Two agents (or two worktrees) often invoke the same local gate against the
same tree within minutes of each other. The second invocation historically
collided on the shared test lock and retried in a lock-error loop. This tool
makes that case cheap and honest:

* Identical validated inputs reuse a completed receipt instead of executing.
* Anything else (unknown identity, changed files/ref/tool, incomplete or
  failed prior run, different gate) executes.
* Concurrent identical requests serialize on a per-receipt lock: the waiter
  re-checks after acquiring and reuses the winner's receipt, so simultaneous
  identical requests execute once while unrelated gates proceed in parallel.

Receipts never certify hosted required checks and never transfer across
changed integration trees: the worktree HEAD, status, base ref, and tool
versions are all part of the identity. A failed prior run leaves no receipt,
so failures always re-execute.

Usage:
  python scripts/local_validation.py run --gate pr-preflight-fast -- make pr-preflight-fast-tests
  python scripts/local_validation.py run --gate member-check --batch-id B --batch-member M --batch-role member -- pytest tests/unit -q
  python scripts/local_validation.py ordered --focused-cmd 'pytest -m fast -q' --preflight-cmd 'make pr-preflight'
  python scripts/local_validation.py show --gate pr-preflight-fast
  python scripts/local_validation.py clear-test-lock ~/.benchbox/test.lock
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
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
MAX_IDENTITY_RETRIES = 3

# These files affect local gate behavior even when a gate command does not
# mention them directly.  Their content is recorded separately from the
# changed-file list so a receipt cannot outlive a local configuration edit.
VALIDATION_CONFIG_FILES = (
    ".pre-commit-config.yaml",
    "Makefile",
    "pyproject.toml",
    "pytest.ini",
    "ruff.toml",
    "setup.cfg",
    "tox.ini",
    "uv.lock",
)


class IdentityUnknown(Exception):
    """The working-tree identity cannot be established exactly."""


def read_holder(lock_path: Path) -> str:
    """Best-effort holder description for wait/timeout messages."""
    try:
        return lock_path.read_text(encoding="utf-8").strip() or "(empty lock file)"
    except OSError:
        return "(could not read lock file)"


def write_holder(fd: int, lock_path: Path, *, phase: str, gate: str | None = None) -> None:
    """Publish bounded owner/progress information while holding *fd*.

    The kernel lock, rather than this text, is the liveness authority.  The
    text is only diagnostic and is deliberately best effort so a read-only or
    unusual filesystem cannot turn a valid lock into a bypass.
    """
    started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    command = " ".join(shlex.quote(part) for part in sys.argv[:8])
    details = f" phase:{phase}"
    if gate:
        details += f" gate:{gate}"
    payload = f"pid:{os.getpid()} started:{started}{details} cmd:{command}\n".encode()
    try:
        os.ftruncate(fd, 0)
        os.lseek(fd, 0, os.SEEK_SET)
        os.write(fd, payload)
    except OSError:
        pass


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
            time.sleep(min(LOCK_POLL_SECONDS, max(0.0, deadline - time.monotonic())))


def wait_for_lock(lock_path: Path, timeout_seconds: float) -> int:
    """Open *lock_path* and acquire it via :func:`wait_on_fd`.

    Returns the open fd (caller must close it to release). Closes the fd
    before raising TimeoutError.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        wait_on_fd(fd, lock_path, timeout_seconds)
    except BaseException:
        os.close(fd)
        raise
    return fd


def clear_inactive_lock(lock_path: Path) -> int:
    """Remove only an inactive diagnostic lock file.

    The non-blocking kernel lock is authoritative; stale text alone never
    grants permission to remove the path.  Active holders are left untouched.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError):
            print(f"[local-validation] active lock retained: {lock_path}", file=sys.stderr)
            return 1
        try:
            os.unlink(lock_path)
        except FileNotFoundError:
            pass
        print(f"[local-validation] removed inactive lock: {lock_path}")
        return 0
    finally:
        os.close(fd)


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


def _tool_version(executable: str) -> str:
    """Return a stable version string, or raise when the tool is unavailable."""
    try:
        proc = subprocess.run(
            [executable, "--version"],
            check=True,
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise IdentityUnknown(f"cannot determine {executable} version: {exc}") from exc
    version = (proc.stdout or proc.stderr).strip().splitlines()
    if not version:
        raise IdentityUnknown(f"{executable} returned no version")
    return version[0]


def _command_tools(argv: list[str]) -> list[str]:
    """Find executables whose versions can affect a local command.

    The command itself remains part of the identity.  Version probing is
    intentionally limited to the command's executable and wrappers commonly
    used by this repository, avoiding unrelated ambient-tool drift.
    """
    if not argv:
        return []
    candidates = [Path(argv[0]).name]
    if candidates[0] in {"uv", "make"}:
        candidates.append("python3")
    return list(dict.fromkeys(candidates))


def _hash_bounded(repo: Path, names: list[str], kind: str, budget: list) -> dict[str, str]:
    """Content digests under shared file/byte bounds; raises IdentityUnknown."""
    if len(names) > MAX_UNTRACKED_FILES:
        raise IdentityUnknown(f"{len(names)} {kind} files exceed bound")
    digests: dict[str, str] = {}
    for name in names:
        path = repo / name
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise IdentityUnknown(f"cannot stat {kind} {name}: {exc}") from exc
        budget[0] += size
        if budget[0] > MAX_UNTRACKED_BYTES:
            raise IdentityUnknown(f"{kind} bytes exceed bound")
        try:
            digests[name] = _sha256_file(path)
        except OSError as exc:
            raise IdentityUnknown(f"cannot hash {kind} {name}: {exc}") from exc
    return digests


def tracked_modified(porcelain: list[str]) -> list[str]:
    """Worktree-relative paths of tracked files with any staged/unstaged change."""
    names = []
    for line in porcelain:
        if line.startswith("?? ") or len(line) < 4:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        names.append(raw.strip().strip('"'))
    return sorted(set(names))


def content_identity(repo: Path, argv: list[str]) -> dict:
    """Exact validated-input identity for *repo* and command *argv*.

    Raises IdentityUnknown. Tracked modifications are content-hashed (porcelain
    status text alone cannot see edits to an already-dirty file), and the exact
    command is part of the key so a stronger command under the same gate name
    never reuses a weaker command's receipt.
    """
    try:
        head = _git(repo, "rev-parse", "HEAD").strip()
        base = _git(repo, "rev-parse", "origin/develop").strip()
        porcelain = _git(repo, "status", "--porcelain=v1", "--untracked-files=all").splitlines()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise IdentityUnknown(f"git identity failed: {exc}") from exc
    untracked = sorted(line[3:] for line in porcelain if line.startswith("?? "))
    budget = [0]
    digests = _hash_bounded(repo, untracked, "untracked", budget)
    tracked = _hash_bounded(repo, tracked_modified(porcelain), "tracked-modified", budget)
    uv_lock = repo / "uv.lock"
    try:
        lock_digest: str | None = _sha256_file(uv_lock) if uv_lock.is_file() else None
    except OSError as exc:
        raise IdentityUnknown(f"cannot hash uv.lock: {exc}") from exc
    config_digests: dict[str, str | None] = {}
    for name in VALIDATION_CONFIG_FILES:
        path = repo / name
        if path.is_file():
            try:
                config_digests[name] = _sha256_file(path)
            except OSError as exc:
                raise IdentityUnknown(f"cannot hash validation config {name}: {exc}") from exc
        else:
            config_digests[name] = None
    tool_versions = {tool: _tool_version(tool) for tool in _command_tools(argv)}
    return {
        "head": head,
        "base": base,
        "porcelain": sorted(porcelain),
        "untracked_digests": digests,
        "tracked_digests": tracked,
        "argv": [str(part) for part in argv],
        "python": sys.version.split()[0],
        "uv_lock": lock_digest,
        "validation_config": config_digests,
        "tool_versions": tool_versions,
    }


def store_dir(repo: Path) -> Path:
    """Content-shared receipt store: identity already binds head/base SHAs,
    tree digests, argv, interpreter, and lockfile, so identical validated
    inputs coalesce across worktrees instead of re-executing per clone."""
    override = os.environ.get("BENCHBOX_VALIDATION_RECEIPTS_DIR")
    if override:
        return Path(override).expanduser()
    _ = repo
    return Path.home() / ".benchbox" / "validation-receipts" / "shared"


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
        identity = content_identity(repo, list(argv))
    except IdentityUnknown as exc:
        print(f"[local-validation] identity unknown ({exc}); executing without receipt")
        return subprocess.run(list(argv), cwd=repo, check=False).returncode
    for attempt in range(MAX_IDENTITY_RETRIES):
        receipt = receipt_path(store, gate, identity, batch)
        lock_path = receipt.with_name(receipt.stem + ".lock")
        lock_fd = wait_for_lock(lock_path, lock_wait_seconds)
        try:
            # The tree may have changed while waiting.  Never reuse a receipt
            # or execute against the old key after that race; move to the new
            # receipt namespace while retaining the bounded lock wait.
            current_unknown = False
            try:
                current = content_identity(repo, list(argv))
            except IdentityUnknown as exc:
                print(f"[local-validation] identity changed to unknown ({exc}); executing without receipt")
                current = None
                current_unknown = True
            if current is not None and current != identity:
                identity = current
                continue
            write_holder(lock_fd, lock_path, phase="checking", gate=gate)
            hit = None if current_unknown else read_receipt(receipt)
            if hit is not None:
                print(
                    f"[local-validation] REUSED {gate} receipt "
                    f"(head {identity['head'][:12]}, recorded {hit.get('recorded_at', '?')})"
                )
                return 0
            write_holder(lock_fd, lock_path, phase="executing", gate=gate)
            print(f"[local-validation] EXECUTING {gate}: {' '.join(argv)}")
            proc = subprocess.run(list(argv), cwd=repo, check=False)
            if proc.returncode == 0:
                try:
                    final_identity = content_identity(repo, list(argv))
                except IdentityUnknown as exc:
                    final_identity = None
                    print(f"[local-validation] identity became unknown ({exc}); no receipt stored")
                if not current_unknown and final_identity == identity:
                    tmp = receipt.with_suffix(f".{os.getpid()}.tmp")
                    tmp.write_text(
                        json.dumps(
                            {
                                "schema": 2,
                                "gate": gate,
                                "identity": identity,
                                "batch": batch,
                                "delivery": {
                                    "member_preparation_is_not_integration_certification": True,
                                    "role": (batch or {}).get("role") if batch else None,
                                    "integration_identity": {
                                        key: (batch or {}).get(key)
                                        for key in (
                                            "source_base",
                                            "source_head",
                                            "integration_head",
                                            "integration_tree",
                                            "accepted_head",
                                            "scope_hash",
                                            "config_hash",
                                            "changed_paths",
                                        )
                                        if batch and (batch or {}).get(key) is not None
                                    },
                                },
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
                    print("[local-validation] inputs changed during execution; no receipt stored")
            else:
                print(f"[local-validation] {gate} failed (exit {proc.returncode}); no receipt stored")
            return proc.returncode
        finally:
            os.close(lock_fd)
    # A continuously changing tree cannot safely produce reusable evidence.
    # Execute once without a receipt instead of spinning or reusing stale data.
    print("[local-validation] inputs changed repeatedly; executing without receipt")
    return subprocess.run(list(argv), cwd=repo, check=False).returncode


def show_gate(gate: str, batch: dict | None, repo: Path, store: Path, argv: list[str] | None = None) -> int:
    try:
        identity = content_identity(repo, list(argv or []))
    except IdentityUnknown as exc:
        print(f"[local-validation] identity unknown ({exc})")
        return 2
    receipt = receipt_path(store, gate, identity, batch)
    hit = read_receipt(receipt)
    print(f"[local-validation] gate={gate} head={identity['head'][:12]} base={identity['base'][:12]}")
    print(f"[local-validation] receipt={'present' if hit is not None else 'absent'} ({receipt.name})")
    return 0


def run_ordered_path(
    *,
    focused_gate: str,
    focused_command: list[str],
    preflight_gate: str,
    preflight_command: list[str],
    batch: dict | None,
    lock_wait_seconds: float,
    repo: Path,
    store: Path,
) -> int:
    """Run the focused local gate before the required preflight gate.

    The two names are explicit receipt namespaces.  A preflight receipt can
    never stand in for the focused check, and a failed focused gate prevents
    the required path from being reported as complete.
    """
    focused_status = run_gate(focused_gate, focused_command, batch, lock_wait_seconds, repo, store)
    if focused_status != 0:
        return focused_status
    return run_gate(preflight_gate, preflight_command, batch, lock_wait_seconds, repo, store)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run a gate unless an identical completed receipt exists")
    run.add_argument("--gate", required=True, help="exact gate name (receipt namespace)")
    run.add_argument("--batch-id", default=None)
    run.add_argument("--batch-member", default=None)
    run.add_argument("--batch-role", default=None, choices=["member", "integrator"])
    for parser_arg in (run,):
        parser_arg.add_argument("--batch-source-base", default=None)
        parser_arg.add_argument("--batch-source-head", default=None)
        parser_arg.add_argument("--batch-integration-head", default=None)
        parser_arg.add_argument("--batch-integration-tree", default=None)
        parser_arg.add_argument("--batch-accepted-head", default=None)
        parser_arg.add_argument("--batch-scope-hash", default=None)
        parser_arg.add_argument("--batch-config-hash", default=None)
        parser_arg.add_argument("--batch-changed-paths", default=None)
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
    show.add_argument("--batch-source-base", default=None)
    show.add_argument("--batch-source-head", default=None)
    show.add_argument("--batch-integration-head", default=None)
    show.add_argument("--batch-integration-tree", default=None)
    show.add_argument("--batch-accepted-head", default=None)
    show.add_argument("--batch-scope-hash", default=None)
    show.add_argument("--batch-config-hash", default=None)
    show.add_argument("--batch-changed-paths", default=None)
    show.add_argument("argv", nargs=argparse.REMAINDER, help="gate command after -- (same as run)")
    ordered = sub.add_parser("ordered", help="run focused checks, then the required preflight")
    ordered.add_argument("--focused-gate", default="local-focused-check")
    ordered.add_argument("--focused-cmd", required=True)
    ordered.add_argument("--preflight-gate", default="required-pr-preflight")
    ordered.add_argument("--preflight-cmd", required=True)
    ordered.add_argument("--batch-id", default=None)
    ordered.add_argument("--batch-member", default=None)
    ordered.add_argument("--batch-role", default=None, choices=["member", "integrator"])
    ordered.add_argument("--batch-source-base", default=None)
    ordered.add_argument("--batch-source-head", default=None)
    ordered.add_argument("--batch-integration-head", default=None)
    ordered.add_argument("--batch-integration-tree", default=None)
    ordered.add_argument("--batch-accepted-head", default=None)
    ordered.add_argument("--batch-scope-hash", default=None)
    ordered.add_argument("--batch-config-hash", default=None)
    ordered.add_argument("--batch-changed-paths", default=None)
    ordered.add_argument("--lock-wait-seconds", type=float, default=DEFAULT_LOCK_WAIT_SECONDS)
    clear = sub.add_parser("clear-test-lock", help="remove an inactive shared test lock")
    clear.add_argument("path", type=Path)
    return parser


def batch_block(args: argparse.Namespace) -> dict | None:
    fields = {
        "batch_id": getattr(args, "batch_id", None),
        "member": getattr(args, "batch_member", None),
        "role": getattr(args, "batch_role", None),
        "source_base": getattr(args, "batch_source_base", None),
        "source_head": getattr(args, "batch_source_head", None),
        "integration_head": getattr(args, "batch_integration_head", None),
        "integration_tree": getattr(args, "batch_integration_tree", None),
        "accepted_head": getattr(args, "batch_accepted_head", None),
        "scope_hash": getattr(args, "batch_scope_hash", None),
        "config_hash": getattr(args, "batch_config_hash", None),
        "changed_paths": getattr(args, "batch_changed_paths", None),
    }
    if not any(value is not None for value in fields.values()):
        return None
    return fields


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        repo = repo_toplevel(Path.cwd())
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        print("[local-validation] not inside a git repository", file=sys.stderr)
        return 2
    store = store_dir(repo)
    batch = batch_block(args)
    if args.command == "clear-test-lock":
        return clear_inactive_lock(args.path)
    if args.command == "ordered":
        try:
            return run_ordered_path(
                focused_gate=args.focused_gate,
                focused_command=shlex.split(args.focused_cmd),
                preflight_gate=args.preflight_gate,
                preflight_command=shlex.split(args.preflight_cmd),
                batch=batch,
                lock_wait_seconds=args.lock_wait_seconds,
                repo=repo,
                store=store,
            )
        except TimeoutError as exc:
            print(f"[local-validation] {exc}", file=sys.stderr)
            return 1
    if args.command == "show":
        cmd = list(args.argv)
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]
        return show_gate(args.gate, batch, repo, store, cmd)
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
