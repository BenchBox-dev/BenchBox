override BENCHBOX_MAKEFILE_ROOT := $(dir $(realpath $(lastword $(MAKEFILE_LIST))))

PR_FANOUT_JOBS ?= 4
PR_REVIEW_BASE ?= develop
PR_REVIEW_PR_LIMIT ?= 1000
PR_REVIEW_MAX_COMMENTS ?= 0
PR_REVIEW_INCLUDE_RESOLVED ?= 0
PR_REVIEW_INCLUDE_POST_MERGE ?= 0
PR_REVIEW_FAIL_ON_PENDING ?= 0
PR_REVIEW_EXECUTOR_SANDBOX ?= workspace-write
PR_REVIEW_EXECUTOR_APPROVAL ?= never
PR_STATUS_LIMIT ?= 20
PR_STATUS_ALL_OPEN_LIMIT ?= 1000
DEV_LOOP_METRICS_DAYS ?= 30
DEV_LOOP_METRICS_LIMIT ?= 100
AUDIT_SHA_TARGET_REF ?= origin/develop
AUDIT_SHA_REQUIRE_CURRENT ?=
JOINORDER_BUILD_DIR ?= $(HOME)/Developer/benchmark_runs/joinorder/build/joinorder-imdb-2013-v1
JOINORDER_POSTGRES_DB ?= imdb
JOINORDER_POSTGRES_USER ?= postgres
JOINORDER_QUERIES ?= _project/joinorder/build-inputs/queries
JOINORDER_REFERENCE ?= _project/joinorder/reference_cardinalities.json

DEVELOPMENT_TREE_ONLY_TARGETS := \
	correctness-gate-digests-regen cross-surface-baseline-autodetect \
	oracle-coverage-map oracle-coverage-map-check cross-surface-applicability-report \
	joinorder-verify-reference-results complexity-check complexity-report \
	quality-governance-typecheck uv-lock-revision-check sqlglot-repro-retirement-check audit-deps audit-raw audit-raw-check \
	audit-sha-check lint-explorer-tokens lint-site-theme-tokens lint-explorer-stale-theme \
	explorer-snapshot-check artifact-hygiene agent-instructions-check agent-identity-check security-audit \
	agent-commit-range-check skill-integrity-check ci-lint pr-arm-auto-merge shrink-rollup \
	pr-review-followups-list pr-review-followups dev-loop-metrics platform-manifest \
	platform-manifest-check test-docker-parity blind-spots-list blind-spots-report \
	soundness-drain-report soundness-drain-self-test worktree-audit worktree-finish

.PHONY: test test-unit test-integration test-tpch test-all test-fast test-unlock test-medium test-medium-selected test-slow test-stress test-pytest clean lint lint-markers lint-imports lint-explorer-tokens lint-site-theme-tokens artifact-hygiene agent-instructions-check agent-identity-check agent-commit-range-check audit-sha-check agent-write-preflight install develop coverage coverage-fast coverage-all coverage-opt-in-all coverage-html coverage-report coverage-check test-duckdb test-sqlite test-read-primitives test-benchmarks test-ci typecheck quality-governance-typecheck validate-imports catalog-schema-check format dependency-check docs-build docs-serve docs-clean docs-linkcheck docs-validate docs-check docs-images test-pyspark ci-lint ci-test ci-docs ci-local security-audit spellcheck test-package test-integration-smoke test-correctness-gate plan-capture-gate correctness-gate-digests-regen test-local-matrix joinorder-verify-reference-results complexity-check complexity-report duplicate-check duplicate-check-verbose duplicate-check-json duplicate-check-delta makefile-inventory-check skill-sync skill-sync-check mutation-test tpchavoc-equivalence-report tpchavoc-equivalence-report-postgres tpchavoc-equivalence-report-datafusion tpchavoc-equivalence-report-clickhouse tpchavoc-dataframe-equivalence-report ssb-cross-surface-equivalence-report amplab-cross-surface-equivalence-report coffeeshop-cross-surface-equivalence-report clickbench-cross-surface-equivalence-report joinorder-synthetic-cross-surface-equivalence-report h2odb-cross-surface-equivalence-report read-primitives-cross-surface-equivalence-report cross-surface-update-baseline cross-surface-baseline-autodetect oracle-coverage-map oracle-coverage-map-check cross-surface-applicability-report compile-tpcds-binaries parity-fixtures parity-check compat-docs compat-docs-check query-docs platform-manifest platform-manifest-check pricing-data pricing-data-check pr-preflight pr-preflight-fast-tests pr-preflight-medium-tests pr-content-guard pr-open pr-ready pr-arm-auto-merge pr-status pr-review-followups pr-review-followups-list dev-loop-metrics shrink-rollup worktree-create worktree-remove worktree-list worktree-audit local-validation local-validation-show local-validation-path

test: test-fast
	@echo "Default test run completed. Use 'make help' to see all test options."

$(DEVELOPMENT_TREE_ONLY_TARGETS): .development-tree-required

.PHONY: .development-tree-required
.development-tree-required:
	@if [ ! -d "$(BENCHBOX_MAKEFILE_ROOT)_project/decisions" ]; then \
		echo "Error: this target requires the BenchBox development tree (full development tree required); curated releases retain only the Results Explorer publication helpers under _project/scripts/." >&2; \
		exit 2; \
	fi

.PHONY: publication-help
publication-help:
	@echo "Publication flow:"
	@echo "  1. gh workflow run publication-deploy.yml --ref develop -f candidate_only=true"
	@echo "  2. Select the numeric artifact ID from that run."
	@echo "  3. gh workflow run publication-transaction.yml --ref develop -f kind=promotion -f candidate_artifact_id=<id>"
	@echo "  4. Approve the github-pages environment once; the workflow validates and records the result."
	@echo "  Retry with a new transaction run against the same artifact after a pre-write failure."

test-all:
	@echo "Running non-resource-heavy tests in parallel..."
	BENCHBOX_TEST_TIER=t2 uv run -- python -m pytest -m "not (slow or stress or resource_heavy or live_integration)" --timeout=300
	@echo "Running slow and resource-heavy tests serially..."
	BENCHBOX_TEST_TIER=t3 uv run -- python -m pytest -m "(slow or resource_heavy) and not (stress or live_integration)" -n 0 --timeout=1200

test-unit:
	BENCHBOX_TEST_TIER=t2 uv run -- python -m pytest -m "unit" --tb=short

test-integration:
	BENCHBOX_TEST_TIER=t2 uv run -- python -m pytest -m "integration and not live_integration and not stress" --tb=short

test-tpch:
	BENCHBOX_TEST_TIER=t2 uv run -- python -m pytest -m "tpch" --tb=short

test-quick:
	BENCHBOX_TEST_TIER=t1 uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short --maxfail=5 --timeout=120

test-verbose:
	BENCHBOX_TEST_TIER=t3 uv run -- python -m pytest -v

test-pytest:
	BENCHBOX_TEST_TIER=t2 uv run -- python -m pytest -m "not stress"

test-fast:
	BENCHBOX_TEST_TIER=t1 uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=120

test-unlock:
	@LOCK_DIR="$${BENCHBOX_TEST_LOCK_DIR:-$$HOME/.benchbox}"; \
	case "$$LOCK_DIR" in \
		"~") LOCK_DIR="$$HOME" ;; \
		"~/"*) LOCK_DIR="$$HOME/$${LOCK_DIR#\~/}" ;; \
	esac; \
	LOCK_PATH="$$LOCK_DIR/test.lock"; \
	python3 scripts/local_validation.py clear-test-lock "$$LOCK_PATH"

test-medium:
	BENCHBOX_TEST_TIER=t2 uv run -- python -m pytest -m "medium and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=60 -n 5

test-medium-selected:
	@set -eu; \
	OUTPUT=$$(mktemp); \
	trap 'rm -f "$$OUTPUT"' EXIT; \
	BENCHBOX_TEST_TIER=t2 uv run -- python scripts/canary_impact.py \
		--changed-json-env BENCHBOX_MEDIUM_CHANGED_PATHS_JSON \
		--marker-expression "medium and not (slow or stress or resource_heavy or live_integration)" --cant-affect-list empty \
		--product-code-only --run-selected --output "$$OUTPUT"

test-slow:
	BENCHBOX_TEST_TIER=t3 uv run -- python -m pytest -m "slow and not (stress or live_integration)" -n 0 --tb=short -v --timeout=1200

test-stress:
	BENCHBOX_TEST_TIER=t3 uv run -- python -m pytest -m "stress" -n 0 --tb=short -v --timeout=1800

test-dev:
	BENCHBOX_TEST_TIER=t1 uv run -- python -m pytest -m "fast and unit and not (slow or stress or resource_heavy or live_integration)" --tb=short --maxfail=3 --timeout=120

test-smoke: test-quick

CORRECTNESS_GATE_QUERY_IDS := 1,2,3,4,5,6,7,8,9,10,12,13,14,15,17,19,21,22

test-correctness-gate:
	@REPORT="$$(mktemp)"; \
	BENCHBOX_STRICT_EXPECTED_RESULTS=1 BENCHBOX_EMIT_RESULT_DIGEST=1 BENCHBOX_CORRECTNESS_GATE_QUERY_IDS=$(CORRECTNESS_GATE_QUERY_IDS) uv run -- python -m pytest -m stress "tests/integration/test_local_platform_benchmark_matrix.py::test_local_platform_benchmark_matrix[tpch-duckdb]" -n 0 --tb=short --timeout=1200 -v --junitxml="$$REPORT"; \
	PYTEST_STATUS=$$?; \
	uv run -- python -c "import sys, xml.etree.ElementTree as ET; root = ET.parse(sys.argv[1]).getroot(); suites = [root] if root.tag == 'testsuite' else root.findall('testsuite'); tests = sum(int(s.get('tests') or 0) for s in suites); skipped = sum(int(s.get('skipped') or 0) for s in suites); errors = sum(int(s.get('errors') or 0) for s in suites); failures = sum(int(s.get('failures') or 0) for s in suites); print('correctness gate guard: ran=%d skipped=%d failures=%d errors=%d' % (tests, skipped, failures, errors)); sys.exit(0 if (tests == 1 and skipped == 0 and errors == 0 and failures == 0) else 'correctness gate: expected exactly 1 node to run with 0 skipped/failed/errored; a selected skip means duckdb/tpch dropped from the stable matrix or the node-id drifted')" "$$REPORT"; \
	GUARD_STATUS=$$?; \
	rm -f "$$REPORT"; \
	test $$PYTEST_STATUS -eq 0 && test $$GUARD_STATUS -eq 0

plan-capture-gate:
	uv run -- python -m pytest tests/integration/test_plan_capture_gate.py -q -n 0 --tb=short

correctness-gate-digests-regen:
	BENCHBOX_CORRECTNESS_GATE_QUERY_IDS=$(CORRECTNESS_GATE_QUERY_IDS) uv run -- python _project/scripts/regenerate_correctness_gate_digests.py

tpchavoc-equivalence-report:
	uv run -- python -m benchbox.core.tpchavoc.equivalence

tpchavoc-equivalence-report-postgres:
	uv run -- python -m benchbox.core.tpchavoc.equivalence --engine postgres

tpchavoc-equivalence-report-datafusion:
	uv run -- python -m benchbox.core.tpchavoc.equivalence --engine datafusion

tpchavoc-equivalence-report-clickhouse:
	uv run -- python -m benchbox.core.tpchavoc.equivalence --engine clickhouse

tpchavoc-dataframe-equivalence-report:
	uv run -- python -m benchbox.core.tpchavoc.dataframe_equivalence

ssb-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark ssb

amplab-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark amplab

coffeeshop-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark coffeeshop

clickbench-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark clickbench

joinorder-synthetic-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark joinorder_synthetic

h2odb-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark h2odb

read-primitives-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark read_primitives

flightdata-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark flightdata

datavault-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark datavault

nyctaxi-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark nyctaxi

tsbs-devops-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark tsbs_devops

tpch-skew-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark tpch_skew

tpch-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark tpch

tpcds-cross-surface-equivalence-report:
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark tpcds

