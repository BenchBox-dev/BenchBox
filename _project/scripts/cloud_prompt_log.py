#!/usr/bin/env python3
"""Consolidated prompt history for Claude Code *cloud* sessions.

Local sessions accumulate their transcripts under ``~/.claude/projects/``, so a
consolidated prompt history can be rebuilt from disk at any time. Cloud sessions
cannot: each one runs in an ephemeral container that is reclaimed with its
storage, and a container only ever holds its own transcript. Nothing survives to
be exported later, so the history has to be captured *during* the session and
pushed somewhere durable before the container goes away.

This script is that capture. It runs as three Claude Code hooks:

    UserPromptSubmit -> ``capture``  append the prompt to a per-session JSONL
    Stop             -> ``sync``     push what has accumulated so far
    SessionEnd       -> ``sync``     final flush

Capture is local and unconditional; ``sync`` pushes only when a sink is
configured. That split is deliberate: installing the hooks can never publish
anything on its own, and pointing ``CLAUDE_PROMPT_HISTORY_REMOTE`` at a
repository is the single, explicit act that starts sending prompts off the box.
Point it at a PRIVATE repository -- prompt history is personal metadata, and a
public repository publishes it permanently and irrevocably.

Environment:
    CLAUDE_PROMPT_HISTORY_REMOTE  git URL of the sink repo (unset => never push)
    CLAUDE_PROMPT_HISTORY_BRANCH  branch in the sink repo (default: main)
    CLAUDE_PROMPT_HISTORY_DIR     capture root (default: ~/.claude/prompt-history)

Hooks must never break a session, so every entry point traps its own errors and
exits 0. Failures land in ``<history-dir>/errors.log`` instead of the terminal.

Usage:
    cloud_prompt_log.py capture           # hook: reads hook JSON on stdin
    cloud_prompt_log.py sync              # hook: push to the configured sink
    cloud_prompt_log.py install           # register the hooks in ~/.claude/settings.json
    cloud_prompt_log.py emit-setup        # print a standalone installer to paste
                                          # into a cloud environment setup script
    cloud_prompt_log.py merge --out FILE  # (run locally) fold cloud + local
                                          # history into one consolidated JSONL
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HISTORY_DIR = "~/.claude/prompt-history"
DEFAULT_BRANCH = "main"
GIT_TIMEOUT = 60
PUSH_ATTEMPTS = 4
INSTALLED_SCRIPT_NAME = "cloud_prompt_log.py"

# Hook entries this script owns. `install` matches on the script name, so
# re-running it upgrades the commands in place instead of stacking duplicates.
HOOK_EVENTS = {
    "UserPromptSubmit": "capture",
    "Stop": "sync",
    "SessionEnd": "sync",
}


# --------------------------------------------------------------------------
# paths and environment
# --------------------------------------------------------------------------


def history_dir() -> Path:
    return Path(os.environ.get("CLAUDE_PROMPT_HISTORY_DIR", DEFAULT_HISTORY_DIR)).expanduser()


def sessions_dir() -> Path:
    return history_dir() / "sessions"


def is_cloud_session() -> bool:
    """True inside a Claude Code cloud container.

    ``CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE`` (e.g. ``cloud_default``) is set by
    the remote runtime and absent on a local machine. The gate keeps a hook
    installed from a shared repo config from double-capturing local sessions,
    which already have durable transcripts of their own.
    """
    return bool(os.environ.get("CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE"))


def log_error(message: str) -> None:
    with contextlib.suppress(OSError):
        history_dir().mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).isoformat()
        with (history_dir() / "errors.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp} {message}\n")


def run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=GIT_TIMEOUT,
        check=False,
    )


def repo_slug(cwd: str | None) -> str | None:
    """Return ``owner/name`` for the session's repo, or None.

    The remote URL is not usable as-is: cloud containers rewrite it to a
    session-scoped local proxy (``http://local_proxy@127.0.0.1:PORT/git/owner/name``)
    that carries credentials and a port number meaningless outside this
    container. Only the ``owner/name`` tail is stable and safe to record.
    """
    if not cwd or not Path(cwd).is_dir():
        return None
    result = run_git(["remote", "get-url", "origin"], cwd=Path(cwd))
    if result.returncode != 0:
        return None
    match = re.search(r"([^/:]+/[^/]+?)(?:\.git)?/?$", result.stdout.strip())
    return match.group(1) if match else None


def git_branch(cwd: str | None) -> str | None:
    if not cwd or not Path(cwd).is_dir():
        return None
    result = run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=Path(cwd))
    return result.stdout.strip() or None if result.returncode == 0 else None


# --------------------------------------------------------------------------
# capture
# --------------------------------------------------------------------------


def cmd_capture(args: argparse.Namespace) -> int:
    """UserPromptSubmit hook: append one prompt to this session's JSONL."""
    if not (is_cloud_session() or args.force):
        return 0

    raw = sys.stdin.read().strip()
    if not raw:
        return 0
    payload = json.loads(raw)

    prompt = (payload.get("prompt") or "").strip()
    if not prompt:
        return 0

    session_id = payload.get("session_id") or os.environ.get("CLAUDE_CODE_SESSION_ID") or "unknown"
    cwd = payload.get("cwd") or os.getcwd()
    now = datetime.now(timezone.utc)

    record = {
        "ts": now.isoformat(),
        "source": "cloud",
        "session_id": session_id,
        "prompt": prompt,
        "cwd": cwd,
        "repo": repo_slug(cwd),
        "branch": git_branch(cwd),
        "env_type": os.environ.get("CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE"),
        "container_id": os.environ.get("CLAUDE_CODE_CONTAINER_ID"),
    }

    # One file per session: concurrent cloud sessions pushing to the same sink
    # then only ever *add* files, so a rebase can never hit a content conflict.
    target = sessions_dir() / f"{now:%Y-%m-%d}-{session_id}.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return 0


# --------------------------------------------------------------------------
# sync
# --------------------------------------------------------------------------


def sink_remote() -> str | None:
    return (os.environ.get("CLAUDE_PROMPT_HISTORY_REMOTE") or "").strip() or None


def prepare_clone(remote: str, branch: str) -> Path | None:
    """Return a working clone of the sink repo, cloning it on first use.

    The clone lives under the history dir, never inside the session's own
    checkout: committing and pushing here must not touch the working tree or
    index that the agent is using.
    """
    clone = history_dir() / "sink"
    if (clone / ".git").is_dir():
        run_git(["remote", "set-url", "origin", remote], cwd=clone)
        run_git(["fetch", "origin", branch], cwd=clone)
        # Reset onto the remote tip when it exists; a brand-new sink repo has
        # no such branch yet and the local commits become its first history.
        if run_git(["rev-parse", "--verify", f"origin/{branch}"], cwd=clone).returncode == 0:
            run_git(["reset", "--hard", f"origin/{branch}"], cwd=clone)
        return clone

    clone.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(["clone", "--depth", "1", "--branch", branch, remote, str(clone)])
    if result.returncode != 0:
        # An empty sink repo has no branch to clone; start one locally.
        result = run_git(["clone", remote, str(clone)])
        if result.returncode != 0:
            log_error(f"sync: clone failed: {result.stderr.strip()}")
            return None
        run_git(["checkout", "-B", branch], cwd=clone)
    return clone


def cmd_sync(args: argparse.Namespace) -> int:
    """Stop/SessionEnd hook: copy captured sessions into the sink and push."""
    if not (is_cloud_session() or args.force):
        return 0

    remote = sink_remote()
    if not remote:
        # No sink configured: capture stays on the box. This is the default and
        # is not an error -- it is what keeps installation from publishing.
        return 0

    captured = sorted(sessions_dir().glob("*.jsonl"))
    if not captured:
        return 0

    # Stop and SessionEnd can overlap at the end of a session; one push at a time.
    history_dir().mkdir(parents=True, exist_ok=True)
    lock_path = history_dir() / "sync.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0

        branch = os.environ.get("CLAUDE_PROMPT_HISTORY_BRANCH", DEFAULT_BRANCH)
        for attempt in range(PUSH_ATTEMPTS):
            clone = prepare_clone(remote, branch)
            if clone is None:
                return 0

            dest = clone / "sessions"
            dest.mkdir(parents=True, exist_ok=True)
            for path in captured:
                shutil.copy2(path, dest / path.name)

            run_git(["add", "sessions"], cwd=clone)
            if not run_git(["diff", "--cached", "--quiet"], cwd=clone).returncode:
                return 0  # nothing new since the last push

            session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "unknown")
            commit = run_git(
                [
                    "-c",
                    "user.name=Claude Code",
                    "-c",
                    "user.email=noreply@anthropic.com",
                    "commit",
                    "-m",
                    f"prompt history: cloud session {session_id}",
                ],
                cwd=clone,
            )
            if commit.returncode != 0:
                log_error(f"sync: commit failed: {commit.stderr.strip()}")
                return 0

            push = run_git(["push", "origin", f"HEAD:{branch}"], cwd=clone)
            if push.returncode == 0:
                return 0

            # Another session pushed first. prepare_clone() re-fetches and
            # resets on the next pass, and per-session filenames mean the
            # replayed copy cannot conflict.
            log_error(f"sync: push attempt {attempt + 1} failed: {push.stderr.strip()}")
            if attempt < PUSH_ATTEMPTS - 1:
                time.sleep(2**attempt)
    return 0


