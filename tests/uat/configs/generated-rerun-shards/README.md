# Generated rerun shards (frozen historical)

These YAML files are **generated rerun shards** — operational scratch emitted by
the 2026-05-05 tuned follow-up UAT sweep (one aggregate config plus one per
platform). They are class 3 ("generated rerun shard") in the config lifecycle
documented in `docs/operations/uat-framework.md`.

They are **not editable templates** and must not be cloned as starting points:

- They pin a specific platform/scale/resume slice from a single past sweep.
- They are retained here as evidence of that sweep, frozen as-is.
- To start a new sweep, clone a top-level `# TEMPLATE` config in
  `tests/uat/configs/` instead.

Do not add new generated shards to the top-level `tests/uat/configs/` directory;
emit them here (or to an ignored scratch path) so they cannot masquerade as
reusable templates. Ephemeral per-run resume state is `resume.json` under the
run's log dir — not a config file and not stored here.
