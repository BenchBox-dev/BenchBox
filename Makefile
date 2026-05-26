# BenchBox Makefile
# This makefile provides commands for building, testing and development

PR_FANOUT_JOBS ?= 4
PR_REVIEW_BASE ?= develop
PR_REVIEW_PR_LIMIT ?= 1000
PR_REVIEW_MAX_COMMENTS ?= 0
PR_REVIEW_EXECUTOR_SANDBOX ?= workspace-write
PR_REVIEW_EXECUTOR_APPROVAL ?= never
POOL_SIZE ?= 10
WORKTREE_POOL_PARENT ?= ..
DEV_LOOP_METRICS_DAYS ?= 30
DEV_LOOP_METRICS_LIMIT ?= 100
AUDIT_SHA_TARGET_REF ?= origin/develop
AUDIT_SHA_REQUIRE_CURRENT ?=
# Minimum free disk space (in 1K-blocks) required on the pool parent
# directory before `make worktree-claim` will allocate a slot. Default
# 5 GB. Override to 0 to bypass the check (e.g. during low-space CI).
POOL_MIN_FREE_KB ?= 5000000
JOINORDER_BUILD_DIR ?= $(HOME)/Developer/benchmark_runs/joinorder/build/joinorder-imdb-2013-v1
JOINORDER_POSTGRES_DB ?= imdb
JOINORDER_POSTGRES_USER ?= postgres
JOINORDER_QUERIES ?= _project/joinorder/build-inputs/queries
JOINORDER_REFERENCE ?= _project/joinorder/reference_cardinalities.json

# Age threshold (in seconds) before a `.benchbox/claim_in_progress` marker
# is treated as evidence of an aborted claim by `worktree-pool-check`.
# Fresh markers indicate an in-flight `worktree-claim` and must not be
# reported as aborted: `worktree-pool-check` is documented as safe for
# periodic / cron use, and `worktree-claim` writes the marker at the
# start of a normal claim and only removes it at the end. Default 600s
# (10 min); concurrent claim runs typically finish in seconds.
POOL_CLAIM_MARKER_STALE_SECONDS ?= 600

# Shell command snippet that resolves the main clone's directory name
# (e.g. "BenchBox"). Pool worktree paths derive from it as
# $(WORKTREE_POOL_PARENT)/$(POOL_REPO_CMD).pool-NN. Inlined as a Make
# variable so the four pool-management targets share a single source of
# truth instead of repeating the four-deep nested expansion.
POOL_REPO_CMD = basename "$$(dirname "$$(realpath "$$(git rev-parse --git-common-dir)")")"

.PHONY: test test-unit test-integration test-tpch test-all test-fast test-unlock test-medium test-slow test-stress test-pytest clean lint lint-markers lint-explorer-tokens lint-site-theme-tokens artifact-hygiene audit-sha-check install develop coverage coverage-fast coverage-all coverage-html coverage-report coverage-check test-duckdb test-sqlite test-read-primitives test-benchmarks test-ci typecheck validate-imports catalog-schema-check format dependency-check docs-build docs-serve docs-clean docs-linkcheck docs-validate docs-check docs-images test-pyspark ci-lint ci-test ci-docs ci-local security-audit spellcheck docstring-coverage test-package test-integration-smoke test-local-matrix joinorder-verify-reference-results complexity-check complexity-report duplicate-check duplicate-check-verbose duplicate-check-json skill-sync skill-sync-check skill-sync-lock-audit mutation-test compile-tpcds-binaries parity-fixtures parity-check compat-docs compat-docs-check pr-preflight pr-preflight-fast-tests pr-content-guard pr-open pr-status pr-review-followups pr-review-followups-list dev-loop-metrics shrink-rollup worktree-pool-init worktree-pool-status worktree-pool-check worktree-claim worktree-claim-locked worktree-claim-attempt worktree-release worktree-pool-reset worktree-pool-sweep-stale worktree-pool-disk-clean worktree-add worktree-list worktree-prune todo-reindex

# Primary test commands using pytest marker system
test: test-fast
	@echo "Default test run completed. Use 'make help' to see all test options."

test-all:
	@echo "Running non-resource-heavy tests in parallel..."
	uv run -- python -m pytest -m "not (slow or stress or resource_heavy or live_integration)"
	@echo "Running slow and resource-heavy tests serially..."
	uv run -- python -m pytest -m "(slow or resource_heavy) and not (stress or live_integration)" -n 0

test-unit:
	uv run -- python -m pytest -m "unit" --tb=short

test-integration:
	uv run -- python -m pytest -m "integration and not live_integration and not stress" --tb=short

test-tpch:
	uv run -- python -m pytest -m "tpch" --tb=short

# Curated lightweight smoke lane
test-quick:
	uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short --maxfail=5

# Verbose test output for all tests
test-verbose:
	uv run -- python -m pytest -v

# Enhanced pytest commands using comprehensive marker system
test-pytest:
	uv run -- python -m pytest -m "not stress"

# Speed-based testing
test-fast:
	uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short

test-unlock:
	@LOCK_DIR="$${BENCHBOX_TEST_LOCK_DIR:-$$HOME/.benchbox}"; \
	case "$$LOCK_DIR" in \
		"~") LOCK_DIR="$$HOME" ;; \
		"~/"*) LOCK_DIR="$$HOME/$${LOCK_DIR#\~/}" ;; \
	esac; \
	LOCK_PATH="$$LOCK_DIR/test.lock"; \
	echo "Removing stale BenchBox test lock at $$LOCK_PATH..."; \
	rm -f "$$LOCK_PATH"
	@echo "Lock cleared."

test-medium:
	uv run -- python -m pytest -m "medium and not (slow or stress or resource_heavy or live_integration)" --tb=short --timeout=60 -n 5

test-slow:
	uv run -- python -m pytest -m "slow and not (stress or live_integration)" -n 0 --tb=short -v

test-stress:
	uv run -- python -m pytest -m "stress" -n 0 --tb=short -v

# Development cycle testing using the curated fast unit subset
test-dev:
	uv run -- python -m pytest -m "fast and unit and not (slow or stress or resource_heavy or live_integration)" --tb=short --maxfail=3

# Smoke tests (alias for test-quick)
test-smoke: test-quick

# Real benchmark matrix across local SQL platforms x all benchmarks (heavy, opt-in)
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

# Database-specific testing
test-duckdb:
	uv run -- python -m pytest -m "duckdb" --tb=short

test-sqlite:
	uv run -- python -m pytest -m "sqlite" --tb=short

test-pyspark:
	./scripts/run_pyspark_tests.sh

# Benchmark-specific testing
test-read-primitives:
	uv run -- python -m pytest -m "primitives" --tb=short

test-benchmarks:
	uv run -- python -m pytest -m "tpch or tpcds or ssb or amplab or clickbench or h2odb or merge" --tb=short

test-tpcds:
	uv run -- python -m pytest -m "tpcds" --tb=short

# Feature-specific testing
test-olap:
	uv run -- python -m pytest -m "olap" --tb=short

test-window:
	uv run -- python -m pytest -m "window_functions" --tb=short

# CI/CD testing
test-ci:
	uv run -- python -m pytest -c pytest-ci.ini -m "not (slow or flaky or local_only)" --cov=benchbox --cov-report=term-missing:skip-covered --cov-report=xml:coverage.xml

# Fast CI feedback (excludes cloud platform tests for speed)
test-no-cloud:
	uv run -- python -m pytest -m "not (slow or cloud_import)" --ignore=tests/unit/platforms/databricks --ignore=tests/unit/platforms/snowflake --ignore=tests/unit/platforms/bigquery --ignore=tests/unit/platforms/redshift --tb=short

# Complete test suite (nightly/full validation)
test-full:
	uv run -- python -m pytest -m "not stress" --tb=short -v

# Parallel testing
test-parallel:
	uv run -- python -m pytest -n auto --tb=short

test-parallel-fast:
	uv run -- python -m pytest -n auto -m "fast" --tb=short

# Live integration tests (require cloud credentials)
test-live:
	@echo "Running live integration tests (requires cloud credentials)"
	@echo "See .env.example for credential setup"
	uv run -- python -m pytest -m "live_integration" --tb=short -v

test-live-databricks:
	@echo "Running Databricks live tests (requires DATABRICKS_TOKEN)"
	uv run -- python -m pytest -m "live_databricks" --tb=short -v

test-live-snowflake:
	@echo "Running Snowflake live tests (requires SNOWFLAKE_PASSWORD)"
	uv run -- python -m pytest -m "live_snowflake" --tb=short -v

test-live-bigquery:
	@echo "Running BigQuery live tests (requires BIGQUERY_PROJECT)"
	uv run -- python -m pytest -m "live_bigquery" --tb=short -v

test-live-all:
	@echo "Running all live integration tests (requires credentials for all platforms)"
	uv run -- python -m pytest -m "live_integration" --tb=short -v

test-live-redshift:
	@echo "Running Redshift live tests (requires REDSHIFT_HOST)"
	uv run -- python -m pytest -m "live_redshift" --tb=short -v

test-live-athena:
	@echo "Running Athena live tests (requires ATHENA_REGION)"
	uv run -- python -m pytest -m "live_athena" --tb=short -v

test-live-firebolt:
	@echo "Running Firebolt live tests (requires FIREBOLT_CLIENT_ID)"
	uv run -- python -m pytest -m "live_firebolt" --tb=short -v

test-live-firebolt-core:
	@echo "Running Firebolt Core live tests (requires Docker - make test-docker-up-firebolt)"
	uv run -- python -m pytest -m "live_firebolt_core" --tb=short -v -n 0

test-live-starburst:
	@echo "Running Starburst Galaxy live tests (requires STARBURST_HOST)"
	uv run -- python -m pytest -m "live_starburst" --tb=short -v

test-live-motherduck:
	@echo "Running MotherDuck live tests (requires MOTHERDUCK_TOKEN)"
	uv run -- python -m pytest -m "live_motherduck" --tb=short -v

test-live-pg-duckdb:
	@echo "Running pg_duckdb live tests (requires Docker PostgreSQL with pg_duckdb)"
	uv run -- python -m pytest -m "live_pg_duckdb" --tb=short -v

test-live-pg-mooncake:
	@echo "Running pg_mooncake live tests (requires Docker PostgreSQL with pg_mooncake)"
	uv run -- python -m pytest -m "live_pg_mooncake" --tb=short -v

test-live-cedardb:
	@echo "Running CedarDB live tests (requires Docker CedarDB - make test-docker-up-cedardb)"
	uv run -- python -m pytest -m "live_cedardb" --tb=short -v -n 0

test-docker-up-pg-extensions:
	@echo "Starting pg_duckdb (port 5432) and pg_mooncake (port 5433)..."
	@set -e; \
		state_dir="$(DOCKER_TEST_STATE_DIR)"; \
		project_file="$$state_dir/pg-extensions.project"; \
		mkdir -p "$$state_dir"; \
		project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
		if [ -z "$$project_name" ]; then \
			project_name="benchbox-pg-extensions-test-$$(date +%s)-$$RANDOM"; \
		fi; \
		status=1; \
		cleanup() { \
			if [ $$status -ne 0 ]; then \
				docker compose -p "$$project_name" -f docker/postgres-extensions/docker-compose.yml down -v >/dev/null 2>&1 || true; \
				rm -f "$$project_file"; \
			fi; \
		}; \
		trap cleanup EXIT INT TERM; \
		docker compose -p "$$project_name" -f docker/postgres-extensions/docker-compose.yml up -d --wait; \
		printf '%s\n' "$$project_name" > "$$project_file"; \
		status=0

