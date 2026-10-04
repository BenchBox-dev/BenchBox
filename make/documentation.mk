##@ Documentation

# Build Sphinx documentation locally
.PHONY: docs-build
docs-build: docs-generate
	@echo "Building documentation..."
	@cd docs && uv run sphinx-build -b html --keep-going . _build/html
	@echo "✅ Docs built: docs/_build/html/index.html"

# Build and serve documentation on http://localhost:8000
.PHONY: docs-serve
docs-serve: docs-build
	@echo "Serving docs at http://localhost:8000"
	@echo "Press Ctrl+C to stop"
	@cd docs/_build/html && uv run -- python -m http.server 8000

# Clean documentation build artifacts
.PHONY: docs-clean
docs-clean:
	@echo "Cleaning documentation build artifacts..."
	@rm -rf docs/_build
	@echo "✅ Documentation artifacts cleaned"

# Check for broken links in documentation
.PHONY: docs-linkcheck
docs-linkcheck: docs-generate
	@echo "Checking documentation for broken links..."
	@cd docs && uv run sphinx-build -b linkcheck . _build/linkcheck
	@echo ""
	@echo "Link check results:"
	@cat docs/_build/linkcheck/output.txt || echo "No broken links found!"

# Validate example file references
.PHONY: docs-validate
docs-validate:
	@echo "Validating example file references..."
	@uv run -- python scripts/validate_example_references.py
	@echo ""
	@echo "Checking example file syntax..."
	@uv run -- python scripts/check_example_syntax.py
	@echo ""
	@echo "Validating visualization screenshot sync..."
	@$(MAKE) docs-images-check
	@echo ""
	@echo "Generating per-query template pages (link targets, not committed)..."
	@uv run -- python scripts/generate_query_docs.py
	@echo ""
	@echo "Checking repo-local doc relative links..."
	@uv run -- python scripts/check_doc_relative_links.py

# Refresh generated visualization screenshots and sync shared docs/blog copies
.PHONY: docs-images
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

.PHONY: query-docs
query-docs:
	uv run -- python scripts/generate_query_docs.py

.PHONY: docs-images-check
docs-images-check:
	@uv run -- python scripts/validate_visualization_images.py

.PHONY: docs-generate
docs-generate: query-docs prompt-quickstarts-check compat-docs-check docs-images-check

SITE_DIR ?= site
SITE_INVENTORY ?= $(SITE_DIR)-inventory
.PHONY: site-inventory
site-inventory:
	@uv run -- python scripts/site_inventory.py build --site-dir "$(SITE_DIR)" --output-dir "$(SITE_INVENTORY)" --source-sha "$$(git rev-parse HEAD)"

SITE_INVENTORY_BASELINE ?= _project/design/site-inventory/baseline-develop
.PHONY: site-inventory-diff
site-inventory-diff: site-inventory
	@uv run -- python scripts/site_inventory.py diff --baseline "$(SITE_INVENTORY_BASELINE)" --candidate "$(SITE_INVENTORY)"

SITE_INVENTORY_KNOWN_BROKEN ?= _project/design/site-inventory/known-broken-links.json
.PHONY: site-inventory-check
site-inventory-check: site-inventory
	@uv run -- python scripts/site_inventory.py check --inventory "$(SITE_INVENTORY)" --known-broken "$(SITE_INVENTORY_KNOWN_BROKEN)"

.PHONY: site-deps
site-deps:
	@if [ ! -f website/node_modules/.package-lock.json ] || [ website/package-lock.json -nt website/node_modules/.package-lock.json ]; then npm --prefix website ci; fi

.PHONY: site-build
site-build: docs-generate site-deps
	@npm --prefix website run build
	@test -s website/dist/index.html
	@echo "Site built: website/dist/index.html"

.PHONY: site-dev
site-dev: site-deps
	@npm --prefix website run dev

.PHONY: site-check
site-check: docs-generate site-deps
	@npm --prefix website run check
	@BENCHBOX_SITE_UNBUILT=1 npm --prefix website test
	@npm --prefix website run audit:high

.PHONY: site-test-built
site-test-built:
	@npm --prefix website test
	@npm --prefix website run verify:not-found
	@npm --prefix website run verify:landing

SITE_VISUAL_DIR ?= site-visual-astro

