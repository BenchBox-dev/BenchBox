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
	@echo ""
	@echo "Checking repo-local doc relative links..."
	@uv run -- python scripts/check_doc_relative_links.py

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

# Regenerate the contributor-facing platform inventory from the typed manifest.
platform-manifest:
	uv run -- python _project/scripts/platform_manifest.py

# Validate manifest invariants, subsystem keys, runtime coordinates, and generated docs.
platform-manifest-check:
	uv run -- python _project/scripts/platform_manifest.py --check

# Verify fixtures match the current Python implementation without overwriting.
# Fails if any fixture is out of date (drift detected).
parity-check:
	@tmpdir=$$(mktemp -d) && \
	uv run -- python tests/parity/generate_visualization_fixtures.py --out $$tmpdir && \
	diff -r --exclude='.gitkeep' tests/parity/fixtures $$tmpdir && \
	echo "parity-check: fixtures match Python source" && \
	rm -rf $$tmpdir || \
	(echo "parity-check FAILED: fixtures are out of date - run 'make parity-fixtures' to regenerate (or 'make guards-fix' to regenerate every mechanical drift-guard artifact)" && rm -rf $$tmpdir && exit 1)