test-docker-down-pg-extensions:
	@set -e; \
		state_dir="$(DOCKER_TEST_STATE_DIR)"; \
		project_file="$$state_dir/pg-extensions.project"; \
		project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
		if [ -z "$$project_name" ]; then \
			echo "No tracked Docker test stack for pg-extensions"; \
			exit 0; \
		fi; \
		docker compose -p "$$project_name" -f docker/postgres-extensions/docker-compose.yml down -v; \
		rm -f "$$project_file"

test-docker-pg-extensions:
	@echo "Running pg_duckdb and pg_mooncake Docker integration tests"
	@set -e; \
		project_name="benchbox-pg-extensions-test-$$(date +%s)-$$RANDOM"; \
		cleanup() { docker compose -p "$$project_name" -f docker/postgres-extensions/docker-compose.yml down -v || true; }; \
		trap cleanup EXIT INT TERM; \
		docker compose -p "$$project_name" -f docker/postgres-extensions/docker-compose.yml up -d --wait; \
		uv run -- python -m pytest -m "live_pg_duckdb or live_pg_mooncake" --tb=short -v -n 0

# Docker-based integration tests (requires Docker and docker compose)
DOCKER_PLATFORMS := clickhouse trino presto postgresql starrocks doris databend influxdb cedardb firebolt questdb singlestore
DOCKER_TEST_STATE_DIR ?= /tmp/benchbox-docker-projects

test-docker-up-%:
	@set -e; \
		state_dir="$(DOCKER_TEST_STATE_DIR)"; \
		project_file="$$state_dir/$*.project"; \
		mkdir -p "$$state_dir"; \
		project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
		if [ -z "$$project_name" ]; then \
			project_name="benchbox-$*-test-$$(date +%s)-$$RANDOM"; \
		fi; \
		status=1; \
		cleanup() { \
			if [ $$status -ne 0 ]; then \
				docker compose -p "$$project_name" -f docker/$*/docker-compose.yml down -v >/dev/null 2>&1 || true; \
				rm -f "$$project_file"; \
			fi; \
		}; \
		trap cleanup EXIT INT TERM; \
		docker compose -p "$$project_name" -f docker/$*/docker-compose.yml up -d --wait; \
		printf '%s\n' "$$project_name" > "$$project_file"; \
		status=0

test-docker-down-%:
	@set -e; \
		state_dir="$(DOCKER_TEST_STATE_DIR)"; \
		project_file="$$state_dir/$*.project"; \
		project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
		if [ -z "$$project_name" ]; then \
			echo "No tracked Docker test stack for $*"; \
			exit 0; \
		fi; \
		docker compose -p "$$project_name" -f docker/$*/docker-compose.yml down -v; \
		rm -f "$$project_file"

# Explicit override: generic test-docker-% expands to -m "live_firebolt" (cloud tests).
# Firebolt Core Docker tests use the separate live_firebolt_core marker.
test-docker-firebolt:
	@echo "Running Firebolt Core Docker integration tests"
	@set -e; \
		project_name="benchbox-firebolt-test-$$(date +%s)-$$RANDOM"; \
		cleanup() { docker compose -p "$$project_name" -f docker/firebolt/docker-compose.yml down -v || true; }; \
		trap cleanup EXIT INT TERM; \
		docker compose -p "$$project_name" -f docker/firebolt/docker-compose.yml up -d --wait; \
		uv run -- python -m pytest -m "live_firebolt_core" --tb=short -v -n 0

test-docker-%:
	@echo "Running $* Docker integration tests"
	@set -e; \
		project_name="benchbox-$*-test-$$(date +%s)-$$RANDOM"; \
		cleanup() { docker compose -p "$$project_name" -f docker/$*/docker-compose.yml down -v || true; }; \
		trap cleanup EXIT INT TERM; \
		docker compose -p "$$project_name" -f docker/$*/docker-compose.yml up -d --wait; \
		uv run -- python -m pytest -m "live_$*" --tb=short -v -n 0

test-docker-up-all:
	@set -e; \
		state_dir="$(DOCKER_TEST_STATE_DIR)"; \
		mkdir -p "$$state_dir"; \
		run_id="$$(date +%s)-$$RANDOM"; \
		status=1; \
		cleanup() { \
			if [ $$status -ne 0 ]; then \
				echo "Cleaning up partially started Docker services..."; \
				for p in $(DOCKER_PLATFORMS); do \
					project_file="$$state_dir/$$p.project"; \
					project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
					if [ -n "$$project_name" ]; then \
						docker compose -p "$$project_name" -f docker/$$p/docker-compose.yml down -v >/dev/null 2>&1 || true; \
						rm -f "$$project_file"; \
					fi; \
				done; \
			fi; \
		}; \
		trap cleanup EXIT INT TERM; \
		for p in $(DOCKER_PLATFORMS); do \
			project_file="$$state_dir/$$p.project"; \
			project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
			if [ -z "$$project_name" ]; then \
				project_name="benchbox-$$p-test-$$run_id"; \
				printf '%s\n' "$$project_name" > "$$project_file"; \
			fi; \
			echo "Starting $$p..."; \
			docker compose -p "$$project_name" -f docker/$$p/docker-compose.yml up -d --wait; \
		done; \
		status=0

test-docker-down-all:
	@set -e; \
		state_dir="$(DOCKER_TEST_STATE_DIR)"; \
		for p in $(DOCKER_PLATFORMS); do \
			project_file="$$state_dir/$$p.project"; \
			project_name="$$(cat "$$project_file" 2>/dev/null || true)"; \
			if [ -z "$$project_name" ]; then \
				echo "Skipping $$p (no tracked Docker test stack)"; \
				continue; \
			fi; \
			echo "Stopping $$p..."; \
			docker compose -p "$$project_name" -f docker/$$p/docker-compose.yml down -v; \
			rm -f "$$project_file"; \
		done

test-docker-all:
	@echo "Running all Docker integration tests (requires Docker)"
	@for p in $(DOCKER_PLATFORMS); do \
		echo "=== Testing $$p ==="; \
		$(MAKE) test-docker-$$p || exit 1; \
	done

# Coverage commands using pytest
coverage-fast:
	uv run -- python -m pytest -c pytest-ci.ini -m "fast and not (slow or stress or resource_heavy or live_integration or cloud_import)" --cov=benchbox --cov-report=term-missing:skip-covered

coverage-all:
	uv run -- python -m pytest -c pytest-ci.ini --cov=benchbox --cov-branch --cov-report=term-missing:skip-covered --cov-report=html:htmlcov --cov-report=xml:coverage.xml

coverage: coverage-all

coverage-html:
	uv run -- python -m pytest -c pytest-ci.ini --cov=benchbox --cov-report=html:htmlcov

coverage-report:
	uv run -- python -m pytest -c pytest-ci.ini --cov=benchbox --cov-report=xml:coverage.xml --cov-report=term-missing


# Cyclomatic complexity checks
complexity-check:
	uv run -- python scripts/check_complexity.py

complexity-report:
	uv run -- python scripts/check_complexity.py --no-fail --top 30

# Install and development
install:
	uv sync

develop:
	uv sync --group dev

# Clean build artifacts
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

# Linting (ruff + explorer token scan)
lint:
	uv run ruff check .
	$(MAKE) lint-explorer-tokens
	$(MAKE) lint-site-theme-tokens

# Dependency audit - checks that every declared dep has an import site or is allowlisted.
# Fails if an unused dep is introduced. See _project/scripts/dependency_audit/.
audit-deps:
	uv run -- python _project/scripts/dependency_audit/check_deps.py

# Validate that an audit report records the develop SHA it describes.
audit-sha-check:
	@test -n "$(FILE)" || { echo "Usage: make audit-sha-check FILE=<audit.md>"; exit 1; }
	uv run --no-project -- python _project/scripts/audit_sha_check.py \
		--target-ref "$(AUDIT_SHA_TARGET_REF)" \
		$(if $(AUDIT_SHA_REQUIRE_CURRENT),--require-current $(AUDIT_SHA_REQUIRE_CURRENT),) \
		"$(FILE)"

# Validate test marker annotations - fails on speed-lane conflicts or fast-incompatible pairs.
# Uses --collect-only so no tests run; the conflict-detection hook fires at collection time.
lint-markers:
	uv run -- python -m pytest --collect-only -q -p no:warnings

# Token-scan gate for the Results Explorer retheme: fails when raw Tailwind
# palette literals (text-/bg-/border-/...-{slate|gray|...}-{50..950}) appear
# under results-explorer/src outside an explicit allowlist marker. Stdlib-only
# so no dependency sync is required before the gate runs.
lint-explorer-tokens:
	python3 _project/scripts/scan_explorer_tokens.py

lint-site-theme-tokens:
	python3 _project/scripts/scan_explorer_tokens.py landing/shared landing/index.html landing/style.css landing/prompts/index.html landing/prompts/prompts.css docs/_templates/page.html docs/_static/custom.css results-explorer/index.html results-explorer/src/components/Layout.tsx

# Stale-theme gate: fails when active Results Explorer source/tests or
# unsuperseded analysis files revive the retired mixed-theme contract phrases.
# Allowlist: inline `allow-stale-theme: <reason>` marker, or a supersession
# header (Superseded / supersedes / supersession) in `_project/analysis/*`
# files. `_project/DONE/*` is excluded by design.
lint-explorer-stale-theme:
	python3 _project/scripts/scan_explorer_stale_theme.py

artifact-hygiene:
	uv run -- python _project/scripts/artifact_hygiene_check.py --all-tracked

# skill-sync — materialize project-local skill mirrors from ~/.skill-sync/skills.
# Manifest is tracked (skill-sync.yaml/skill-sync.lock); the materialized
# .claude/skills, .codex/skills, .gemini/skills are gitignored and regenerated
# locally per developer. Override SKILL_SYNC to point at a different install
# (e.g. an npm-installed copy).
SKILL_SYNC ?= /Users/joe/Developer/skill-sync/dist/cli/index.js

skill-sync:
	@if [ -f "$(SKILL_SYNC)" ]; then \
		node "$(SKILL_SYNC)" sync; \
	else \
		echo "skill-sync not installed at $(SKILL_SYNC); skipping (override with SKILL_SYNC=path/to/dist/cli/index.js)"; \
	fi

skill-sync-check:
	@if [ -f "$(SKILL_SYNC)" ]; then \
		node "$(SKILL_SYNC)" doctor; \
	else \
		echo "skill-sync not installed at $(SKILL_SYNC); skipping (override with SKILL_SYNC=path/to/dist/cli/index.js)"; \
	fi

# Review helper for PRs that modify skill-sync.lock while .claude/skills is gitignored.
# Usage: make skill-sync-lock-audit [BASE=origin/develop] [TODO=_project/.../item.yaml] [CHECK=1]
skill-sync-lock-audit:
	uv run --project _project/scripts -- python _project/scripts/skill_sync_lock_audit.py \
		--base $${BASE:-origin/develop} \
		$${TODO:+--todo $$TODO} \
		$${CHECK:+--check}

# Duplicate code detection (AST structural clone detection)
duplicate-check:
	uv run -- python scripts/check_duplicate_code.py

duplicate-check-verbose:
	uv run -- python scripts/check_duplicate_code.py --verbose --top-n 30

duplicate-check-json:
	uv run -- python scripts/check_duplicate_code.py --json

mutation-test:
	@echo "Running mutation tests on critical modules..."
	uv run -- mutmut run
	@echo "--- Mutation test results ---"
	uv run -- mutmut results

##@ CI Local Equivalents
# These targets mirror GitHub Actions workflows for local validation