.PHONY: site-visual-capture
site-visual-capture:
	@test -s website/dist/results/index.html
	@rm -rf "$(SITE_VISUAL_DIR)"
	@E2E_PAGES_SHAPED=1 E2E_SITE_DIR="$(CURDIR)/website/dist" PUBLIC_SITE_VISUAL_RENDERER=astro PUBLIC_SITE_VISUAL_PHASE=capture PUBLIC_SITE_VISUAL_OUTPUT="$(abspath $(SITE_VISUAL_DIR))" PUBLIC_SITE_VISUAL_SOURCE_SHA="$(SITE_PARITY_SHA)" npm --prefix results-explorer run test:e2e:public-site

SITE_PARITY_DIR ?= site-parity
SITE_PARITY_SHA ?= $(shell git rev-parse HEAD)
SITE_PARITY_DESIGN ?= _project/design/site-inventory
SITE_PARITY_REMOVALS = $(foreach file,$(sort $(wildcard $(SITE_PARITY_DESIGN)/expected-removals-*.json)),--expected-removals $(file))

.PHONY: site-parity-sphinx
site-parity-sphinx: docs-build
	@rm -rf "$(SITE_PARITY_DIR)/sphinx"
	@uv run -- python scripts/assemble_public_site.py --site-dir "$(SITE_PARITY_DIR)/sphinx"

.PHONY: site-parity-inventory
site-parity-inventory:
	@rm -rf "$(SITE_PARITY_DIR)/inventory-sphinx" "$(SITE_PARITY_DIR)/inventory-astro"
	@uv run -- python scripts/site_inventory.py build --site-dir "$(SITE_PARITY_DIR)/sphinx" --output-dir "$(SITE_PARITY_DIR)/inventory-sphinx" --source-sha "$(SITE_PARITY_SHA)"
	@uv run -- python scripts/site_inventory.py build --site-dir website/dist --output-dir "$(SITE_PARITY_DIR)/inventory-astro" --source-sha "$(SITE_PARITY_SHA)"

.PHONY: site-parity-browser
site-parity-browser:
	@mkdir -p "$(SITE_PARITY_DIR)"
	@rm -f "$(SITE_PARITY_DIR)/browser-report.json" "$(SITE_PARITY_DIR)/explorer-result.json" "$(SITE_PARITY_DIR)/parity-result.json"
	@status=0; \
	npm --prefix website run verify:explorer; code=$$?; \
	printf '{"check": "explorer e2e", "exit": %s}\n' "$$code" > "$(SITE_PARITY_DIR)/explorer-result.json"; \
	[ "$$code" -eq 0 ] || status=1; \
	PARITY_E2E_REPORT="$(CURDIR)/$(SITE_PARITY_DIR)/browser-report.json" npm --prefix website run verify:parity; code=$$?; \
	printf '{"check": "template axe and search", "exit": %s}\n' "$$code" > "$(SITE_PARITY_DIR)/parity-result.json"; \
	[ "$$code" -eq 0 ] || status=1; \
	exit $$status

.PHONY: site-parity-privacy
site-parity-privacy:
	@mkdir -p "$(SITE_PARITY_DIR)"
	@rm -f "$(SITE_PARITY_DIR)/privacy-result.json"
	@uv run -- python scripts/publication/check_artifact_privacy.py website/dist; code=$$?; \
	printf '{"check": "privacy scan", "exit": %s}\n' "$$code" > "$(SITE_PARITY_DIR)/privacy-result.json"; \
	exit $$code

.PHONY: site-parity-diff
site-parity-diff: site-parity-inventory
	@rm -f "$(SITE_PARITY_DIR)/published-diff.txt"
	@status=0; \
	uv run -- python scripts/site_inventory.py diff --baseline "$(SITE_PARITY_DIR)/inventory-sphinx" --candidate "$(SITE_PARITY_DIR)/inventory-astro" $(SITE_PARITY_REMOVALS) --allowed-differences "$(SITE_PARITY_DESIGN)/allowed-differences.json" || status=1; \
	uv run -- python scripts/site_inventory.py check --inventory "$(SITE_PARITY_DIR)/inventory-astro" --known-broken "$(SITE_INVENTORY_KNOWN_BROKEN)" || status=1; \
	echo "site_inventory diff against the published baseline (informational)"; \
	uv run -- python scripts/site_inventory.py diff --baseline "$(SITE_INVENTORY_BASELINE)" --candidate "$(SITE_PARITY_DIR)/inventory-astro" $(SITE_PARITY_REMOVALS) --allowed-differences "$(SITE_PARITY_DESIGN)/allowed-differences.json" > "$(SITE_PARITY_DIR)/published-diff.txt" || true; \
	tail -n 1 "$(SITE_PARITY_DIR)/published-diff.txt"; \
	exit $$status

