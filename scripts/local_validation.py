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
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

# Bounds keep identity computation cheap; exceeding them means "unknown",
# which forces execution (fail open to running, never to false reuse).
MAX_UNTRACKED_FILES = 200
MAX_UNTRACKED_BYTES = 50 * 1024 * 1024
LOCK_POLL_SECONDS = 0.25
DEFAULT_LOCK_WAIT_SECONDS = 3600.0
MAX_IDENTITY_RETRIES = 3
MAX_ORDERED_RETRIES = 3
WAIT_PROGRESS_SECONDS = 5.0

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
VALIDATION_ENV_PREFIXES = ("BENCHBOX_", "PYTEST_", "PYTHON", "UV_", "PRE_COMMIT")
VALIDATION_ENV_KEYS = {"CI", "GITHUB_ACTIONS", "PATH", "VIRTUAL_ENV"}
RECEIPT_STORE_ENV = "BENCHBOX_VALIDATION_RECEIPTS_DIR"
MEMBER_BATCH_FIELDS = (
    "batch_id",
    "member",
    "role",
    "source_base",
    "source_head",
    "accepted_head",
    "scope_hash",
    "config_hash",
    "changed_paths",
)
INTEGRATOR_BATCH_FIELDS = (
    "batch_id",
    "role",
    "integration_head",
    "integration_tree",
    "predecessor_head",
    "predecessor_tree",
    "member_identity",
)
MEMBER_IDENTITY_FIELDS = frozenset(
    {"id", "source_base", "source_head", "accepted_head", "scope_hash", "config_hash", "changed_paths"}
)
MEMBER_IDENTITY_HASH_FIELDS = ("scope_hash", "config_hash")
ACCOUNTING_STATUSES = frozenset({"executed", "reused", "failed", "cancelled", "skipped", "ordered_success"})
ACCOUNTING_FIELDS = frozenset(
    {
        "schema",
        "event_kind",
        "event_id",
        "status",
        "gate",
        "identity_key",
        "batch",
        "started_at",
        "completed_at",
        "duration_seconds",
        "command_executions",
        "executed_count",
        "reused_count",
        "exit_code",
        "hosted_required_certification",
    }
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
    wait_started = time.monotonic()
    last_report = 0.0
    reported_wait = False
    holder = read_holder(lock_path)
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            if reported_wait:
                elapsed = time.monotonic() - wait_started
                print(f"[local-validation] acquired lock after waiting {elapsed:.1f}s: {lock_path}", file=sys.stderr)
            return
        except (BlockingIOError, OSError):
            holder = read_holder(lock_path)
            now = time.monotonic()
            if not reported_wait or now - last_report >= WAIT_PROGRESS_SECONDS:
                print(
                    f"[local-validation] waiting for lock {lock_path} (holder: {holder})", file=sys.stderr, flush=True
                )
                reported_wait = True
                last_report = now
            if now >= deadline:
                raise TimeoutError(f"timed out waiting for {lock_path} (holder: {holder})") from None
            time.sleep(min(LOCK_POLL_SECONDS, max(0.0, deadline - now)))


def wait_for_lock(lock_path: Path, timeout_seconds: float) -> int:
    """Open *lock_path* and acquire it via :func:`wait_on_fd`.

    Returns the open fd (caller must close it to release). Closes the fd
    before raising while waiting for the lock.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        wait_on_fd(fd, lock_path, timeout_seconds)
    except KeyboardInterrupt:
        print(f"[local-validation] lock wait cancelled: {lock_path}", file=sys.stderr, flush=True)
        os.close(fd)
        raise
    except BaseException:
        os.close(fd)
        raise
    return fd


def clear_inactive_lock(lock_path: Path) -> int:
    """Clear inactive diagnostic text without unlinking the lock pathname."""
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
        os.ftruncate(fd, 0)
        print(f"[local-validation] cleared inactive lock: {lock_path}")
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


def _tool_identity(executable: str) -> dict[str, str]:
    """Resolve the exact executable and record its version."""
    resolved = shutil.which(executable) if not os.path.isabs(executable) else executable
    if not resolved:
        raise IdentityUnknown(f"cannot resolve executable: {executable}")
    resolved = str(Path(resolved).resolve())
    try:
        proc = subprocess.run(
            [resolved, "--version"],
            check=True,
            text=True,
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise IdentityUnknown(f"cannot determine {resolved} version: {exc}") from exc
    version = (proc.stdout or proc.stderr).strip().splitlines()
    if not version:
        raise IdentityUnknown(f"{resolved} returned no version")
    return {"path": resolved, "version": version[0]}


def _command_tools(argv: list[str]) -> list[str]:
    """Find executables whose versions can affect a local command.

    The command itself remains part of the identity.  Version probing is
    intentionally limited to the command's executable and wrappers commonly
    used by this repository, avoiding unrelated ambient-tool drift.
    """
    if not argv:
        return []
    candidates = [argv[0]]
    executable = Path(argv[0]).name
    if executable == "make":
        candidates.extend(("uv", "pre-commit", "pytest", "ruff"))
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


def active_skill_mirror_identity(repo: Path, budget: list) -> dict:
    """Digest the ignored active skill mirror when it is present.

    The mirror is intentionally untracked, so Git porcelain cannot contribute
    it to receipt identity. A validation run that reads the mirror must not be
    reused in a checkout where the mirror is absent or has different bytes.
    """
    root = repo / ".agents" / "skills"
    if not root.is_dir():
        return {"present": False}
    names = sorted(path.relative_to(repo).as_posix() for path in root.rglob("*") if path.is_file())
    return {"present": True, "files": _hash_bounded(repo, names, "active skill mirror", budget)}


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


def _config_digests(repo: Path) -> dict[str, str | None]:
    digests: dict[str, str | None] = {}
    for name in VALIDATION_CONFIG_FILES:
        path = repo / name
        if path.is_file():
            try:
                digests[name] = _sha256_file(path)
            except OSError as exc:
                raise IdentityUnknown(f"cannot hash validation config {name}: {exc}") from exc
        else:
            digests[name] = None
    return digests


def _environment_identity() -> dict[str, str]:
    """Hash gate-relevant environment values without persisting raw secrets.

    ``BENCHBOX_VALIDATION_RECEIPTS_DIR`` is intentionally excluded: it selects
    the local evidence store and does not change gate behavior; including it
    would also make the receipt key depend on the store that contains it.
    """
    selected: dict[str, str] = {}
    for key, value in os.environ.items():
        if key == RECEIPT_STORE_ENV:
            continue
        if key in VALIDATION_ENV_KEYS or key.startswith(VALIDATION_ENV_PREFIXES):
            selected[key] = hashlib.sha256(value.encode()).hexdigest()
    return selected


def _canonical_paths(value: object) -> list[str]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value) if value.lstrip().startswith("[") else value.split(",")
        except json.JSONDecodeError as exc:
            raise IdentityUnknown(f"invalid changed_paths JSON: {exc}") from exc
    else:
        parsed = value
    if not isinstance(parsed, (list, tuple)):
        raise IdentityUnknown("changed_paths must be a list or comma-separated string")
    result: set[str] = set()
    for raw in parsed:
        if not isinstance(raw, str) or not raw.strip():
            raise IdentityUnknown("changed_paths entries must be non-empty strings")
        path = raw.strip().replace("\\", "/")
        normalized = PurePosixPath(path)
        if normalized.is_absolute() or ".." in normalized.parts or path == ".":
            raise IdentityUnknown(f"changed_paths contains unsafe path: {raw!r}")
        result.add(normalized.as_posix())
    return sorted(result)


def _batch_config_hash(repo: Path) -> str:
    canonical = json.dumps(_config_digests(repo), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _batch_config_hash_at_commit(repo: Path, revision: str) -> str:
    digests: dict[str, str | None] = {}
    for name in VALIDATION_CONFIG_FILES:
        try:
            payload = subprocess.run(
                ["git", "show", f"{revision}:{name}"],
                cwd=repo,
                check=True,
                capture_output=True,
                timeout=60,
            ).stdout
        except subprocess.CalledProcessError:
            digests[name] = None
        except subprocess.TimeoutExpired as exc:
            raise IdentityUnknown(f"cannot read config {name} at {revision}: {exc}") from exc
        else:
            digests[name] = hashlib.sha256(payload).hexdigest()
    canonical = json.dumps(digests, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _git_diff_paths(repo: Path, base: str, head: str) -> list[str]:
    """Return canonical changed paths, retaining both sides of renames."""
    try:
        output = _git(repo, "diff", "--name-status", "-z", "-M", f"{base}...{head}")
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise IdentityUnknown(f"cannot derive source scope: {exc}") from exc
    fields = output.split("\0")
    paths: list[str] = []
    index = 0
    while index < len(fields) - 1:
        status = fields[index]
        index += 1
        if not status:
            continue
        path_count = 2 if status[0] in {"R", "C"} else 1
        paths.extend(fields[index : index + path_count])
        index += path_count
    try:
        return _canonical_paths(paths)
    except IdentityUnknown as exc:
        raise IdentityUnknown(f"cannot canonicalize source scope: {exc}") from exc


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _canonical_member_record(repo: Path, raw: object, integration_head: str) -> tuple[dict | None, str]:
    if not isinstance(raw, dict):
        return None, "integrator member_identity entries must be objects"
    if set(raw) != MEMBER_IDENTITY_FIELDS:
        return None, f"integrated member identity fields must be exactly {sorted(MEMBER_IDENTITY_FIELDS)}"
    member_id = raw.get("id")
    if not isinstance(member_id, str) or not member_id.strip():
        return None, "integrated member identity requires a non-empty id"
    heads: dict[str, str] = {}
    for field in ("source_base", "source_head", "accepted_head"):
        ref = raw.get(field)
        try:
            resolved = _git(repo, "rev-parse", f"{ref}^{{commit}}").strip()
            if field != "source_base":
                _git(repo, "merge-base", "--is-ancestor", resolved, integration_head)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return None, f"integrated member {member_id} has invalid {field}: {exc}"
        heads[field] = resolved
    try:
        _git(repo, "merge-base", "--is-ancestor", heads["source_base"], heads["source_head"])
        _git(repo, "merge-base", "--is-ancestor", heads["source_base"], heads["accepted_head"])
        source_paths = _git_diff_paths(repo, heads["source_base"], heads["source_head"])
        accepted_paths = _git_diff_paths(repo, heads["source_base"], heads["accepted_head"])
    except (IdentityUnknown, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return None, f"integrated member {member_id} has invalid source scope: {exc}"
    for field in MEMBER_IDENTITY_HASH_FIELDS:
        if not _is_sha256(raw.get(field)):
            return None, f"integrated member {member_id} requires a SHA-256 {field}"
    try:
        changed_paths = _canonical_paths(raw["changed_paths"])
    except IdentityUnknown as exc:
        return None, f"integrated member {member_id} has invalid changed_paths: {exc}"
    if changed_paths != source_paths or changed_paths != accepted_paths:
        return None, f"integrated member {member_id} changed_paths do not match source scope"
    expected_scope = hashlib.sha256(json.dumps(changed_paths, separators=(",", ":")).encode()).hexdigest()
    if str(raw["scope_hash"]).lower() != expected_scope:
        return None, f"integrated member {member_id} scope_hash does not match source scope"
    try:
        expected_config = _batch_config_hash_at_commit(repo, heads["accepted_head"])
    except IdentityUnknown as exc:
        return None, f"integrated member {member_id} config identity is unknown: {exc}"
    if str(raw["config_hash"]).lower() != expected_config:
        return None, f"integrated member {member_id} config_hash does not match accepted head"
    record = dict(raw)
    record.update(heads)
    for field in MEMBER_IDENTITY_HASH_FIELDS:
        record[field] = str(record[field]).lower()
    record["changed_paths"] = changed_paths
    return {key: record[key] for key in sorted(record)}, ""


def _canonical_member_identity(repo: Path, value: object) -> tuple[list[dict] | None, str]:
    if not isinstance(value, (list, tuple)) or not value:
        return None, "integrator member_identity must be a non-empty JSON list"
    try:
        integration_head = _git(repo, "rev-parse", "HEAD^{commit}").strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return None, f"cannot resolve integration head: {exc}"
    canonical: list[dict] = []
    seen: set[str] = set()
    for raw in value:
        record, reason = _canonical_member_record(repo, raw, integration_head)
        if reason:
            return None, reason
        assert record is not None
        if record["id"] in seen:
            return None, f"duplicate integrated member id: {record['id']}"
        seen.add(record["id"])
        canonical.append(record)
    canonical.sort(key=lambda record: record["id"])
    return canonical, ""


def _prepare_batch(repo: Path, batch: dict | None) -> tuple[dict | None, str]:
    if batch is None:
        return None, ""
    if not isinstance(batch, dict):
        return None, "batch metadata must be an object"
    normalized = dict(batch)
    role = normalized.get("role")
    try:
        if role == "member":
            normalized["changed_paths"] = _canonical_paths(normalized["changed_paths"])
        elif role == "integrator":
            normalized["member_identity"], reason = _canonical_member_identity(repo, normalized["member_identity"])
            if reason:
                return None, reason
            if normalized.get("predecessor_head") not in (None, ""):
                normalized["predecessor_head"] = _git(
                    repo, "rev-parse", f"{normalized['predecessor_head']}^{{commit}}"
                ).strip()
        else:
            return None, "batch role must be member or integrator"
    except (KeyError, IdentityUnknown, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return None, str(exc)
    return normalized, ""


def _validate_member_batch(repo: Path, batch: dict) -> tuple[bool, str]:
    missing = [field for field in MEMBER_BATCH_FIELDS if batch.get(field) in (None, "")]
    if missing:
        return False, f"member batch metadata missing: {', '.join(missing)}"
    try:
        if _git(repo, "status", "--porcelain=v1", "--untracked-files=all").strip():
            return False, "member batch evidence requires a clean checkout"
        changed_paths = _canonical_paths(batch["changed_paths"])
        head = _git(repo, "rev-parse", "HEAD").strip()
        base = _git(repo, "rev-parse", "origin/develop").strip()
        _git(repo, "merge-base", "--is-ancestor", batch["source_base"], batch["source_head"])
        actual_paths = _git_diff_paths(repo, batch["source_base"], batch["source_head"])
    except (IdentityUnknown, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if batch["source_head"] != head or batch["accepted_head"] != head:
        return False, "member source/accepted head does not match current HEAD"
    if batch["source_base"] != base:
        return False, "member source base does not match origin/develop"
    if changed_paths != actual_paths:
        return False, "member changed_paths do not match source base to head diff"
    expected_scope = hashlib.sha256(json.dumps(changed_paths, separators=(",", ":")).encode()).hexdigest()
    if batch["scope_hash"] != expected_scope:
        return False, "member scope hash does not match canonical changed paths"
    try:
        expected_config = _batch_config_hash(repo)
    except IdentityUnknown as exc:
        return False, str(exc)
    if batch["config_hash"] != expected_config:
        return False, "member config hash does not match validation config"
    return True, ""


def _validate_integrator_batch(repo: Path, batch: dict) -> tuple[bool, str]:
    missing = [field for field in INTEGRATOR_BATCH_FIELDS if batch.get(field) in (None, "")]
    if missing:
        return False, f"integrator batch metadata missing: {', '.join(missing)}"
    try:
        if _git(repo, "status", "--porcelain=v1", "--untracked-files=all").strip():
            return False, "integrator batch evidence requires a clean checkout"
        head = _git(repo, "rev-parse", "HEAD").strip()
        tree = _git(repo, "rev-parse", "HEAD^{tree}").strip()
        predecessor = _git(repo, "rev-parse", f"{batch['predecessor_head']}^{{commit}}").strip()
        predecessor_tree = _git(repo, "rev-parse", f"{predecessor}^{{tree}}").strip()
        _git(repo, "merge-base", "--is-ancestor", predecessor, head)
    except subprocess.CalledProcessError as exc:
        return False, f"invalid integrator revision: {exc}"
    except (subprocess.TimeoutExpired, IdentityUnknown) as exc:
        return False, str(exc)
    if batch["integration_head"] != head:
        return False, "integrator integration head does not match current HEAD"
    if predecessor == head:
        return False, "integrator predecessor must be a real prior head"
    if batch["integration_tree"] != tree:
        return False, "integrator integration tree does not match current HEAD tree"
    if batch["predecessor_tree"] != predecessor_tree:
        return False, "integrator predecessor tree does not match predecessor head"
    member_identity = batch["member_identity"]
    if not isinstance(member_identity, list) or not member_identity:
        return False, "integrator member identity is not a canonical non-empty list"
    return True, ""


def validate_batch(repo: Path, batch: dict | None) -> tuple[bool, str]:
    """Validate role-specific delivery metadata against the current checkout."""
    normalized, reason = _prepare_batch(repo, batch)
    if reason:
        return False, reason
    return _validate_prepared_batch(repo, normalized)


def _validate_prepared_batch(repo: Path, normalized: dict | None) -> tuple[bool, str]:
    if normalized is None:
        return True, ""
    if normalized.get("role") == "member":
        return _validate_member_batch(repo, normalized)
    if normalized.get("role") == "integrator":
        return _validate_integrator_batch(repo, normalized)
    return False, "batch role must be member or integrator"


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
    active_mirror = active_skill_mirror_identity(repo, budget)
    uv_lock = repo / "uv.lock"
    try:
        lock_digest: str | None = _sha256_file(uv_lock) if uv_lock.is_file() else None
    except OSError as exc:
        raise IdentityUnknown(f"cannot hash uv.lock: {exc}") from exc
    config_digests = _config_digests(repo)
    tool_versions = {tool: _tool_identity(tool) for tool in _command_tools(argv)}
    environment = _environment_identity()
    return {
        "head": head,
        "base": base,
        "porcelain": sorted(porcelain),
        "untracked_digests": digests,
        "tracked_digests": tracked,
        "active_skill_mirror": active_mirror,
        "argv": [str(part) for part in argv],
        "python": sys.version.split()[0],
        "uv_lock": lock_digest,
        "validation_config": config_digests,
        "tool_versions": tool_versions,
        "environment": environment,
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


def read_receipt(path: Path, *, gate: str, identity: dict, batch: dict | None) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("schema") != 2 or data.get("gate") != gate or data.get("exit") != 0:
        return None
    if data.get("identity") != identity or data.get("batch") != batch:
        return None
    delivery = data.get("delivery")
    if (
        not isinstance(delivery, dict)
        or delivery.get("member_preparation_is_not_integration_certification") is not True
        or delivery.get("role") != ((batch or {}).get("role") if batch else None)
        or delivery.get("integration_identity") != batch
    ):
        return None
    return data


def _identity_key(gate: str, identity: dict | None, batch: dict | None) -> str | None:
    if identity is None:
        return None
    payload = json.dumps(
        {"gate": gate, "identity": identity, "batch": batch}, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _event_batch(batch: dict | None) -> dict | None:
    """Return only validated delivery identity; never persist caller input."""
    if batch is None:
        return None
    role = batch.get("role") if isinstance(batch, dict) else None
    fields = MEMBER_BATCH_FIELDS if role == "member" else INTEGRATOR_BATCH_FIELDS if role == "integrator" else ()
    if not fields or set(batch) != set(fields):
        return None
    result = {field: batch[field] for field in fields if field != "member_identity"}
    if role == "integrator":
        members = batch.get("member_identity")
        if not isinstance(members, list) or any(not isinstance(member, dict) for member in members):
            return None
        member_fields = sorted(MEMBER_IDENTITY_FIELDS)
        if any(set(member) != set(member_fields) for member in members):
            return None
        result["member_identity"] = [
            {field: member[field] for field in member_fields} for member in sorted(members, key=lambda item: item["id"])
        ]
    return result


def _valid_event_batch(batch: object) -> bool:
    if batch is None:
        return True
    if not isinstance(batch, dict) or batch.get("role") not in {"member", "integrator"}:
        return False
    fields = MEMBER_BATCH_FIELDS if batch["role"] == "member" else INTEGRATOR_BATCH_FIELDS
    if set(batch) != set(fields) or not isinstance(batch.get("batch_id"), str) or not batch["batch_id"]:
        return False
    if batch["role"] == "integrator":
        members = batch.get("member_identity")
        return (
            isinstance(members, list)
            and bool(members)
            and all(isinstance(member, dict) and set(member) == MEMBER_IDENTITY_FIELDS for member in members)
        )
    return isinstance(batch.get("member"), str) and bool(batch["member"])


def _valid_event(event: object) -> bool:
    if not isinstance(event, dict) or set(event) - ACCOUNTING_FIELDS - {"stages"}:
        return False
    if event.get("schema") != 2 or event.get("status") not in ACCOUNTING_STATUSES:
        return False
    kind = event.get("event_kind")
    expected = ACCOUNTING_FIELDS | ({"stages"} if kind == "ordered" else set())
    if kind not in {"gate", "ordered"} or set(event) != expected:
        return False
    if kind == "gate" and event["status"] == "ordered_success":
        return False
    if kind == "ordered" and event["status"] != "ordered_success":
        return False
    if not isinstance(event.get("event_id"), str) or not event["event_id"]:
        return False
    if not isinstance(event.get("gate"), str) or not event["gate"]:
        return False
    identity_key = event.get("identity_key")
    if identity_key is not None and (not isinstance(identity_key, str) or len(identity_key) != 64):
        return False
    if not _valid_event_batch(event.get("batch")):
        return False
    if not all(isinstance(event.get(field), str) and event[field] for field in ("started_at", "completed_at")):
        return False
    duration = event.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration < 0:
        return False
    counts = (event.get("command_executions"), event.get("executed_count"), event.get("reused_count"))
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts):
        return False
    if event.get("hosted_required_certification") is not False:
        return False
    if event["event_kind"] == "gate":
        expected_counts = (1, 0) if event["status"] == "executed" else (0, 1) if event["status"] == "reused" else (0, 0)
        if (event["executed_count"], event["reused_count"]) != expected_counts:
            return False
        expected_commands = {
            "executed": {1},
            "reused": {0},
            "failed": {1},
            "cancelled": {0, 1},
            "skipped": {0},
        }[event["status"]]
        return event["command_executions"] in expected_commands
    stages = event.get("stages")
    if not isinstance(stages, list) or len(stages) != 2:
        return False
    stage_fields = {"gate", "status", "identity_key", "argv", "tool_versions", "command_executions"}
    if any(
        not isinstance(stage, dict)
        or set(stage) != stage_fields
        or stage["status"] not in {"executed", "reused"}
        or not isinstance(stage["gate"], str)
        or not isinstance(stage["identity_key"], str)
        or len(stage["identity_key"]) != 64
        or not isinstance(stage["argv"], list)
        or not all(isinstance(part, str) for part in stage["argv"])
        or not isinstance(stage["tool_versions"], dict)
        or not all(
            isinstance(value, dict)
            and set(value) == {"path", "version"}
            and all(isinstance(item, str) and item for item in value.values())
            for value in stage["tool_versions"].values()
        )
        or isinstance(stage["command_executions"], bool)
        or not isinstance(stage["command_executions"], int)
        or stage["command_executions"] < 0
        or stage["command_executions"] != (1 if stage["status"] == "executed" else 0)
        for stage in stages
    ):
        return False
    return (
        event["command_executions"] == sum(stage["command_executions"] for stage in stages)
        and event["executed_count"] == sum(stage["status"] == "executed" for stage in stages)
        and event["reused_count"] == sum(stage["status"] == "reused" for stage in stages)
    )


def _append_accounting_event(
    store: Path,
    *,
    status: str,
    gate: str,
    identity: dict | None,
    batch: dict | None,
    started_at: str,
    completed_at: str,
    duration_seconds: float,
    command_executions: int,
    exit_code: int | None,
    reason: str | None = None,
    lock_wait_seconds: float = 5.0,
) -> None:
    """Append one immutable local accounting event; accounting never gates execution."""
    safe_batch = _event_batch(batch)
    event = {
        "schema": 2,
        "event_kind": "gate",
        "event_id": f"{os.getpid()}-{time.time_ns()}",
        "status": status,
        "gate": gate,
        "identity_key": _identity_key(gate, identity, batch),
        "batch": safe_batch,
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_seconds": round(max(0.0, duration_seconds), 6),
        "command_executions": command_executions,
        "executed_count": 1 if status == "executed" else 0,
        "reused_count": 1 if status == "reused" else 0,
        "exit_code": exit_code,
        "hosted_required_certification": False,
    }
    if not _valid_event(event):
        return
    lock_fd: int | None = None
    try:
        store.mkdir(parents=True, exist_ok=True)
        lock_fd = wait_for_lock(store / "events.lock", lock_wait_seconds)
        path = store / "events.jsonl"
        line = (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd = os.open(str(path), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
        try:
            os.write(fd, line)
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, TimeoutError):
        return
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def _append_ordered_event(
    store: Path,
    transaction: dict,
    focused: dict,
    required: dict,
    started_at: str,
    duration_seconds: float,
    lock_wait_seconds: float,
) -> None:
    stages = []
    for result, name in ((focused, "focused"), (required, "required")):
        identity = transaction[name]
        stages.append(
            {
                "gate": transaction[f"{name}_gate"],
                "status": result["status"],
                "identity_key": _identity_key(transaction[f"{name}_gate"], identity, transaction["batch"]),
                "argv": identity["argv"],
                "tool_versions": identity["tool_versions"],
                "command_executions": result["commands"],
            }
        )
    payload = json.dumps({"batch": transaction["batch"], "stages": stages}, sort_keys=True, separators=(",", ":"))
    event = {
        "schema": 2,
        "event_kind": "ordered",
        "event_id": f"{os.getpid()}-{time.time_ns()}",
        "status": "ordered_success",
        "gate": "ordered",
        "identity_key": hashlib.sha256(payload.encode()).hexdigest(),
        "batch": _event_batch(transaction["batch"]),
        "started_at": started_at,
        "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "duration_seconds": round(max(0.0, duration_seconds), 6),
        "command_executions": sum(item["commands"] for item in (focused, required)),
        "executed_count": sum(item["status"] == "executed" for item in (focused, required)),
        "reused_count": sum(item["status"] == "reused" for item in (focused, required)),
        "exit_code": 0,
        "hosted_required_certification": False,
        "stages": stages,
    }
    if not _valid_event(event):
        return
    lock_fd: int | None = None
    try:
        store.mkdir(parents=True, exist_ok=True)
        lock_fd = wait_for_lock(store / "events.lock", lock_wait_seconds)
        fd = os.open(str(store / "events.jsonl"), os.O_CREAT | os.O_WRONLY | os.O_APPEND, 0o644)
        try:
            os.write(fd, (json.dumps(event, sort_keys=True, separators=(",", ":")) + "\n").encode())
            os.fsync(fd)
        finally:
            os.close(fd)
    except (OSError, TimeoutError):
        return
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def _accounting_report(store: Path, gate: str | None = None) -> dict:
    events: list[dict] = []
    invalid_records = 0
    path = store / "events.jsonl"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            invalid_records += 1
            continue
        if not _valid_event(event):
            invalid_records += 1
            continue
        if gate is None or event.get("gate") == gate:
            events.append(event)
    counts: dict[str, int] = {}
    groups: dict[str, dict] = {}
    for event in events:
        status = str(event.get("status", "unknown"))
        counts[status] = counts.get(status, 0) + 1
        batch = event["batch"]
        group_key = (
            "unbatched"
            if batch is None
            else hashlib.sha256(json.dumps(batch, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        )
        group = groups.setdefault(
            group_key,
            {"batch": batch, "events": 0, "executed": 0, "reused": 0, "statuses": {}},
        )
        group["events"] += 1
        group["executed"] += event["executed_count"]
        group["reused"] += event["reused_count"]
        group["statuses"][status] = group["statuses"].get(status, 0) + 1
    return {
        "schema": 2,
        "hosted_required_certification": False,
        "counts": counts,
        "groups": groups,
        "invalid_records": invalid_records,
        "events": events,
    }


def _record_skip(gate: str, batch: dict | None, repo: Path, store: Path) -> int:
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.monotonic()
    safe_batch = None
    if batch is not None:
        prepared, reason = _prepare_batch(repo, batch)
        if reason:
            print(f"[local-validation] invalid batch metadata; skip refused: {reason}", file=sys.stderr)
            return 2
        valid, reason = _validate_prepared_batch(repo, prepared)
        if not valid or reason:
            print(f"[local-validation] invalid batch metadata; skip refused: {reason}", file=sys.stderr)
            return 2
        safe_batch = prepared
    identity: dict | None
    try:
        identity = content_identity(repo, [])
    except IdentityUnknown:
        identity = None
    _append_accounting_event(
        store,
        status="skipped",
        gate=gate,
        identity=identity,
        batch=safe_batch,
        started_at=started_at,
        completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        duration_seconds=time.monotonic() - started,
        command_executions=0,
        exit_code=0,
        reason="hook or caller skipped this local gate",
    )
    print(f"[local-validation] SKIPPED {gate} (no command executed)")
    return 0


def _finish_gate(
    *,
    store: Path,
    gate: str,
    status: str,
    exit_code: int | None,
    identity: dict | None,
    batch: dict | None,
    started_at: str,
    started: float,
    command_executions: int,
    lock_wait_seconds: float,
) -> int:
    _append_accounting_event(
        store,
        status=status,
        gate=gate,
        identity=identity,
        batch=batch,
        started_at=started_at,
        completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        duration_seconds=time.monotonic() - started,
        command_executions=command_executions,
        exit_code=exit_code,
        lock_wait_seconds=min(lock_wait_seconds, 5.0),
    )
    return 1 if exit_code is None else exit_code


def _execute_without_receipt(
    *,
    gate: str,
    argv: list[str],
    repo: Path,
    store: Path,
    identity: dict | None,
    batch: dict | None,
    started_at: str,
    started: float,
    lock_wait_seconds: float,
) -> int:
    try:
        proc = subprocess.run(list(argv), cwd=repo, check=False)
    except KeyboardInterrupt:
        _finish_gate(
            store=store,
            gate=gate,
            status="cancelled",
            exit_code=130,
            identity=identity,
            batch=batch,
            started_at=started_at,
            started=started,
            command_executions=1,
            lock_wait_seconds=lock_wait_seconds,
        )
        raise
    return _finish_gate(
        store=store,
        gate=gate,
        status="executed" if proc.returncode == 0 else "failed",
        exit_code=proc.returncode,
        identity=identity,
        batch=batch,
        started_at=started_at,
        started=started,
        command_executions=1,
        lock_wait_seconds=lock_wait_seconds,
    )


def _write_receipt(path: Path, gate: str, identity: dict, batch: dict) -> None:
    temporary = path.with_suffix(f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "schema": 2,
                "gate": gate,
                "identity": identity,
                "batch": batch,
                "delivery": {
                    "member_preparation_is_not_integration_certification": True,
                    "role": (batch or {}).get("role"),
                    "integration_identity": batch,
                },
                "exit": 0,
                "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _validated_batch(repo: Path, batch: dict | None) -> tuple[dict | None, str]:
    prepared, reason = _prepare_batch(repo, batch)
    if reason:
        return None, reason
    valid, reason = _validate_prepared_batch(repo, prepared)
    return (prepared, "") if valid and not reason else (None, reason or "batch metadata is invalid")


def run_gate(
    gate: str,
    argv: list[str],
    batch: dict | None,
    lock_wait_seconds: float,
    repo: Path,
    store: Path,
) -> int:
    """Run *argv* under the singleflight receipt contract. Returns its exit code."""
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.monotonic()

    batch, batch_reason = _validated_batch(repo, batch)
    if batch_reason:
        print(f"[local-validation] batch identity unknown ({batch_reason}); executing without receipt")
        return _execute_without_receipt(
            gate=gate,
            argv=argv,
            repo=repo,
            store=store,
            identity=None,
            batch=None,
            started_at=started_at,
            started=started,
            lock_wait_seconds=lock_wait_seconds,
        )
    try:
        identity = content_identity(repo, list(argv))
    except IdentityUnknown as exc:
        print(f"[local-validation] identity unknown ({exc}); executing without receipt")
        return _execute_without_receipt(
            gate=gate,
            argv=argv,
            repo=repo,
            store=store,
            identity=None,
            batch=batch,
            started_at=started_at,
            started=started,
            lock_wait_seconds=lock_wait_seconds,
        )
    for attempt in range(MAX_IDENTITY_RETRIES):
        receipt = receipt_path(store, gate, identity, batch)
        lock_path = receipt.with_name(receipt.stem + ".lock")
        try:
            lock_fd = wait_for_lock(lock_path, lock_wait_seconds)
        except KeyboardInterrupt:
            _finish_gate(
                store=store,
                gate=gate,
                status="cancelled",
                exit_code=130,
                identity=identity,
                batch=batch,
                started_at=started_at,
                started=started,
                command_executions=0,
                lock_wait_seconds=lock_wait_seconds,
            )
            raise
        except TimeoutError:
            _finish_gate(
                store=store,
                gate=gate,
                status="cancelled",
                exit_code=1,
                identity=identity,
                batch=batch,
                started_at=started_at,
                started=started,
                command_executions=0,
                lock_wait_seconds=lock_wait_seconds,
            )
            raise
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
            current_batch, current_batch_reason = _validated_batch(repo, batch)
            current_batch_valid = not current_batch_reason
            if not current_batch_valid:
                print(
                    f"[local-validation] batch identity changed to unknown ({current_batch_reason}); "
                    "executing without receipt"
                )
                current_unknown = True
            elif current_batch != batch:
                batch = current_batch
                continue
            if current is not None and current != identity:
                identity = current
                continue
            write_holder(lock_fd, lock_path, phase="checking", gate=gate)
            hit = None if current_unknown else read_receipt(receipt, gate=gate, identity=identity, batch=batch)
            if hit is not None:
                print(
                    f"[local-validation] REUSED {gate} receipt "
                    f"(head {identity['head'][:12]}, recorded {hit.get('recorded_at', '?')})"
                )
                return _finish_gate(
                    store=store,
                    gate=gate,
                    status="reused",
                    exit_code=0,
                    identity=identity,
                    batch=batch,
                    started_at=started_at,
                    started=started,
                    command_executions=0,
                    lock_wait_seconds=lock_wait_seconds,
                )
            write_holder(lock_fd, lock_path, phase="executing", gate=gate)
            print(f"[local-validation] EXECUTING {gate}: {' '.join(argv)}")
            try:
                proc = subprocess.run(list(argv), cwd=repo, check=False)
            except KeyboardInterrupt:
                _finish_gate(
                    store=store,
                    gate=gate,
                    status="cancelled",
                    exit_code=130,
                    identity=identity,
                    batch=batch,
                    started_at=started_at,
                    started=started,
                    command_executions=1,
                    lock_wait_seconds=lock_wait_seconds,
                )
                raise
            if proc.returncode == 0:
                try:
                    final_identity = content_identity(repo, list(argv))
                except IdentityUnknown as exc:
                    final_identity = None
                    print(f"[local-validation] identity became unknown ({exc}); no receipt stored")
                final_batch, final_batch_reason = _validated_batch(repo, batch)
                final_batch_valid = not final_batch_reason
                if not final_batch_valid:
                    print(f"[local-validation] batch identity became unknown ({final_batch_reason}); no receipt stored")
                if not current_unknown and final_identity == identity and final_batch_valid and final_batch == batch:
                    _write_receipt(receipt, gate, identity, batch)
                else:
                    print("[local-validation] inputs changed during execution; no receipt stored")
            else:
                print(f"[local-validation] {gate} failed (exit {proc.returncode}); no receipt stored")
            return _finish_gate(
                store=store,
                gate=gate,
                status="executed" if proc.returncode == 0 else "failed",
                exit_code=proc.returncode,
                identity=identity,
                batch=batch,
                started_at=started_at,
                started=started,
                command_executions=1,
                lock_wait_seconds=lock_wait_seconds,
            )
        finally:
            os.close(lock_fd)
    # A continuously changing tree cannot safely produce reusable evidence.
    # Execute once without a receipt instead of spinning or reusing stale data.
    print("[local-validation] inputs changed repeatedly; executing without receipt")
    return _execute_without_receipt(
        gate=gate,
        argv=argv,
        repo=repo,
        store=store,
        identity=identity,
        batch=batch,
        started_at=started_at,
        started=started,
        lock_wait_seconds=lock_wait_seconds,
    )


def show_gate(gate: str, batch: dict | None, repo: Path, store: Path, argv: list[str] | None = None) -> int:
    batch, prepare_reason = _prepare_batch(repo, batch)
    if prepare_reason:
        print(f"[local-validation] batch identity unknown ({prepare_reason})")
        return 2
    valid_batch, batch_reason = _validate_prepared_batch(repo, batch)
    if not valid_batch or batch_reason:
        print(f"[local-validation] batch identity unknown ({batch_reason})")
        return 2
    try:
        identity = content_identity(repo, list(argv or []))
    except IdentityUnknown as exc:
        print(f"[local-validation] identity unknown ({exc})")
        return 2
    receipt = receipt_path(store, gate, identity, batch)
    hit = read_receipt(receipt, gate=gate, identity=identity, batch=batch)
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
    started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    started = time.monotonic()
    for attempt in range(MAX_ORDERED_RETRIES):
        try:
            before = ordered_identity(repo, batch, focused_gate, focused_command, preflight_gate, preflight_command)
        except IdentityUnknown as exc:
            print(f"[local-validation] ordered input identity unknown: {exc}", file=sys.stderr)
            return 1
        focused_receipt = receipt_path(store, focused_gate, before["focused"], before["batch"])
        focused_reused = (
            read_receipt(focused_receipt, gate=focused_gate, identity=before["focused"], batch=before["batch"])
            is not None
        )
        focused_status = run_gate(focused_gate, focused_command, batch, lock_wait_seconds, repo, store)
        if focused_status != 0:
            return focused_status
        try:
            after_focused = ordered_identity(
                repo, batch, focused_gate, focused_command, preflight_gate, preflight_command
            )
        except IdentityUnknown as exc:
            print(f"[local-validation] ordered input changed after focused stage: {exc}", file=sys.stderr)
            continue
        focused_ready = (
            read_receipt(focused_receipt, gate=focused_gate, identity=before["focused"], batch=before["batch"])
            is not None
        )
        if after_focused != before or not focused_ready:
            print("[local-validation] ordered input changed between stages; restarting focused stage")
            continue
        required_receipt = receipt_path(store, preflight_gate, before["required"], before["batch"])
        required_reused = (
            read_receipt(required_receipt, gate=preflight_gate, identity=before["required"], batch=before["batch"])
            is not None
        )
        preflight_status = run_gate(preflight_gate, preflight_command, batch, lock_wait_seconds, repo, store)
        if preflight_status != 0:
            return preflight_status
        try:
            after_preflight = ordered_identity(
                repo, batch, focused_gate, focused_command, preflight_gate, preflight_command
            )
        except IdentityUnknown as exc:
            print(f"[local-validation] ordered input changed after required stage: {exc}", file=sys.stderr)
            continue
        required_ready = (
            read_receipt(required_receipt, gate=preflight_gate, identity=before["required"], batch=before["batch"])
            is not None
        )
        if after_preflight == before and required_ready:
            _append_ordered_event(
                store,
                before,
                {"status": "reused" if focused_reused else "executed", "commands": 0 if focused_reused else 1},
                {"status": "reused" if required_reused else "executed", "commands": 0 if required_reused else 1},
                started_at,
                time.monotonic() - started,
                lock_wait_seconds,
            )
            return 0
        print("[local-validation] ordered input changed during required stage; restarting focused stage")
    print("[local-validation] ordered input did not stabilize; no combined certification", file=sys.stderr)
    return 1


def ordered_identity(
    repo: Path,
    batch: dict | None,
    focused_gate: str | None = None,
    focused_command: list[str] | None = None,
    required_gate: str | None = None,
    required_command: list[str] | None = None,
) -> dict:
    normalized, reason = _prepare_batch(repo, batch)
    if reason:
        raise IdentityUnknown(reason)
    valid, reason = _validate_prepared_batch(repo, normalized)
    if not valid or reason:
        raise IdentityUnknown(reason)
    if focused_command is None or required_command is None:
        return {"content": content_identity(repo, []), "batch": normalized}
    focused = content_identity(repo, focused_command)
    required = content_identity(repo, required_command)
    return {
        "batch": normalized,
        "focused_gate": focused_gate,
        "focused": focused,
        "required_gate": required_gate,
        "required": required,
    }


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
        parser_arg.add_argument("--batch-predecessor-head", default=None)
        parser_arg.add_argument("--batch-predecessor-tree", default=None)
        parser_arg.add_argument("--batch-member-identity", default=None)
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
    show.add_argument("--batch-predecessor-head", default=None)
    show.add_argument("--batch-predecessor-tree", default=None)
    show.add_argument("--batch-member-identity", default=None)
    show.add_argument("argv", nargs=argparse.REMAINDER, help="gate command after -- (same as run)")
    skip = sub.add_parser("skip", help="record a local gate that intentionally did no work")
    skip.add_argument("--gate", required=True)
    skip.add_argument("--batch-id", default=None)
    skip.add_argument("--batch-member", default=None)
    skip.add_argument("--batch-role", default=None, choices=["member", "integrator"])
    skip.add_argument("--batch-member-identity", default=None)
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
    ordered.add_argument("--batch-predecessor-head", default=None)
    ordered.add_argument("--batch-predecessor-tree", default=None)
    ordered.add_argument("--batch-member-identity", default=None)
    ordered.add_argument("--lock-wait-seconds", type=float, default=DEFAULT_LOCK_WAIT_SECONDS)
    report = sub.add_parser("report", help="report local validation accounting events")
    report.add_argument("--gate", default=None)
    clear = sub.add_parser("clear-test-lock", help="clear an inactive shared test lock")
    clear.add_argument("path", type=Path)
    return parser


def batch_block(args: argparse.Namespace) -> dict | None:
    member_identity = getattr(args, "batch_member_identity", None)
    if member_identity is not None:
        try:
            member_identity = json.loads(member_identity)
        except (TypeError, json.JSONDecodeError):
            member_identity = {"__invalid_json__": True}
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
        "predecessor_head": getattr(args, "batch_predecessor_head", None),
        "predecessor_tree": getattr(args, "batch_predecessor_tree", None),
        "member_identity": member_identity,
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
    if args.command == "report":
        print(json.dumps(_accounting_report(store, args.gate), indent=2, sort_keys=True))
        return 0
    if args.command == "skip":
        return _record_skip(args.gate, batch, repo, store)
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
