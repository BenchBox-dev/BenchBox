#!/usr/bin/env bash
set -euo pipefail

# ---- usage ----
usage() {
  cat <<EOF
Usage: $0 [options]

Options:
  --scale <factor>              Fixed scale factor override for all benchmarks.
                                Default: registry smoke scale per benchmark
                                (min_scale, else default_scale; TPC-DS defaults to 0.01).
                                TPC-DS subscale runs (SF<1) are allowed by default.
  --phases <list>               Pass --phases to benchbox run
                                (default: load,power)
  --platform <name>             Run a single platform (e.g. duckdb)
  --platform-group <group>      Run a platform group: sql, fast, slow, dataframe, docker,
                                docker-fast, docker-slow, all (default: all)
  --benchmark <name>            Run a single benchmark (e.g. tpch)
  --benchmark-group <group>     Run a benchmark group: tpc, primitives, industry, academic,
                                timeseries, realworld, aiml, experimental, all (default: all)
  --compression <spec>          Pass --compression to benchbox run (e.g. zstd:3).
                                Default: unset - lets each platform choose its native format.
  --per-benchmark-timeout <sec> Per-benchmark wall-clock timeout in seconds (default: 0 = none).
                                Uses timeout(1)/gtimeout(1) when available,
                                otherwise falls back to perl(1).
  --log-dir <dir>               Directory for captured stdout/stderr logs
                                (default: benchmark_runs/logs)
  --skip-unavailable            Skip platforms that fail a pre-flight connectivity check
                                instead of counting them as failures
  -h, --help                    Show this help

Platform groups:
  fast        - Fast OLAP benchmark execution:
                duckdb datafusion lakesail clickhouse-local clickhouse-server cedardb starrocks
  slow        - Slower benchmark execution (OLTP, JVM, timeseries):
                sqlite spark postgresql presto trino databend doris
                influxdb pg-duckdb pg-mooncake timescaledb questdb singlestore
  sql         - All SQL platforms (fast + slow)
  dataframe   - polars-df pandas-df modin-df pyspark-df dask-df datafusion-df
  docker      - All Docker Compose platforms (fast + slow docker)
  docker-fast - clickhouse-server cedardb starrocks
  docker-slow - postgresql presto trino databend doris influxdb
                pg-duckdb pg-mooncake timescaledb questdb singlestore
Benchmark groups: tpc, primitives, industry, academic, timeseries, realworld, aiml, experimental, all
EOF
  exit 1
}

# ---- args ----
SCALE_OVERRIDE=""
PHASES="load,power"
PLATFORM_FILTER=""
PLATFORM_GROUP="all"
BENCHMARK_FILTER=""
BENCHMARK_GROUP="all"
COMPRESSION=""
PER_BENCHMARK_TIMEOUT="0"
LOG_DIR="benchmark_runs/logs"
SKIP_UNAVAILABLE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scale)                  SCALE_OVERRIDE="$2";          shift 2 ;;
    --phases)                 PHASES="$2";                  shift 2 ;;
    --platform)               PLATFORM_FILTER="$2";         shift 2 ;;
    --platform-group)         PLATFORM_GROUP="$2";          shift 2 ;;
    --benchmark)              BENCHMARK_FILTER="$2";        shift 2 ;;
    --benchmark-group)        BENCHMARK_GROUP="$2";         shift 2 ;;
    --compression)            COMPRESSION="$2";             shift 2 ;;
    --per-benchmark-timeout)  PER_BENCHMARK_TIMEOUT="$2";   shift 2 ;;
    --log-dir)                LOG_DIR="$2";                 shift 2 ;;
    --skip-unavailable)       SKIP_UNAVAILABLE=1;           shift ;;
    -h|--help) usage ;;
    *) echo "Unknown argument: $1"; usage ;;
  esac
done

mkdir -p "$LOG_DIR"

# ---- Locate timeout backend ----
TIMEOUT_BACKEND="none"
TIMEOUT_BIN=""

have_working_timeout_bin() {
  local candidate="$1" resolved
  command -v "$candidate" >/dev/null 2>&1 || return 1
  resolved="$(command -v "$candidate")"
  "$resolved" --help >/dev/null 2>&1 || return 1
  TIMEOUT_BIN="$resolved"
  return 0
}

