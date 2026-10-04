##@ Documentation

# Build Sphinx documentation locally
.PHONY: docs-build
docs-build:
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
docs-linkcheck:
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
	@uv run -- python scripts/validate_visualization_images.py
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

# Regenerate the per-query documentation tree under docs/benchmarks/queries/.
# The tree is not committed (see docs/conf.py) -- the Sphinx build regenerates
# it for the building host's platform, since TPC query text is not byte-stable
# across architectures. This target is for previewing it outside a build.
.PHONY: query-docs
query-docs:
	uv run -- python scripts/generate_query_docs.py

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
site-build: query-docs site-deps
	@npm --prefix website run build
	@test -s website/dist/index.html
	@echo "Site built: website/dist/index.html"

.PHONY: site-dev
site-dev: site-deps
	@npm --prefix website run dev

.PHONY: site-check
site-check: query-docs site-deps
	@npm --prefix website run check
	@npm --prefix website run audit:high

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