.PHONY: site-parity-report
site-parity-report: site-parity-inventory
	@rm -rf "$(SITE_PARITY_DIR)/report"
	@status=0; \
	uv run -- python scripts/site_parity.py --baseline "$(SITE_PARITY_DIR)/inventory-sphinx" --published-baseline "$(SITE_INVENTORY_BASELINE)" --candidate "$(SITE_PARITY_DIR)/inventory-astro" --baseline-site "$(SITE_PARITY_DIR)/sphinx" --candidate-site website/dist --output-dir "$(SITE_PARITY_DIR)/report" --e2e-report "$(SITE_PARITY_DIR)/browser-report.json" --step-result "$(SITE_PARITY_DIR)/explorer-result.json" --step-result "$(SITE_PARITY_DIR)/parity-result.json" --step-result "$(SITE_PARITY_DIR)/privacy-result.json" || status=$$?; \
	if [ -n "$$GITHUB_STEP_SUMMARY" ] && [ -f "$(SITE_PARITY_DIR)/report/url-compatibility-report.md" ]; then cat "$(SITE_PARITY_DIR)/report/url-compatibility-report.md" >> "$$GITHUB_STEP_SUMMARY"; fi; \
	exit $$status

.PHONY: site-parity
site-parity:
	@failed=""; \
	for target in site-parity-sphinx site-build site-parity-browser site-parity-privacy site-parity-diff site-parity-report; do \
		$(MAKE) $$target || failed="$$failed $$target"; \
	done; \
	if [ -n "$$failed" ]; then echo "site-parity failed in:$$failed" >&2; exit 1; fi

# Run all documentation checks (build, linkcheck, validate)
.PHONY: docs-check
docs-check: docs-validate docs-linkcheck docs-build
	@echo ""
	@echo "✅ All documentation checks passed!"

# Compile TPC-DS (and TPC-H) binaries from patched sources for the current
# platform and deploy them into benchbox/_binaries/ so they are used at runtime.
# No Docker required - builds natively on macOS ARM64/x86_64.
# Run this whenever _sources/tpc-ds/tools/ patches change.
.PHONY: compile-tpcds-binaries
compile-tpcds-binaries:
	bash _sources/compilation/scripts/compile-all-platforms.sh --native

# ---------------------------------------------------------------------------
# Visualization parity fixtures (CLI↔explorer contract)
# ---------------------------------------------------------------------------

# Regenerate fixtures from the canonical Python implementation.
# This CHANGES the contract - commit the resulting diff after review.
.PHONY: parity-fixtures
parity-fixtures:
	uv run python tests/parity/generate_visualization_fixtures.py

# Regenerate sql_compat capability matrix and skip reference docs from the registry.
.PHONY: compat-docs
compat-docs:
	uv run -- python scripts/generate_compat_docs.py

# Verify committed compat docs and DDL governance match the registry/source.
.PHONY: compat-docs-check
compat-docs-check:
	uv run -- python scripts/generate_compat_docs.py --check
	uv run -- python -m benchbox.sql_compat.inventory --output /tmp/benchbox-compat-inventory.jsonl --check-ddl-drift

# Regenerate the vendor-derived pricing tables from the checked-in vendor evidence.
.PHONY: pricing-data
pricing-data:
	uv run -- python scripts/generate_pricing_data.py

# Verify committed pricing tables match the vendor evidence without overwriting.
.PHONY: pricing-data-check
pricing-data-check:
	uv run -- python scripts/generate_pricing_data.py --check

# Regenerate the contributor-facing platform inventory from the typed manifest.
.PHONY: platform-manifest
platform-manifest:
	uv run -- python _project/scripts/platform_manifest.py

# Validate manifest invariants, subsystem keys, runtime coordinates, and generated docs.
.PHONY: platform-manifest-check
platform-manifest-check:
	uv run -- python _project/scripts/platform_manifest.py --check

# Verify fixtures match the current Python implementation without overwriting.
# Fails if any fixture is out of date (drift detected).
.PHONY: parity-check
parity-check:
	@tmpdir=$$(mktemp -d) && \
	uv run -- python tests/parity/generate_visualization_fixtures.py --out $$tmpdir && \
	diff -r --exclude='.gitkeep' tests/parity/fixtures $$tmpdir && \
	echo "parity-check: fixtures match Python source" && \
	rm -rf $$tmpdir || \
	(echo "parity-check FAILED: fixtures are out of date - run 'make parity-fixtures' to regenerate (or 'make guards-fix' to regenerate every mechanical drift-guard artifact)" && rm -rf $$tmpdir && exit 1)