have_working_perl() {
  local resolved
  command -v perl >/dev/null 2>&1 || return 1
  resolved="$(command -v perl)"
  "$resolved" -e 'exit 0' >/dev/null 2>&1 || return 1
  TIMEOUT_BIN="$resolved"
  return 0
}

if [[ "$PER_BENCHMARK_TIMEOUT" != "0" ]]; then
  if have_working_timeout_bin timeout; then
    TIMEOUT_BACKEND="coreutils"
  elif have_working_timeout_bin gtimeout; then
    TIMEOUT_BACKEND="coreutils"
  elif have_working_perl; then
    TIMEOUT_BACKEND="perl"
  else
    echo "Error: --per-benchmark-timeout requires timeout(1), gtimeout(1), or a working perl(1) interpreter" >&2
    exit 2
  fi
fi

# ---- Platform lists ----
# Each platform appears in exactly one list. Speed based on OLAP benchmark execution time.
FAST_NATIVE=( duckdb datafusion lakesail clickhouse-local )
FAST_DOCKER=( clickhouse-server cedardb starrocks )
SLOW_NATIVE=( sqlite spark )
SLOW_DOCKER=( postgresql presto trino databend doris influxdb pg-duckdb pg-mooncake timescaledb questdb singlestore velox )
DF_PLATFORMS=( polars-df pandas-df modin-df pyspark-df dask-df datafusion-df )

# Derived (no platform names repeated above)
FAST_SQL_PLATFORMS=( "${FAST_NATIVE[@]}" "${FAST_DOCKER[@]}" )
SLOW_SQL_PLATFORMS=( "${SLOW_NATIVE[@]}" "${SLOW_DOCKER[@]}" )
SQL_PLATFORMS=( "${FAST_SQL_PLATFORMS[@]}" "${SLOW_SQL_PLATFORMS[@]}" )
DOCKER_PLATFORMS=( "${FAST_DOCKER[@]}" "${SLOW_DOCKER[@]}" )

# ---- Pre-flight TCP connectivity checks ----
# Maps platform → host:port. Some platforms share ports (e.g. PG-based on 5432)
# but each platform gets its own reachability cache entry (keyed by platform).
get_platform_port() {
  case "$1" in
    singlestore)        echo "localhost:13306" ;;
    questdb)            echo "localhost:8812" ;;
    presto)             echo "localhost:18081" ;;
    trino)              echo "localhost:18080" ;;
    clickhouse-server)  echo "localhost:9000" ;;
    starrocks)          echo "localhost:19030" ;;
    cedardb)            echo "localhost:5435" ;;
    databend)           echo "localhost:8000" ;;
    doris)              echo "localhost:19031" ;;
    influxdb)           echo "localhost:8181" ;;
    pg-duckdb)          echo "localhost:5432" ;;
    pg-mooncake)        echo "localhost:5432" ;;
    timescaledb)        echo "localhost:5432" ;;
    postgresql)         echo "localhost:5432" ;;
    velox)              echo "localhost:50051" ;;
    *)                  echo "" ;;
  esac
}

# Per-benchmark extra --platform-option settings for Docker port remaps.
get_platform_extra_opts() {
  case "$1" in
    questdb)     echo "--platform-option http_port=19000" ;;
    starrocks)   echo "--platform-option port=19030 --platform-option http_port=18040" ;;
    doris)       echo "--platform-option port=19031 --platform-option http_port=18030 --platform-option be_http_port=18040" ;;
    singlestore) echo "--platform-option port=13306 --platform-option password=benchbox" ;;
    velox)       echo "--platform-option deployment=remote --platform-option endpoint=sc://localhost:50051" ;;
    *)           echo "" ;;
  esac
}

