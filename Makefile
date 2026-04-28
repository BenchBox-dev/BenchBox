# BenchBox Makefile
# This makefile provides commands for building, testing and development

.PHONY: test test-unit test-integration test-tpch test-all test-fast test-unlock test-medium test-slow test-stress test-pytest clean lint lint-markers install develop coverage coverage-fast coverage-all coverage-html coverage-report coverage-check test-duckdb test-sqlite test-read-primitives test-benchmarks test-ci typecheck validate-imports format dependency-check docs-build docs-serve docs-clean docs-linkcheck docs-validate docs-check docs-images test-pyspark ci-lint ci-test ci-docs ci-local security-audit spellcheck docstring-coverage test-package test-integration-smoke test-local-matrix complexity-check complexity-report duplicate-check duplicate-check-verbose duplicate-check-json codex-skills-sync codex-skills-check mutation-test compile-tpcds-binaries parity-fixtures parity-check compat-docs compat-docs-check pr-preflight pr-open pr-status worktree-add worktree-list worktree-prune

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
	@echo "Removing stale BenchBox test lock..."
	@rm -f ~/.benchbox/test.lock
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

# Linting (ruff only)
lint:
	uv run ruff check .

# Dependency audit - checks that every declared dep has an import site or is allowlisted.
# Fails if an unused dep is introduced. See _project/scripts/dependency_audit/.
audit-deps:
	uv run -- python _project/scripts/dependency_audit/check_deps.py

# Validate test marker annotations - fails on speed-lane conflicts or fast-incompatible pairs.
# Uses --collect-only so no tests run; the conflict-detection hook fires at collection time.
lint-markers:
	uv run -- python -m pytest --collect-only -q -p no:warnings

# Sync/check repo-local shared skill mirrors for Codex portability
codex-skills-sync:
	uv run -- python _project/scripts/sync_codex_shared_skills.py sync

codex-skills-check:
	uv run -- python _project/scripts/sync_codex_shared_skills.py check

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
	uv run -- python _project/scripts/sync_codex_shared_skills.py check
	uv run -- python _project/scripts/timing_policy_check.py --strict
	$(MAKE) compat-docs-check
	$(MAKE) audit-deps
	@echo "✅ CI lint checks passed"

