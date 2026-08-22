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

# Container engine for local test-docker-* compose stacks: `docker` (default,
# and the ONLY engine CI uses) or `mocker` (Docker-compatible CLI over Apple
# `container`; Apple-silicon/macOS-26 LOCAL DEV ONLY, MUST NOT run in CI). The
# docker/*/docker-compose.yml files stay unmodified; only the driver swaps.
# See docs/operations/uat-framework.md "Mocker validation status".
CONTAINER_ENGINE ?= docker
COMPOSE := $(CONTAINER_ENGINE) compose

# Some docker/*/docker-compose.yml files (lakesail, velox) mount
# BENCHBOX_DATA_DIR with NO inline default -- see docker/lakesail/docker-compose.yml
# and docker/velox/docker-compose.yml for why (mocker 0.7.2 misparses a
# nested default, and silently leaves a required-variable default
# (${VAR:?...}) unsubstituted even when the variable IS set). Two earlier
# designs were tried here and reverted: a file-wide `BENCHBOX_DATA_DIR ?=
# ...; export BENCHBOX_DATA_DIR` leaked an unrelated default into every one
# of this Makefile's ~192 targets, not just the two that need it (and
# BENCHBOX_DATA_DIR is a documented user-facing variable -- see
# docs/reference/cli/configuration.md); and a per-stack docker/<platform>/.env
# fallback could only supply a directory-relative default, which breaks the
# host/container path-mirroring contract these two compose files rely on (a
# relative value can never equal an absolute host path). There is
# deliberately NO default here: callers must export an absolute
# BENCHBOX_DATA_DIR themselves. require_data_dir_if_mounted below enforces
# that -- non-empty and absolute -- scoped to just the lakesail/velox
# bring-up targets, before compose is invoked.
# $(1)=platform being brought up.
define require_data_dir_if_mounted
case " lakesail velox " in *" $(1) "*) case "$$BENCHBOX_DATA_DIR" in "") echo "ERROR: BENCHBOX_DATA_DIR must be exported before bringing up docker/$(1) -- its compose file binds the data directory at the SAME absolute path inside the container as on the host, because the server resolves client-sent file paths server-side; an unset value is silently accepted as an empty mount by both docker compose and mocker. Example: export BENCHBOX_DATA_DIR=$$HOME/benchbox-data" >&2; exit 1 ;; /*) : ;; *) echo "ERROR: BENCHBOX_DATA_DIR must be an ABSOLUTE path (got '$$BENCHBOX_DATA_DIR') -- docker/$(1)'s compose file binds it at the SAME path inside the container as on the host, so a relative value can never match. Example: export BENCHBOX_DATA_DIR=$$HOME/benchbox-data" >&2; exit 1 ;; esac ;; esac
endef

# `compose down -v` extended to also remove leaked named volumes on a SUCCESSFUL
# down. mocker 0.5.4's `compose down -v` removes containers but LEAKS named
# volumes (a stale-data risk across runs); this removes the project's volumes
# afterward. A no-op beyond `down -v` on docker (which already removes them).
# EXACT-NAME matching: volume keys are read from the compose file's top-level
# `volumes:` block and joined as <project>-<key> (mocker's live-verified
# joiner) and <project>_<key> (docker compose's, future-proofing). A
# name-prefix grep here would also match a sibling project whose name extends
# this one (`p` vs `p-ha`) and delete its data -- same fix as
# tests/uat/docker_assets.py sweep_leaked_mocker_volumes.
#
# BENCHBOX_DATA_DIR is deliberately NOT validated here the way
# require_data_dir_if_mounted validates it for `up`: `down` is called from
# every one of this file's teardown paths (test-docker-down-%,
# test-docker-down-all, and the failure-cleanup traps in test-docker-up-%,
# test-docker-%, test-docker-firebolt, test-docker-up-all -- some of which
# fire even when `up` never ran, e.g. require_data_dir_if_mounted itself
# rejecting the value), so a hard failure here would risk exactly the
# teardown leak this macro exists to close. `down` never re-mounts anything
# (it only needs the compose file to interpolate/parse), so an unset or
# relative BENCHBOX_DATA_DIR is replaced with a throwaway absolute
# placeholder instead of erroring -- a no-op for every platform other than
# lakesail/velox, whose compose files are the only ones that reference it.
# $(1)=project $(2)=compose file.
define compose_down_fresh
case "$$BENCHBOX_DATA_DIR" in /*) ;; *) BENCHBOX_DATA_DIR="/tmp/benchbox-teardown-placeholder"; export BENCHBOX_DATA_DIR ;; esac; $(COMPOSE) -p "$(1)" -f "$(2)" down -v; if [ "$(CONTAINER_ENGINE)" = "mocker" ]; then awk '/^volumes:/{f=1;next} f&&/^[^ ]/{f=0} f&&/^  [A-Za-z0-9._-]+:/{k=$$1;sub(/:.*/,"",k);print k}' "$(2)" 2>/dev/null | while read -r _k; do mocker volume rm "$(1)-$$_k" >/dev/null 2>&1 || true; mocker volume rm "$(1)"_"$$_k" >/dev/null 2>&1 || true; done; fi
endef