# --------------------------------------------------------------------------
# install
# --------------------------------------------------------------------------


def hook_entry(command: str) -> dict:
    return {"hooks": [{"type": "command", "command": command}]}


def owns(entry: dict) -> bool:
    """True when a settings.json hook entry is one this script installed."""
    return any(INSTALLED_SCRIPT_NAME in (hook.get("command") or "") for hook in entry.get("hooks", []))


def cmd_install(args: argparse.Namespace) -> int:
    """Copy this script next to settings.json and register its three hooks."""
    target_dir = Path(args.claude_dir).expanduser()
    target_dir.mkdir(parents=True, exist_ok=True)

    installed = target_dir / INSTALLED_SCRIPT_NAME
    source = Path(__file__).resolve()
    if not installed.exists() or source != installed.resolve():
        shutil.copyfile(source, installed)
    installed.chmod(0o755)

    settings_path = target_dir / "settings.json"
    settings = {}
    if settings_path.exists():
        with settings_path.open(encoding="utf-8") as handle:
            settings = json.load(handle)

    hooks = settings.setdefault("hooks", {})
    for event, subcommand in HOOK_EVENTS.items():
        entries = [entry for entry in hooks.get(event, []) if not owns(entry)]
        entries.append(hook_entry(f"{sys.executable} {installed} {subcommand}"))
        hooks[event] = entries

    with settings_path.open("w", encoding="utf-8") as handle:
        json.dump(settings, handle, indent=2)
        handle.write("\n")

    print(f"installed {installed}")
    print(f"registered {', '.join(HOOK_EVENTS)} hooks in {settings_path}")
    remote = sink_remote()
    print(f"sink: {remote}" if remote else "sink: none (CLAUDE_PROMPT_HISTORY_REMOTE unset; capture stays local)")
    return 0