# CI test check - exact match for test.yml workflow (fast tests with coverage)
# Note: -p pytest_cov re-enables pytest-cov which is disabled by default in pytest.ini
# Suite-wide coverage threshold set to 70%
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
	uv build
	uvx twine check dist/*
	@echo "Testing package installation..."
	@rm -rf test-venv
	uv venv test-venv
	. test-venv/bin/activate && uv pip install dist/*.whl && python -c "import benchbox; print('Package installation successful')" && benchbox --help > /dev/null
	@rm -rf test-venv
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
	ty check

# Type checking with uv (for development)
typecheck-uv:
	uv run ty check

# Import validation
validate-imports:
	uv run -- python scripts/validate_imports.py

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
	uv run scripts/generate_compat_docs.py

# Verify the committed compat docs match the registry. CI gate against drift.
compat-docs-check:
	uv run scripts/generate_compat_docs.py --check

# Verify fixtures match the current Python implementation without overwriting.
# Fails if any fixture is out of date (drift detected).
# comparison_artifact.json is excluded from the diff - it requires real result bundles to generate
# and is verified by the comparisonArtifact.parity.test.tsx suite instead.
parity-check:
	@tmpdir=$$(mktemp -d) && \
	uv run python tests/parity/generate_visualization_fixtures.py --out $$tmpdir && \
	diff -r --exclude='.gitkeep' --exclude='comparison_artifact.json' tests/parity/fixtures $$tmpdir && \
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
#   develop is intentionally NOT modified post-release. dev-only paths
#   (_project/, _blog/, AGENTS.md, etc.) live on develop and are removed
#   from the release branch by release-cut's curation step.
#
# See docs/operations/release-guide.md and _project/decisions/single-repo-migration.md.

.PHONY: release-cut release-finalize

# Cut a release branch from develop in one shot:
#   1. Create v$(VERSION) branch off develop (develop is not modified).
#   2. On v$(VERSION): bump version sources (scripts/update_version.py).
#   3. On v$(VERSION): generate CHANGELOG.md entry.
#   4. $EDITOR opens CHANGELOG.md for hand-curation (skipped if EDITOR unset).
#   5. Curate: git rm dev-only paths (per A3 in single-repo-migration.md).
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
	uv run python scripts/update_version.py --version $(VERSION) --update-pyproject
	uv run python scripts/generate_changelog_entry.py --version $(VERSION)
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
	-git rm -rf _project _blog .claude .codex .gemini
	-git rm -f .pre-commit-config.yaml _benchbox_pytest_xdist_safety.py todo.config.yaml skill-sync.yaml skill-sync.lock .coveragerc_core .dockerignore .env.example .mcp.json AGENTS.md CLAUDE.md GEMINI.md
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
	@echo "  2. Wait for CI green."
	@echo "  3. make release-finalize VERSION=$(VERSION)"

# After release-cut's PR is approved and CI is green: squash-merge it,
# tag main, push the tag (fires release.yml), and leave develop alone.
# Usage: make release-finalize VERSION=X.Y.Z
release-finalize:
	@test -n "$(VERSION)" || (echo "Usage: make release-finalize VERSION=X.Y.Z" && exit 1)
	@PR=$$(gh pr list --base main --head v$(VERSION) --state open --json number --jq '.[0].number'); \
	test -n "$$PR" || (echo "Error: no open PR found for v$(VERSION) → main" && exit 1); \
	echo "==> Squash-merging PR #$$PR (ruleset main-release-only blocks merge if CI is not green)"; \
	gh pr merge --squash "$$PR"
	git fetch origin --tags
	git checkout main
	git pull --ff-only origin main
	git tag v$(VERSION)
	git push origin v$(VERSION)
	@echo
	@echo "Tag v$(VERSION) pushed; release.yml will publish to PyPI."
	@echo "develop is intentionally unchanged — dev-only paths persist on develop."

# =============================================================================
# PR + worktree workflow
# Solo-dev develop is PR-gated (CI must be green; linear history; squash).
# These targets collapse the PR roundtrip to one command and let multiple
# branches stay live in parallel via worktrees.
# =============================================================================

.PHONY: pr-preflight pr-open pr-status worktree-add worktree-list worktree-prune

# Mirror the CI gate locally before pushing. Catches ~all CI failures
# without the network roundtrip. Delegates to ci-lint so the local
# preflight surface stays in sync with lint.yml automatically.
pr-preflight:
	@$(MAKE) ci-lint
	@echo "==> fast tests"
	@uv run -- python -m pytest -m fast -q

# Push current branch and open a PR against develop with auto-merge enabled.
# Squash-merge happens automatically once `lint` + `test (ubuntu-latest, 3.12)`
# go green. Refuses to run from develop/main.
pr-open:
	@CURRENT=$$(git branch --show-current); \
	case "$$CURRENT" in \
		develop|main) echo "Refusing to open PR from $$CURRENT — switch to a feature branch."; exit 1 ;; \
	esac; \
	git push -u origin "$$CURRENT" && \
	URL=$$(gh pr create --base develop --fill --head "$$CURRENT") && \
	echo "$$URL" && \
	gh pr merge --auto --squash "$$URL"

# Show open PRs against develop and their CI + auto-merge state.
pr-status:
	@gh pr list --base develop --state open --limit 20 --json number,title,headRefName,statusCheckRollup,autoMergeRequest \
		--template '{{range .}}#{{.number}} {{.title}} ({{.headRefName}}){{"\n"}}  auto-merge: {{if .autoMergeRequest}}ON{{else}}OFF{{end}}{{"\n"}}  checks: {{range .statusCheckRollup}}{{.name}}={{.conclusion}} {{end}}{{"\n\n"}}{{end}}'

# Create a worktree off origin/develop. Usage: make worktree-add BRANCH=fix/foo
# Path convention: ../BenchBox.<branch-with-slashes-as-dashes>/
# After: cd into the path, work, run `make pr-open` from inside.
worktree-add:
	@test -n "$(BRANCH)" || { echo "Usage: make worktree-add BRANCH=<branch-name>"; exit 1; }
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

# Remove worktrees whose branches are gone on origin (already merged).
# Pairs with auto-merge: PR merges → branch deleted → worktree pruned.
worktree-prune:
	@git fetch --prune --quiet
	@git worktree list --porcelain | awk '/^worktree /{wt=$$2} /^branch /{br=$$2; print wt"|"br}' | \
		while IFS='|' read -r wt br; do \
			[ "$$wt" = "$$(git rev-parse --show-toplevel)" ] && continue; \
			short=$${br#refs/heads/}; \
			if ! git ls-remote --exit-code --heads origin "$$short" >/dev/null 2>&1; then \
				echo "Removing worktree (branch gone on origin): $$wt [$$short]"; \
				git worktree remove "$$wt" 2>/dev/null || git worktree remove --force "$$wt"; \
				git branch -D "$$short" 2>/dev/null || true; \
			fi; \
		done
	@git worktree prune

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
	@echo "  make test-ci         CI-optimized test suite"
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
	@echo "  make test-ci         Run CI-optimized test suite"
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
	@echo "  make pr-preflight    Run lint + fast tests locally; mirrors CI gate"
	@echo "  make pr-open         Push branch + open PR vs develop + enable auto-merge (squash)"
	@echo "  make pr-status       List your open PRs vs develop with CI + auto-merge state"
	@echo "  make worktree-add BRANCH=name  Create a worktree off origin/develop at ../BenchBox.<name>"
	@echo "  make worktree-list   List active worktrees"
	@echo "  make worktree-prune  Remove worktrees whose branches are gone on origin (post-merge cleanup)"
	@echo ""
	@echo "Release Workflow (2-command flow; see docs/operations/release-guide.md):"
	@echo "  make release-cut VERSION=X.Y.Z      Cut v\$$VERSION off develop, bump + changelog + curate, push, open PR vs main"
	@echo "  make release-finalize VERSION=X.Y.Z Squash-merge the release PR, tag main, push tag (fires release.yml)"
	@echo ""
	@echo "  make help            Show this help message"