cross-surface-update-baseline:
	@test -n "$(BENCHMARK)" || { echo "Usage: make cross-surface-update-baseline BENCHMARK=<ssb|amplab|coffeeshop|clickbench|joinorder_synthetic|h2odb|read_primitives|flightdata|datavault>"; exit 1; }
	uv run -- python -m benchbox.core.equivalence.cross_surface --benchmark $(BENCHMARK) --update-baseline

cross-surface-baseline-autodetect:
	uv run -- python _project/scripts/cross_surface_baseline_autodetect.py \
		--json-out _project/cross-surface-baseline-autodetect/summary.json

oracle-coverage-map:
	uv run -- python _project/scripts/generate_oracle_coverage_map.py

oracle-coverage-map-check:
	uv run -- python _project/scripts/generate_oracle_coverage_map.py --check

cross-surface-applicability-report:
	uv run -- python _project/scripts/cross_surface_applicability_sweep.py

test-local-matrix:
	uv run -- python -m pytest tests/integration/test_local_platform_benchmark_matrix.py -m stress -n 0 --tb=short -v
	@echo "Tip: set BENCHBOX_SERVICE_LOCAL_MATRIX=1 to include Trino/Presto/Firebolt/PostgreSQL/TimescaleDB service-backed locals."

joinorder-verify-reference-results:
	@[ -n "$(JOINORDER_POSTGRES_CONTAINER)" ] || { echo "JOINORDER_POSTGRES_CONTAINER is required"; exit 2; }
	uv run -- python _project/scripts/build_joinorder_data.py verify-reference-results \
		--work-dir "$(JOINORDER_BUILD_DIR)" \
		--container-name "$(JOINORDER_POSTGRES_CONTAINER)" \
		--database "$(JOINORDER_POSTGRES_DB)" \
		--user "$(JOINORDER_POSTGRES_USER)" \
		--queries "$(JOINORDER_QUERIES)" \
		--reference "$(JOINORDER_REFERENCE)"

test-duckdb:
	uv run -- python -m pytest -m "duckdb" --tb=short

test-sqlite:
	uv run -- python -m pytest -m "sqlite" --tb=short

test-pyspark:
	./scripts/run_pyspark_tests.sh

test-read-primitives:
	uv run -- python -m pytest -m "primitives" --tb=short

test-benchmarks:
	uv run -- python -m pytest -m "tpch or tpcds or ssb or amplab or clickbench or h2odb or merge" --tb=short

test-tpcds:
	uv run -- python -m pytest -m "tpcds" --tb=short

test-olap:
	uv run -- python -m pytest -m "olap" --tb=short

test-window:
	uv run -- python -m pytest -m "window_functions" --tb=short

test-ci:
	uv run -- python -m pytest -c pytest-ci.ini -m "not (slow or stress or resource_heavy or live_integration)" --cov=benchbox --cov-report=term-missing:skip-covered --cov-report=xml:coverage.xml --cov-fail-under=0 --timeout=300

test-no-cloud:
	uv run -- python -m pytest -m "not (slow or cloud_import)" --ignore=tests/unit/platforms/databricks --ignore=tests/unit/platforms/snowflake --ignore=tests/unit/platforms/bigquery --ignore=tests/unit/platforms/redshift --tb=short

test-full:
	uv run -- python -m pytest -m "not stress" --tb=short -v

test-parallel:
	uv run -- python -m pytest -n auto --tb=short

test-parallel-fast:
	uv run -- python -m pytest -n auto -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=120

include $(BENCHBOX_MAKEFILE_ROOT)make/platform-tests.mk

coverage-fast:
	uv run -- python -m pytest -c pytest-ci.ini -m "fast and not (slow or stress or resource_heavy or live_integration or cloud_import)" --cov=benchbox --cov-report=term-missing:skip-covered --cov-fail-under=0 --timeout=120

coverage-all:
	uv run -- python -m pytest -c pytest-ci.ini -m "not (stress or resource_heavy or live_integration)" --cov=benchbox --cov-branch --cov-report=term-missing:skip-covered --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=0

coverage-opt-in-all:
	uv run -- python -m pytest -c pytest-ci.ini --cov=benchbox --cov-branch --cov-report=term-missing:skip-covered --cov-report=html:htmlcov --cov-report=xml:coverage.xml --cov-fail-under=0

coverage: coverage-all

coverage-html:
	uv run -- python -m pytest -c pytest-ci.ini -m "not (stress or resource_heavy or live_integration)" --cov=benchbox --cov-report=html:htmlcov --cov-fail-under=0

coverage-report:
	uv run -- python -m pytest -c pytest-ci.ini -m "not (stress or resource_heavy or live_integration)" --cov=benchbox --cov-report=xml:coverage.xml --cov-report=term-missing --cov-fail-under=0


complexity-check:
	uv run -- python _project/scripts/check_complexity.py

complexity-report:
	uv run -- python _project/scripts/check_complexity.py --no-fail --top 30

quality-governance-typecheck:
	uv run ty check --error all _project/scripts/check_complexity.py

install:
	uv sync

develop:
	uv sync --group dev

clean:
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info/
	rm -rf __pycache__/
	rm -rf .pytest_cache/
	rm -rf .coverage
	rm -rf htmlcov/
	find . -name '*.pyc' -delete
	find . -name '__pycache__' -delete
	find . -name '*.pyo' -delete
	find . -name '.DS_Store' -delete

lint:
	uv run ruff check .
	$(MAKE) comment-policy-check
	$(MAKE) windows-antipatterns-check
	$(MAKE) lint-explorer-tokens
	$(MAKE) lint-site-theme-tokens

.PHONY: uv-lock-revision-check
uv-lock-revision-check:
	uv run -- python _project/scripts/check_uv_lock_revision.py $(if $(BASE_REF),--baseline-ref "$(BASE_REF)",)

.PHONY: sqlglot-repro-retirement-check
sqlglot-repro-retirement-check:
	uv run -- python scripts/check_sqlglot_repro_retirement.py $(if $(BASE_REF),--base-ref "$(BASE_REF)",) --check

audit-deps:
	uv run -- python _project/scripts/dependency_audit/check_deps.py

audit-raw:
	uv run -- python _project/scripts/dependency_audit/parse_deps.py

audit-raw-check:
	uv run -- python _project/scripts/dependency_audit/parse_deps.py --check

audit-sha-check:
	@test -n "$(FILE)" || { echo "Usage: make audit-sha-check FILE=<audit.md>"; exit 1; }
	uv run --no-project -- python _project/scripts/audit_sha_check.py \
		--target-ref "$(AUDIT_SHA_TARGET_REF)" \
		--ancestry-ref "$(or $(AUDIT_SHA_ANCESTRY_REF),HEAD)" \
		$(if $(AUDIT_SHA_REQUIRE_CURRENT),--require-current $(AUDIT_SHA_REQUIRE_CURRENT),) \
		"$(FILE)"

.PHONY: windows-antipatterns-check
windows-antipatterns-check:
	uv run -- python scripts/check_windows_antipatterns.py

.PHONY: comment-policy-check comment-policy-strict comment-policy-report
comment-policy-check:
	uv run -- python scripts/run_comment_policy.py --native-tests

comment-policy-strict:
	uv run -- python scripts/check_comment_policy.py --mode strict

comment-policy-report:
	uv run -- python scripts/check_comment_policy.py --mode report

lint-markers:
	uv run -- python -m pytest --collect-only -q -p no:warnings
	uv run -- python -m pytest tests/unit/test_marker_strategy.py -q

lint-imports:
	uv run -- lint-imports

lint-explorer-tokens:
	python3 _project/scripts/scan_explorer_tokens.py

lint-site-theme-tokens:
	python3 _project/scripts/scan_explorer_tokens.py landing/shared landing/index.html landing/style.css landing/prompts/index.html landing/prompts/prompts.css docs/_templates/page.html docs/_static/custom.css results-explorer/index.html results-explorer/src/components/Layout.tsx

lint-explorer-stale-theme:
	python3 _project/scripts/scan_explorer_stale_theme.py

SNAPSHOT ?= results-explorer/public/data/results.duckdb
.PHONY: explorer-snapshot-check
explorer-snapshot-check:
	uv run -- python _project/scripts/results_explorer_snapshot_invariants.py "$(SNAPSHOT)"

artifact-hygiene:
	uv run -- python _project/scripts/artifact_hygiene_check.py --all-tracked

agent-instructions-check:
	uv run -- python _project/scripts/agent_instruction_audit.py

agent-identity-check:
	uv run -- python _project/scripts/agent_instruction_audit.py --check-git-identity

AGENT_IDENTITY_BASE_REF ?= origin/develop
agent-commit-range-check:
	@git fetch origin $(patsubst origin/%,%,$(AGENT_IDENTITY_BASE_REF)) --quiet 2>/dev/null || true
	uv run -- python _project/scripts/agent_instruction_audit.py --check-commit-range $(AGENT_IDENTITY_BASE_REF)

SKILL_SYNC ?= tools/skill-sync

skill-sync:
	@dry_run=""; \
	for flag_word in $(MAKEFLAGS); do \
		case "$$flag_word" in \
			n|-n|--dry-run|--just-print) dry_run=1; break ;; \
			-*) ;; \
			*n*) case "$$flag_word" in *[!a-zA-Z]*) ;; *) dry_run=1; break ;; esac ;; \
		esac; \
	done; \
	if [ -n "$$dry_run" ]; then echo "dry-run (-n): skipping skill-sync"; exit 0; fi; \
	if [ ! -x "$(SKILL_SYNC)" ]; then \
		echo "skill-sync wrapper not found or not executable at $(SKILL_SYNC); refusing to report success without syncing (override with SKILL_SYNC=path/to/skill-sync)" >&2; \
		exit 1; \
	fi; \
	$(MAKE) -s agent-write-preflight && \
	"$(SKILL_SYNC)" apply && \
	cp .claude/skills/skill-sync.config.yaml .agents/skills/skill-sync.config.yaml