def cmd_emit_setup(args: argparse.Namespace) -> int:
    """Print a standalone installer for a cloud environment's setup script.

    The environment setup script runs before any repo checkout is guaranteed to
    exist, and it has to work for sessions on repos that do not carry this file
    at all. So the installer embeds the script rather than referencing a path:
    it is generated from this exact file, and cannot drift from it.
    """
    payload = base64.b64encode(Path(__file__).resolve().read_bytes()).decode("ascii")
    chunks = "\n".join(payload[i : i + 100] for i in range(0, len(payload), 100))
    print(
        f"""#!/bin/bash
# Install the Claude Code cloud prompt-history hooks.
# Generated by `cloud_prompt_log.py emit-setup` -- paste into the setup script
# field of a cloud environment (claude.ai/code environment settings).
set -euo pipefail

mkdir -p ~/.claude
base64 -d > ~/.claude/{INSTALLED_SCRIPT_NAME} <<'PROMPT_LOG_B64'
{chunks}
PROMPT_LOG_B64

chmod +x ~/.claude/{INSTALLED_SCRIPT_NAME}
python3 ~/.claude/{INSTALLED_SCRIPT_NAME} install
"""
    )
    return 0


# --------------------------------------------------------------------------
# merge (local side)
# --------------------------------------------------------------------------