# CI lint check - exact match for lint.yml workflow
ci-lint:
	@echo "Running CI lint checks..."
	uv run ruff check .
	uv run ruff format --check .
	uv run ty check
	$(MAKE) lint-markers
	$(MAKE) lint-explorer-tokens
	$(MAKE) lint-site-theme-tokens
	$(MAKE) artifact-hygiene
	$(MAKE) skill-sync-check
	uv run -- python _project/scripts/timing_policy_check.py --strict
	$(MAKE) compat-docs-check
	$(MAKE) audit-deps
	@echo "✅ CI lint checks passed"

# CI test check - exact match for test.yml workflow (fast tests with coverage)
# Note: -p pytest_cov re-enables pytest-cov which is disabled by default in pytest.ini
# Suite-wide coverage threshold set to 70%. tests/conftest.py emits a separate
# non-failing advisory warning below 80%; 70 is the blocking CI floor.
ci-test:
	@echo "Running CI test suite..."
	uv run -- python -m pytest tests -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short -p pytest_cov --cov=benchbox --cov-report=xml:coverage.xml --cov-report=term-missing --cov-fail-under=70
	@echo "✅ CI test suite passed"

# CI docs build - exact match for docs.yml workflow
ci-docs:
	@echo "Running CI docs checks..."
	@$(MAKE) docs-validate
	@cd docs && uv run sphinx-build -b html --keep-going . _build/html
	@echo "✅ CI docs build passed"

# Security audit - exact match for test.yml security job
security-audit:
	@echo "Running security audit..."
	@if [ -n "$(PIP_AUDIT_IGNORE_VULNS)" ]; then \
		IGNORE_ARGS=$$(printf '%s' "$(PIP_AUDIT_IGNORE_VULNS)" | tr ',' '\n' | sed '/^$$/d;s/^/--ignore-vuln /' | tr '\n' ' '); \
		uvx pip-audit $$IGNORE_ARGS; \
	else \
		uvx pip-audit; \
	fi
	@echo "✅ Security audit passed"

# Spellcheck - exact match for docs.yml spellcheck job
spellcheck:
	@echo "Running spellcheck..."
	uvx codespell --ignore-words=.codespell-ignore.txt --skip="*.pyc,_build,*.json,*.lock,*.svg,*.min.js,*.min.css,_binaries,*.tpl,*.dst,*.tbl,_sources,benchmark_runs,*.dat,*.pdf,_project,_blog,htmlcov,.venv"
	@echo "✅ Spellcheck passed"

# Linkcheck - exact match for docs.yml linkcheck job
ci-linkcheck:
	@echo "Running documentation link check..."
	@cd docs && uv run sphinx-build -b linkcheck . _build/linkcheck
	@echo "Link check results:"
	@cat docs/_build/linkcheck/output.txt 2>/dev/null || echo "No output file generated"
	@echo "✅ Linkcheck passed"

# Docstring coverage - exact match for docs.yml docstring-coverage job
docstring-coverage:
	@echo "Running docstring coverage check..."
	uvx interrogate -c pyproject.toml --fail-under 90 benchbox/
	@echo "✅ Docstring coverage passed"

# Package build and install test - exact match for test.yml test-package job
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

# Integration smoke tests - exact match for test.yml integration-smoke job
test-integration-smoke:
	@echo "Running integration smoke tests..."
	uv run -- python -m pytest tests/integration -m "platform_smoke or (integration and fast)" --tb=short
	@echo "✅ Integration smoke tests passed"

# Run all CI checks locally - ensures CI will pass before push
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

# Type checking
typecheck:
	uv run ty check

# Backward-compatible alias for older local notes/scripts.
typecheck-uv: typecheck

# Import validation
validate-imports:
	uv run -- python scripts/validate_imports.py

# Field-level schema validation for migrated YAML catalogs (see benchbox/core/catalog_schema.py).
catalog-schema-check:
	uv run -- python -m benchbox.core.catalog_schema

# Dependency matrix / validation
dependency-check:
	uv run -- python -m benchbox.utils.dependency_validation $(ARGS)
# Format code (ruff formatter)
format:
	uv run ruff format .

##@ Documentation

# Build Sphinx documentation locally
docs-build:
	@echo "Building documentation..."
	@cd docs && uv run sphinx-build -b html --keep-going . _build/html
	@echo "✅ Docs built: docs/_build/html/index.html"

# Build and serve documentation on http://localhost:8000
docs-serve: docs-build
	@echo "Serving docs at http://localhost:8000"
	@echo "Press Ctrl+C to stop"
	@cd docs/_build/html && uv run -- python -m http.server 8000

# Clean documentation build artifacts
docs-clean:
	@echo "Cleaning documentation build artifacts..."
	@rm -rf docs/_build
	@echo "✅ Documentation artifacts cleaned"

# Check for broken links in documentation
docs-linkcheck:
	@echo "Checking documentation for broken links..."
	@cd docs && uv run sphinx-build -b linkcheck . _build/linkcheck
	@echo ""
	@echo "Link check results:"
	@cat docs/_build/linkcheck/output.txt || echo "No broken links found!"

# Validate example file references
docs-validate:
	@echo "Validating example file references..."
	@uv run -- python scripts/validate_example_references.py
	@echo ""
	@echo "Checking example file syntax..."
	@uv run -- python scripts/check_example_syntax.py
	@echo ""
	@echo "Validating visualization screenshot sync..."
	@uv run -- python scripts/validate_visualization_images.py

# Refresh generated visualization screenshots and sync shared docs/blog copies
docs-images:
	@echo "Capturing visualization screenshots..."
	@uv run -- python scripts/capture_chart_images.py

# Regenerate the /prompts/ landing route catalog include from catalog.yaml.
prompt-quickstarts-write:
	@uv run -- python scripts/generate_landing_quickstarts.py --write

# Fail if landing/prompts/catalog.generated.js is stale or invalid.
# Wired into docs CI by `landing-prompts-launch-gates`.
prompt-quickstarts-check:
	@uv run -- python scripts/generate_landing_quickstarts.py --check

# Run all documentation checks (build, linkcheck, validate)
docs-check: docs-validate docs-linkcheck docs-build
	@echo ""
	@echo "✅ All documentation checks passed!"

# Compile TPC-DS (and TPC-H) binaries from patched sources for the current
# platform and deploy them into benchbox/_binaries/ so they are used at runtime.
# No Docker required - builds natively on macOS ARM64/x86_64.
# Run this whenever _sources/tpc-ds/tools/ patches change.
compile-tpcds-binaries:
	bash _sources/compilation/scripts/compile-all-platforms.sh --native

# ---------------------------------------------------------------------------
# Visualization parity fixtures (CLI↔explorer contract)
# ---------------------------------------------------------------------------

# Regenerate fixtures from the canonical Python implementation.
# This CHANGES the contract - commit the resulting diff after review.
parity-fixtures:
	uv run python tests/parity/generate_visualization_fixtures.py

# Regenerate sql_compat capability matrix and skip reference docs from the registry.
compat-docs:
	uv run -- python scripts/generate_compat_docs.py

# Verify committed compat docs and DDL governance match the registry/source.
compat-docs-check:
	uv run -- python scripts/generate_compat_docs.py --check
	uv run -- python -m benchbox.sql_compat.inventory --output /tmp/benchbox-compat-inventory.jsonl --check-ddl-drift

# Verify fixtures match the current Python implementation without overwriting.
# Fails if any fixture is out of date (drift detected).
parity-check:
	@tmpdir=$$(mktemp -d) && \
	uv run -- python tests/parity/generate_visualization_fixtures.py --out $$tmpdir && \
	diff -r --exclude='.gitkeep' tests/parity/fixtures $$tmpdir && \
	echo "parity-check: fixtures match Python source" && \
	rm -rf $$tmpdir || \
	(echo "parity-check FAILED: fixtures are out of date - run 'make parity-fixtures' to regenerate" && rm -rf $$tmpdir && exit 1)

# Create distribution packages
dist: clean
	uv build

# Run a specific test file
# Usage: make run-test TEST=tests/specialized/test_tpch_minimal.py
run-test:
	uv run -- python $(TEST)

# ---------------------------------------------------------------------------
# Release flow (single-repo migration, version-branch model)
# ---------------------------------------------------------------------------
# These targets must be run from the public clone (origin -> joeharris76/BenchBox).
# Do NOT invoke from the legacy private clone — it has no `origin` remote.
#
# Flow: develop -> v$(VERSION) -> (squash) main -> tag main -> release.yml publishes
#   develop is intentionally NOT modified post-release. dev-only paths and
#   deferred release surfaces (_project/, _blog/, results explorer, AGENTS.md,
#   etc.) live on develop and are removed from the release branch by
#   release-cut's curation step. landing/ and docs/blog/ stay in the release
#   tree.
#
# See docs/operations/release-guide.md and _project/decisions/single-repo-migration.md.

RELEASE_REQUIRED_CONTEXTS := validate-base release-required-result

.PHONY: release-cut release-finalize

# Cut a release branch from develop in one shot:
#   1. Create v$(VERSION) branch off develop (develop is not modified).
#   2. On v$(VERSION): bump version sources (scripts/update_version.py).
#   3. On v$(VERSION): generate CHANGELOG.md entry.
#   4. $EDITOR opens CHANGELOG.md for hand-curation (skipped if EDITOR unset).
#   5. Curate: git rm dev-only/deferred paths (per A3 in single-repo-migration.md).
#   6. Commit "Release v$(VERSION)" (bump + changelog + curation in one squash-friendly commit).
#   7. Push, open PR vs main.
#   8. Sweep stale v* branches on origin (option-c lifecycle).
# Pre-conditions: on develop, clean tree.
# Usage: make release-cut VERSION=X.Y.Z
release-cut:
	@test -n "$(VERSION)" || (echo "Usage: make release-cut VERSION=X.Y.Z" && exit 1)
	@[ "$$(git rev-parse --abbrev-ref HEAD)" = "develop" ] || (echo "Error: must be on develop branch" && exit 1)
	@[ -z "$$(git status --porcelain)" ] || (echo "Error: working tree must be clean" && exit 1)
	git fetch origin
	git checkout -b v$(VERSION) develop
	uv run -- python scripts/update_version.py --version $(VERSION) --update-pyproject
	uv run -- python scripts/generate_changelog_entry.py --version $(VERSION)
	@if [ -n "$$EDITOR" ]; then \
		echo "==> Opening CHANGELOG.md in $$EDITOR for hand-curation"; \
		$$EDITOR CHANGELOG.md; \
	elif [ -t 0 ]; then \
		echo "==> EDITOR unset; skipping interactive CHANGELOG curation"; \
	else \
		echo "ERROR: EDITOR unset and no TTY — refusing to skip changelog curation in headless mode." >&2; exit 1; \
	fi
	@# Curation FIRST so dev-only paths are never staged. Order matters: git rm
	@# before git add ensures untracked files inside _project/ etc. don't end up
	@# staged-for-add by a later git add.
	@# Curation list: A3 of _project/decisions/single-repo-migration.md.
	-git rm -rf _project _blog results-data results-explorer .claude .codex .gemini
	-git rm -f .pre-commit-config.yaml _benchbox_pytest_xdist_safety.py todo.config.yaml skill-sync.yaml skill-sync.lock .coveragerc_core .dockerignore .env.example .mcp.json AGENTS.md CLAUDE.md GEMINI.md
	-git rm -f .github/workflows/results-explorer-browser.yml .github/workflows/seed-corpus.yml .github/workflows/sync-results-data-to-published.yml .github/workflows/validate-submission.yml
	@# Stage only the files update_version.py + generate_changelog_entry.py write.
	@# Explicit list (not `git add -A`) to avoid staging build/cache artifacts.
	git add pyproject.toml benchbox/__init__.py landing/index.html README.md docs/README.md benchbox/utils/VERSION_MANAGEMENT.md CHANGELOG.md
	git commit -m "Release v$(VERSION)"
	git push -u origin v$(VERSION)
	gh pr create --base main --head v$(VERSION) --title "Release v$(VERSION)" --body-file .github/RELEASE_PR_TEMPLATE.md
	@# Option-c lifecycle: delete any prior v* branches on origin (loop sweeps stale entries).
	@# Use grep -Fxv (literal, full-line match) so version strings with `.` aren't treated as regex.
	@for br in $$(git ls-remote --heads origin 'v*' | awk '{print $$2}' | sed 's|refs/heads/||' | grep -Fxv "v$(VERSION)"); do \
		echo "==> Deleting prior release branch on origin: $$br"; \
		git push origin --delete "$$br" || true; \
	done
	@echo
	@echo "Release PR opened. Next steps:"
	@echo "  1. Review the PR diff; confirm CHANGELOG and curation are correct."
	@echo "  2. Wait for the required release contexts: $(RELEASE_REQUIRED_CONTEXTS)."
	@echo "  3. make release-finalize VERSION=$(VERSION)"