# Per-platform extra benchbox CLI flags (not --platform-option).
#
# velox: limit to 1 measurement iteration - Docker Desktop's memory ceiling
# (11.7 GB) is too low for 3xSF=1 TPC-H passes inside a Spark/Velox container.
# One warmup + one measurement run is sufficient to verify correctness, which
# is the only goal of this stress script.  Tradeoff: applies globally to every
# velox benchmark, including micro-benchmarks (read_primitives, write_primitives,
# joinorder) where a single pass produces noise-dominated timings.  This is
# acceptable here because the script's purpose is functional verification, not
# performance validity.  If a future benchmark needs multi-iteration sampling
# even under stress conditions, switch to per-benchmark granularity:
#   case "$1-$benchmark" in velox-foo) echo "" ;; velox-*) echo "--iterations 1" ;; ...
get_platform_cli_flags() {
  case "$1" in
    velox) echo "--iterations 1" ;;
    *)     echo "" ;;
  esac
}

# Cache reachability by platform name via $TMPDIR sentinel files.
# Key by platform, not host:port, so shared-port platforms (pg-duckdb,
# pg-mooncake, timescaledb, postgresql on 5432) are probed independently.
PCHK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/bb_pchk.XXXXXX")"
trap 'rm -rf "$PCHK_DIR"' EXIT

# TCP probe: nc if available, else bash /dev/tcp fallback.
tcp_probe() {
  local host="$1" port="$2"
  if command -v nc >/dev/null 2>&1; then
    nc -z -w 2 "$host" "$port" >/dev/null 2>&1
    return $?
  fi
  # Bash builtin fallback. No built-in timeout, but connect to localhost
  # returns quickly on closed ports.
  ( exec 3<>"/dev/tcp/$host/$port" ) >/dev/null 2>&1
}

# Returns 0 if reachable (or no probe configured), 1 otherwise.
platform_is_reachable() {
  local platform="$1" addr sentinel host port
  addr="$(get_platform_port "$platform")"
  [[ -z "$addr" ]] && return 0
  sentinel="$PCHK_DIR/$platform"
  if [[ ! -f "$sentinel" ]]; then
    host="${addr%:*}"; port="${addr#*:}"
    if tcp_probe "$host" "$port"; then
      echo "0" > "$sentinel"
    else
      echo "1" > "$sentinel"
    fi
  fi
  return "$(cat "$sentinel")"
}

# ---- Benchmark / smoke-scale / SQL-only lists (from registry, with hardcoded fallback) ----
# Query benchmark_registry.py so groupings and supports_dataframe flags never
# drift from the source of truth.
load_benchmark_registry() {
  local tmpsh
  tmpsh="$(uv run --no-sync -- python -c '
from benchbox.core.benchmark_registry import BENCHMARK_METADATA, get_benchmarks_by_category, get_categories
cats = {c: list(get_benchmarks_by_category(c).keys()) for c in get_categories()}
sql_only = [i for i, m in BENCHMARK_METADATA.items() if not m.get("supports_dataframe", True)]
smoke_scales = {}
for i, m in BENCHMARK_METADATA.items():
    if i == "tpcds":
        # Registry default_scale stays at 1.0 for methodology reasons; the
        # local smoke suite intentionally exercises patched subscale support.
        smoke_scales[i] = 0.01
    else:
        smoke_scales[i] = m["min_scale"] if m.get("min_scale") is not None else m["default_scale"]
def arr(name, items):
    print(f"{name}=( " + " ".join(items) + " )")
arr("TPC_BENCHMARKS",          cats.get("TPC", []))
arr("PRIMITIVES_BENCHMARKS",   cats.get("Primitives", []))
arr("INDUSTRY_BENCHMARKS",     cats.get("Industry", []))
arr("ACADEMIC_BENCHMARKS",     cats.get("Academic", []))
arr("TIMESERIES_BENCHMARKS",   cats.get("Time Series", []))
arr("REALWORLD_BENCHMARKS",    cats.get("Real World", []))
arr("AIML_BENCHMARKS",         cats.get("AI/ML", []))
arr("EXPERIMENTAL_BENCHMARKS", cats.get("Experimental", []))
arr("SQL_ONLY_BENCHMARKS",     sql_only)
print("BENCHMARK_SMOKE_SCALES=()")
for k, v in sorted(smoke_scales.items()):
    print(f"BENCHMARK_SMOKE_SCALES+=(\"{k}={v}\")")
' 2>/dev/null)" || return 1
  eval "$tmpsh"
  return 0
}

