SITE_INPUTS_OUT ?= site-inputs
.PHONY: site-inputs
site-inputs:
	@uv run -- python scripts/site_inputs.py build --out "$(SITE_INPUTS_OUT)" \
		$(if $(SITE_INPUTS_CORE_SHA),--core-sha "$(SITE_INPUTS_CORE_SHA)") \
		$(if $(SITE_INPUTS_PARENT_SHA),--parent-core-sha "$(SITE_INPUTS_PARENT_SHA)") \
		$(if $(SITE_INPUTS_PARENT_SOURCE),--parent-source "$(SITE_INPUTS_PARENT_SOURCE)") \
		$(if $(SITE_INPUTS_CERTIFIED_BY),--certified-by "$(SITE_INPUTS_CERTIFIED_BY)")
	@uv run -- python scripts/site_inputs.py verify "$(SITE_INPUTS_OUT)"
