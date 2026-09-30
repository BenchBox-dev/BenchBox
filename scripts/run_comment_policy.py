from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

BOOTSTRAP_BASE = "a0744baff99d664759abd4e11ba28367cb0de0a5"
TRUSTED_FILES = (
    "scripts/check_comment_policy.py",
    "scripts/comment_syntax.py",
    "scripts/comment_syntax_js.cjs",
    "scripts/comment_payloads.py",
    "scripts/comment_execution.py",
    "scripts/comment_policy_entry.py",
    "quality/comment-policy-requirements.txt",
    "quality/comment-policy-package.json",
    "quality/comment-policy-package-lock.json",
)


def parser_environment(trusted: Path) -> tuple[Path, dict[str, str]]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {
            "PYTHONPATH",
            "PYTHONHOME",
            "NODE_PATH",
            "NODE_OPTIONS",
            "COMMENT_POLICY_TYPESCRIPT",
            "VIRTUAL_ENV",
            "UV_PROJECT_ENVIRONMENT",
        }
        and not key.upper().startswith(("UV_", "PIP_", "NPM_"))
    }
    python = trusted / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        ["uv", "--no-config", "venv", "--python", sys.executable, str(trusted / "venv")], env=env, check=True
    )
    subprocess.run(
        [
            "uv",
            "--no-config",
            "pip",
            "install",
            "--python",
            str(python),
            "--require-hashes",
            "--only-binary",
            ":all:",
            "--no-deps",
            "--index-url",
            "https://pypi.org/simple",
            "-r",
            str(trusted / "comment-policy-requirements.txt"),
        ],
        env=env,
        check=True,
    )
    (trusted / "package.json").write_bytes((trusted / "comment-policy-package.json").read_bytes())
    (trusted / "package-lock.json").write_bytes((trusted / "comment-policy-package-lock.json").read_bytes())
    for config in ("npm-user.conf", "npm-global.conf"):
        (trusted / config).write_text("", encoding="utf-8")
    subprocess.run(
        [
            "npm",
            "ci",
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--userconfig",
            str(trusted / "npm-user.conf"),
            "--globalconfig",
            str(trusted / "npm-global.conf"),
        ],
        cwd=trusted,
        env=env,
        check=True,
    )
    env["COMMENT_POLICY_TYPESCRIPT"] = str(trusted / "node_modules/typescript")
    return python, env


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
    parser.add_argument("--native-tests", action="store_true")
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
            python, env = parser_environment(trusted)
            command = [
                str(python),
                "-I",
                str(trusted / "comment_policy_entry.py"),
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
            result = subprocess.run(command, cwd=trusted, env=env, check=False).returncode
            if result:
                return result
            if args.native_tests:
                subprocess.run(
                    ["node", "--test", str(root / "tests/unit/scripts/test_comment_syntax_js.cjs")],
                    cwd=trusted,
                    env=env,
                    check=True,
                )
            return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"comment-policy: trusted invocation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
