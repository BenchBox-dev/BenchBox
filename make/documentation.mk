.PHONY: docs-build
docs-build:
	@echo "Building documentation..."
	@cd docs && uv run sphinx-build -b html --keep-going . _build/html
	@echo "✅ Docs built: docs/_build/html/index.html"

.PHONY: docs-serve
docs-serve: docs-build
	@echo "Serving docs at http://localhost:8000"
	@echo "Press Ctrl+C to stop"
	@cd docs/_build/html && uv run -- python -m http.server 8000

.PHONY: docs-clean
docs-clean:
	@echo "Cleaning documentation build artifacts..."
	@rm -rf docs/_build
	@echo "✅ Documentation artifacts cleaned"

.PHONY: docs-linkcheck
docs-linkcheck:
	@echo "Checking documentation for broken links..."
	@cd docs && uv run sphinx-build -b linkcheck . _build/linkcheck
	@echo ""
	@echo "Link check results:"
	@cat docs/_build/linkcheck/output.txt || echo "No broken links found!"

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

.PHONY: docs-images
docs-images:
	@echo "Capturing visualization screenshots..."
	@uv run -- python scripts/capture_chart_images.py

prompt-quickstarts-write:
	@uv run -- python scripts/generate_landing_quickstarts.py --write

prompt-quickstarts-check:
	@uv run -- python scripts/generate_landing_quickstarts.py --check

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

.PHONY: docs-check
docs-check: docs-validate docs-linkcheck docs-build
	@echo ""
	@echo "✅ All documentation checks passed!"

.PHONY: compile-tpcds-binaries
compile-tpcds-binaries:
	bash _sources/compilation/scripts/compile-all-platforms.sh --native

.PHONY: parity-fixtures
parity-fixtures:
	uv run python tests/parity/generate_visualization_fixtures.py

.PHONY: compat-docs
compat-docs:
	uv run -- python scripts/generate_compat_docs.py

.PHONY: compat-docs-check
compat-docs-check:
	uv run -- python scripts/generate_compat_docs.py --check
	uv run -- python -m benchbox.sql_compat.inventory --output /tmp/benchbox-compat-inventory.jsonl --check-ddl-drift

.PHONY: pricing-data
pricing-data:
	uv run -- python scripts/generate_pricing_data.py

.PHONY: pricing-data-check
pricing-data-check:
	uv run -- python scripts/generate_pricing_data.py --check

.PHONY: platform-manifest
platform-manifest:
	uv run -- python _project/scripts/platform_manifest.py

.PHONY: platform-manifest-check
platform-manifest-check:
	uv run -- python _project/scripts/platform_manifest.py --check

.PHONY: parity-check
parity-check:
	@tmpdir=$$(mktemp -d) && \
	uv run -- python tests/parity/generate_visualization_fixtures.py --out $$tmpdir && \
	diff -r --exclude='.gitkeep' tests/parity/fixtures $$tmpdir && \
	echo "parity-check: fixtures match Python source" && \
	rm -rf $$tmpdir || \
	(echo "parity-check FAILED: fixtures are out of date - run 'make parity-fixtures' to regenerate (or 'make guards-fix' to regenerate every mechanical drift-guard artifact)" && rm -rf $$tmpdir && exit 1)
