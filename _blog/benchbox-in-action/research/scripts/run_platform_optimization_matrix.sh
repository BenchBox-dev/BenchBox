#!/usr/bin/env bash
set -euo pipefail

# BenchBox CLI matrix for post #6:
# "BenchBox in action: when the same query needs different code"
#
# Default behavior is dry-run so the matrix can be reviewed before execution.
# Execute with: ./run_platform_optimization_matrix.sh --execute

BENCHBOX_CLI="${BENCHBOX_CLI:-./.venv/bin/benchbox}"
BENCHMARK="${BENCHMARK:-tpcds}"
QUERIES="${QUERIES:-Q16,Q95}"
PHASES="${PHASES:-power}"
SEED="${SEED:-42}"
REPEATS="${REPEATS:-5}"
PLATFORMS_CSV="${PLATFORMS_CSV:-polars-df,datafusion-df,pyspark-df}"
SCALES_CSV="${SCALES_CSV:-1}"
OUTPUT_ROOT="${OUTPUT_ROOT:-benchmark_runs/results}"
MODE="dry-run"

usage() {
  cat <<'EOF'
Usage: run_platform_optimization_matrix.sh [options]

Options:
  --execute                   Run the matrix (default is dry-run).
  --dry-run                   Print the matrix without running commands (default).
  --preview                   Alias for --dry-run.
  --repeats N                 Repeat each matrix point N times (default: 5).
  --platforms CSV             Platform list (default: polars-df,datafusion-df,pyspark-df).
  --scales CSV                Scale factors (default: 1). TPC-DS requires scale >= 1.
  --queries CSV               Query subset (default: Q16,Q95).
  --phases TEXT               Benchmark phases (default: power).
  --seed N                    RNG seed (default: 42).
  --benchbox-cli PATH         BenchBox CLI path (default: ./.venv/bin/benchbox).
  --output-root PATH          Output directory for matrix artifacts.
  -h, --help                  Show this help.

Environment overrides:
  BENCHBOX_CLI, BENCHMARK, QUERIES, PHASES, SEED, REPEATS,
  PLATFORMS_CSV, SCALES_CSV, OUTPUT_ROOT
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --execute)
      MODE="execute"
      shift
      ;;
    --dry-run|--preview)
      MODE="dry-run"
      shift
      ;;
    --repeats)
      REPEATS="$2"
      shift 2
      ;;
    --platforms)
      PLATFORMS_CSV="$2"
      shift 2
      ;;
    --scales)
      SCALES_CSV="$2"
      shift 2
      ;;
    --queries)
      QUERIES="$2"
      shift 2
      ;;
    --phases)
      PHASES="$2"
      shift 2
      ;;
    --seed)
      SEED="$2"
      shift 2
      ;;
    --benchbox-cli)
      BENCHBOX_CLI="$2"
      shift 2
      ;;
    --output-root)
      OUTPUT_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! [[ "$REPEATS" =~ ^[0-9]+$ ]] || [[ "$REPEATS" -lt 1 ]]; then
  echo "Invalid --repeats value: $REPEATS" >&2
  exit 1
fi

if [[ ! -x "$BENCHBOX_CLI" ]]; then
  echo "BenchBox CLI not executable at: $BENCHBOX_CLI" >&2
  echo "Set --benchbox-cli or BENCHBOX_CLI to a valid path." >&2
  exit 1
fi

IFS=',' read -r -a PLATFORMS <<<"$PLATFORMS_CSV"
IFS=',' read -r -a SCALES <<<"$SCALES_CSV"

for s in "${SCALES[@]}"; do
  if ! awk "BEGIN { exit !($s >= 1) }"; then
    echo "Invalid scale factor for TPC-DS: $s (must be >= 1)" >&2
    exit 1
  fi
done

mkdir -p "$OUTPUT_ROOT"
RUN_ID="$(date +%Y%m%d_%H%M%S)"
PLAN_FILE="$OUTPUT_ROOT/platform_opt_matrix_plan_${RUN_ID}.txt"
RESULTS_FILE="$OUTPUT_ROOT/platform_opt_matrix_results_${RUN_ID}.tsv"

echo "# BenchBox CLI matrix plan" >"$PLAN_FILE"
echo "# generated_at=$(date -u +"%Y-%m-%dT%H:%M:%SZ")" >>"$PLAN_FILE"
echo "# benchmark=$BENCHMARK queries=$QUERIES phases=$PHASES seed=$SEED repeats=$REPEATS" >>"$PLAN_FILE"
echo >>"$PLAN_FILE"

if [[ "$MODE" == "execute" ]]; then
  echo -e "platform\tscale\trepeat\tresult_file" >"$RESULTS_FILE"
fi

append_plan_cmd() {
  printf '%q ' "$@" >>"$PLAN_FILE"
  printf '\n' >>"$PLAN_FILE"
}

print_cmd() {
  printf '[%s] ' "$MODE"
  printf '%q ' "$@"
  printf '\n'
}

run_one() {
  local platform="$1"
  local scale="$2"
  local -a cmd=(
    "$BENCHBOX_CLI" run
    --platform "$platform"
    --benchmark "$BENCHMARK"
    --scale "$scale"
    --phases "$PHASES"
    --queries "$QUERIES"
    --seed "$SEED"
    --non-interactive
    --quiet
  )

  # PySpark can fail preflight memory checks at SF1 in constrained environments.
  if [[ "$platform" == "pyspark-df" ]]; then
    cmd+=(--ignore-memory-warnings)
  fi

  if [[ "$MODE" == "dry-run" ]]; then
    printf '[%s x%s] ' "$MODE" "$REPEATS"
    printf '%q ' "${cmd[@]}"
    printf '\n'
    echo "# repeats=$REPEATS platform=$platform scale=$scale" >>"$PLAN_FILE"
    append_plan_cmd "${cmd[@]}"
    return
  fi

  append_plan_cmd "${cmd[@]}"
  for ((r = 1; r <= REPEATS; r++)); do
    printf '[%s %s/%s] ' "$MODE" "$r" "$REPEATS"
    printf '%q ' "${cmd[@]}"
    printf '\n'

    local out
    out="$("${cmd[@]}")"
    local result_file
    result_file="$(printf '%s\n' "$out" | tail -n 1)"
    echo -e "${platform}\t${scale}\t${r}\t${result_file}" >>"$RESULTS_FILE"
  done
}

matrix_points=0
for platform in "${PLATFORMS[@]}"; do
  for scale in "${SCALES[@]}"; do
    run_one "$platform" "$scale"
    matrix_points=$((matrix_points + 1))
  done
done

echo
echo "Matrix points: $matrix_points"
echo "Total runs: $((matrix_points * REPEATS))"
echo "Plan file: $PLAN_FILE"
if [[ "$MODE" == "execute" ]]; then
  echo "Results file: $RESULTS_FILE"
fi