if ! load_benchmark_registry; then
  echo "Warning: benchmark registry load failed; using hardcoded fallback lists" >&2
  TPC_BENCHMARKS=(         tpch tpcds tpcdi )
  PRIMITIVES_BENCHMARKS=(  read_primitives write_primitives transaction_primitives metadata_primitives ai_primitives )
  INDUSTRY_BENCHMARKS=(    clickbench h2odb coffeeshop )
  ACADEMIC_BENCHMARKS=(    ssb joinorder amplab )
  TIMESERIES_BENCHMARKS=(  tsbs_devops )
  REALWORLD_BENCHMARKS=(   nyctaxi flightdata )
  AIML_BENCHMARKS=(        vector_search )
  EXPERIMENTAL_BENCHMARKS=( tpchavoc tpch_skew tpcds_obt datavault )
  SQL_ONLY_BENCHMARKS=(    ai_primitives vector_search )
  BENCHMARK_SMOKE_SCALES=(
    "ai_primitives=0.01" "amplab=0.01" "clickbench=1.0" "coffeeshop=0.001"
    "datavault=0.01" "flightdata=0.01" "h2odb=0.01" "joinorder=1.0"
    "metadata_primitives=1.0" "nyctaxi=0.01" "read_primitives=0.01"
    "ssb=0.01" "tpch=0.01" "tpcdi=0.01" "tpcds=0.01" "tpcds_obt=1.0"
    "tpch_skew=0.01" "tpchavoc=0.01" "transaction_primitives=0.01"
    "tsbs_devops=0.01" "vector_search=0.01" "write_primitives=0.01"
  )
fi

ALL_BENCHMARKS=(
  "${TPC_BENCHMARKS[@]}"
  "${PRIMITIVES_BENCHMARKS[@]}"
  "${INDUSTRY_BENCHMARKS[@]}"
  "${ACADEMIC_BENCHMARKS[@]}"
  "${TIMESERIES_BENCHMARKS[@]}"
  "${REALWORLD_BENCHMARKS[@]}"
  "${AIML_BENCHMARKS[@]}"
  "${EXPERIMENTAL_BENCHMARKS[@]}"
)

# ---- helpers ----

contains() {
  local val="$1"; shift
  for x in "$@"; do [[ "$x" == "$val" ]] && return 0; done
  return 1
}

is_sql_only() { contains "$1" "${SQL_ONLY_BENCHMARKS[@]}"; }

benchmark_scale_for() {
  local benchmark="$1"
  local entry key
  if [[ -n "$SCALE_OVERRIDE" ]]; then
    printf '%s\n' "$SCALE_OVERRIDE"
    return 0
  fi
  for entry in "${BENCHMARK_SMOKE_SCALES[@]}"; do
    key="${entry%%=*}"
    if [[ "$key" == "$benchmark" ]]; then
      printf '%s\n' "${entry#*=}"
      return 0
    fi
  done
  echo "No smoke scale registered for benchmark: $benchmark" >&2
  return 1
}

scale_is_subscale() {
  local scale="$1"
  awk -v scale="$scale" 'BEGIN { exit !(scale < 1.0) }'
}

FAILURES=()
INTERRUPTED=0
CURRENT=""
LAST_RUN_TIMED_OUT=0

