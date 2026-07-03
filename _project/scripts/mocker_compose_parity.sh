#!/usr/bin/env bash
# mocker_compose_parity.sh -- acceptance test for the `make test-docker-*` compose
# lifecycle across container engines (docker | mocker).
#
# It drives the ACTUAL make targets (test-docker-up-% / test-docker-down-%), so it
# measures what developers run rather than a re-implementation, then asserts the
# three properties a working engine must provide:
#   1. `up -d --wait` returns 0 only once services report HEALTHY (health-gated).
#   2. the published host port actually SERVES (external reachability).
#   3. teardown leaves NO container and NO named volume -- the `down -v` fresh-state
#      guarantee that mocker 0.5.4's `down -v` breaks and the Makefile teardown wrap
#      (compose_down_fresh) restores.
# The same script and the same assertions run on both engines, so parity is
# MEASURED, not assumed. Apple `container`/mocker are Apple-silicon/macOS-26
# local-dev only and MUST NOT run in CI (CI uses docker on ubuntu).
#
# Usage: _project/scripts/mocker_compose_parity.sh <docker|mocker> [platform ...]
#        (default platforms: questdb postgresql)
set -uo pipefail

ENGINE="${1:-}"; shift || true
case "$ENGINE" in
  docker|mocker) ;;
  *) echo "usage: $0 <docker|mocker> [platform ...]" >&2; exit 2 ;;
esac
PLATFORMS=("$@"); [ "${#PLATFORMS[@]}" -gt 0 ] || PLATFORMS=(questdb postgresql)

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
STATE_DIR="${DOCKER_TEST_STATE_DIR:-/tmp/benchbox-docker-projects}"
fails=0

# TCP connect check via bash /dev/tcp (no nc dependency). The subshell opens and
# (on exit) closes the fd; success == the connect succeeded.
tcp_ok() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# "Published host port serves" -- platform-aware, with a generic first-port fallback
# so the harness is reusable for the heavier multi-service stacks (w2).
port_serves() {
  local plat="$1" hp
  case "$plat" in
    questdb)    curl -fsS --max-time 15 -o /dev/null http://127.0.0.1:9003 ;;
    postgresql) tcp_ok 5432 ;;
    *)  # first published host port; resolve a `${VAR:-default}:container` mapping to
        # its default so stacks like doris/starrocks (which use that syntax) work.
        hp="$(grep -oE '"[^"]+:[0-9]+"' "$ROOT/docker/$plat/docker-compose.yml" 2>/dev/null | head -1 | tr -d '"' | sed -E 's/:[0-9]+$//' | grep -oE '[0-9]+' | tail -1)"
        [ -n "$hp" ] && tcp_ok "$hp" ;;
  esac
}

# Tear down the in-flight stack if interrupted between up and down.
current_plat=""
trap 'if [ -n "$current_plat" ]; then make -C "$ROOT" "test-docker-down-$current_plat" CONTAINER_ENGINE="$ENGINE" >/dev/null 2>&1 || true; fi; exit 130' INT TERM

for plat in "${PLATFORMS[@]}"; do
  echo "== [$ENGINE] $plat =="
  current_plat="$plat"
  if ! make -C "$ROOT" "test-docker-up-$plat" CONTAINER_ENGINE="$ENGINE"; then
    echo "  FAIL: up -d --wait did not return healthy"; fails=1; current_plat=""; continue
  fi
  proj="$(cat "$STATE_DIR/$plat.project" 2>/dev/null || true)"
  [ -n "$proj" ] || { echo "  FAIL: could not read project name (state file missing)"; fails=1; }

  if port_serves "$plat"; then echo "  PASS: published port serves"; else echo "  FAIL: published port did not serve"; fails=1; fi

  if ! make -C "$ROOT" "test-docker-down-$plat" CONTAINER_ENGINE="$ENGINE"; then
    echo "  FAIL: teardown errored"; fails=1
  fi
  current_plat=""

  # Fresh-state assertions, scoped to THIS project. Grep the project-prefixed name
  # directly (no header/column-position assumption). A missing project name is a
  # FAIL above, not a silent pass here.
  if [ -z "$proj" ]; then
    echo "  SKIP: fresh-state checks (no project name)"
  else
    if "$ENGINE" ps -a 2>/dev/null | grep -Fq -- "$proj-"; then
      echo "  FAIL: container survived teardown"; fails=1
    else
      echo "  PASS: no container after teardown"
    fi
    # Volume names differ by engine: docker `<proj>_<vol>`, mocker `<proj>-<vol>`.
    if "$ENGINE" volume ls 2>/dev/null | grep -Eq -- "(^|[[:space:]])$proj[-_]"; then
      echo "  FAIL: named volume survived teardown (leak)"; fails=1
    else
      echo "  PASS: no named volume after teardown"
    fi
  fi
done

if [ "$fails" -eq 0 ]; then
  echo "PARITY OK ($ENGINE): ${PLATFORMS[*]}"
else
  echo "PARITY FAILURES ($ENGINE): ${PLATFORMS[*]}"
fi
exit "$fails"
