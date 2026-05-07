#!/usr/bin/env python3
"""Bring up a UAT local platform stack with an explicit health probe."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.uat import docker_assets, matrix  # noqa: E402

DOCUMENT_ONLY_PLATFORMS = frozenset({"lakesail", "pg-duckdb", "pg-mooncake", "timescaledb"})


def automated_platforms() -> tuple[str, ...]:
    """Return platforms with UAT-managed Docker startup support."""
    return tuple(
        sorted(
            platform
            for platform, spec in docker_assets.docker_platform_specs().items()
            if spec.managed_start_allowed and not spec.fixed_container_names
        )
    )


def known_platforms() -> tuple[str, ...]:
    return tuple(sorted(set(automated_platforms()) | DOCUMENT_ONLY_PLATFORMS))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="uat-bring-up")
    parser.add_argument("--platform", required=True, help="Local UAT platform to start")
    parser.add_argument("--timeout-s", type=int, default=300, help="docker compose --wait timeout")
    parser.add_argument("--project-name", default=None, help="Optional docker compose project name override")
    parser.add_argument(
        "--dry-run", action="store_true", help="Print/run command construction without Docker execution"
    )
    args = parser.parse_args(argv)

    platform = args.platform.strip()
    if platform in DOCUMENT_ONLY_PLATFORMS:
        print(
            f"platform {platform!r} is document-only for UAT bring-up; see docs/operations/uat-local-provisioning.md",
            file=sys.stderr,
        )
        return 2
    if platform not in automated_platforms():
        print(
            f"unknown platform {platform!r}; supported automated platforms: {', '.join(automated_platforms())}",
            file=sys.stderr,
        )
        return 2

    spec = docker_assets.docker_platform_spec(platform)
    try:
        docker_assets.validate_managed_start_allowed(spec)
    except docker_assets.DockerAssetError as exc:
        print(f"platform {platform!r} cannot be UAT-managed: {exc}", file=sys.stderr)
        return 2

    project_name = args.project_name or docker_assets.compose_project_name("manual", platform)
    argv_up = docker_assets.compose_up_command(spec, project_name, start_timeout_s=args.timeout_s)
    result = docker_assets.run_docker_command(
        argv_up,
        dry_run=args.dry_run,
        timeout_s=args.timeout_s,
        cwd=docker_assets.REPO_ROOT,
    )
    print(result.command)
    if not result.succeeded:
        details = result.error or result.stderr or result.stdout or f"exit {result.returncode}"
        print(f"UAT bring-up failed for {platform}: {details}", file=sys.stderr)
        return result.returncode or 1

    matrix.reset_reachability_cache()
    if not args.dry_run and not matrix.platform_is_reachable(platform):
        endpoint = spec.tcp_probe_label or "configured endpoint"
        print(f"UAT bring-up failed for {platform}: {endpoint} is still unreachable", file=sys.stderr)
        return 1

    print(f"UAT bring-up OK for {platform} (project={project_name})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