print_summary() {
  echo ""
  if [[ $INTERRUPTED -eq 1 ]]; then
    echo "=== INTERRUPTED ==="
    [[ -n "$CURRENT" ]] && echo "  (was running: $CURRENT)"
  fi
  if [[ ${#FAILURES[@]} -gt 0 ]]; then
    echo "=== FAILED (${#FAILURES[@]}) ==="
    for f in "${FAILURES[@]}"; do echo "  $f"; done
  else
    echo "=== ALL PASSED ==="
  fi
}

handle_interrupt() {
  INTERRUPTED=1
  echo ""
  echo "  (interrupted)"
  print_summary
  exit 130
}

trap handle_interrupt INT TERM

run_with_optional_timeout() {
  local timeout_seconds="$1"
  shift

  LAST_RUN_TIMED_OUT=0
  if [[ "$timeout_seconds" == "0" ]]; then
    "$@"
    return $?
  fi

  case "$TIMEOUT_BACKEND" in
    coreutils)
      "$TIMEOUT_BIN" "$timeout_seconds" "$@"
      ;;
    perl)
      "$TIMEOUT_BIN" - "$timeout_seconds" "$@" <<'PERL'
use strict;
use warnings;
use POSIX qw(setsid);

my ($timeout, @cmd) = @ARGV;
die "timeout must be positive\n" unless defined $timeout && $timeout > 0;
die "no command provided\n" unless @cmd;

my $pid = fork();
die "fork failed: $!\n" unless defined $pid;

if ($pid == 0) {
    setsid() or die "setsid failed: $!\n";
    exec @cmd or die "exec failed: $!\n";
}

my $timed_out = 0;
local $SIG{ALRM} = sub {
    $timed_out = 1;
    kill "TERM", -$pid;
    select undef, undef, undef, 0.2;
    kill "KILL", -$pid;
};

alarm $timeout;
my $waited = waitpid($pid, 0);
alarm 0;

if ($timed_out) {
    exit 124;
}
if ($waited < 0) {
    exit 125;
}
if ($? == -1) {
    exit 125;
}
if ($? & 127) {
    exit 128 + ($? & 127);
}
exit($? >> 8);
PERL
      ;;
    *)
      echo "Internal error: timeout backend unavailable" >&2
      return 125
      ;;
  esac

  local rc=$?
  if [[ "$rc" -eq 124 ]]; then
    LAST_RUN_TIMED_OUT=1
  fi
  return "$rc"
}