test-docker-up-%:
	@set -e; \
		$(call require_data_dir_if_mounted,$*); \
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
				{ $(call compose_down_fresh,$$project_name,docker/$*/docker-compose.yml) ; } >/dev/null 2>&1 || true; \
				rm -f "$$project_file"; \
			fi; \
		}; \
		trap cleanup EXIT INT TERM; \
		$(COMPOSE) -p "$$project_name" -f docker/$*/docker-compose.yml up -d --wait; \
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
		$(call compose_down_fresh,$$project_name,docker/$*/docker-compose.yml); \
		rm -f "$$project_file"

# Explicit override: generic test-docker-% expands to -m "live_firebolt" (cloud tests).
# Firebolt Core Docker tests use the separate live_firebolt_core marker.
test-docker-firebolt:
	@echo "Running Firebolt Core Docker integration tests"
	@set -e; \
		project_name="benchbox-firebolt-test-$$(date +%s)-$$RANDOM"; \
		cleanup() { { $(call compose_down_fresh,$$project_name,docker/firebolt/docker-compose.yml) ; } || true; }; \
		trap cleanup EXIT INT TERM; \
		$(COMPOSE) -p "$$project_name" -f docker/firebolt/docker-compose.yml up -d --wait; \
		uv run -- python -m pytest -m "live_firebolt_core" --tb=short -v -n 0

test-docker-%:
	@echo "Running $* Docker integration tests"
	@set -e; \
		project_name="benchbox-$*-test-$$(date +%s)-$$RANDOM"; \
		cleanup() { { $(call compose_down_fresh,$$project_name,docker/$*/docker-compose.yml) ; } || true; }; \
		trap cleanup EXIT INT TERM; \
		$(call require_data_dir_if_mounted,$*); \
		$(COMPOSE) -p "$$project_name" -f docker/$*/docker-compose.yml up -d --wait; \
		uv run -- python -m pytest -m "live_$*" --tb=short -v -n 0

# No require_data_dir_if_mounted call in the loop below: DOCKER_PLATFORMS
# (above) never includes lakesail or velox, so the call would be
# permanently dead here -- coverage that reads as real but never fires.
# `make test-docker-up-lakesail` / `test-docker-up-velox` (test-docker-up-%)
# is the supported bring-up path for those two and IS guarded.
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
						{ $(call compose_down_fresh,$$project_name,docker/$$p/docker-compose.yml) ; } >/dev/null 2>&1 || true; \
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
			$(COMPOSE) -p "$$project_name" -f docker/$$p/docker-compose.yml up -d --wait; \
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
			$(call compose_down_fresh,$$project_name,docker/$$p/docker-compose.yml); \
			rm -f "$$project_file"; \
		done

test-docker-all:
	@echo "Running all Docker integration tests (requires Docker)"
	@for p in $(DOCKER_PLATFORMS); do \
		echo "=== Testing $$p ==="; \
		$(MAKE) test-docker-$$p || exit 1; \
	done

# Compose-lifecycle parity acceptance test: asserts up --wait health-gating,
# published-port reachability, and the down -v fresh-state guarantee (no leaked
# container/volume) for the selected engine. Same asserts on docker and mocker so
# parity is measured. Usage:
#   make test-docker-parity                             # docker (default)
#   make test-docker-parity CONTAINER_ENGINE=mocker     # Apple container backend
#   make test-docker-parity PARITY_PLATFORMS="questdb postgresql doris"
PARITY_PLATFORMS ?= questdb postgresql
.PHONY: test-docker-parity
test-docker-parity:
	@bash _project/scripts/mocker_compose_parity.sh $(CONTAINER_ENGINE) $(PARITY_PLATFORMS)