def text_of(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def is_human_turn(record: dict) -> bool:
    """True for turns the user typed, excluding tool results and meta records."""
    if record.get("type") != "user" or record.get("isMeta") or record.get("isCompactSummary"):
        return False
    content = record.get("message", {}).get("content")
    if isinstance(content, list) and any(
        isinstance(part, dict) and part.get("type") == "tool_result" for part in content
    ):
        return False
    return bool(text_of(content).strip())


def read_local_transcripts(projects_dir: Path) -> list[dict]:
    """Extract prompts from local ``~/.claude/projects`` session transcripts."""
    records = []
    for path in sorted(projects_dir.glob("*/*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not is_human_turn(entry):
                    continue
                records.append(
                    {
                        "ts": entry.get("timestamp"),
                        "source": "local",
                        "session_id": entry.get("sessionId") or path.stem,
                        "prompt": text_of(entry["message"].get("content")).strip(),
                        "cwd": entry.get("cwd"),
                        "repo": None,
                        "branch": entry.get("gitBranch"),
                    }
                )
    return records


def read_cloud_history(root: Path) -> list[dict]:
    records = []
    for path in sorted(root.glob("*.jsonl")):
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        records.append(json.loads(line))
    return records


def cmd_merge(args: argparse.Namespace) -> int:
    """Fold cloud and local prompt history into one deduplicated JSONL."""
    records: list[dict] = []
    if args.cloud:
        records += read_cloud_history(Path(args.cloud).expanduser())
    if args.local:
        records += read_local_transcripts(Path(args.local).expanduser())

    # Extending an existing consolidated file is the normal case: read it back
    # in so repeated merges accumulate rather than overwrite.
    out_path = Path(args.out).expanduser()
    if out_path.exists():
        with out_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    with contextlib.suppress(json.JSONDecodeError):
                        records.append(json.loads(line))

    seen = set()
    merged = []
    for record in sorted(records, key=lambda row: (row.get("ts") or "", row.get("session_id") or "")):
        key = (record.get("session_id"), record.get("ts"), record.get("prompt"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as handle:
        for record in merged:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    cloud = sum(1 for record in merged if record.get("source") == "cloud")
    print(f"{len(merged)} prompt(s) -> {out_path} ({cloud} cloud, {len(merged) - cloud} local)")
    return 0


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="UserPromptSubmit hook: record one prompt")
    capture.add_argument("--force", action="store_true", help="capture even outside a cloud session")
    capture.set_defaults(func=cmd_capture)

    sync = sub.add_parser("sync", help="Stop/SessionEnd hook: push captured prompts to the sink")
    sync.add_argument("--force", action="store_true", help="sync even outside a cloud session")
    sync.set_defaults(func=cmd_sync)

    install = sub.add_parser("install", help="register the hooks in a settings.json")
    install.add_argument("--claude-dir", default="~/.claude", help="directory holding settings.json")
    install.set_defaults(func=cmd_install)

    emit = sub.add_parser("emit-setup", help="print a standalone installer for an environment setup script")
    emit.set_defaults(func=cmd_emit_setup)

    merge = sub.add_parser("merge", help="consolidate cloud + local history into one JSONL")
    merge.add_argument("--cloud", help="directory of cloud session JSONL files (the sink's sessions/)")
    merge.add_argument("--local", help="local transcript root (e.g. ~/.claude/projects)")
    merge.add_argument("--out", required=True, help="consolidated JSONL to create or extend")
    merge.set_defaults(func=cmd_merge)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Hooks run on every prompt and every turn; a crash here must never be what
    # ends someone's session, so failures are logged and swallowed.
    if args.command in {"capture", "sync"}:
        try:
            return args.func(args)
        except Exception as error:  # noqa: BLE001
            log_error(f"{args.command}: {type(error).__name__}: {error}")
            return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
