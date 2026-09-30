from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BOOTSTRAP_BASE = "8fbad03469746539959af14e865a19c53fab68f5"
TRUSTED_FILES = (
    "scripts/check_comment_policy.py",
    "scripts/comment_syntax.py",
    "scripts/comment_syntax_js.cjs",
    "scripts/comment_payloads.py",
)


def resolve_base(root: Path, requested: str | None) -> str:
    if os.environ.get("GITHUB_ACTIONS") == "true":
        event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
        if os.environ.get("GITHUB_EVENT_NAME") == "pull_request":
            base = event["pull_request"]["base"]["sha"]
        elif os.environ.get("GITHUB_EVENT_NAME") == "merge_group":
            base = event["merge_group"]["base_sha"]
        else:
            raise ValueError("unsupported CI event")
        if requested and requested != base:
            raise ValueError("supplied base does not match the platform event")
    else:
        base = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "--verify", f"{requested or 'origin/develop'}^{{commit}}"], text=True
        ).strip()
    if not re.fullmatch(r"[a-f0-9]{40}", base):
        raise ValueError("invalid base SHA")
    subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", base, "HEAD"], check=True)
    return base


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the comment policy with immutable base parsers.")
    parser.add_argument("--base", default=os.environ.get("BASE_REF"))
    parser.add_argument("--staged", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    try:
        base = resolve_base(root, args.base)
        with tempfile.TemporaryDirectory(prefix="benchbox-comment-policy-") as directory:
            trusted = Path(directory)
            missing = []
            for name in TRUSTED_FILES:
                result = subprocess.run(["git", "show", f"{base}:{name}"], cwd=root, capture_output=True)
                if result.returncode:
                    missing.append(name)
                else:
                    (trusted / Path(name).name).write_bytes(result.stdout)
            bootstrap = bool(missing)
            if bootstrap:
                if base != BOOTSTRAP_BASE or len(missing) != len(TRUSTED_FILES):
                    raise ValueError("trusted checker missing outside the pinned initial rollout")
                for name in TRUSTED_FILES:
                    (trusted / Path(name).name).write_bytes((root / name).read_bytes())
            command = [
                sys.executable,
                str(trusted / "check_comment_policy.py"),
                "--root",
                str(root),
                "--mode",
                "transition",
                "--base",
                base,
            ]
            if bootstrap:
                command.append("--bootstrap")
            if args.staged:
                command.append("--staged")
            return subprocess.run(command, cwd=root, check=False).returncode
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"comment-policy: trusted invocation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
