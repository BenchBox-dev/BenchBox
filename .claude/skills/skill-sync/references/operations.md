# Skill-Sync Operations

- **Setup:** discover the desired destination, write config, dry-run, then
  sync when the task approves it.
- **Sync:** default to dry-run when uncertain; run configured sync, validate,
  and report changed files.
- **Status:** report dirty managed files, untracked materialized files, missing
  sources, pins, and mirror drift.
- **Validate:** check config, frontmatter, name/description, valid references,
  and duplicate canonical paths.
- **Diff:** no writes; report source revision, destination, additions,
  removals, and modifications.
- **Doctor:** check CLI, config parse, source reachability, destination
  permissions, and drift.
- **Pin/unpin:** update config only, then validate.
- **Prune:** dry-run first; remove only files known to be managed.
- **Promote:** inspect diff, validate, then commit/push the source repo with
  explicit file staging.