skill-sync-check:
	@if [ ! -x "$(SKILL_SYNC)" ]; then \
		echo "skill-sync wrapper not found or not executable at $(SKILL_SYNC); cannot verify the mirror (override with SKILL_SYNC=path/to/skill-sync)" >&2; \
		exit 1; \
	fi
	@tmp=$$(mktemp); \
	"$(SKILL_SYNC)" preview >"$$tmp" || { rc=$$?; rm -f "$$tmp"; exit $$rc; }; \
	drift=""; \
	while IFS= read -r row; do \
		case "$$row" in "A "*|"M "*|"D "*|"R "*) ;; *) continue ;; esac; \
		path="$${row#? }"; \
		case "$$path" in ./*) path="$${path#./}";; esac; \
		case "$$path" in .agents/skills/*|.claude/skills/blog/*) continue;; esac; \
		drift="$$drift$$row\n"; \
	done <"$$tmp"; \
	rm -f "$$tmp"; \
	if [ -n "$$drift" ]; then \
		echo "skill-sync-check: tracked mirror drifts from skill-sync.conf:" >&2; \
		printf '%b' "$$drift" >&2; \
		exit 3; \
	fi; \
	echo "skill-sync-check: tracked mirror up to date."

skill-integrity-check:
	@set -eu; \
	uv run -- python scripts/skill_sync_ci_policy.py validate --manifest skill-sync.conf; \
	"$(SKILL_SYNC)" verify; \
	sh scripts/check_untracked_skill_mirrors.sh; \
	$(MAKE) agent-instructions-check; \
	$(MAKE) agent-identity-check; \
	$(MAKE) agent-commit-range-check; \
	$(MAKE) artifact-hygiene

duplicate-check:
	uv run -- python scripts/check_duplicate_code.py

duplicate-check-verbose:
	uv run -- python scripts/check_duplicate_code.py --verbose --top-n 30

duplicate-check-json:
	uv run -- python scripts/check_duplicate_code.py --json

duplicate-check-delta:
	uv run -- python scripts/check_duplicate_code.py --delta-vs "$(if $(BASE_REF),$(BASE_REF),origin/develop)"

makefile-inventory-check:
	uv run -- python make/check_makefile_inventory.py

mutation-test:
	@echo "Running mutation tests on critical modules..."
	uv run -- mutmut run
	@echo "--- Mutation test results ---"
	uv run -- mutmut results

.PHONY: guards-fix
guards-fix:
	@echo "== guards-fix: regenerating every mechanically-regenerable drift-guard artifact =="
	@$(MAKE) -s agent-write-preflight
	@echo "-- dependency inventory (audit-raw) --"
	@$(MAKE) -s audit-raw
	@echo "-- benchmark correctness-oracle coverage map --"
	@$(MAKE) -s oracle-coverage-map
	@echo "-- visualization parity fixtures --"
	@$(MAKE) -s parity-fixtures
	@echo "-- sql_compat capability matrix / skip-reference docs --"
	@$(MAKE) -s compat-docs
	@echo "-- vendor-derived pricing tables (offline, from checked-in evidence) --"
	@$(MAKE) -s pricing-data
	@echo "-- Makefile public contract inventory --"
	@uv run -- python make/check_makefile_inventory.py --write
	@echo "-- skill-sync (fail-closed: a missing wrapper aborts instead of no-op-ing) --"
	@status=0; $(MAKE) -s skill-sync || status=$$?; \
	if [ "$$status" -ne 0 ]; then \
		echo "guards-fix: WARNING - the skill-sync step FAILED (see its output above); every other drift-guard artifact was still regenerated. Fix and re-run 'make skill-sync' separately."; \
	fi; \
	echo ""; \
	echo "No regen mode -- these are reviewed hand edits, guards-fix does not touch them:"; \
	echo "  - module-size guard: tests/system/test_module_size_thresholds.py (see its failure output for the ALLOWLIST entry to paste)"; \
	echo "  - DDL governance drift: benchbox/sql_compat/inventory.py --check-ddl-drift (register the transform, alias it, or exempt it)"; \
	echo "  - release curation list: scripts/check_release_curation.py (classify the path as main-only or release-cut curated)"; \
	echo ""; \
	echo "== guards-fix done. Review the diff below, then commit what you intend to keep. =="; \
	git status --porcelain; \
	exit "$$status"

ci-lint:
	@echo "Running CI lint checks..."
	@case " $(MAKEFLAGS) " in *" n "*|*" -n "*|*" --just-print "*) echo "Dry-run: ci-lint guards suppressed"; exit 0;; esac; \
	set +e; failed=""; \
	uv run ruff check .; \
	[ $$? -eq 0 ] || failed="$$failed ruff-check"; \
	uv run ruff format --check .; \
	[ $$? -eq 0 ] || failed="$$failed ruff-format"; \
	uv run ty check; \
	[ $$? -eq 0 ] || failed="$$failed ty-check"; \
	$(MAKE) quality-governance-typecheck; \
	[ $$? -eq 0 ] || failed="$$failed quality-governance-typecheck"; \
	$(MAKE) uv-lock-revision-check; \
	[ $$? -eq 0 ] || failed="$$failed uv-lock-revision"; \
	$(MAKE) sqlglot-repro-retirement-check; \
	[ $$? -eq 0 ] || failed="$$failed sqlglot-repro-retirement"; \
	$(MAKE) lint-markers; \
	[ $$? -eq 0 ] || failed="$$failed lint-markers"; \
	$(MAKE) lint-imports; \
	[ $$? -eq 0 ] || failed="$$failed lint-imports"; \
	$(MAKE) windows-antipatterns-check; \
	[ $$? -eq 0 ] || failed="$$failed windows-antipatterns"; \
	$(MAKE) comment-policy-check; \
	[ $$? -eq 0 ] || failed="$$failed comment-policy"; \
	$(MAKE) lint-explorer-tokens; \
	[ $$? -eq 0 ] || failed="$$failed lint-explorer-tokens"; \
	$(MAKE) lint-site-theme-tokens; \
	[ $$? -eq 0 ] || failed="$$failed lint-site-theme-tokens"; \
	$(MAKE) artifact-hygiene; \
	[ $$? -eq 0 ] || failed="$$failed artifact-hygiene"; \
	$(MAKE) agent-instructions-check; \
	[ $$? -eq 0 ] || failed="$$failed agent-instructions"; \
	GATE=$$(uv run -- python _project/scripts/ci_lint_environment_gate.py agent-identity || true); \
	if [ "$$GATE" != "SKIP" ]; then \
		$(MAKE) agent-identity-check; \
		[ $$? -eq 0 ] || failed="$$failed agent-identity"; \
	fi; \
	$(MAKE) agent-commit-range-check; \
	[ $$? -eq 0 ] || failed="$$failed agent-commit-range"; \
	GATE=$$(uv run -- python _project/scripts/ci_lint_environment_gate.py skill-sync-check || true); \
	if [ "$$GATE" != "SKIP" ]; then \
		$(MAKE) skill-sync-check; \
		[ $$? -eq 0 ] || failed="$$failed skill-sync-check"; \
	fi; \
	uv run -- python _project/scripts/timing_policy_check.py --strict; \
	[ $$? -eq 0 ] || failed="$$failed timing-policy"; \
	uv run -- python _project/scripts/fast_lane_ceiling_check.py --strict; \
	[ $$? -eq 0 ] || failed="$$failed fast-lane-ceiling"; \
	uv run --project _project/scripts --no-sync -- python _project/scripts/uat_loc_table.py --check; \
	[ $$? -eq 0 ] || failed="$$failed uat-loc-table"; \
	$(MAKE) compat-docs-check; \
	[ $$? -eq 0 ] || failed="$$failed compat-docs-check"; \
	$(MAKE) platform-manifest-check; \
	[ $$? -eq 0 ] || failed="$$failed platform-manifest-check"; \
	$(MAKE) oracle-coverage-map-check; \
	[ $$? -eq 0 ] || failed="$$failed oracle-coverage-map-check"; \
	$(MAKE) pricing-data-check; \
	[ $$? -eq 0 ] || failed="$$failed pricing-data-check"; \
	$(MAKE) makefile-inventory-check; \
	[ $$? -eq 0 ] || failed="$$failed makefile-inventory-check"; \
	uv run -- python scripts/check_public_contract_drift.py; \
	[ $$? -eq 0 ] || failed="$$failed public-contract-drift"; \
	$(MAKE) audit-deps; \
	[ $$? -eq 0 ] || failed="$$failed audit-deps"; \
	$(MAKE) audit-raw-check; \
	[ $$? -eq 0 ] || failed="$$failed audit-raw-check"; \
	uv run -- python scripts/check_release_curation.py; \
	[ $$? -eq 0 ] || failed="$$failed release-curation"; \
	sh scripts/check_untracked_skill_mirrors.sh; \
	[ $$? -eq 0 ] || failed="$$failed skill-mirror-drift"; \
	$(MAKE) duplicate-check-delta; \
	[ $$? -eq 0 ] || failed="$$failed duplicate-delta"; \
	$(MAKE) complexity-check; \
	[ $$? -eq 0 ] || failed="$$failed complexity-check"; \
	$(MAKE) spellcheck; \
	[ $$? -eq 0 ] || failed="$$failed spellcheck"; \
	uv run -- python scripts/check_rerun_shard_retention.py; \
	[ $$? -eq 0 ] || failed="$$failed rerun-shard-retention"; \
	uv run -- python _project/scripts/check_project_references.py; \
	[ $$? -eq 0 ] || failed="$$failed project-references"; \
	if [ -n "$$failed" ]; then \
		echo ""; \
		echo "❌ FAILED guards:$$failed"; \
		exit 1; \
	fi; \
	echo "✅ CI lint checks passed"

ci-test:
	@echo "Running CI test suite..."
	uv run -- python -m pytest tests -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=120 -p pytest_cov --cov=benchbox --cov-report=xml:coverage.xml --cov-report=term-missing --cov-fail-under=70
	@echo "✅ CI test suite passed"

ci-docs:
	@echo "Running CI docs checks..."
	@$(MAKE) docs-validate
	@cd docs && uv run sphinx-build -b html -W --keep-going . _build/html
	@echo "✅ CI docs build passed"

security-audit:
	@echo "Running security audit..."
	@if [ -n "$(PIP_AUDIT_IGNORE_VULNS)" ]; then \
		IGNORE_ARGS=$$(printf '%s' "$(PIP_AUDIT_IGNORE_VULNS)" | tr ',' '\n' | sed '/^$$/d;s/^/--ignore-vuln /' | tr '\n' ' '); \
		uvx pip-audit $$IGNORE_ARGS; \
	else \
		uvx pip-audit; \
	fi
	@echo "✅ Security audit passed"

SPELLCHECK_SKIP_GLOBS := *.pyc,*.json,*.lock,*.svg,*.min.js,*.min.css,*.tpl,*.dst,*.tbl,*.dat,*.pdf
SPELLCHECK_EXCLUDE_PATHS := \
	':(exclude,glob).*'             ':(exclude,glob).*/**' \
	':(exclude,glob)**/.*'          ':(exclude,glob)**/.*/**' \
	':(exclude,glob)**/_binaries/**' ':(exclude,glob)_binaries/**' \
	':(exclude,glob)**/_sources/**'  ':(exclude,glob)_sources/**' \
	':(exclude,glob)**/_project/**'  ':(exclude,glob)_project/**' \
	':(exclude,glob)**/_blog/**'     ':(exclude,glob)_blog/**'

spellcheck:
	@echo "Running spellcheck..."
	git ls-files -z -- $(SPELLCHECK_EXCLUDE_PATHS) \
		| xargs -0 uvx codespell --ignore-words=.codespell-ignore.txt --skip="$(SPELLCHECK_SKIP_GLOBS)"
	@echo "✅ Spellcheck passed"

ci-linkcheck:
	@echo "Running documentation link check..."
	@cd docs && uv run sphinx-build -b linkcheck . _build/linkcheck
	@echo "Link check results:"
	@cat docs/_build/linkcheck/output.txt 2>/dev/null || echo "No output file generated"
	@echo "✅ Linkcheck passed"

test-package:
	@echo "Building and testing package installation..."
	rm -rf dist/
	uv build
	uvx twine check dist/*
	@echo "Testing package installation..."
	@wheel_count=$$(find "$$PWD/dist" -maxdepth 1 -type f -name '*.whl' | wc -l | tr -d '[:space:]'); \
	if [ "$$wheel_count" != "1" ]; then \
		echo "Expected exactly one wheel, found $$wheel_count"; \
		find "$$PWD/dist" -maxdepth 1 -type f -print; \
		exit 1; \
	fi; \
	wheel=$$(find "$$PWD/dist" -maxdepth 1 -type f -name '*.whl' -print -quit); \
	tmpdir=$$(mktemp -d); \
	trap 'rm -rf "$$tmpdir"' EXIT; \
	cd "$$tmpdir"; \
	uv run --isolated --no-project --with "$$wheel" -- python -c "import benchbox; print('Package installation successful')"; \
	uv run --isolated --no-project --with "$$wheel" -- benchbox --help > /dev/null
	@echo "✅ Package test passed"

test-integration-smoke:
	@echo "Running integration smoke tests..."
	uv run -- python -m pytest tests/integration -m "platform_smoke or (integration and fast)" --tb=short
	@echo "✅ Integration smoke tests passed"

ci-local:
	@echo "========================================"
	@echo "Running all CI checks locally..."
	@echo "========================================"
	@echo ""
	@echo "Step 1/5: Lint checks..."
	@$(MAKE) ci-lint
	@echo ""
	@echo "Step 2/5: Fast tests with coverage..."
	@$(MAKE) ci-test
	@echo ""
	@echo "Step 3/5: Integration smoke tests..."
	@$(MAKE) test-integration-smoke
	@echo ""
	@echo "Step 4/5: Documentation build..."
	@$(MAKE) ci-docs
	@echo ""
	@echo "Step 5/5: Package build..."
	@$(MAKE) test-package
	@echo ""
	@echo "========================================"
	@echo "✅ All CI checks passed!"
	@echo "========================================"

CI_LINUX_MACHINE ?= benchbox-agent
CI_LINUX_CMD ?= make test-correctness-gate
.PHONY: ci-linux
ci-linux:
	@if [ "$$(uname -s)" != "Darwin" ] || [ "$$(uname -m)" != "arm64" ]; then \
		echo "ci-linux: skipped -- Apple silicon macOS only (host $$(uname -s)/$$(uname -m)); no-op."; \
		exit 0; \
	fi; \
	if [ "$$(sw_vers -productVersion | cut -d. -f1)" -lt 26 ]; then \
		echo "ci-linux: skipped -- needs macOS 26+ (host $$(sw_vers -productVersion)); no-op."; \
		exit 0; \
	fi; \
	if ! command -v container >/dev/null 2>&1; then \
		echo "ci-linux: Apple 'container' not installed -> 'brew install container'."; \
		exit 1; \
	fi; \
	if ! container machine list 2>/dev/null | awk 'NR>1{print $$1}' | grep -Fqx "$(CI_LINUX_MACHINE)"; then \
		echo "ci-linux: machine '$(CI_LINUX_MACHINE)' not found. One-time setup:"; \
		echo "  container system start"; \
		echo "  container build --arch arm64 --tag local/benchbox-agent docker/benchbox-agent"; \
		echo "  container machine create local/benchbox-agent --name $(CI_LINUX_MACHINE) --home-mount rw --cpus 4 --memory 8G"; \
		exit 1; \
	fi; \
	echo "==> ci-linux: '$(CI_LINUX_CMD)' inside container machine '$(CI_LINUX_MACHINE)'"; \
	container machine run -n $(CI_LINUX_MACHINE) -- bash -lc 'cd "$(CURDIR)" && $(CI_LINUX_CMD)'

typecheck:
	uv run ty check

typecheck-uv: typecheck

validate-imports: lint-imports

catalog-schema-check:
	uv run -- python -m benchbox.core.catalog_schema

dependency-check:
	uv run -- python -m benchbox.utils.dependency_validation $(ARGS)
format:
	uv run ruff format .

include $(BENCHBOX_MAKEFILE_ROOT)make/documentation.mk


dist: clean
	uv build

run-test:
	uv run -- python $(TEST)

RELEASE_REQUIRED_CONTEXTS := validate-base release-required-result

.PHONY: release-cut release-cut-abort release-finalize .release-cut-tree-required

.release-cut-tree-required:
	@if [ -z "$(VERSION)" ]; then \
		echo "Usage: make release-cut VERSION=X.Y.Z" >&2; \
		exit 1; \
	fi; \
	if [ ! -d "$(BENCHBOX_MAKEFILE_ROOT)_project/decisions" ]; then \
		BRANCH=$$(git rev-parse --abbrev-ref HEAD 2>/dev/null || true); \
		if [ "$$BRANCH" != "v$(VERSION)" ]; then \
			echo "Error: release-cut requires the BenchBox development tree unless resuming v$(VERSION) after curation." >&2; \
			exit 2; \
		fi; \
	fi

release-cut: .release-cut-tree-required
	@test -n "$(VERSION)" || (echo "Usage: make release-cut VERSION=X.Y.Z" && exit 1)
	sh scripts/release_cut_start.sh "$(VERSION)"
	uv run -- python scripts/update_version.py --version $(VERSION) --update-pyproject
	uv lock
	uv run -- python scripts/generate_changelog_entry.py --version $(VERSION) --since-ref origin/release
	@if [ -n "$$EDITOR" ] && [ -t 0 ]; then \
		echo "==> Opening CHANGELOG.md in $$EDITOR for hand-curation"; \
		$$EDITOR CHANGELOG.md; \
	else \
		echo "==> Non-interactive: CHANGELOG.md holds the raw generated draft."; \
		echo "    Hand-curate the [$(VERSION)] section, then re-run: make release-cut VERSION=$(VERSION)"; \
	fi
	uv run -- python scripts/generate_changelog_entry.py --check-curation --version $(VERSION)
	git rm -rf --ignore-unmatch _project ':(exclude)_project/scripts/explorer_pipeline/**' ':(exclude)_project/scripts/explorer_publish.py' ':(exclude)_project/scripts/results_explorer_snapshot_invariants.py' _blog .claude .codex .gemini tools
	git rm -f --ignore-unmatch .pre-commit-config.yaml .importlinter todo.config.yaml skill-sync.conf .gitattributes .coveragerc_core .dockerignore .env.example .mcp.json AGENTS.md CLAUDE.md GEMINI.md ANTIGRAVITY.md
	git rm -f --ignore-unmatch .github/workflows/results-explorer-browser.yml .github/workflows/seed-corpus.yml .github/workflows/sync-results-data-to-published.yml .github/workflows/validate-submission.yml
	git rm -rf --ignore-unmatch tests/unit/scripts/explorer_pipeline tests/unit/explorer
	git rm -f --ignore-unmatch tests/uat/test_explorer_smoke.py tests/unit/release/test_ruleset_drift_review_coverage.py tests/unit/release/test_ruleset_review_enforcement.py tests/unit/scripts/test_blind_spot_tools.py tests/unit/scripts/test_build_joinorder_data.py tests/unit/scripts/test_check_complexity.py tests/unit/scripts/test_explorer_build_contract.py tests/unit/scripts/test_pr_review_followups.py tests/unit/scripts/test_reference_usage_audit.py tests/unit/scripts/test_scan_explorer_stale_theme.py tests/unit/scripts/test_scan_explorer_tokens.py tests/unit/scripts/test_shrink_rollup.py tests/unit/scripts/test_submission_workflow_waiver.py tests/unit/test_agent_write_preflight.py tests/unit/test_auto_merge_soundness_paths.py tests/unit/test_cross_surface_applicability.py tests/unit/test_oracle_coverage_map.py tests/unit/test_ruleset_drift.py tests/unit/test_self_binding_detector.py tests/unit/test_site_header_parity.py tests/unit/test_sync_results_workflow.py tests/unit/core/joinorder/test_canonical_queries.py tests/unit/core/test_platform_labels.py tests/unit/workflows/test_validate_submission_comment_security.py tests/unit/workflows/test_detect_orphaned_commits.py tests/unit/workflows/test_validate_submission_vendor_gate.py
	git rm -f --ignore-unmatch tests/integration/test_todo_db_standalone_compat_real.py tests/unit/core/equivalence/test_cross_surface_baseline_autodetect.py tests/unit/docs/test_architecture_decision_surfaces.py
	git rm -f --ignore-unmatch tests/unit/scripts/test_agent_instruction_audit.py tests/unit/scripts/test_audit_sha_check.py tests/unit/scripts/test_browser_gate_aggregate.py tests/unit/scripts/test_check_release_curation.py tests/unit/scripts/test_check_uv_lock_revision.py tests/unit/scripts/test_ci_lint_environment_boundary.py tests/unit/scripts/test_corpus_privacy_invariant.py tests/unit/scripts/test_dev_loop_pr_metrics.py tests/unit/scripts/test_fast_lane_ratchet_check.py tests/unit/scripts/test_green_unmerged_sweep.py tests/unit/scripts/test_guard_messages.py tests/unit/scripts/test_mirror_partial_validation_policy.py tests/unit/scripts/test_path_filter_decision.py tests/unit/scripts/test_results_explorer_corpus_migrate.py tests/unit/scripts/test_results_explorer_snapshot_invariants.py tests/unit/scripts/test_skill_sync_ci_policy.py tests/unit/scripts/test_soundness_drain_report.py tests/unit/scripts/test_fast_lane_ceiling_check.py tests/unit/scripts/test_timing_policy_check.py tests/unit/scripts/test_todo_db_shadow.py tests/unit/scripts/test_todo_db_standalone_compat.py tests/unit/scripts/test_todo_schema_migration_check.py tests/unit/scripts/test_todo_verification_lint.py tests/unit/scripts/test_todo_wrapper.py
	git rm -f --ignore-unmatch tests/unit/test_auto_merge_hold_is_durable.py tests/unit/test_release_infrastructure.py tests/unit/workflows/test_auto_merge_partial_stack_race.py tests/unit/workflows/test_develop_post_merge_gaps.py tests/unit/workflows/test_merge_group_triggers.py tests/unit/workflows/test_published_results_base_ci.py tests/unit/workflows/test_results_explorer_browser_gate.py tests/unit/workflows/test_results_explorer_dependency_audit.py tests/unit/workflows/test_seed_corpus_pr_base.py tests/unit/workflows/test_validate_submission_changed_bundles.py tests/unit/workflows/test_validate_submission_fail_open.py
	git rm -f --ignore-unmatch tests/integration/worktree/test_pr_process.py tests/integration/worktree/test_worktree_audit.py tests/integration/worktree/test_worktree_finish_preview.py tests/unit/scripts/test_migrate_clickhouse_labels.py tests/unit/scripts/test_pr_arm.py tests/unit/scripts/test_pr_ready_make.py tests/unit/scripts/test_pr_landing.py tests/unit/scripts/test_results_explorer_cpu_attestation_backfill.py tests/unit/scripts/test_todo_state_contract_check.py tests/unit/scripts/test_worktree_audit.py tests/unit/workflows/test_publication_preview.py tests/unit/workflows/test_queue_certification.py tests/integration/worktree/test_batch_skill_delivery.py tests/unit/scripts/publication/test_plan_reconciliation.py tests/unit/workflows/test_validate_submission_override_approval.py tests/unit/scripts/test_sqlite_extract_repro.py tests/unit/workflows/test_validate_submission_workflow_guard_mirror.py tests/unit/workflows/test_validate_submission_trusted_checkout.py tests/unit/workflows/test_validate_submission_corpus_allowlist.py tests/unit/workflows/test_corpus_trust_boundary.py tests/unit/scripts/test_branch_prune_merged.py tests/unit/docs/test_publication_architecture.py
	@LEFTOVER=$$(git ls-files _project ':(exclude)_project/scripts/explorer_pipeline/**' ':(exclude)_project/scripts/explorer_publish.py' ':(exclude)_project/scripts/results_explorer_snapshot_invariants.py' _blog .claude .codex .gemini .pre-commit-config.yaml .importlinter todo.config.yaml skill-sync.conf tools .gitattributes .coveragerc_core .dockerignore .env.example .mcp.json AGENTS.md CLAUDE.md GEMINI.md ANTIGRAVITY.md .github/workflows/results-explorer-browser.yml .github/workflows/seed-corpus.yml .github/workflows/sync-results-data-to-published.yml .github/workflows/validate-submission.yml tests/unit/scripts/explorer_pipeline tests/unit/explorer tests/uat/test_explorer_smoke.py tests/unit/release/test_ruleset_drift_review_coverage.py tests/unit/release/test_ruleset_review_enforcement.py tests/unit/scripts/test_blind_spot_tools.py tests/unit/scripts/test_build_joinorder_data.py tests/unit/scripts/test_check_complexity.py tests/unit/scripts/test_explorer_build_contract.py tests/unit/scripts/test_pr_review_followups.py tests/unit/scripts/test_reference_usage_audit.py tests/unit/scripts/test_scan_explorer_stale_theme.py tests/unit/scripts/test_scan_explorer_tokens.py tests/unit/scripts/test_shrink_rollup.py tests/unit/scripts/test_submission_workflow_waiver.py tests/unit/test_agent_write_preflight.py tests/unit/test_auto_merge_soundness_paths.py tests/unit/test_cross_surface_applicability.py tests/unit/test_oracle_coverage_map.py tests/unit/test_ruleset_drift.py tests/unit/test_self_binding_detector.py tests/unit/test_site_header_parity.py tests/unit/test_sync_results_workflow.py tests/unit/core/joinorder/test_canonical_queries.py tests/unit/core/test_platform_labels.py tests/unit/workflows/test_validate_submission_comment_security.py tests/unit/workflows/test_detect_orphaned_commits.py tests/unit/workflows/test_validate_submission_vendor_gate.py tests/integration/test_todo_db_standalone_compat_real.py tests/unit/core/equivalence/test_cross_surface_baseline_autodetect.py tests/unit/docs/test_architecture_decision_surfaces.py tests/unit/scripts/test_agent_instruction_audit.py tests/unit/scripts/test_audit_sha_check.py tests/unit/scripts/test_browser_gate_aggregate.py tests/unit/scripts/test_check_release_curation.py tests/unit/scripts/test_check_uv_lock_revision.py tests/unit/scripts/test_ci_lint_environment_boundary.py tests/unit/scripts/test_corpus_privacy_invariant.py tests/unit/scripts/test_dev_loop_pr_metrics.py tests/unit/scripts/test_fast_lane_ratchet_check.py tests/unit/scripts/test_green_unmerged_sweep.py tests/unit/scripts/test_guard_messages.py tests/unit/scripts/test_mirror_partial_validation_policy.py tests/unit/scripts/test_path_filter_decision.py tests/unit/scripts/test_results_explorer_corpus_migrate.py tests/unit/scripts/test_results_explorer_snapshot_invariants.py tests/unit/scripts/test_skill_sync_ci_policy.py tests/unit/scripts/test_soundness_drain_report.py tests/unit/scripts/test_fast_lane_ceiling_check.py tests/unit/scripts/test_timing_policy_check.py tests/unit/scripts/test_todo_db_shadow.py tests/unit/scripts/test_todo_db_standalone_compat.py tests/unit/scripts/test_todo_schema_migration_check.py tests/unit/scripts/test_todo_verification_lint.py tests/unit/scripts/test_todo_wrapper.py tests/unit/test_auto_merge_hold_is_durable.py tests/unit/test_release_infrastructure.py tests/unit/workflows/test_auto_merge_partial_stack_race.py tests/unit/workflows/test_develop_post_merge_gaps.py tests/unit/workflows/test_merge_group_triggers.py tests/unit/workflows/test_published_results_base_ci.py tests/unit/workflows/test_results_explorer_browser_gate.py tests/unit/workflows/test_results_explorer_dependency_audit.py tests/unit/workflows/test_seed_corpus_pr_base.py tests/unit/workflows/test_validate_submission_changed_bundles.py tests/unit/workflows/test_validate_submission_fail_open.py tests/integration/worktree/test_pr_process.py tests/integration/worktree/test_worktree_audit.py tests/integration/worktree/test_worktree_finish_preview.py tests/unit/scripts/test_migrate_clickhouse_labels.py tests/unit/scripts/test_pr_arm.py tests/unit/scripts/test_pr_ready_make.py tests/unit/scripts/test_pr_landing.py tests/unit/scripts/test_results_explorer_cpu_attestation_backfill.py tests/unit/scripts/test_todo_state_contract_check.py tests/unit/scripts/test_worktree_audit.py tests/unit/workflows/test_publication_preview.py tests/unit/workflows/test_queue_certification.py tests/integration/worktree/test_batch_skill_delivery.py tests/unit/scripts/publication/test_plan_reconciliation.py tests/unit/workflows/test_validate_submission_override_approval.py tests/unit/scripts/test_sqlite_extract_repro.py tests/unit/workflows/test_validate_submission_workflow_guard_mirror.py tests/unit/workflows/test_validate_submission_trusted_checkout.py tests/unit/workflows/test_validate_submission_corpus_allowlist.py tests/unit/workflows/test_corpus_trust_boundary.py tests/unit/scripts/test_branch_prune_merged.py tests/unit/docs/test_publication_architecture.py); \
	if [ -n "$$LEFTOVER" ]; then \
		echo "ERROR: release curation incomplete; development-only paths still tracked:" >&2; \
		echo "$$LEFTOVER" | sed 's/^/  /' >&2; \
		exit 1; \
	fi
	@for required_dir in results-data results-explorer _project/scripts/explorer_pipeline; do \
		test -d "$$required_dir" || { echo "ERROR: curated Explorer publication directory is missing: $$required_dir" >&2; exit 1; }; \
		git ls-files "$$required_dir" | grep -q . || { echo "ERROR: curated Explorer publication directory is not tracked: $$required_dir" >&2; exit 1; }; \
	done
	@for required_file in _project/scripts/explorer_publish.py _project/scripts/results_explorer_snapshot_invariants.py; do \
		test -f "$$required_file" && git ls-files --error-unmatch "$$required_file" >/dev/null || { echo "ERROR: curated Explorer publication helper is missing: $$required_file" >&2; exit 1; }; \
	done
	git add pyproject.toml uv.lock benchbox/__init__.py landing/index.html README.md docs/README.md benchbox/utils/VERSION_MANAGEMENT.md CHANGELOG.md
	git commit --no-verify -m "Release v$(VERSION)"
	@echo "==> Aligning release histories: merging origin/release into v$(VERSION) (strategy: ours)"
	@RELEASE_TREE=$$(git rev-parse 'HEAD^{tree}') && \
	git merge -s ours --no-verify --allow-unrelated-histories origin/release \
		-m "Merge release into v$(VERSION) (strategy: ours) to align release histories" && \
	MERGED_TREE=$$(git rev-parse 'HEAD^{tree}') && \
	if [ "$$RELEASE_TREE" != "$$MERGED_TREE" ]; then \
		echo "ERROR: alignment merge changed the curated release tree ($$RELEASE_TREE -> $$MERGED_TREE)" >&2; \
		exit 1; \
	fi
	PRE_COMMIT_ALLOW_NO_CONFIG=1 git push -u origin v$(VERSION)
	gh pr create --base release --head v$(VERSION) --title "Release v$(VERSION)" --body-file .github/RELEASE_PR_TEMPLATE.md
	@for br in $$(git ls-remote --heads origin 'v*' | awk '$$2 ~ /^refs\/heads\/v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.+-]+)?$$/ {print $$2}' | sed 's|refs/heads/||' | grep -Fxv "v$(VERSION)"); do \
		echo "==> Deleting prior release branch on origin: $$br"; \
		PRE_COMMIT_ALLOW_NO_CONFIG=1 git push origin --delete "$$br" || true; \
	done
	@echo
	@echo "Release PR opened. Next steps:"
	@echo "  1. Review the PR diff; confirm CHANGELOG and curation are correct."
	@echo "  2. Wait for the required release contexts: $(RELEASE_REQUIRED_CONTEXTS)."
	@echo "  3. make release-finalize VERSION=$(VERSION)"

release-cut-abort:
	@test -n "$(VERSION)" || (echo "Usage: make release-cut-abort VERSION=X.Y.Z" && exit 1)
	sh scripts/release_cut_abort.sh "$(VERSION)"

release-finalize:
	@test -n "$(VERSION)" || (echo "Usage: make release-finalize VERSION=X.Y.Z" && exit 1)
	uv run -- python scripts/release_finalize.py --version "$(VERSION)" --required-contexts "$(RELEASE_REQUIRED_CONTEXTS)"
	@echo
	@echo "Check the matching release.yml run before reporting publication."
	@echo "Push-to-release jobs are post-merge signals; release publication relied on $(RELEASE_REQUIRED_CONTEXTS)."
	@echo "develop is intentionally unchanged — dev-only paths persist on develop."

.PHONY: release-prep release-check
release-prep:
	@test -n "$(VERSION)" || (echo "Usage: make release-prep VERSION=X.Y.Z" && exit 1)
	uv run --frozen -- python scripts/release_flow.py prep --version "$(VERSION)" $(if $(SINCE_REF),--since-ref "$(SINCE_REF)",)

release-check:
	@test -n "$(VERSION)" || (echo "Usage: make release-check VERSION=X.Y.Z" && exit 1)
	uv run --locked -- python scripts/release_flow.py check --version "$(VERSION)" $(if $(BASE_REF),--baseline-ref "$(BASE_REF)",)

.PHONY: pr-arm pr-preflight pr-preflight-uncached .pr-preflight-route pr-preflight-focused-tests pr-preflight-fast-tests pr-content-guard skill-integrity-check pr-open pr-ready pr-arm-auto-merge pr-fanout pr-refresh pr-conflict-scan pr-status pr-review-followups pr-review-followups-list dev-loop-metrics shrink-rollup audit-sha-check agent-write-preflight worktree-create worktree-remove worktree-list branch-prune-merged blind-spots-list blind-spots-report blind-spots-sweep soundness-drain-report soundness-drain-self-test

agent-write-preflight:
	@sh scripts/agent_write_preflight.sh

pr-preflight-uncached:
	@set -eu; \
	DECISION=$$(mktemp); \
	LISTS=$$(mktemp -d); \
	trap 'rm -f "$$DECISION"; rm -rf "$$LISTS"' EXIT; \
	git fetch origin develop --quiet; \
	uv run -- python scripts/path_filter_decision.py --base-ref origin/develop --json-out "$$DECISION" --lists-dir "$$LISTS" >/dev/null; \
	$(MAKE) -s .pr-preflight-route PATH_DECISION="$$DECISION" PATH_LISTS="$$LISTS" SKIP_FAST_TESTS="$(SKIP_FAST_TESTS)"; \
	$(MAKE) -s pr-preflight-medium-tests PATH_DECISION="$$DECISION"; \
	$(MAKE) -s uat-artifact-hygiene

pr-preflight:
	@git fetch origin develop --quiet
	uv run -- python scripts/local_validation.py ordered \
		--focused-gate "local-focused-check" --focused-cmd 'make pr-preflight-focused-tests' \
		--preflight-gate "required-pr-preflight" --preflight-cmd '$(MAKE) -s pr-preflight-uncached SKIP_FAST_TESTS=1' \
		$(BATCH_ARGS)

.pr-preflight-route:
	@set -eu; \
	[ -n "$(PATH_DECISION)" ] && [ -f "$(PATH_DECISION)" ] || { echo "PATH_DECISION is required" >&2; exit 2; }; \
	[ -n "$(PATH_LISTS)" ] && [ -d "$(PATH_LISTS)" ] || { echo "PATH_LISTS is required" >&2; exit 2; }; \
	ROUTE=$$(uv run -- python -c 'import json, sys; d=json.load(open(sys.argv[1], encoding="utf-8")); keys=("skill_integrity_needed", "content_guard_needed", "skill_integrity_only", "needs_code_ci"); assert all(type(d.get(k)) is bool for k in keys), "invalid preflight decision"; assert not d["skill_integrity_only"] or (d["skill_integrity_needed"] and not d["needs_code_ci"]), "contradictory preflight decision"; print(*(str(d[k]).lower() for k in keys))' "$(PATH_DECISION)"); \
	set -- $$ROUTE; SKILL=$$1; CONTENT=$$2; SKILL_ONLY=$$3; \
	if [ "$$SKILL_ONLY" = true ] && [ "$$CONTENT" != true ]; then \
		echo "Selected preflight lanes: skill-integrity"; \
		$(MAKE) -s skill-integrity-check; \
	elif [ "$$SKILL_ONLY" = true ]; then \
		echo "Selected preflight lanes: skill-integrity content"; \
		$(MAKE) -s skill-integrity-check; \
		$(MAKE) -s pr-content-guard PATH_LISTS="$(PATH_LISTS)"; \
	else \
		LANES=product; [ "$$CONTENT" = true ] && LANES="$$LANES content"; [ "$$SKILL" = true ] && LANES="$$LANES skill-integrity"; \
		echo "Selected preflight lanes: $$LANES"; \
		$(MAKE) ci-lint; \
		if [ "$$SKILL" = true ]; then $(MAKE) -s skill-integrity-check; fi; \
		if [ "$(SKIP_FAST_TESTS)" = "1" ]; then \
			echo "Focused local gate already completed; skipping duplicate fast tests."; \
			$(MAKE) -s pr-content-guard PATH_LISTS="$(PATH_LISTS)"; \
		else \
			$(MAKE) -s pr-preflight-fast-tests PATH_DECISION="$(PATH_DECISION)" PATH_LISTS="$(PATH_LISTS)"; \
		fi; \
	fi

pr-preflight-focused-tests:
	@$(MAKE) -s pr-preflight-fast-tests SKIP_CONTENT_GUARD=1

pr-preflight-fast-tests:
	@set -eu; \
	if [ -n "$(PATH_DECISION)" ] || [ -n "$(PATH_LISTS)" ]; then \
		[ -n "$(PATH_DECISION)" ] && [ -f "$(PATH_DECISION)" ] || { echo "PATH_DECISION is required" >&2; exit 2; }; \
		[ -n "$(PATH_LISTS)" ] && [ -d "$(PATH_LISTS)" ] || { echo "PATH_LISTS is required" >&2; exit 2; }; \
		DECISION="$(PATH_DECISION)"; \
		LISTS="$(PATH_LISTS)"; \
	else \
		DECISION=$$(mktemp); \
		LISTS=$$(mktemp -d); \
		trap 'rm -f "$$DECISION"; rm -rf "$$LISTS"' EXIT; \
		git fetch origin develop --quiet; \
		uv run -- python scripts/path_filter_decision.py --base-ref origin/develop --json-out "$$DECISION" --lists-dir "$$LISTS" >/dev/null; \
	fi; \
	if [ "$(SKIP_CONTENT_GUARD)" = "1" ]; then \
		echo "Focused checks defer content guard to required preflight."; \
	else \
		$(MAKE) -s pr-content-guard PATH_LISTS="$$LISTS"; \
	fi; \
	if uv run -- python scripts/path_filter_decision.py --json-in "$$DECISION" --check needs-code-ci >/dev/null; then \
		echo "==> fast tests (CI marker selection; coverage remains CI-only)"; \
		uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=120 -q; \
	else \
		echo "No code changes detected; skipping fast tests."; \
	fi

pr-preflight-medium-tests:
	@set -eu; \
	if [ -n "$(PATH_DECISION)" ]; then \
		[ -f "$(PATH_DECISION)" ] || { echo "PATH_DECISION is required" >&2; exit 2; }; \
		DECISION="$(PATH_DECISION)"; \
	else \
		DECISION=$$(mktemp); \
		trap 'rm -f "$$DECISION"' EXIT; \
		git fetch origin develop --quiet; \
		uv run -- python scripts/path_filter_decision.py --base-ref origin/develop --json-out "$$DECISION" >/dev/null; \
	fi; \
	if uv run -- python scripts/path_filter_decision.py --json-in "$$DECISION" --check needs-code-ci >/dev/null; then \
		CHANGED_JSON=$$(uv run -- python -c 'import json, sys; d=json.load(open(sys.argv[1], encoding="utf-8")); paths=d["changed_paths"]; assert isinstance(paths, list) and all(isinstance(path, str) for path in paths); print(json.dumps(paths, separators=(",", ":")))' "$$DECISION"); \
		echo "==> medium tier (impact-selected local tests)"; \
		env -u PATH_DECISION -u PATH_LISTS -u SKIP_FAST_TESTS BENCHBOX_MEDIUM_CHANGED_PATHS_JSON="$$CHANGED_JSON" MAKEFLAGS= $(MAKE) -s local-validation GATE=medium-tier CMD="make test-medium-selected"; \
	else \
		echo "No code changes detected; skipping medium tier."; \
	fi

local-validation:
	@[ -n "$(GATE)" ] || { echo "GATE is required" >&2; exit 2; }; \
	[ -n "$(CMD)" ] || { echo "CMD is required" >&2; exit 2; }; \
	uv run -- python scripts/local_validation.py run --gate "$(GATE)" $(BATCH_ARGS) -- $(CMD)

local-validation-show:
	@[ -n "$(GATE)" ] || { echo "GATE is required" >&2; exit 2; }; \
	uv run -- python scripts/local_validation.py show --gate "$(GATE)" $(BATCH_ARGS) $(if $(CMD),-- $(CMD),)

FOCUSED_CMD ?= uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short -q
PREFLIGHT_CMD ?= make pr-preflight
local-validation-path:
	@echo "Running receipt-bound canonical preflight path (focused then required lanes)."
	$(MAKE) -s pr-preflight $(BATCH_ARGS)

pr-landing-start:
	uv run -- python scripts/pr_landing.py --repo "$(or $(REPO),BenchBox-dev/BenchBox)" \
		--worktree . --branch "$(or $(BRANCH),$(shell git branch --show-current))" \
		$(if $(WORKTREE_ID),--worktree-id "$(WORKTREE_ID)",) start

pr-landing-withdraw:
	@[ -n "$(PR)" ] || { echo "PR is required" >&2; exit 2; }; \
	uv run -- python scripts/pr_landing.py --repo "$(or $(REPO),BenchBox-dev/BenchBox)" \
		--worktree . --branch "$(or $(BRANCH),$(shell git branch --show-current))" \
		$(if $(WORKTREE_ID),--worktree-id "$(WORKTREE_ID)",) \
		$(if $(PR_NODE_ID),--pr-node-id "$(PR_NODE_ID)",) withdraw --pr "$(PR)" \
		$(if $(HEAD),--expected-head "$(HEAD)",)

pr-landing-ready:
	@set -eu; \
	[ -n "$(PR)" ] || { echo "PR is required" >&2; exit 2; }; \
	[ -n "$(HEAD)" ] || { echo "HEAD is required" >&2; exit 2; }; \
	[ -n "$(EVIDENCE)" ] || { echo "EVIDENCE is required" >&2; exit 2; }; \
	uv run -- python scripts/pr_landing.py --repo "$(or $(REPO),BenchBox-dev/BenchBox)" \
		--worktree . --branch "$(or $(BRANCH),$(shell git branch --show-current))" \
		$(if $(WORKTREE_ID),--worktree-id "$(WORKTREE_ID)",) \
		$(if $(PR_NODE_ID),--pr-node-id "$(PR_NODE_ID)",) ready --pr "$(PR)" \
		--expected-head "$(HEAD)" --evidence-json "$(EVIDENCE)" \
		$(if $(ARM),--arm,) $(if $(BATCH),--require-batch,)

pr-followup-record:
	@[ -n "$(KEY)" ] || { echo "KEY is required" >&2; exit 2; }; \
	@[ -n "$(STATE)" ] || { echo "STATE is required" >&2; exit 2; }; \
	uv run -- python scripts/pr_landing.py --worktree . followup-record --key "$(KEY)" --state-json "$(STATE)"

pr-followup-resume:
	@[ -n "$(KEY)" ] || { echo "KEY is required" >&2; exit 2; }; \
	uv run -- python scripts/pr_landing.py --worktree . followup-resume --key "$(KEY)"

pr-content-guard:
	@set -eu; \
	[ -n "$(PATH_LISTS)" ] || { echo "PATH_LISTS is required"; exit 2; }; \
	EXISTING=$$(mktemp); \
	trap 'rm -f "$$EXISTING"' EXIT; \
	$(MAKE) artifact-hygiene; \
	if [ -s "$(PATH_LISTS)/yaml.txt" ]; then \
		: > "$$EXISTING"; \
		while IFS= read -r path; do \
			if [ -e "$$path" ]; then printf '%s\n' "$$path" >> "$$EXISTING"; else echo "Skipping deleted YAML path: $$path"; fi; \
		done < "$(PATH_LISTS)/yaml.txt"; \
		if [ -s "$$EXISTING" ]; then uv run -- pre-commit run check-yaml --files $$(cat "$$EXISTING"); else echo "No existing YAML content paths to lint."; fi; \
	else \
		echo "No YAML content paths changed."; \
	fi; \
	if [ -s "$(PATH_LISTS)/markdown.txt" ]; then \
		: > "$$EXISTING"; \
		while IFS= read -r path; do \
			if [ -e "$$path" ]; then printf '%s\n' "$$path" >> "$$EXISTING"; else echo "Skipping deleted markdown path: $$path"; fi; \
		done < "$(PATH_LISTS)/markdown.txt"; \
		if [ -s "$$EXISTING" ]; then uv run -- pre-commit run markdownlint --files $$(cat "$$EXISTING"); else echo "No existing markdown content paths to lint."; fi; \
	else \
		echo "No markdown content paths changed."; \
	fi; \
	if [ -s "$(PATH_LISTS)/docs.txt" ]; then \
		$(MAKE) docs-validate; \
	else \
		echo "No docs paths changed."; \
	fi

pr-open:
	@set -eu; \
	$(MAKE) -s agent-write-preflight; \
	CURRENT=$$(git branch --show-current); \
	case "$$CURRENT" in \
		develop|main|release) echo "Refusing to open PR from $$CURRENT — switch to a feature branch."; exit 1 ;; \
	esac; \
	if [ -n "$(PR_BODY_FILE)" ] && [ ! -f "$(PR_BODY_FILE)" ]; then \
		echo "PR_BODY_FILE does not exist: $(PR_BODY_FILE)" >&2; \
		exit 1; \
	fi; \
	REPOSITORY="$(or $(REPO),BenchBox-dev/BenchBox)"; \
	case "$$REPOSITORY" in \
		*/*/*|/*|*/|"") echo "REPO must be a GitHub owner/name identity" >&2; exit 2 ;; \
		*/*) ;; \
		*) echo "REPO must be a GitHub owner/name identity" >&2; exit 2 ;; \
	esac; \
	ORIGIN_URL=$$(git remote get-url --push origin) || { echo "Could not resolve the origin remote" >&2; exit 1; }; \
	case "$$ORIGIN_URL" in \
		git@github.com:*) ORIGIN_REPOSITORY="$${ORIGIN_URL#git@github.com:}" ;; \
		ssh://git@github.com/*) ORIGIN_REPOSITORY="$${ORIGIN_URL#ssh://git@github.com/}" ;; \
		https://github.com/*) ORIGIN_REPOSITORY="$${ORIGIN_URL#https://github.com/}" ;; \
		*) echo "origin remote is not a supported GitHub URL or SSH form" >&2; exit 1 ;; \
	esac; \
	ORIGIN_REPOSITORY="$${ORIGIN_REPOSITORY%.git}"; \
	ORIGIN_REPOSITORY="$${ORIGIN_REPOSITORY%/}"; \
	ORIGIN_OWNER="$${ORIGIN_REPOSITORY%%/*}"; \
	case "$$ORIGIN_REPOSITORY" in \
		*/*/*|/*|*/|"") echo "origin remote is not a GitHub owner/name identity" >&2; exit 1 ;; \
		*/*) ;; \
		*) echo "origin remote is not a GitHub owner/name identity" >&2; exit 1 ;; \
	esac; \
	HEAD_SPEC="$$CURRENT"; \
	ORIGIN_REPOSITORY_KEY=$$(printf '%s' "$$ORIGIN_REPOSITORY" | tr 'A-Z' 'a-z'); \
	TARGET_REPOSITORY_KEY=$$(printf '%s' "$$REPOSITORY" | tr 'A-Z' 'a-z'); \
	if [ "$$ORIGIN_REPOSITORY_KEY" != "$$TARGET_REPOSITORY_KEY" ]; then \
		HEAD_SPEC="$$ORIGIN_OWNER:$$CURRENT"; \
	fi; \
	PR_HEAD_OWNER="$$ORIGIN_OWNER"; \
	PR_HEAD_NAME="$$CURRENT"; \
	export PR_HEAD_OWNER PR_HEAD_NAME; \
	git fetch origin develop --quiet; \
	if ! git merge-base --is-ancestor origin/develop HEAD; then \
		if ! git merge-tree --write-tree origin/develop HEAD >/dev/null 2>&1; then \
			echo "Refusing to open PR: HEAD conflicts with origin/develop. Resolve the conflict first; no refresh merge is attempted." >&2; \
			exit 1; \
		fi; \
		QUEUE_REPORT=$$(mktemp); \
		trap 'rm -f "$$QUEUE_REPORT"' EXIT; \
		if ! gh auth token 2>/dev/null | uv run -- python scripts/ruleset_drift_check.py --queue-policy \
			--require-bypass-actor-visibility --repo "$$REPOSITORY" --token-stdin \
			--output "$$QUEUE_REPORT"; then \
			echo "Refusing to open PR: native merge queue and its protections could not be verified. Run 'make pr-refresh' to satisfy the current-base gate." >&2; \
			exit 1; \
		fi; \
		if ! DECISION=$$(uv run -- python scripts/pr_landing.py --worktree . queue-policy --queue-report "$$QUEUE_REPORT"); then \
			echo "Refusing to open PR: queue policy did not authorize stale-base publication. Run 'make pr-refresh'." >&2; \
			exit 1; \
		fi; \
		[ "$$DECISION" = "publish-without-refresh" ] || { echo "Refusing to open PR: unexpected stale-base decision $$DECISION." >&2; exit 1; }; \
		echo "Verified native merge queue: publishing without an author-side base refresh."; \
	fi; \
	$(MAKE) -s pr-conflict-scan BRANCH="$$CURRENT" || true; \
	git push -u origin "$$CURRENT" || { echo "Push failed for $$CURRENT — aborting before opening a PR (remote branch may be stale)." >&2; exit 1; }; \
	REUSED_PR=0; \
	URL=$$(gh pr list --repo "$$REPOSITORY" --base develop --state open \
		--json url,headRepositoryOwner,headRefName \
		--jq '.[] | select((.headRepositoryOwner.login | ascii_downcase) == (env.PR_HEAD_OWNER | ascii_downcase) and .headRefName == env.PR_HEAD_NAME) | .url' \
		2>/dev/null | sed -n '1p'); \
	if [ -z "$$URL" ]; then \
		if [ -n "$(PR_BODY_FILE)" ]; then \
			URL=$$(gh pr create --repo "$$REPOSITORY" --base develop --fill --head "$$HEAD_SPEC" --body-file "$(PR_BODY_FILE)"); \
		else \
			URL=$$(gh pr create --repo "$$REPOSITORY" --base develop --fill --head "$$HEAD_SPEC"); \
		fi; \
	else \
		REUSED_PR=1; \
		echo "Reusing existing PR: $$URL"; \
		if [ -n "$(PR_BODY_FILE)" ]; then \
			gh pr edit --repo "$$REPOSITORY" "$$URL" --body-file "$(PR_BODY_FILE)"; \
		fi; \
	fi && \
	echo "$$URL" && \
	if [ "$(READY)" != "1" ]; then \
		echo "Next: make pr-arm once the review fixes are pushed; the merge queue merges it when the required checks pass."; \
	elif [ -n "$(EVIDENCE)$(BATCH)" ]; then \
		if [ "$$REUSED_PR" != "1" ]; then \
			echo "READY=1 with EVIDENCE or BATCH applies to a reused PR, so this new PR is not armed."; \
			echo "Arm it after review with make pr-arm, or with the evidence transaction: make pr-ready REPO=\"$$REPOSITORY\" URL=\"$$URL\" HEAD=\"$$(git rev-parse HEAD)\" EVIDENCE=\"<readiness-evidence.json>\""; \
		else \
			$(MAKE) -s pr-ready REPO="$$REPOSITORY" URL="$$URL" HEAD="$$(git rev-parse HEAD)" EVIDENCE="$(EVIDENCE)" BATCH="$(BATCH)"; \
		fi; \
	else \
		PR_NUMBER=$$(gh pr view --repo "$$REPOSITORY" "$$URL" --json number --jq '.number') || { echo "Could not resolve $$URL to a PR in $$REPOSITORY" >&2; exit 1; }; \
		$(MAKE) -s pr-arm PR="$$PR_NUMBER" REPO="$$REPOSITORY" HEAD="$$(git rev-parse HEAD)"; \
	fi

pr-arm-auto-merge:
	@set -eu; \
	[ -n "$(EVIDENCE)" ] || { echo "EVIDENCE is required; use pr-landing-ready with exact readiness evidence" >&2; exit 2; }; \
	REPOSITORY="$(or $(REPO),BenchBox-dev/BenchBox)"; \
	CURRENT=$$(git branch --show-current); \
	PR_NUMBER="$(PR)"; \
	if [ -n "$(URL)" ]; then \
		if [ -n "$$PR_NUMBER" ]; then echo "PR and URL are mutually exclusive" >&2; exit 2; fi; \
		PR_NUMBER=$$(gh pr view --repo "$$REPOSITORY" "$(URL)" --json number --jq '.number') || { echo "Could not resolve URL to a PR in $$REPOSITORY" >&2; exit 1; }; \
	fi; \
	case "$$PR_NUMBER" in *[!0-9]*) echo "PR must resolve to a positive number" >&2; exit 2 ;; esac; \
	if [ -n "$$PR_NUMBER" ] && [ "$$PR_NUMBER" -le 0 ]; then echo "PR must resolve to a positive number" >&2; exit 2; fi; \
	[ -n "$$PR_NUMBER" ] || { echo "PR or URL is required" >&2; exit 2; }; \
	EXPECTED_HEAD="$(HEAD)"; \
	if [ -z "$$EXPECTED_HEAD" ]; then EXPECTED_HEAD=$$(git rev-parse HEAD); fi; \
	$(MAKE) -s pr-landing-ready REPO="$$REPOSITORY" PR="$$PR_NUMBER" HEAD="$$EXPECTED_HEAD" \
		EVIDENCE="$(EVIDENCE)" BATCH="$(BATCH)" ARM=1

PR_ARM_PR_SET := $(if $(filter undefined,$(origin PR)),,1)
PR_ARM_HEAD_SET := $(if $(filter undefined,$(origin HEAD)),,1)
PR_ARM_REPO_SET := $(if $(filter undefined,$(origin REPO)),,1)
pr-arm: override PR := $(value PR)
pr-arm: override HEAD := $(value HEAD)
pr-arm: override REPO := $(value REPO)
pr-arm: export PR_ARM_PR := $(PR)
pr-arm: export PR_ARM_PR_SET := $(PR_ARM_PR_SET)
pr-arm: export PR_ARM_HEAD := $(HEAD)
pr-arm: export PR_ARM_HEAD_SET := $(PR_ARM_HEAD_SET)
pr-arm: export PR_ARM_REPO := $(REPO)
pr-arm: export PR_ARM_REPO_SET := $(PR_ARM_REPO_SET)
pr-arm:
	@uv run -- python scripts/pr_arm.py

pr-ready:
	@[ -n "$(PR)" ] || [ -n "$(URL)" ] || { echo "PR or URL is required" >&2; exit 2; }
	@[ -n "$(HEAD)" ] || { echo "HEAD is required" >&2; exit 2; }
	@if [ -n "$(EVIDENCE)$(BATCH)" ]; then \
		$(MAKE) -s pr-arm-auto-merge REPO="$(or $(REPO),BenchBox-dev/BenchBox)" PR="$(PR)" URL="$(URL)" HEAD="$(HEAD)" EVIDENCE="$(EVIDENCE)" BATCH="$(BATCH)"; \
	elif [ -n "$(URL)" ]; then \
		[ -z "$(PR)" ] || { echo "PR and URL are mutually exclusive" >&2; exit 2; }; \
		REPOSITORY="$(or $(REPO),BenchBox-dev/BenchBox)"; \
		PR_INFO=$$(gh pr view --repo "$$REPOSITORY" "$(URL)" --json number,url --jq '"\(.number) \(.url)"') || { echo "Could not resolve URL to a PR in $$REPOSITORY" >&2; exit 1; }; \
		PR_NUMBER="$${PR_INFO%% *}"; PR_URL=$$(printf '%s' "$${PR_INFO#* }" | tr 'A-Z' 'a-z'); \
		WANT=$$(printf '%s' "$$REPOSITORY" | tr 'A-Z' 'a-z'); \
		case "$$PR_URL" in "https://github.com/$$WANT/pull/"*) ;; *) echo "URL names a PR outside $$REPOSITORY; refusing to arm it" >&2; exit 2 ;; esac; \
		$(MAKE) -s pr-arm PR="$$PR_NUMBER" REPO="$$REPOSITORY" HEAD="$(HEAD)"; \
	else \
		$(MAKE) -s pr-arm PR="$(PR)" REPO="$(or $(REPO),BenchBox-dev/BenchBox)" HEAD="$(HEAD)"; \
	fi

shrink-rollup:
	@git fetch origin develop --quiet
	@uv run --project _project/scripts -- python _project/scripts/shrink_rollup.py

pr-fanout:
	@MAIN_CLONE=$$(dirname "$$(realpath "$$(git rev-parse --git-common-dir)")"); \
	TMP=$$(mktemp); \
	LOGDIR=$$(mktemp -d); \
	trap 'rm -f "$$TMP"; rm -rf "$$LOGDIR"' EXIT; \
	git worktree list --porcelain | sed -n 's/^worktree //p' | while IFS= read -r wt; do \
		[ "$$(realpath "$$wt")" = "$$MAIN_CLONE" ] && { echo "(skip $$wt: main clone)"; continue; }; \
		BR=$$(git -C "$$wt" branch --show-current 2>/dev/null); \
		case "$$BR" in develop|main|release|"") echo "(skip $$wt: branch=$$BR)"; continue ;; esac; \
		IDX=$$(($${IDX:-0} + 1)); \
		printf '%06d|%s\0' "$$IDX" "$$wt" >> "$$TMP"; \
	done; \
	if [ ! -s "$$TMP" ]; then exit 0; fi; \
	xargs -0 -n 1 -P "$(PR_FANOUT_JOBS)" sh -c 'logdir="$$1"; record="$$2"; idx="$${record%%|*}"; wt="$${record#*|}"; br=$$(git -C "$$wt" branch --show-current 2>/dev/null); { echo "==> $$wt [$$br]"; ( cd "$$wt" && $(MAKE) -s pr-open ) || { echo "(failed: $$wt)"; exit 1; }; } > "$$logdir/$$idx.log" 2>&1' sh "$$LOGDIR" < "$$TMP"; \
	STATUS=$$?; \
	for log in "$$LOGDIR"/*.log; do [ -e "$$log" ] && cat "$$log"; done; \
	exit $$STATUS

pr-refresh:
	@CURRENT=$$(git branch --show-current); \
	case "$$CURRENT" in \
		develop|main|release|"") echo "Refusing to refresh $$CURRENT — switch to a feature branch worktree."; exit 1 ;; \
	esac; \
	git fetch origin develop --quiet && \
	git merge --no-edit origin/develop && \
	$(MAKE) -s pr-open

pr-conflict-scan:
	@CURRENT="$(BRANCH)"; \
	[ -n "$$CURRENT" ] || CURRENT=$$(git branch --show-current); \
	gh pr list --base develop --state open --json number,headRefName \
		--jq '.[] | "\(.number) \(.headRefName)"' 2>/dev/null | \
	while read num branch; do \
		[ "$$branch" = "$$CURRENT" ] && continue; \
		git fetch origin "$$branch" --quiet 2>/dev/null || continue; \
		git rev-parse --verify --quiet "origin/$$branch^{commit}" >/dev/null || continue; \
		out=$$(git merge-tree --write-tree --name-only HEAD "origin/$$branch" 2>/dev/null); \
		[ $$? -eq 1 ] || continue; \
		files=$$(printf '%s\n' "$$out" | awk 'NR>1 && NF==0{exit} NR>1{printf "%s%s", sep, $$0; sep=", "}'); \
		echo "  ⚠ textual conflict with PR #$$num ($$branch) in $$files — coordinate before landing"; \
	done; true

pr-status:
	@if [ "$(ALL_OPEN)" = "1" ] || [ "$(ALL_OPEN)" = "true" ] || [ "$(ALL_OPEN)" = "yes" ]; then \
		echo "All open develop PRs (bounded to $(PR_STATUS_ALL_OPEN_LIMIT)):"; \
		LIMIT="$(PR_STATUS_ALL_OPEN_LIMIT)"; \
	else \
		LIMIT="$(PR_STATUS_LIMIT)"; \
	fi; \
	gh pr list --base develop --state open --limit "$$LIMIT" --json number,title,headRefName,statusCheckRollup,autoMergeRequest \
		--template '{{range .}}#{{.number}} {{.title}} ({{.headRefName}}){{"\n"}}  auto-merge: {{if .autoMergeRequest}}ON{{else}}OFF{{end}}{{"\n"}}  checks: {{range .statusCheckRollup}}{{.name}}={{.conclusion}} {{end}}{{"\n\n"}}{{end}}'

pr-review-followups-list:
	@uv run --project _project/scripts -- python _project/scripts/pr_review_followups.py list \
		--base "$(PR_REVIEW_BASE)" \
		--limit-prs "$(PR_REVIEW_PR_LIMIT)" \
		--max-comments "$(PR_REVIEW_MAX_COMMENTS)" \
		$(if $(filter 1 true yes,$(PR_REVIEW_INCLUDE_RESOLVED)),--include-resolved) \
		$(if $(filter 1 true yes,$(PR_REVIEW_INCLUDE_POST_MERGE)),--include-post-merge) \
		$(if $(filter 1 true yes,$(PR_REVIEW_FAIL_ON_PENDING)),--fail-on-pending) \
		$(if $(PR_REVIEW_REPO),--repo "$(PR_REVIEW_REPO)") \
		$(if $(PR_REVIEW_SINCE),--since "$(PR_REVIEW_SINCE)") \
		$(if $(PR_REVIEW_UNTIL),--until "$(PR_REVIEW_UNTIL)")

pr-review-followups:
	@uv run --project _project/scripts -- python _project/scripts/pr_review_followups.py run \
		--base "$(PR_REVIEW_BASE)" \
		--limit-prs "$(PR_REVIEW_PR_LIMIT)" \
		--max-comments "$(PR_REVIEW_MAX_COMMENTS)" \
		--executor-sandbox "$(PR_REVIEW_EXECUTOR_SANDBOX)" \
		--executor-approval "$(PR_REVIEW_EXECUTOR_APPROVAL)" \
		$(if $(PR_REVIEW_REPO),--repo "$(PR_REVIEW_REPO)") \
		$(if $(PR_REVIEW_SINCE),--since "$(PR_REVIEW_SINCE)") \
		$(if $(PR_REVIEW_UNTIL),--until "$(PR_REVIEW_UNTIL)") \
		$(if $(PR_REVIEW_EXECUTOR_MODEL),--executor-model "$(PR_REVIEW_EXECUTOR_MODEL)") \
		$(if $(filter 1 true yes,$(PR_REVIEW_INCLUDE_POST_MERGE)),--include-post-merge) \
		$(if $(filter 0 false no,$(PR_REVIEW_REPLY)),--no-reply) \
		$(if $(filter 0 false no,$(PR_REVIEW_SUBMIT)),--no-submit) \
		$(if $(filter 1 true yes,$(PR_REVIEW_RESUME)),--resume)

dev-loop-metrics:
	@set -e; \
	TMP=$$(mktemp -d); \
	trap 'rm -rf "$$TMP"' EXIT; \
	SINCE=$$(uv run -- python -c 'from datetime import datetime, timedelta, timezone; print((datetime.now(timezone.utc) - timedelta(days=int("$(DEV_LOOP_METRICS_DAYS)"))).date().isoformat())'); \
	echo "Fetching develop-post-merge metrics since $$SINCE (limit $(DEV_LOOP_METRICS_LIMIT))..."; \
	RUN_IDS=$$(gh run list --workflow develop-post-merge.yml --branch develop --event push --created ">=$$SINCE" --limit "$(DEV_LOOP_METRICS_LIMIT)" --json databaseId --jq '.[].databaseId' 2>/dev/null || true); \
	for id in $$RUN_IDS; do \
		gh run download "$$id" -n metrics -D "$$TMP/$$id" >/dev/null 2>&1 || true; \
	done; \
	FILES=$$(find "$$TMP" -type f -name '*.json' | sort); \
	if [ -z "$$FILES" ]; then \
		echo "Metrics artifacts: 0"; \
		echo "PR-to-merged P50: n/a"; \
		echo "PR-to-merged P95: n/a"; \
		echo "Post-merge red rate: n/a (0/0)"; \
		echo "Conflict rate: n/a (0/0)"; \
		echo "runner minutes total: 0"; \
		exit 0; \
	fi; \
	jq -r -s ' \
		def nums($$k): [.[].[$$k] | select(type == "number")]; \
		def ceil_num: if . == floor then . else floor + 1 end; \
		def pct($$a; $$p): \
			if ($$a | length) == 0 then null \
			else ($$a | sort) as $$s | (((($$s | length) * $$p / 100) | ceil_num) - 1) as $$idx | $$s[$$idx] end; \
		def fmt: if . == null then "n/a" else tostring end; \
		def rate($$n; $$d): if $$d == 0 then "n/a" else (((100 * $$n / $$d) | tostring) + "%") end; \
		. as $$rows | \
		($$rows | length) as $$total | \
		(nums("pr_open_to_merged_seconds")) as $$merge_seconds | \
		([$$rows[] | select(.post_merge_red == true)] | length) as $$red | \
		([$$rows[] | select(.conflict_on_merge == true)] | length) as $$conflicts | \
		((nums("ci_runner_minutes") | add) // 0) as $$runner | \
		[ \
			"Metrics artifacts: \($$total)", \
			"PR-to-merged P50: \(pct($$merge_seconds; 50) | fmt) seconds", \
			"PR-to-merged P95: \(pct($$merge_seconds; 95) | fmt) seconds", \
			"Post-merge red rate: \(rate($$red; $$total)) (\($$red)/\($$total))", \
			"Conflict rate: \(rate($$conflicts; $$total)) (\($$conflicts)/\($$total))", \
			"runner minutes total: \($$runner)" \
		] | .[]' $$FILES
	@echo "---"; \
	echo "Dev-loop PR metrics (CI-failure baseline, see dev-loop-metrics-ci-failure-baseline-2):"; \
	test -f _project/scripts/dev_loop_pr_metrics.py && uv run -- python _project/scripts/dev_loop_pr_metrics.py --days "$(DEV_LOOP_METRICS_DAYS)" || true

include $(BENCHBOX_MAKEFILE_ROOT)make/worktrees.mk

include $(BENCHBOX_MAKEFILE_ROOT)make/worktree-maintenance.mk

branch-prune-merged:
	@command -v gh >/dev/null 2>&1 || { echo "gh CLI required for branch-prune-merged" >&2; exit 1; }
	@DRY_RUN='$(if $(filter 1,$(DRY_RUN)),1,$(if $(strip $(DRY_RUN)),invalid,))' \
		uv run -- python scripts/branch_prune_merged.py

.PHONY: uat-cell uat-execute uat-validate uat-package uat-explorer-smoke uat-report uat-sweep uat-smoke uat-stress uat-bring-up uat-prepull uat-docker-cleanup uat-artifact-hygiene uat-gate-check

uat-artifact-hygiene:
	@uv run --no-sync -- python -m tests.uat.artifact_hygiene \
		$(if $(OUTPUT),--output "$(OUTPUT)",) \
		$(if $(THRESHOLD_BYTES),--threshold-bytes "$(THRESHOLD_BYTES)",)

uat-cell:
	@if [ -z "$(PLATFORM)" ] || [ -z "$(BENCHMARK)" ] || [ -z "$(SCALE)" ]; then \
		echo "Usage: make uat-cell PLATFORM=<name> BENCHMARK=<name> SCALE=<float>" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli \
		--platform "$(PLATFORM)" \
		--benchmark "$(BENCHMARK)" \
		--scale "$(SCALE)" \
		$(if $(PHASES),--phases "$(PHASES)",) \
		$(if $(COMPRESSION),--compression "$(COMPRESSION)",) \
		$(if $(TIMEOUT_S),--timeout-s "$(TIMEOUT_S)",) \
		$(if $(LOG_DIR),--log-dir "$(LOG_DIR)",)

uat-validate:
	@if [ -z "$(RESULTS_DIR)" ] || [ -z "$(OUTPUT_TSV)" ]; then \
		echo "Usage: make uat-validate RESULTS_DIR=<dir> OUTPUT_TSV=<path> [FLOOR=0.80]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli validate \
		--results-dir "$(RESULTS_DIR)" \
		--output-tsv "$(OUTPUT_TSV)" \
		$(if $(FLOOR),--floor "$(FLOOR)",)

uat-report:
	@if [ -z "$(CELLS_JSONL)" ] || [ -z "$(OUTPUT_TSV)" ]; then \
		echo "Usage: make uat-report CELLS_JSONL=<path> OUTPUT_TSV=<path> [RUNGS=...] [CROSS_SCALE_FLOOR=N]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli report \
		--cells-jsonl "$(CELLS_JSONL)" \
		--output-tsv "$(OUTPUT_TSV)" \
		$(if $(RUNGS),--rungs "$(RUNGS)",) \
		$(if $(CROSS_SCALE_FLOOR),--cross-scale-floor "$(CROSS_SCALE_FLOOR)",)

uat-explorer-smoke:
	@if [ -z "$(BUNDLES_DIR)" ] || [ -z "$(OUTPUT_DIR)" ] || [ -z "$(LOG_DIR)" ]; then \
		echo "Usage: make uat-explorer-smoke BUNDLES_DIR=<path> OUTPUT_DIR=<path> LOG_DIR=<path> [BROWSERS=chromium]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli explorer-smoke \
		--data-dir "$(BUNDLES_DIR)" \
		--output-dir "$(OUTPUT_DIR)" \
		--log-dir "$(LOG_DIR)" \
		$(if $(BROWSERS),--browsers "$(BROWSERS)",)

uat-package:
	@if [ -z "$(CONFIG)" ] || [ -z "$(SUBMISSIONS_DIR)" ] || [ -z "$(RESULTS)" ]; then \
		echo "Usage: make uat-package CONFIG=<path> SUBMISSIONS_DIR=<path> RESULTS=\"r1.json r2.json ...\"" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli package \
		--config "$(CONFIG)" \
		--submissions-dir "$(SUBMISSIONS_DIR)" \
		$(foreach r,$(RESULTS),--result "$(r)")

UAT_BRING_UP_KNOWN_PLATFORMS := cedardb clickhouse-server databend doris influxdb lakesail pg-duckdb pg-mooncake postgresql presto questdb singlestore starrocks timescaledb trino velox

uat-bring-up:
	$(if $(strip $(PLATFORM)),$(if $(filter $(PLATFORM),$(UAT_BRING_UP_KNOWN_PLATFORMS)),,$(error unknown platform '$(PLATFORM)'; supported: $(UAT_BRING_UP_KNOWN_PLATFORMS))),)
	@if [ -z "$(PLATFORM)" ]; then \
		echo "Usage: make uat-bring-up PLATFORM=<name> [TIMEOUT_S=300] [DRY_RUN=1] [BENCHMARK_RUNS_DIR=~/Developer/benchmark_runs]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python scripts/uat-bring-up/uat_bring_up.py \
		--platform "$(PLATFORM)" \
		$(if $(TIMEOUT_S),--timeout-s "$(TIMEOUT_S)",) \
		$(if $(BENCHMARK_RUNS_DIR),--benchmark-runs-dir "$(BENCHMARK_RUNS_DIR)",) \
		$(if $(DRY_RUN),--dry-run,)

uat-prepull:
	$(if $(strip $(PLATFORM)),$(if $(filter $(PLATFORM),$(UAT_BRING_UP_KNOWN_PLATFORMS)),,$(error unknown platform '$(PLATFORM)'; supported: $(UAT_BRING_UP_KNOWN_PLATFORMS))),)
	@if [ -z "$(PLATFORM)" ]; then \
		echo "Usage: make uat-prepull PLATFORM=<name> [PREPULL_TIMEOUT_S=900] [DRY_RUN=1]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python scripts/uat-bring-up/uat_bring_up.py \
		--platform "$(PLATFORM)" \
		--prepull-only \
		$(if $(PREPULL_TIMEOUT_S),--prepull-timeout-s "$(PREPULL_TIMEOUT_S)",) \
		$(if $(DRY_RUN),--dry-run,)

uat-docker-cleanup:
	@uv run --no-sync -- python -m tests.uat._cli docker-cleanup \
		$(if $(ENGINE),--engine "$(ENGINE)",) \
		$(if $(MODE),--mode "$(MODE)",) \
		$(if $(PREFIX),--prefix "$(PREFIX)",) \
		$(if $(APPLY),--apply,)

uat-sweep:
	@if [ -z "$(CONFIG)" ]; then \
		echo "Usage: make uat-sweep CONFIG=<path> [DRY_RUN=1]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli sweep --config "$(CONFIG)" \
		$(if $(DRY_RUN),--dry-run,)

uat-smoke:
	@uv run --no-sync -- python -m tests.uat._cli sweep --config tests/uat/configs/uat-smoke.yaml

uat-stress:
	@uv run --no-sync -- python -m tests.uat._cli stress \
		$(if $(CONFIG),--config "$(CONFIG)",) \
		$(if $(PLATFORM),--platform "$(PLATFORM)",) \
		$(if $(BENCHMARK),--benchmark "$(BENCHMARK)",) \
		$(if $(SCALE),--scale "$(SCALE)",)

uat-gate-check:
	@if [ -z "$(STAGE1)" ] || [ -z "$(STAGE2)" ] || [ -z "$(STAGE3)" ]; then \
		echo "Usage: make uat-gate-check STAGE1=<run-dir> STAGE2=<run-dir> STAGE3=<run-dir> [OUTPUT=<path>]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli gate-check \
		--stage1 "$(STAGE1)" \
		--stage2 "$(STAGE2)" \
		--stage3 "$(STAGE3)" \
		$(if $(OUTPUT),--output "$(OUTPUT)",)

uat-execute:
	@if [ -z "$(CONFIG)" ]; then \
		echo "Usage: make uat-execute CONFIG=<path>" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli execute \
		--config "$(CONFIG)" \
		$(if $(DATABASES_ROOT),--databases-root "$(DATABASES_ROOT)",) \
		$(if $(NO_CLEANUP),--no-cleanup,)

include $(BENCHBOX_MAKEFILE_ROOT)make/help.mk
