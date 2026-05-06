---
id: 2026-05-05-154305-uat-orphan-yaml-fields
date: 2026-05-05
status: merged-to-todo
finding_kind: framework-gap
review_context: "principal-engineer review of UAT framework PR #205 (post-merge simplification audit)"
related_paths:
  - tests/uat/configs/uat-2026-05-02.yaml
  - tests/uat/configs/stress-default.yaml
  - tests/uat/cleanup.py
  - tests/uat/phases/package.py
  - _project/specs/uat-framework.md
suggested_sweep: "either implement the fields (each has a documented intent in the spec) or delete them from configs and spec; right now they are documentation that the code does not honour."
todo_id: uat-framework-review-followups
---

# Three UAT YAML fields are declared in spec/configs but silently noop

## Finding
Three fields are present in shipped configs and the spec's schema documentation
but have **zero readers anywhere in `tests/uat/` or `benchbox/`**:

- `cleanup.preserve_datagen` — declared in `tests/uat/configs/uat-2026-05-02.yaml:45`
  and `_project/specs/uat-framework.md:219,433`. No grep hit for any reader.
- `cleanup.prune_databases` — declared in `tests/uat/configs/uat-2026-05-02.yaml:46`
  and spec lines 220, 434. No grep hit. The cleanup phase actually consults
  `cleanup_enabled`, a Python kwarg passed from `tests/uat/_cli.py:321`, NOT the YAML key.
- `package.pr_target_branch` — spec line 264 declares this as optional. No grep hit
  in any code under `tests/uat/` or `benchbox/cli/commands/submit.py`.

A sweep author setting `cleanup.preserve_datagen: false` today expects datagen
to be wiped between cells. The setting is silently ignored. Same for the other
two.

## Why this matters
Spec-declared / config-declared fields without readers are worse than absent
fields: they create a false promise that tooling honours an operator's intent.
The fields appear in the frozen 2026-05-02 replay config, so any reviewer
comparing "shipped UAT used these settings" against current behaviour gets a
misleading picture of what was actually controlled by the YAML.

## Suggested next steps
- [ ] Decide per-field: implement OR delete-from-spec-and-configs.
- [ ] If implemented, the frozen 2026-05-02 config is locked — clone to a
      `uat-2026-05-02-corrected.yaml` rather than mutating the frozen file
      (the frozen-config drift guard at `tests/uat/test_frozen_configs.py`
      will reject in-place edits).
- [ ] Add a `tests/uat/test_config.py` regression: every field present in
      `stress-default.yaml` MUST have a reader under `tests/uat/` or
      `benchbox/`. Mechanical grep test, fast-marked.

## Triage log

- 2026-05-05: actionable (sweep). Confirmed: zero readers in `tests/uat/` or
  `benchbox/` for `cleanup.preserve_datagen`, `cleanup.prune_databases`,
  `package.pr_target_branch`. Tracked under
  `uat-framework-review-followups`. Carry forward all three next-steps.
- 2026-05-05: promoted to TODO `uat-framework-review-followups`
