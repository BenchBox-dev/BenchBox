#!/usr/bin/env bash
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

DATA_DIR="${BENCHBOX_DATA_DIR:-$ROOT/benchmark_runs}"

tcp_ok() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

port_serves() {
  local plat="$1" hp
  case "$plat" in
    questdb)    curl -fsS --max-time 15 -o /dev/null http://127.0.0.1:9003 ;;
    postgresql) tcp_ok 5432 ;;
    *)
        hp="$(grep -oE '"[^"]+:[0-9]+"' "$ROOT/docker/$plat/docker-compose.yml" 2>/dev/null | head -1 | tr -d '"' | sed -E 's/:[0-9]+$//' | grep -oE '[0-9]+' | tail -1)"
        [ -n "$hp" ] && tcp_ok "$hp" ;;
  esac
}

current_plat=""
trap 'if [ -n "$current_plat" ]; then make -C "$ROOT" "test-docker-down-$current_plat" CONTAINER_ENGINE="$ENGINE" BENCHBOX_DATA_DIR="$DATA_DIR" >/dev/null 2>&1 || true; fi; exit 130' INT TERM

for plat in "${PLATFORMS[@]}"; do
  echo "== [$ENGINE] $plat =="
  current_plat="$plat"
  if ! make -C "$ROOT" "test-docker-up-$plat" CONTAINER_ENGINE="$ENGINE" BENCHBOX_DATA_DIR="$DATA_DIR"; then
    echo "  FAIL: up -d --wait did not return healthy"; fails=1; current_plat=""; continue
  fi
  proj="$(cat "$STATE_DIR/$plat.project" 2>/dev/null || true)"
  [ -n "$proj" ] || { echo "  FAIL: could not read project name (state file missing)"; fails=1; }

  if port_serves "$plat"; then echo "  PASS: published port serves"; else echo "  FAIL: published port did not serve"; fails=1; fi

  if ! make -C "$ROOT" "test-docker-down-$plat" CONTAINER_ENGINE="$ENGINE" BENCHBOX_DATA_DIR="$DATA_DIR"; then
    echo "  FAIL: teardown errored"; fails=1
  fi
  current_plat=""

  if [ -z "$proj" ]; then
    echo "  SKIP: fresh-state checks (no project name)"
  else
    if "$ENGINE" ps -a 2>/dev/null | grep -Fq -- "$proj-"; then
      echo "  FAIL: container survived teardown"; fails=1
    else
      echo "  PASS: no container after teardown"
    fi
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
