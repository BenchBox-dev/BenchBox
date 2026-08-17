# Skill-Sync Operations

## Source roles

- **Source:** authoritative editable package selected by `source_name`, then
  manifest order.
- **Target:** generated installation. Do not promote by editing it in place.
- **Bundled operator:** `skills/skill-sync` in the product repository. Change it
  with the CLI contract and package it from that repository.

## Actions

- **Setup:** discover the destination, write the manifest, dry-run, then sync
  when authorized.
- **Sync:** dry-run when uncertain; sync, validate, and report changed files.
- **Status:** report dirty, missing, extra, pinned, and drifted managed content.
- **Validate:** check config, frontmatter, references, compatibility, and paths.
- **Verify:** without source access, prove tracked targets match their lock and
  generated config.
- **Diff:** without writes, report source, destination, and planned changes.
- **Doctor:** check CLI, config, source access, destinations, and drift.
- **Pin/unpin:** update config, then validate.
- **Prune:** dry-run first; remove only known managed content.
- **Settings:** use `settings generate` to show required agent settings.
- **Agent config:** use `agent-config capture|validate|restore` for the exact
  six-file local instruction snapshot. Validate before restore; require
  `--force` to replace modified destinations.

## Promote

1. Resolve the winning source and its repository before editing.
2. For a local source, edit that source and run its source-native validation.
3. For a git consumer, update the ref or pin, dry-run, sync, then verify the
   consumer lock and tracked targets.
4. For the bundled operator, run CLI/flag compatibility and package-content
   checks in the product repository.
5. Commit, push, or open a PR only when authorized. Publish the source before
   updating downstream pins and mirrors.

## Consumer lock, attributes, and pins

- A git source is cloned `--depth 1` of the default branch. A pin that exists
  only on a feature branch fails as a missing ref. Land the source change on
  that default branch before advancing a consumer pin.
- Sync rewrites `skill-sync.lock` every time. Revert timestamp-only
  `lockedAt`/`fetchedAt` churn; keep source refs, revisions, and file digests
  when they change. Unconditional `git checkout skill-sync.lock` discards a
  real pin or digest update.
- Sync may move its managed `.gitattributes` block to end-of-file. Sequence
  that rewrite with any other `.gitattributes` edit rather than landing both
  in parallel.

## Deployment and branch tests

- Serve global loaders from a generated store built from merged, pinned source
  revisions, not an authoring checkout.
- Test a feature branch through project-local targets sourced from its worktree;
  do not repoint the global store.