# Invoked as: run_benchmark <platform> <benchmark> <scale> <compression>
# <compression> may be empty to defer to benchbox/platform defaults.
run_benchmark() {
  local platform="$1" benchmark="$2" scale="$3" compression="$4"
  CURRENT="$platform/$benchmark"
  local extra_opts=()
  # shellcheck disable=SC2086
  read -r -a extra_opts <<<"$(get_platform_extra_opts "$platform")"

  local log_file
  log_file="$LOG_DIR/${platform}_${benchmark}_$(date +%Y%m%d_%H%M%S).log"

  # Run WITHOUT --quiet so stderr/stdout are meaningful on failure.
  # All child output is captured to the log file; only our status line is
  # shown to the terminal.
  # Platforms that require optional uv extras use `uv run --extra X` so the
  # extra is guaranteed present even if the venv is re-synced between runs.
  # All other platforms use `--no-sync` to avoid per-invocation sync overhead.
  local platform_extra
  platform_extra="$(get_platform_uv_extra "$platform")"
  local uv_run_flags=( --no-sync )
  [[ -n "$platform_extra" ]] && uv_run_flags=( --extra "$platform_extra" )
  local bb_cmd=( uv run "${uv_run_flags[@]}" -- benchbox run
                 --platform "$platform"
                 --benchmark "$benchmark"
                 --scale "$scale"
                 --non-interactive
                 --phases "$PHASES" )
  [[ -n "$compression" ]] && bb_cmd+=( --compression "$compression" )
  local platform_cli_flags
  platform_cli_flags="$(get_platform_cli_flags "$platform")"
  # shellcheck disable=SC2206
  [[ -n "$platform_cli_flags" ]] && bb_cmd+=( $platform_cli_flags )
  [[ ${#extra_opts[@]} -gt 0 && -n "${extra_opts[0]:-}" ]] && bb_cmd+=( "${extra_opts[@]}" )

  echo -n "  $benchmark (SF=$scale) ... "
  local t0=$SECONDS
  local rc=0
  run_with_optional_timeout "$PER_BENCHMARK_TIMEOUT" "${bb_cmd[@]}" >"$log_file" 2>&1 || rc=$?
  local elapsed=$(( SECONDS - t0 ))

  if [[ "$rc" -eq 0 ]]; then
    # Extract result JSON path from log if present.
    local result_path
    result_path=$(grep -oE 'benchmark_runs/results/[^[:space:]]+\.json' "$log_file" | tail -1 || true)
    if [[ -n "$result_path" ]]; then
      echo "done (${elapsed}s) → $result_path"
    else
      echo "done (${elapsed}s)"
    fi
  else
    if [[ "$LAST_RUN_TIMED_OUT" -eq 1 ]]; then
      echo "TIMEOUT after ${elapsed}s - see $log_file"
    else
      echo "FAILED (${elapsed}s) - see $log_file"
    fi
    FAILURES+=( "$platform/$benchmark" )
  fi
  CURRENT=""
}

# ---- Resolve platform lists ----
if [[ -n "$PLATFORM_FILTER" ]]; then
  RUN_SQL_PLATFORMS=()
  RUN_DF_PLATFORMS=()
  for p in "${SQL_PLATFORMS[@]}"; do [[ "$p" == "$PLATFORM_FILTER" ]] && RUN_SQL_PLATFORMS=( "$p" ) && break; done
  for p in "${DF_PLATFORMS[@]}";  do [[ "$p" == "$PLATFORM_FILTER" ]] && RUN_DF_PLATFORMS=( "$p" )  && break; done
  if [[ ${#RUN_SQL_PLATFORMS[@]} -eq 0 && ${#RUN_DF_PLATFORMS[@]} -eq 0 ]]; then
    echo "Unknown platform: $PLATFORM_FILTER" >&2; usage
  fi
else
  case "$(printf '%s' "$PLATFORM_GROUP" | tr '[:upper:]' '[:lower:]')" in
    sql)         RUN_SQL_PLATFORMS=( "${SQL_PLATFORMS[@]}" );         RUN_DF_PLATFORMS=() ;;
    fast)        RUN_SQL_PLATFORMS=( "${FAST_SQL_PLATFORMS[@]}" );    RUN_DF_PLATFORMS=() ;;
    slow)        RUN_SQL_PLATFORMS=( "${SLOW_SQL_PLATFORMS[@]}" );    RUN_DF_PLATFORMS=() ;;
    dataframe)   RUN_SQL_PLATFORMS=();                                RUN_DF_PLATFORMS=( "${DF_PLATFORMS[@]}" ) ;;
    docker)      RUN_SQL_PLATFORMS=( "${DOCKER_PLATFORMS[@]}" );      RUN_DF_PLATFORMS=() ;;
    docker-fast) RUN_SQL_PLATFORMS=( "${FAST_DOCKER[@]}" );           RUN_DF_PLATFORMS=() ;;
    docker-slow) RUN_SQL_PLATFORMS=( "${SLOW_DOCKER[@]}" );           RUN_DF_PLATFORMS=() ;;
    all)         RUN_SQL_PLATFORMS=( "${SQL_PLATFORMS[@]}" );         RUN_DF_PLATFORMS=( "${DF_PLATFORMS[@]}" ) ;;
    *) echo "Unknown platform group: $PLATFORM_GROUP" >&2; usage ;;
  esac
fi

# ---- Resolve benchmark lists ----
RESOLVED_BENCHMARKS=()
if [[ -n "$BENCHMARK_FILTER" ]]; then
  RESOLVED_BENCHMARKS=( "$BENCHMARK_FILTER" )
else
  case "$(printf '%s' "$BENCHMARK_GROUP" | tr '[:upper:]' '[:lower:]')" in
    tpc)          RESOLVED_BENCHMARKS=( "${TPC_BENCHMARKS[@]}" ) ;;
    primitives)   RESOLVED_BENCHMARKS=( "${PRIMITIVES_BENCHMARKS[@]}" ) ;;
    industry)     RESOLVED_BENCHMARKS=( "${INDUSTRY_BENCHMARKS[@]}" ) ;;
    academic)     RESOLVED_BENCHMARKS=( "${ACADEMIC_BENCHMARKS[@]}" ) ;;
    timeseries)   RESOLVED_BENCHMARKS=( "${TIMESERIES_BENCHMARKS[@]}" ) ;;
    realworld)    RESOLVED_BENCHMARKS=( "${REALWORLD_BENCHMARKS[@]}" ) ;;
    aiml)         RESOLVED_BENCHMARKS=( "${AIML_BENCHMARKS[@]}" ) ;;
    experimental) RESOLVED_BENCHMARKS=( "${EXPERIMENTAL_BENCHMARKS[@]}" ) ;;
    all)          RESOLVED_BENCHMARKS=( "${ALL_BENCHMARKS[@]}" ) ;;
    *) echo "Unknown benchmark group: $BENCHMARK_GROUP" >&2; usage ;;
  esac