# After release-cut's PR is approved and all required release contexts are
# green: squash-merge it, tag main, push the tag (fires release.yml), and
# leave develop alone.
# Usage: make release-finalize VERSION=X.Y.Z
release-finalize:
	@test -n "$(VERSION)" || (echo "Usage: make release-finalize VERSION=X.Y.Z" && exit 1)
	@PR=$$(gh pr list --base main --head v$(VERSION) --state open --json number --jq '.[0].number'); \
	test -n "$$PR" || (echo "Error: no open PR found for v$(VERSION) → main" && exit 1); \
	echo "==> Verifying required release contexts '$(RELEASE_REQUIRED_CONTEXTS)' for PR #$$PR"; \
	for context in $(RELEASE_REQUIRED_CONTEXTS); do \
		CHECK_BUCKET=$$(gh pr checks "$$PR" --required --json name,bucket,state --jq "map(select(.name == \"$$context\")) | if length == 1 then .[0].bucket elif length == 0 then \"missing\" else \"duplicate\" end"); \
		CHECK_RC=$$?; \
		if [ "$$CHECK_RC" != "0" ] && [ "$$CHECK_RC" != "8" ]; then \
			echo "Error: gh pr checks failed while verifying $$context (exit $$CHECK_RC)" >&2; \
			exit "$$CHECK_RC"; \
		fi; \
		case "$$CHECK_BUCKET" in \
			pass) echo "==> $$context is green";; \
			missing) echo "Error: required release context '$$context' is missing. Check main-release-only and release workflows." >&2; exit 1;; \
			pending) echo "Error: required release context '$$context' is pending. Wait for GitHub Actions, then rerun." >&2; exit 1;; \
			fail|cancel|skipping) echo "Error: required release context '$$context' is $$CHECK_BUCKET. Fix the release PR before finalizing." >&2; exit 1;; \
			duplicate) echo "Error: multiple required contexts named '$$context' were returned. Fix workflow/ruleset drift." >&2; exit 1;; \
			*) echo "Error: unexpected $$context status '$$CHECK_BUCKET'." >&2; exit 1;; \
		esac; \
	done; \
	echo "==> Squash-merging PR #$$PR (required release contexts are green)"; \
	gh pr merge --squash "$$PR"
	git fetch origin --tags
	git checkout main
	git pull --ff-only origin main
	git tag v$(VERSION)
	git push origin v$(VERSION)
	@echo
	@echo "Tag v$(VERSION) pushed; release.yml will publish to PyPI."
	@echo "Push-to-main jobs are post-merge signals; release publication relied on $(RELEASE_REQUIRED_CONTEXTS)."
	@echo "develop is intentionally unchanged — dev-only paths persist on develop."

# =============================================================================
# PR + worktree workflow
# Solo-dev develop is PR-gated (CI must be green; linear history; squash).
# These targets collapse the PR roundtrip to one command and let multiple
# branches stay live in parallel via worktrees.
# =============================================================================

.PHONY: pr-preflight pr-preflight-fast-tests pr-content-guard pr-open pr-fanout pr-refresh pr-conflict-scan pr-status pr-review-followups pr-review-followups-list dev-loop-metrics shrink-rollup audit-sha-check worktree-pool-init worktree-pool-status worktree-pool-check worktree-claim worktree-claim-locked worktree-claim-attempt worktree-release worktree-release-locked worktree-pool-reset worktree-pool-reset-locked worktree-pool-sweep-stale worktree-pool-sweep-stale-locked worktree-pool-disk-clean worktree-add worktree-list worktree-prune todo-reindex blind-spots-list blind-spots-report blind-spots-sweep

# Lightweight local gate before pushing. Mirrors CI lint and fast marker
# selection, but not CI's coverage fail-under; run ci-test for the exact
# coverage-enforced test workflow.
pr-preflight:
	@$(MAKE) ci-lint
	@$(MAKE) pr-preflight-fast-tests

pr-preflight-fast-tests:
	@DECISION=$$(mktemp); \
	LISTS=$$(mktemp -d); \
	trap 'rm -f "$$DECISION"; rm -rf "$$LISTS"' EXIT; \
	git fetch origin develop --quiet; \
	uv run -- python scripts/path_filter_decision.py --base-ref origin/develop --json-out "$$DECISION" --lists-dir "$$LISTS" >/dev/null; \
	if uv run -- python scripts/path_filter_decision.py --json-in "$$DECISION" --check needs-code-ci >/dev/null; then \
		echo "==> fast tests (CI marker selection; coverage remains CI-only)"; \
		uv run -- python -m pytest -m "fast and not (slow or stress or resource_heavy or live_integration)" --tb=short -q; \
	else \
		$(MAKE) -s pr-content-guard PATH_LISTS="$$LISTS"; \
		echo "No code changes detected; skipping fast tests."; \
	fi

pr-content-guard:
	@[ -n "$(PATH_LISTS)" ] || { echo "PATH_LISTS is required"; exit 2; }; \
	$(MAKE) artifact-hygiene; \
	if [ -s "$(PATH_LISTS)/yaml.txt" ]; then \
		uv run -- pre-commit run check-yaml --files $$(cat "$(PATH_LISTS)/yaml.txt"); \
	else \
		echo "No YAML content paths changed."; \
	fi; \
	if [ -s "$(PATH_LISTS)/markdown.txt" ]; then \
		uv run -- pre-commit run markdownlint --files $$(cat "$(PATH_LISTS)/markdown.txt"); \
	else \
		echo "No markdown content paths changed."; \
	fi; \
	if [ -s "$(PATH_LISTS)/todo.txt" ]; then \
		while IFS= read -r todo_path; do \
			if [ ! -e "$$todo_path" ]; then \
				echo "Skipping deleted TODO/DONE path: $$todo_path"; \
				continue; \
			fi; \
			uv run --project _project/scripts -- python _project/scripts/validate_todo.py "$$todo_path"; \
		done < "$(PATH_LISTS)/todo.txt"; \
		uv run --project _project/scripts -- python _project/scripts/todo_cli.py check-graph; \
	else \
		echo "No TODO/DONE YAML paths changed."; \
	fi; \
	if [ -s "$(PATH_LISTS)/docs.txt" ]; then \
		$(MAKE) docs-validate; \
	else \
		echo "No docs paths changed."; \
	fi

# Push current branch and open a PR against develop with auto-merge enabled.
# Squash-merge happens automatically once `lint` + `test (ubuntu-latest, 3.12)`
# go green. Refuses to run from develop/main.
#
# Idempotent: safe to rerun. If a PR is already open for the branch, reuses it
# and just (re)enables auto-merge — useful after a partial run, or to flip
# auto-merge on for a PR opened via `gh pr create` directly.
#
# Pre-push warning: runs `git merge-tree` against every other open PR head
# (pure git, ~1s, no CI) and prints any textual conflicts so you can coordinate
# before landing. Warn-only — does not block the push.
pr-open:
	@CURRENT=$$(git branch --show-current); \
	case "$$CURRENT" in \
		develop|main) echo "Refusing to open PR from $$CURRENT — switch to a feature branch."; exit 1 ;; \
	esac; \
	if [ -n "$(PR_BODY_FILE)" ] && [ ! -f "$(PR_BODY_FILE)" ]; then \
		echo "PR_BODY_FILE does not exist: $(PR_BODY_FILE)" >&2; \
		exit 1; \
	fi; \
	$(MAKE) -s pr-conflict-scan BRANCH="$$CURRENT" || true; \
	git push -u origin "$$CURRENT" && \
	URL=$$(gh pr list --base develop --head "$$CURRENT" --state open --json url --jq '.[0].url' 2>/dev/null); \
	if [ -z "$$URL" ]; then \
		if [ -n "$(PR_BODY_FILE)" ]; then \
			URL=$$(gh pr create --base develop --fill --head "$$CURRENT" --body-file "$(PR_BODY_FILE)"); \
		else \
			URL=$$(gh pr create --base develop --fill --head "$$CURRENT"); \
		fi; \
	else \
		echo "Reusing existing PR: $$URL"; \
		if [ -n "$(PR_BODY_FILE)" ]; then \
			gh pr edit "$$URL" --body-file "$(PR_BODY_FILE)"; \
		fi; \
	fi && \
	echo "$$URL" && \
	gh pr merge --auto --squash "$$URL"

shrink-rollup:
	@git fetch origin develop --quiet
	@uv run --project _project/scripts -- python _project/scripts/shrink_rollup.py

