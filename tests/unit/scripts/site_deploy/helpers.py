"""Builders shared by site-deploy tests."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.site_deploy.generation import Generation

ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
}


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True, env=ENV)
    return result.stdout.strip()


def commit_files(repo: Path, files: dict[str, str], message: str = "commit") -> str:
    for rel, content in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def sha(char: str) -> str:
    return char * 40


def gen(trunk: str = "a", index: int = 10, tag: str = "v0.4.1", corpus: str = "c") -> Generation:
    return Generation(trunk_sha=sha(trunk), trunk_index=index, release_tag=tag, corpus_sha=sha(corpus))