fi

# Filter RESOLVED_BENCHMARKS into SQL and DF sublists
SQL_RUN_BENCHMARKS=()
DF_RUN_BENCHMARKS=()
for b in "${RESOLVED_BENCHMARKS[@]}"; do
  SQL_RUN_BENCHMARKS+=( "$b" )
  is_sql_only "$b" || DF_RUN_BENCHMARKS+=( "$b" )
done

# ---- Warm uv environment once ----
# Avoids per-invocation sync overhead; later runs use --no-sync.
# Map platforms → required uv extras so optional dependencies are installed.
get_platform_uv_extra() {
  case "$1" in
    clickhouse-local) echo "clickhouse-local" ;;
    singlestore)      echo "singlestore" ;;
    influxdb)         echo "influxdb" ;;
    *)                echo "" ;;
  esac
}
_uv_sync_args=()
for _p in "${RUN_SQL_PLATFORMS[@]+"${RUN_SQL_PLATFORMS[@]}"}" "${RUN_DF_PLATFORMS[@]+"${RUN_DF_PLATFORMS[@]}"}"; do
  _ex="$(get_platform_uv_extra "$_p")"
  [[ -n "$_ex" ]] && _uv_sync_args+=( "--extra" "$_ex" )
done
uv sync "${_uv_sync_args[@]+"${_uv_sync_args[@]}"}" --quiet >/dev/null 2>&1 || true

# ---- pre-flight check helper (used in run loops) ----
run_platform_benchmarks() {
  local platform="$1"; shift
  if ! platform_is_reachable "$platform"; then
    local addr
    addr="$(get_platform_port "$platform")"
    if [[ $SKIP_UNAVAILABLE -eq 1 ]]; then
      echo "--- $platform --- (SKIPPED: $addr not reachable)"
      return
    else
      echo "--- $platform --- (WARNING: $addr not reachable - benchmarks will likely fail)"
    fi
  else
    echo "--- $platform ---"
  fi
  for benchmark in "$@"; do
    local benchmark_scale
    benchmark_scale="$(benchmark_scale_for "$benchmark")" || {
      echo "FAILED resolving scale for $platform/$benchmark"
      FAILURES+=( "$platform/$benchmark" )
      continue
    }
    run_benchmark "$platform" "$benchmark" "$benchmark_scale" "$COMPRESSION"
  done
}

# ---- run: SQL platforms ----
if [[ ${#RUN_SQL_PLATFORMS[@]} -gt 0 && ${#SQL_RUN_BENCHMARKS[@]} -gt 0 ]]; then
  echo "=== SQL Platforms (phases=$PHASES, scale=${SCALE_OVERRIDE:-registry-smoke}) ==="
  for platform in "${RUN_SQL_PLATFORMS[@]}"; do
    run_platform_benchmarks "$platform" "${SQL_RUN_BENCHMARKS[@]}"
  done
fi

# ---- run: DataFrame platforms (df-compatible benchmarks only) ----
if [[ ${#RUN_DF_PLATFORMS[@]} -gt 0 && ${#DF_RUN_BENCHMARKS[@]} -gt 0 ]]; then
  echo "=== DataFrame Platforms (phases=$PHASES, scale=${SCALE_OVERRIDE:-registry-smoke}) ==="
  for platform in "${RUN_DF_PLATFORMS[@]}"; do
    run_platform_benchmarks "$platform" "${DF_RUN_BENCHMARKS[@]}"
  done
fi

# ---- summary ----
print_summary
[[ ${#FAILURES[@]} -gt 0 ]] && exit 1 || exit 0