# Walk every worktree (except the main clone) and run `make pr-open` in each.
# Use PR_FANOUT_JOBS to bound parallelism.
pr-fanout:
	@MAIN_CLONE=$$(dirname "$$(realpath "$$(git rev-parse --git-common-dir)")"); \
	TMP=$$(mktemp); \
	LOGDIR=$$(mktemp -d); \
	trap 'rm -f "$$TMP"; rm -rf "$$LOGDIR"' EXIT; \
	git worktree list --porcelain | sed -n 's/^worktree //p' | while IFS= read -r wt; do \
		[ "$$(realpath "$$wt")" = "$$MAIN_CLONE" ] && { echo "(skip $$wt: main clone)"; continue; }; \
		BR=$$(git -C "$$wt" branch --show-current 2>/dev/null); \
		case "$$BR" in develop|main|"") echo "(skip $$wt: branch=$$BR)"; continue ;; esac; \
		IDX=$$(($${IDX:-0} + 1)); \
		printf '%06d|%s\0' "$$IDX" "$$wt" >> "$$TMP"; \
	done; \
	if [ ! -s "$$TMP" ]; then exit 0; fi; \
	xargs -0 -n 1 -P "$(PR_FANOUT_JOBS)" sh -c 'logdir="$$1"; record="$$2"; idx="$${record%%|*}"; wt="$${record#*|}"; br=$$(git -C "$$wt" branch --show-current 2>/dev/null); { echo "==> $$wt [$$br]"; ( cd "$$wt" && $(MAKE) -s pr-open ) || echo "(failed: $$wt)"; } > "$$logdir/$$idx.log" 2>&1' sh "$$LOGDIR" < "$$TMP"; \
	STATUS=$$?; \
	for log in "$$LOGDIR"/*.log; do [ -e "$$log" ] && cat "$$log"; done; \
	exit $$STATUS

# Refresh the current PR branch onto origin/develop, then run pr-open.
# This is the stale-PR escape hatch when required checks must be current with
# develop: GitHub can show a PR as CLEAN even though auto-merge is waiting for
# a branch update. Run this one stale PR at a time; updating several branches
# at once can let the first merge stale the others again under strict checks.
pr-refresh:
	@CURRENT=$$(git branch --show-current); \
	case "$$CURRENT" in \
		develop|main|"") echo "Refusing to refresh $$CURRENT — switch to a feature branch worktree."; exit 1 ;; \
	esac; \
	git fetch origin develop --quiet && \
	git merge --no-edit origin/develop && \
	$(MAKE) -s pr-open

# Pure-git pairwise textual-conflict probe. Caller passes BRANCH=<current>;
# we compare HEAD against every other open PR head via `git merge-tree` and
# print warnings. Warn-only; does not exit non-zero. Used internally by pr-open.
pr-conflict-scan:
	@CURRENT="$(BRANCH)"; \
	[ -n "$$CURRENT" ] || CURRENT=$$(git branch --show-current); \
	gh pr list --base develop --state open --json number,headRefName \
		--jq '.[] | "\(.number) \(.headRefName)"' 2>/dev/null | \
	while read num branch; do \
		[ "$$branch" = "$$CURRENT" ] && continue; \
		git fetch origin "$$branch" --quiet 2>/dev/null || continue; \
		base=$$(git merge-base HEAD "origin/$$branch" 2>/dev/null) || continue; \
		out=$$(git merge-tree "$$base" HEAD "origin/$$branch" 2>/dev/null); \
		if echo "$$out" | grep -qE '^(<<<<<<<|changed in both|added in both|removed in local|removed in remote|CONFLICT )'; then \
			echo "  ⚠ textual conflict with PR #$$num ($$branch) — coordinate before landing"; \
		fi; \
	done; true

# Show open PRs against develop and their CI + auto-merge state.
pr-status:
	@gh pr list --base develop --state open --limit 20 --json number,title,headRefName,statusCheckRollup,autoMergeRequest \
		--template '{{range .}}#{{.number}} {{.title}} ({{.headRefName}}){{"\n"}}  auto-merge: {{if .autoMergeRequest}}ON{{else}}OFF{{end}}{{"\n"}}  checks: {{range .statusCheckRollup}}{{.name}}={{.conclusion}} {{end}}{{"\n\n"}}{{end}}'

# Discover candidate bot/agent review comments on merged PRs without making changes.
# Also reports merged PRs whose Codex review hit usage limits and still need a
# fresh @codex review trigger. Default --author filter is the
# chatgpt-codex-connector bot; override with --author (or by editing
# DEFAULT_REVIEW_AUTHORS in the script) to add other reviewers.
pr-review-followups-list:
	@uv run --project _project/scripts -- python _project/scripts/pr_review_followups.py list \
		--base "$(PR_REVIEW_BASE)" \
		--limit-prs "$(PR_REVIEW_PR_LIMIT)" \
		--max-comments "$(PR_REVIEW_MAX_COMMENTS)" \
		$(if $(PR_REVIEW_REPO),--repo "$(PR_REVIEW_REPO)") \
		$(if $(PR_REVIEW_SINCE),--since "$(PR_REVIEW_SINCE)") \
		$(if $(PR_REVIEW_UNTIL),--until "$(PR_REVIEW_UNTIL)")

# One-comment-at-a-time follow-up loop for merged PR review findings from any
# configured reviewer (default: chatgpt-codex-connector). The local executor is
# the codex CLI but is isolated behind --executor-* flags. Each actioned
# comment lands as its own commit *before* the GitHub marker reply is posted,
# so a mid-sweep crash never leaves a phantom-actioned thread on GitHub. After
# the loop, the routine runs pr-preflight and opens one PR through the normal
# pr-open workflow.
#
# Useful overrides:
#   PR_REVIEW_MAX_COMMENTS=N         cap an iteration batch
#   PR_REVIEW_SINCE=YYYY-MM-DD       scope by merged-at date
#   PR_REVIEW_EXECUTOR_MODEL=<name>  choose the executor model
#   PR_REVIEW_REPLY=0                skip GitHub replies. Only the literals
#                                    0|false|no disable; anything else
#                                    (including "1" or "true") is treated as
#                                    the default, so the reply is posted.
#   PR_REVIEW_SUBMIT=0               skip final pr-open. Same accepted values
#                                    as PR_REVIEW_REPLY above.
#   PR_REVIEW_USAGE_LIMIT_RETRY=0    skip the top-level Codex usage-limit
#                                    retry step. By default, the routine posts
#                                    @codex review on merged PRs with no later
#                                    trigger and keeps later-triggered PRs
#                                    visible until a review result appears.
#   PR_REVIEW_RESUME=1               re-drive the routine on a branch that
#                                    already carries per-comment commits from
#                                    a prior crashed sweep. Implies
#                                    --allow-dirty and skips comments already
#                                    committed locally. Only the literals
#                                    1|true|yes enable it.
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

# Initialize retained pool worktrees. Existing pool-NN paths are left untouched.
worktree-pool-init:
	@git fetch origin develop --quiet
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		if [ -e "$$wt" ]; then \
			git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { \
				echo "Path exists but is not a git worktree: $$wt" >&2; \
				exit 1; \
			}; \
			echo "$$pool exists: $$wt"; \
		else \
			echo "$$pool create: $$wt"; \
			git worktree add --detach "$$wt" origin/develop; \
			( cd "$$wt" && uv sync --group dev && uv run -- pre-commit install ); \
		fi; \
		i=$$((i + 1)); \
	done
	@POOL_REPO=$$($(POOL_REPO_CMD)); \
	printf '%-8s | %-60s | %s\n' "pool" "path" "branch"; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		if [ -d "$$wt/.git" ] || git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			branch=$$(git -C "$$wt" branch --show-current 2>/dev/null); \
			[ -n "$$branch" ] || branch="(detached)"; \
		else \
			branch="(missing)"; \
		fi; \
		printf '%-8s | %-60s | %s\n' "$$pool" "$$wt" "$$branch"; \
		i=$$((i + 1)); \
	done

# Claim the first free pool worktree for a feature branch.
#
# Concurrency: every pool-mutating target (claim, release, pool-reset,
# pool-sweep-stale) acquires the same `.git/pool.lock` via
# scripts/_with_pool_lock.sh. They serialize against each other so
# concurrent operations cannot leave a slot in a torn state. The lock
# does NOT cover read-only inspection (worktree-pool-status), which is
# safe to run anytime.
worktree-claim:
	@test -n "$(BRANCH)" || { echo "Usage: make worktree-claim BRANCH=<branch-name>"; exit 1; }
	@case "$(BRANCH)" in chore/?*|fix/?*|feat/?*|docs/?*) ;; *) echo "BRANCH must match ^(chore|fix|feat|docs)/.+"; exit 1 ;; esac
	@git check-ref-format --branch "$(BRANCH)" >/dev/null || { echo "Invalid git branch name: $(BRANCH)"; exit 1; }
	@if [ "$(POOL_MIN_FREE_KB)" -gt 0 ]; then \
		FREE_KB=$$(df -k "$(WORKTREE_POOL_PARENT)" 2>/dev/null | awk 'NR==2 {print $$4}'); \
		if [ -n "$$FREE_KB" ] && [ "$$FREE_KB" -lt "$(POOL_MIN_FREE_KB)" ]; then \
			echo "Refusing to claim: $$FREE_KB KB free on $(WORKTREE_POOL_PARENT) < $(POOL_MIN_FREE_KB) KB required." >&2; \
			echo "Hint: run \`make worktree-pool-disk-clean\` to drop pytest/coverage caches," >&2; \
			echo "      or override with \`POOL_MIN_FREE_KB=0 make worktree-claim BRANCH=...\`." >&2; \
			exit 1; \
		fi; \
	fi
	@git fetch origin develop --quiet
	@LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-claim-locked BRANCH="$(BRANCH)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"

# Orchestrator: try once, then auto-sweep stale slots, then try again.
# The auto-sweep means routine pool exhaustion (forgotten releases) is
# self-healing without operator intervention.
#
# The whole recipe runs in ONE shell (line continuations + a single `@`).
# Each `@`-prefixed make recipe line otherwise spawns its own subshell, so
# `if ... ; then exit 0; fi` would only exit that line's subshell — make
# would happily continue to the auto-sweep retry path even after a
# successful first attempt, falsely reporting failure to the caller.
worktree-claim-locked:
	@if $(MAKE) -s worktree-claim-attempt BRANCH="$(BRANCH)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"; then \
		exit 0; \
	fi; \
	echo "No free pool worktree on first pass — auto-sweeping stale slots..." >&2; \
	$(MAKE) -s worktree-pool-sweep-stale-locked POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)" >&2 || true; \
	if $(MAKE) -s worktree-claim-attempt BRANCH="$(BRANCH)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"; then \
		exit 0; \
	fi; \
	echo "Still no free pool worktree available after auto-sweep." >&2; \
	echo "Hint: dirty or claim-aborted slots are not auto-recovered (they may have valuable state)." >&2; \
	echo "      Run \`make worktree-pool-status\` to inspect, then \`make worktree-pool-reset POOL=NN\`" >&2; \
	echo "      as a last-resort manual escape hatch after reviewing what will be discarded." >&2; \
	exit 1

# Single-pass claim attempt. Iterates the pool once; on the first
# detached, clean, non-claim-aborted slot, hard-resets it to
# origin/develop (scrubbing any residual INDEX/working-tree skew from
# an interrupted release or manual `git checkout`) and mutates it to
# the requested branch under an EXIT trap that rolls back on any failure
# (including SIGINT/SIGTERM). EXIT is POSIX (works in dash/sh/bash); ERR
# is not.
# A `.benchbox/claim_in_progress` marker is written before mutation and
# removed on success or rollback; if the process is SIGKILL'd between
# write and removal, the marker survives and `worktree-pool-status`
# reports the slot as `aborted` so the operator knows it needs reset.
#
# The `reset --hard` immediately before the final emptiness check is the
# hardening for a subtle prior bug: `git status --porcelain` could return
# empty on a slot whose INDEX still had stale staged entries from a
# previous tenant (when the stale blob coincidentally matched HEAD's blob
# for that path). The gate accepted the slot as "clean detached", but
# the resulting worktree carried the previous tenant's INDEX into the new
# branch. Resetting before the final emptiness check normalizes the slot.
#
# Ordering: a normal porcelain gate runs before mutation so dirty
# detached slots are preserved for manual recovery. The marker is then
# written BEFORE `reset --hard` so the EXIT trap can roll back a slot
# whose reset is interrupted mid-flight (SIGINT/SIGTERM during the reset
# would otherwise leave the slot in a partial state with no
# aborted-marker signal). Slots skipped by the post-reset porcelain
# check or a transient reset failure remove the marker before `continue`
# so the trap's cleanup does not target the wrong slot on a later
# iteration. The cleanup function itself runs an extra `reset --hard` so
# an interrupted reset is fully normalized.
worktree-claim-attempt:
	@set -e; \
	marker=""; wt=""; pool=""; claim_ok=0; \
	cleanup() { \
		trap '' INT TERM; \
		if [ "$$claim_ok" != "1" ] && [ -n "$$marker" ]; then \
			cleanup_marker="$$marker"; cleanup_wt="$$wt"; cleanup_pool="$$pool"; \
			marker=""; \
			rm -f "$$cleanup_marker"; \
			git -C "$$cleanup_wt" checkout --detach origin/develop >/dev/null 2>&1 || true; \
			git -C "$$cleanup_wt" reset --hard origin/develop >/dev/null 2>&1 || true; \
			git -C "$$cleanup_wt" branch -D "$(BRANCH)" >/dev/null 2>&1 || true; \
			echo "claim of $$cleanup_pool failed; slot returned to detached origin/develop" >&2; \
		fi; \
	}; \
	on_int() { cleanup; exit 130; }; \
	on_term() { cleanup; exit 143; }; \
	trap cleanup EXIT; \
	trap on_int INT; \
	trap on_term TERM; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		i=$$((i + 1)); \
		git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue; \
		[ -f "$$wt/.benchbox/claim_in_progress" ] && continue; \
		branch=$$(git -C "$$wt" symbolic-ref -q --short HEAD 2>/dev/null || true); \
		[ -z "$$branch" ] || continue; \
		pre_status=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
		if [ -n "$$pre_status" ]; then \
			echo "claim skip $$pool: porcelain non-empty before reset" >&2; \
			continue; \
		fi; \
		marker="$$wt/.benchbox/claim_in_progress"; \
		mkdir -p "$$wt/.benchbox"; \
		printf 'pid=%s started=%s branch=%s\n' "$$$$" "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(BRANCH)" > "$$marker"; \
		if ! git -C "$$wt" reset --hard origin/develop >/dev/null 2>&1; then \
			rm -f "$$marker"; marker=""; \
			echo "claim skip $$pool: reset --hard origin/develop failed" >&2; \
			continue; \
		fi; \
		status=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
		if [ -n "$$status" ]; then \
			rm -f "$$marker"; marker=""; \
			echo "claim skip $$pool: post-reset porcelain non-empty (untracked residue)" >&2; \
			continue; \
		fi; \
		git -C "$$wt" checkout -b "$(BRANCH)" >/dev/null; \
		if [ ! -f "$$wt/.venv/pyvenv.cfg" ] \
			|| [ -n "$$(find "$$wt/uv.lock" "$$wt/pyproject.toml" -newer "$$wt/.venv/pyvenv.cfg" 2>/dev/null | head -n 1)" ]; then \
			( cd "$$wt" && uv sync --group dev >/dev/null ); \
		fi; \
		rm -f "$$marker"; \
		marker=""; \
		claim_ok=1; \
		printf 'WORKTREE_PATH=%s\n' "$$(cd "$$wt" && pwd -P)"; \
		exit 0; \
	done; \
	exit 1

worktree-release:
	@top=$$(git rev-parse --show-toplevel); \
	case "$$top" in *.pool-[0-9][0-9]) ;; *) echo "Refusing: worktree-release must run inside a pool-NN worktree."; exit 1 ;; esac; \
	LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-release-locked FORCE="$(FORCE)"

worktree-release-locked:
	@set -e; \
	top=$$(git rev-parse --show-toplevel); \
	branch=$$(git branch --show-current); \
	test -n "$$branch" || { echo "Refusing: this pool worktree is already detached/free."; exit 1; }; \
	case "$$branch" in develop|main) echo "Refusing to release protected branch $$branch."; exit 1 ;; esac; \
	dirty=$$(git status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
	if [ -n "$$dirty" ] && [ "$(FORCE)" != "1" ]; then \
		echo "Refusing to release dirty pool worktree $$top. Review changes or rerun with FORCE=1."; \
		echo "$$dirty"; \
		exit 1; \
	fi; \
	if [ "$(FORCE)" != "1" ]; then \
		state=$$(gh pr view "$$branch" --json state --jq .state 2>/dev/null || true); \
		[ "$$state" = "MERGED" ] || { echo "Refusing: PR for $$branch is not MERGED; open or close PR first, or rerun with FORCE=1."; exit 1; }; \
	fi; \
	git checkout --detach origin/develop; \
	git fetch origin develop --quiet; \
	git reset --hard origin/develop; \
	git branch -D "$$branch"; \
	git remote prune origin; \
	rm -rf "$$top/.venv"; \
	echo "Released $$branch; worktree is detached at origin/develop (.venv cleared; next claim will re-sync)."

## worktree-pool-status: report pool slot state + venv health + disk usage.
##
## Columns:
##   pool, path, branch, state, claim_age, venv, size
##
## State semantics:
##   free     — detached HEAD, working tree clean
##   claimed  — on a feature branch, no PR or PR is open
##   stale    — on a feature branch, PR is MERGED (release/sweep candidate)
##   dirty    — uncommitted changes (filtered against .benchbox/ scratch
##              dir which is the only expected non-ignored untracked path;
##              .venv/ is .gitignored, so it does not appear in --untracked-files=normal)
##   aborted  — `.benchbox/claim_in_progress` marker survived from a
##              previous claim that was SIGKILL'd or otherwise died
##              before its trap could clean up. Run pool-reset to recover.
##   unknown  — gh pr view/list lookup failed (auth / network / rate limit)
##              — distinguished from claimed-no-PR-yet
##   missing  — pool slot directory absent
##
## Venv health:
##   ok           — .venv/pyvenv.cfg exists and is at least as new as uv.lock + pyproject.toml
##   stale        — .venv exists but uv.lock or pyproject.toml is newer (next claim will re-sync)
##   missing      — .venv absent (claim will recreate; expected for free
##                  slots, since release/sweep clears `.venv/`)
##
## PR-state lookup is batched: a single `gh pr list --state all` runs up
## front and an associative awk lookup per slot replaces N per-slot
## `gh pr view` calls. The bulk window is bumped to 1000 (gh's
## effective max for one page); for any pool branch whose PR falls
## outside the window, a per-branch `gh pr view` fallback fills in the
## state so long-lived stale slots don't get misclassified as `claimed`.
worktree-pool-status:
	@POOL_REPO=$$($(POOL_REPO_CMD)); \
	pr_table=$$(gh pr list --state all --base develop --limit 1000 \
		--json headRefName,state \
		--template '{{range .}}{{.headRefName}}{{"\t"}}{{.state}}{{"\n"}}{{end}}' 2>/dev/null); \
	pr_lookup_failed=0; \
	if [ -z "$$pr_table" ]; then pr_lookup_failed=1; fi; \
	printf '%-8s | %-58s | %-28s | %-8s | %-13s | %-7s | %s\n' "pool" "path" "branch" "state" "claim_age" "venv" "size"; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		branch="-"; state="missing"; age="-"; venv="-"; size="-"; \
		if git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			current=$$(git -C "$$wt" symbolic-ref -q --short HEAD 2>/dev/null || true); \
			dirty=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
			aborted=0; \
			[ -f "$$wt/.benchbox/claim_in_progress" ] && aborted=1; \
			if [ ! -f "$$wt/.venv/pyvenv.cfg" ]; then \
				venv="missing"; \
			elif [ -n "$$(find "$$wt/uv.lock" "$$wt/pyproject.toml" -newer "$$wt/.venv/pyvenv.cfg" 2>/dev/null | head -n 1)" ]; then \
				venv="stale"; \
			else \
				venv="ok"; \
			fi; \
			size=$$(du -sh "$$wt" 2>/dev/null | awk '{print $$1}'); \
			[ -n "$$size" ] || size="-"; \
			if [ "$$aborted" = "1" ]; then \
				state="aborted"; \
				[ -n "$$current" ] && branch="$$current" || branch="(detached)"; \
				age=$$(git -C "$$wt" log -1 --format=%ar 2>/dev/null || echo "-"); \
			elif [ -z "$$current" ]; then \
				branch="(detached)"; \
				if [ -z "$$dirty" ]; then state="free"; else state="dirty"; fi; \
			else \
				branch="$$current"; \
				age=$$(git -C "$$wt" log -1 --format=%ar 2>/dev/null || echo "-"); \
				if [ -n "$$dirty" ]; then \
					state="dirty"; \
				else \
					pr_state=$$(printf '%s\n' "$$pr_table" | awk -F'\t' -v b="$$current" '$$1 == b {print $$2; exit}'); \
					if [ -z "$$pr_state" ] && [ "$$pr_lookup_failed" = "0" ]; then \
						pr_state=$$(gh pr view "$$current" --json state --jq .state 2>/dev/null || true); \
					fi; \
					if [ "$$pr_lookup_failed" = "1" ]; then \
						state="unknown"; \
					elif [ "$$pr_state" = "MERGED" ]; then \
						state="stale"; \
					else \
						state="claimed"; \
					fi; \
				fi; \
			fi; \
		fi; \
		printf '%-8s | %-58s | %-28s | %-8s | %-13s | %-7s | %s\n' "$$pool" "$$wt" "$$branch" "$$state" "$$age" "$$venv" "$$size"; \
		i=$$((i + 1)); \
	done; \
	if [ "$$pr_lookup_failed" = "1" ]; then \
		printf '\nNote: state=unknown — \`gh pr list\` returned no data.\n'; \
		printf '  Check \`gh auth status\` and \`gh api rate_limit\` to recover.\n'; \
	fi

## worktree-pool-check: assert pool invariants and exit non-zero on drift.
##
## Fails if:
##   - any slot directory is missing (count < POOL_SIZE)
##   - extra `pool-NN` directories exist beyond POOL_SIZE in WORKTREE_POOL_PARENT
##   - any slot is in `aborted` state (.benchbox/claim_in_progress survived)
##
## NOT a PR-CI gate. Intended use:
##   - pre-release sanity check (catch drift before cutting a release)
##   - periodic local cron / agent-loop hook
##
## Performance: avoids the gh PR lookup that worktree-pool-status uses, so
## it is fast and safe to run frequently. Runs read-only — never mutates.
##
## See `_project/blind-spots/2026-04-30-214358-pool-size-not-codified-as-contract.md`.
worktree-pool-check:
	@POOL_REPO=$$($(POOL_REPO_CMD)); \
	violations=""; \
	missing_count=0; \
	aborted_count=0; \
	i=1; \
	now_epoch=$$(date +%s); \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		if ! git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1; then \
			violations="$$violations  - $$pool: missing ($$wt is not a git worktree)\n"; \
			missing_count=$$((missing_count + 1)); \
		elif [ -f "$$wt/.benchbox/claim_in_progress" ]; then \
			marker_mtime_epoch=$$(stat -c %Y "$$wt/.benchbox/claim_in_progress" 2>/dev/null || stat -f %m "$$wt/.benchbox/claim_in_progress" 2>/dev/null || echo 0); \
			case "$$marker_mtime_epoch" in ''|*[!0-9]*) marker_mtime_epoch=0 ;; esac; \
			marker_age_seconds=$$((now_epoch - marker_mtime_epoch)); \
			marker_age=$$(date -u -r "$$wt/.benchbox/claim_in_progress" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "?"); \
			if [ "$$marker_age_seconds" -ge "$(POOL_CLAIM_MARKER_STALE_SECONDS)" ]; then \
				violations="$$violations  - $$pool: aborted (claim_in_progress marker present, mtime $$marker_age, age $${marker_age_seconds}s >= $(POOL_CLAIM_MARKER_STALE_SECONDS)s)\n"; \
				aborted_count=$$((aborted_count + 1)); \
			fi; \
		fi; \
		i=$$((i + 1)); \
	done; \
	extras=""; \
	for wt in "$(WORKTREE_POOL_PARENT)/$$POOL_REPO."pool-*; do \
		[ -d "$$wt" ] || continue; \
		base=$$(basename "$$wt"); \
		num=$${base##*pool-}; \
		case "$$num" in [0-9][0-9]) ;; *) continue ;; esac; \
		num_dec=$$(expr "$$num" + 0); \
		if [ "$$num_dec" -gt "$(POOL_SIZE)" ]; then \
			extras="$$extras  - $$base (number > POOL_SIZE=$(POOL_SIZE))\n"; \
		fi; \
	done; \
	if [ -n "$$extras" ]; then \
		violations="$$violations  Extra pool slots beyond POOL_SIZE:\n$$extras"; \
	fi; \
	if [ -n "$$violations" ]; then \
		printf 'Pool invariant check FAILED (POOL_SIZE=%s):\n' "$(POOL_SIZE)" >&2; \
		printf '%b' "$$violations" >&2; \
		printf 'Recover with `make worktree-pool-status` to inspect, then\n' >&2; \
		printf '`make worktree-pool-reset POOL=NN` (last resort) or\n' >&2; \
		printf '`make worktree-pool-init` to recreate missing slots.\n' >&2; \
		exit 1; \
	fi; \
	printf 'Pool invariant check OK: %d slot(s), no aborted markers.\n' "$(POOL_SIZE)"

## worktree-pool-reset POOL=NN [FORCE=1]: hard-reset a stuck pool slot to
## origin/develop. Without FORCE=1, refuses if the slot has uncommitted
## tracked changes. With FORCE=1, prompts for "RESET" then discards
## tracked changes AND scrubs untracked + ignored content (including
## `.venv/`, `benchmark_runs/`, build outputs) so the slot is reclaimed
## clean. The `.benchbox/` cache directory is preserved across reset.
## Use as an escape hatch when worktree-pool-sweep-stale won't release a
## slot (e.g., dirty working tree, no merged PR), or to reclaim disk
## from orphan benchmark output left by previous claims.
worktree-pool-reset:
	@test -n "$(POOL)" || { echo "Usage: make worktree-pool-reset POOL=NN"; exit 1; }
	@case "$(POOL)" in [0-9][0-9]) ;; *) echo "POOL must be two digits, e.g. POOL=03"; exit 1 ;; esac
	@LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-pool-reset-locked POOL="$(POOL)" FORCE="$(FORCE)" POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"

worktree-pool-reset-locked:
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.pool-$(POOL)"; \
	git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "No pool worktree found: $$wt"; exit 1; }; \
	branch=$$(git -C "$$wt" branch --show-current 2>/dev/null || true); \
	dirty=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
	if [ -n "$$dirty" ] && [ "$(FORCE)" != "1" ]; then \
		echo "Refusing to reset dirty pool worktree $$wt. Review changes or rerun with FORCE=1."; \
		echo "$$dirty"; \
		exit 1; \
	fi; \
	if [ "$(FORCE)" = "1" ]; then \
		echo "About to reset $$wt to origin/develop."; \
		if [ -n "$$branch" ]; then echo "Current branch: $$branch"; else echo "Current branch: (detached)"; fi; \
		if [ -n "$$dirty" ]; then echo "Uncommitted changes to discard:"; echo "$$dirty"; fi; \
		printf 'Type RESET to continue: '; \
		read answer; \
		[ "$$answer" = "RESET" ] || { echo "Aborted."; exit 1; }; \
	fi; \
	git -C "$$wt" fetch origin develop --quiet; \
	git -C "$$wt" checkout --detach origin/develop; \
	git -C "$$wt" reset --hard origin/develop; \
	if [ "$(FORCE)" = "1" ]; then git -C "$$wt" clean -fdx -e .benchbox >/dev/null; fi; \
	if [ "$(FORCE)" = "1" ] && [ -n "$$branch" ]; then \
		case "$$branch" in develop|main) ;; *) git branch -D "$$branch" >/dev/null 2>&1 || true ;; esac; \
	fi; \
	echo "Reset pool-$(POOL): $$wt"

## worktree-pool-sweep-stale: auto-release pool slots whose branch's PR
## is MERGED on origin and whose working tree is clean. Idempotent;
## refuses to touch slots that are dirty, claimed-no-PR, claimed-with-open-PR,
## or where the gh API lookup failed (state=unknown). Run after a busy day
## to recover slots that died between work and `make worktree-release`.
##
## Also drops `.venv/` from each released slot to free disk on inactive
## pool worktrees; the next `worktree-claim` re-syncs from `~/.cache/uv/`.
##
## Acquires the pool lock for the duration of the sweep so concurrent
## claims/releases cannot race with the per-slot reset operations.
worktree-pool-sweep-stale:
	@LOCK="$$(realpath "$$(git rev-parse --git-common-dir)")/pool.lock"; \
	scripts/_with_pool_lock.sh "$$LOCK" $(MAKE) -s worktree-pool-sweep-stale-locked POOL_SIZE="$(POOL_SIZE)" WORKTREE_POOL_PARENT="$(WORKTREE_POOL_PARENT)"

worktree-pool-sweep-stale-locked:
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	pr_table=$$(gh pr list --state all --base develop --limit 1000 \
		--json headRefName,state \
		--template '{{range .}}{{.headRefName}}{{"\t"}}{{.state}}{{"\n"}}{{end}}' 2>/dev/null); \
	if [ -z "$$pr_table" ]; then \
		echo "gh pr list returned no data; refusing to sweep without PR-state visibility" >&2; \
		exit 1; \
	fi; \
	swept=0; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		i=$$((i + 1)); \
		git -C "$$wt" rev-parse --is-inside-work-tree >/dev/null 2>&1 || continue; \
		current=$$(git -C "$$wt" symbolic-ref -q --short HEAD 2>/dev/null || true); \
		[ -n "$$current" ] || continue; \
		dirty=$$(git -C "$$wt" status --porcelain --untracked-files=normal | grep -vE '^\?\? \.benchbox(/|$$)' || true); \
		if [ -n "$$dirty" ]; then \
			echo "skip $$pool: dirty (branch=$$current)"; \
			continue; \
		fi; \
		pr_state=$$(printf '%s\n' "$$pr_table" | awk -F'\t' -v b="$$current" '$$1 == b {print $$2; exit}'); \
		if [ -z "$$pr_state" ]; then \
			pr_state=$$(gh pr view "$$current" --json state --jq .state 2>/dev/null || true); \
		fi; \
		if [ "$$pr_state" != "MERGED" ]; then \
			echo "skip $$pool: PR not merged (state=$${pr_state:-none})"; \
			continue; \
		fi; \
		echo "sweep $$pool: releasing $$current (PR MERGED)"; \
		git -C "$$wt" fetch origin develop --quiet; \
		git -C "$$wt" checkout --detach origin/develop >/dev/null; \
		git -C "$$wt" reset --hard origin/develop >/dev/null; \
		git -C "$$wt" branch -D "$$current" >/dev/null 2>&1 || true; \
		git -C "$$wt" remote prune origin >/dev/null 2>&1 || true; \
		rm -rf "$$wt/.venv"; \
		swept=$$((swept + 1)); \
	done; \
	echo "Swept $$swept pool slot(s)."

## worktree-pool-disk-clean: drop pytest, mypy, ruff, coverage caches
## from every pool slot without touching `.venv/` or git state. Useful
## when the pre-claim free-space check refuses or `worktree-pool-status`
## shows slots ballooning past their typical ~2 GB footprint.
##
## Lock-free by design: it only removes ignored cache directories, so
## it cannot corrupt git state or interfere with concurrent claim/release.
worktree-pool-disk-clean:
	@set -e; \
	POOL_REPO=$$($(POOL_REPO_CMD)); \
	freed_total=0; \
	cleaned=0; \
	i=1; \
	while [ "$$i" -le "$(POOL_SIZE)" ]; do \
		pool=$$(printf 'pool-%02d' "$$i"); \
		wt="$(WORKTREE_POOL_PARENT)/$$POOL_REPO.$$pool"; \
		i=$$((i + 1)); \
		[ -d "$$wt" ] || continue; \
		before=$$(du -sk "$$wt" 2>/dev/null | awk '{print $$1}'); \
		find "$$wt" -type d \( -name '__pycache__' -o -name '.pytest_cache' -o -name '.ruff_cache' -o -name '.mypy_cache' \) -prune -exec rm -rf {} + 2>/dev/null || true; \
		find "$$wt" -maxdepth 4 -type f \( -name '.coverage' -o -name '.coverage.*' \) -exec rm -f {} + 2>/dev/null || true; \
		[ -d "$$wt/.benchbox/cache" ] && rm -rf "$$wt/.benchbox/cache" || true; \
		after=$$(du -sk "$$wt" 2>/dev/null | awk '{print $$1}'); \
		delta=$$((before - after)); \
		if [ "$$delta" -gt 0 ]; then \
			echo "$$pool: freed $${delta}K (was $${before}K, now $${after}K)"; \
			freed_total=$$((freed_total + delta)); \
			cleaned=$$((cleaned + 1)); \
		fi; \
	done; \
	echo "Cleaned $$cleaned slot(s); freed $${freed_total}K total."

# Path convention: ../BenchBox.<branch-with-slashes-as-dashes>/
# After: cd into the path, work, run `make pr-open` from inside.
worktree-add:
	@test -n "$(BRANCH)" || { echo "Usage: make worktree-add BRANCH=<branch-name>"; exit 1; }
	@echo "DEPRECATED: use \`make worktree-claim BRANCH=...\` instead. The pool model retains worktrees rather than creating new ones. \`worktree-add\` will be removed in the next release." >&2
	@WTNAME=$$(echo "$(BRANCH)" | tr '/' '-'); \
	WTPATH="../BenchBox.$$WTNAME"; \
	test ! -e "$$WTPATH" || { echo "Path exists: $$WTPATH"; exit 1; }; \
	git fetch origin develop --quiet && \
	git worktree add -b "$(BRANCH)" "$$WTPATH" origin/develop && \
	echo "" && \
	echo "Worktree ready: $$WTPATH" && \
	echo "Branch:        $(BRANCH) (based on origin/develop)" && \
	echo "Next:          cd $$WTPATH && uv sync --group dev"

worktree-list:
	@git worktree list

# Regenerate _project/{TODO,DONE}/_indexes/*.yaml from per-item YAML files.
# Indexes are gitignored — run this whenever you want a fresh local copy.
# todo_cli.py auto-runs the same script on first read, so this is a
# convenience target for explicit regen (e.g. before grepping the indexes).
todo-reindex:
	@uv run _project/scripts/generate_indexes.py

# Remove worktrees whose branches are gone on origin (already merged).
# Legacy cleanup only. Pool worktrees are retained and released instead.
worktree-prune:
	@git fetch --prune --quiet
	@MAIN_CLONE=$$(dirname "$$(realpath "$$(git rev-parse --git-common-dir)")"); \
	git worktree list --porcelain | awk 'function emit(){if (wt != "") print wt "|" br} /^worktree /{emit(); wt=$$2; br=""} /^branch /{br=$$2} END{emit()}' | \
		while IFS='|' read -r wt br; do \
			[ "$$wt" = "$$MAIN_CLONE" ] && continue; \
			base=$$(basename "$$wt"); \
			case "$$base" in *.pool-[0-9][0-9]) pool=$${base##*.}; echo "Skipping pool worktree $$pool (retained)"; continue ;; esac; \
			[ -n "$$br" ] || continue; \
			short=$${br#refs/heads/}; \
			if ! git ls-remote --exit-code --heads origin "$$short" >/dev/null 2>&1; then \
				echo "Removing worktree (branch gone on origin): $$wt [$$short]"; \
				git worktree remove "$$wt" 2>/dev/null || git worktree remove --force "$$wt"; \
				git branch -D "$$short" 2>/dev/null || true; \
			fi; \
		done
	@git worktree prune

# Blind-spot finding triage (file-first capture; see _project/blind-spots/README.md).
blind-spots-list:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py list

blind-spots-report:
	@uv run --project _project/scripts -- python _project/scripts/sweep_blind_spots.py report

# Alias: 'sweep' as the verb users will reach for; report is the v1 sweep view.
blind-spots-sweep: blind-spots-report

# ----------------------------------------------------------------------
# UAT framework (tests/uat/) — see _project/specs/uat-framework.md.
# Operator-only; not exposed as `benchbox` CLI subcommands. UAT is a
# project-developer concern, benchbox is a project-user concern.
# ----------------------------------------------------------------------
.PHONY: uat-cell uat-execute uat-validate uat-package uat-explorer-smoke uat-report uat-sweep uat-stress uat-bring-up uat-docker-cleanup

# make uat-cell PLATFORM=duckdb BENCHMARK=tpch SCALE=0.01
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

# make uat-validate RESULTS_DIR=<dir> OUTPUT_TSV=<path> [FLOOR=0.80]
uat-validate:
	@if [ -z "$(RESULTS_DIR)" ] || [ -z "$(OUTPUT_TSV)" ]; then \
		echo "Usage: make uat-validate RESULTS_DIR=<dir> OUTPUT_TSV=<path> [FLOOR=0.80]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli validate \
		--results-dir "$(RESULTS_DIR)" \
		--output-tsv "$(OUTPUT_TSV)" \
		$(if $(FLOOR),--floor "$(FLOOR)",)

# make uat-report CELLS_JSONL=<path> OUTPUT_TSV=<path> [RUNGS=0.01,0.1,1.0] [CROSS_SCALE_FLOOR=N]
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

# make uat-explorer-smoke BUNDLES_DIR=<path> OUTPUT_DIR=<path> LOG_DIR=<path> [BROWSERS=chromium]
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

# make uat-package CONFIG=<path> SUBMISSIONS_DIR=<path> RESULTS="r1.json r2.json ..."
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

# make uat-bring-up PLATFORM=<name> [TIMEOUT_S=300] [DRY_RUN=1] [BENCHMARK_RUNS_DIR=~/Developer/benchmark_runs]
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

# make uat-docker-cleanup [APPLY=1] [PREFIX=benchbox-uat]
uat-docker-cleanup:
	@uv run --no-sync -- python -m tests.uat._cli docker-cleanup \
		$(if $(PREFIX),--prefix "$(PREFIX)",) \
		$(if $(APPLY),--apply,)

# make uat-sweep CONFIG=tests/uat/configs/<name>.yaml [DRY_RUN=1]
uat-sweep:
	@if [ -z "$(CONFIG)" ]; then \
		echo "Usage: make uat-sweep CONFIG=<path> [DRY_RUN=1]" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli sweep --config "$(CONFIG)" \
		$(if $(DRY_RUN),--dry-run,)

# make uat-stress [PLATFORM=] [BENCHMARK=] [SCALE=] [CONFIG=]
# Canned stress preset using the UAT framework matrix runner.
uat-stress:
	@uv run --no-sync -- python -m tests.uat._cli stress \
		$(if $(CONFIG),--config "$(CONFIG)",) \
		$(if $(PLATFORM),--platform "$(PLATFORM)",) \
		$(if $(BENCHMARK),--benchmark "$(BENCHMARK)",) \
		$(if $(SCALE),--scale "$(SCALE)",)

# make uat-execute CONFIG=tests/uat/configs/uat.yaml
uat-execute:
	@if [ -z "$(CONFIG)" ]; then \
		echo "Usage: make uat-execute CONFIG=<path>" >&2; \
		exit 2; \
	fi
	@uv run --no-sync -- python -m tests.uat._cli execute \
		--config "$(CONFIG)" \
		$(if $(DATABASES_ROOT),--databases-root "$(DATABASES_ROOT)",) \
		$(if $(NO_CLEANUP),--no-cleanup,)

# Help
help:
	@echo "BenchBox Makefile"
	@echo "----------------"
	@echo "Available commands:"
	@echo ""
	@echo "Core Testing:"
	@echo "  make test            Run default test suite (fast tests)"
	@echo "  make test-all        Run all tests"
	@echo "  make test-unit       Run unit tests only"
	@echo "  make test-integration Run integration tests only"
	@echo "  make test-tpch       Run TPC-H tests only"
	@echo "  make test-quick      Run quick tests without slow operations"
	@echo "  make test-verbose    Run tests with verbose output"
	@echo ""
	@echo "Speed-Based Testing:"
	@echo "  make test-pytest     Run all tests with pytest"
	@echo "  make test-fast       Run fast tests (< 1 sec)"
	@echo "  make test-medium     Run medium speed tests (1-10 sec)"
	@echo "  make test-slow       Run slow tests (> 10 sec)"
	@echo "  make test-dev        Fast development cycle testing"
	@echo "  make test-smoke      Quick smoke testing"
	@echo "  make test-local-matrix Run real local benchmark matrix (stress)"
	@echo "  make test-ci         Maintained broad local CI profile"
	@echo ""
	@echo "Database-Specific Testing:"
	@echo "  make test-duckdb     Run DuckDB-specific tests"
	@echo "  make test-sqlite     Run SQLite-specific tests"
	@echo ""
	@echo "Benchmark-Specific Testing:"
	@echo "  make test-read-primitives Run primitives benchmark tests"
	@echo "  make test-benchmarks Run all benchmark tests"
	@echo "  make test-tpcds      Run TPC-DS tests"
	@echo ""
	@echo "Feature-Specific Testing:"
	@echo "  make test-olap       Run OLAP functionality tests"
	@echo "  make test-window     Run window functions tests"
	@echo ""
	@echo "CI/CD Testing:"
	@echo "  make test-ci         Run maintained broad local CI profile"
	@echo ""
	@echo "CI Local Equivalents (run before push):"
	@echo "  make ci-local        Run ALL CI checks locally (lint+test+docs+package)"
	@echo "  make ci-lint         Lint + format check + type check (matches lint.yml)"
	@echo "  make ci-test         Fast tests with coverage (matches test.yml)"
	@echo "  make ci-docs         Build documentation (matches docs.yml)"
	@echo "  make test-integration-smoke  Integration smoke tests"
	@echo "  make test-package    Build and test package installation"
	@echo "  make security-audit  Run pip-audit security check"
	@echo "  make spellcheck      Run codespell on codebase"
	@echo "  make docstring-coverage  Check docstring coverage with interrogate"
	@echo "  make complexity-check    Check cyclomatic complexity (fails on violations)"
	@echo "  make complexity-report   Report cyclomatic complexity (no failure)"
	@echo ""
	@echo "Parallel Testing:"
	@echo "  make test-parallel   Run tests in parallel"
	@echo "  make test-parallel-fast Run fast tests in parallel"
	@echo ""
	@echo "Live Integration Testing (requires cloud credentials):"
	@echo "  make test-live       Run all live integration tests"
	@echo "  make test-live-databricks Run Databricks live tests"
	@echo "  make test-live-snowflake  Run Snowflake live tests"
	@echo "  make test-live-bigquery   Run BigQuery live tests"
	@echo "  make test-live-all   Run all live tests (all platforms)"
	@echo ""
	@echo "Utility:"
	@echo "  make run-test TEST=path Run a specific test file"
	@echo ""
	@echo "UAT Operations:"
	@echo "  make uat-docker-cleanup        Report abandoned UAT Docker resources and non-UAT cleanup commands"
	@echo "  make uat-docker-cleanup APPLY=1 Remove only UAT-owned Docker leftovers"
	@echo ""
	@echo "Coverage:"
	@echo "  make coverage-fast   Run fast-marked tests with coverage (quick feedback)"
	@echo "  make coverage-all    Run full test suite with coverage report"
	@echo "  make coverage-html   Generate HTML coverage report"
	@echo "  make coverage-report Generate comprehensive coverage reports"
	@echo ""
	@echo "Development:"
	@echo "  make lint            Check code style"
	@echo "  make lint-markers    Validate test marker annotations (catches speed-lane conflicts)"
	@echo "  make typecheck       Run type checking with ty"
	@echo "  make typecheck-uv    Run type checking with uv (development)"
	@echo "  make validate-imports Validate import structure and detect circular dependencies"
	@echo "  make dependency-check Validate lock file against pyproject specs (ARGS='--matrix' to show summary)"
	@echo "  make duplicate-check Detect duplicate code via AST structural hashing"
	@echo "  make mutation-test   Run mutation testing on critical modules (mutmut)"
	@echo "  make format          Format code with ruff"
	@echo "  make clean           Remove build artifacts"
	@echo "  make install         Install the package"
	@echo "  make develop         Install the package in development mode"
	@echo "  make dist            Create distribution packages"
	@echo "  make compile-tpcds-binaries  Rebuild TPC-DS/TPC-H binaries from patched sources (no Docker)"
	@echo ""
	@echo "Documentation:"
	@echo "  make docs-build      Build Sphinx documentation locally"
	@echo "  make docs-serve      Build and serve docs at http://localhost:8000"
	@echo "  make docs-clean      Clean documentation build artifacts"
	@echo "  make docs-linkcheck  Check for broken links in documentation"
	@echo "  make docs-validate   Validate example references, syntax, and screenshot sync"
	@echo "  make docs-images     Refresh generated visualization screenshots and sync docs/blog copies"
	@echo "  make docs-check      Run all documentation checks (validate, linkcheck, build)"
	@echo ""
	@echo "PR Workflow & Worktrees:"
	@echo "  make pr-preflight    Run lint + fast marker tests locally (coverage remains CI-only)"
	@echo "  make pr-open [PR_BODY_FILE=path] Push branch + open PR vs develop + enable auto-merge"
	@echo "  make pr-fanout       Run pr-open across worktrees with bounded parallelism (PR_FANOUT_JOBS=$(PR_FANOUT_JOBS))"
	@echo "  make shrink-rollup   Sum merged shrink ledger fragments from origin/develop"
	@echo "  make pr-refresh      Merge origin/develop into current branch, push, and re-enable auto-merge"
	@echo "  make pr-status       List your open PRs vs develop with CI + auto-merge state"
	@echo "  make pr-review-followups-list        List un-actioned bot/agent review comments on merged PRs"
	@echo "  make pr-review-followups             Action each comment, reply with marker, submit PR"
	@echo "  make dev-loop-metrics  Summarize recent develop post-merge metrics (DEV_LOOP_METRICS_DAYS=$(DEV_LOOP_METRICS_DAYS))"
	@echo "Worktree-pool lifecycle (preferred for new write sessions):"
	@echo "  make worktree-pool-init           Bootstrap retained pool worktrees (POOL_SIZE=$(POOL_SIZE))"
	@echo "  make worktree-claim BRANCH=name   Claim a free pool slot for a feature branch"
	@echo "  make worktree-release             Inside a pool worktree: return to detached origin/develop after PR merges"
	@echo "  make worktree-pool-status         Show pool slot state, venv health, and disk usage"
	@echo "  make worktree-pool-check          Assert pool invariants (count, aborted slots) — exit non-zero on drift"
	@echo "  make worktree-pool-sweep-stale    Auto-release pool slots whose PRs have merged"
	@echo "  make worktree-pool-disk-clean     Drop pytest/mypy/ruff/coverage caches from pool slots (preserves .venv)"
	@echo "  make worktree-pool-reset POOL=NN  Manual escape hatch for stuck pool slots"
	@echo ""
	@echo "Legacy / non-pool worktree paths (deprecated, kept for one release):"
	@echo "  make worktree-add BRANCH=name  Deprecated legacy worktree creator (prefer worktree-claim)"
	@echo "  make worktree-list             List active worktrees"
	@echo "  make worktree-prune            Remove legacy non-pool worktrees whose branches are gone on origin"
	@echo ""
	@echo "Blind-Spot Findings (see _project/blind-spots/README.md):"
	@echo "  make blind-spots-list   List open findings (one row each)"
	@echo "  make blind-spots-report Counts by status + kind, oldest active first"
	@echo "  make blind-spots-sweep  Alias for blind-spots-report"
	@echo ""
	@echo "Release Workflow (2-command flow; see docs/operations/release-guide.md):"
	@echo "  make release-cut VERSION=X.Y.Z      Cut v\$$VERSION off develop, bump + changelog + curate, push, open PR vs main"
	@echo "  make release-finalize VERSION=X.Y.Z Verify validate-base and release-required-result, squash-merge the release PR, tag main, push tag"
	@echo ""
	@echo "  make help            Show this help message"
