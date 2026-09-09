# Operations

## Configuration

`skill-sync.conf` at the project root. One target list, then one or more source
groups. `#` starts a comment.

```
target = .claude/skills
target = .agents/skills

source = ~/Developer/skill-sync-skills
rev    = d22ea7fab6b7b9608e54a3910ab4dfa9bb407d42
dir    = skills
skill  = code
skill  = test

source = .
rev    = 0ae997e41ce9e129fb74c894f6b14dbc8059fa7a
skill  = my-project-skill
```

A source may be the project's own checkout. Pin it to a commit like any other:
`rev = HEAD` re-records the project's commit on every sync, so `check` reports a
pending receipt update after every commit.

- `target` — project-relative directory that receives the skills. Every target
  gets the same selection. All `target` lines must precede the first `source`.
- `source` — path to a local Git checkout. `~` expands; relative paths resolve
  against the project root.
- `rev` — required. Any commit-ish that exists locally in that checkout.
- `dir` — subdirectory of the checkout holding skill packages. Default `skills`.
- `skill` — one skill package. A skill may be listed once across the whole file;
  there is no resolver, so shared prerequisites must be listed explicitly.

## Preview, check, apply

`preview` prints one line per changed path and touches nothing:

```
A .claude/skills/code/references/analysis.md
M .claude/skills/code/SKILL.md
D .claude/skills/code/references/old.md
R .claude/skills/blog
```

`A` add, `M` modify (content or executable bit), `D` delete a file inside a
managed skill, `R` remove a skill directory that the receipt records but the
config no longer selects.

`check` prints the same report and exits 3 when anything is pending, 0 when the
project is in sync. It needs the catalog checkout, so it belongs in a local
pre-commit check, not in a CI job on a machine without the catalog.

`verify` is the offline gate. It reads only committed project files — no catalog,
no network, no rsync — and fails when a recorded file is missing, its bytes or
executable bit differ, something extra sits inside a managed skill directory, a
managed path is a symlink, or the receipt and manifest disagree about which
skills the target holds. It proves the payload is what `apply` wrote; it cannot
prove the recorded revision is the intended one. Use it in CI; use `check` where
the catalog exists.

`apply` performs the copy. It refuses when:

- a destination resolves through a symlinked ancestor, which would put writes
  and deletions outside the project;
- it would overwrite or delete a file the receipt does not record it writing;
- the destination has drifted from the revision the receipt already records,
  which means a generated file was edited in place;
- a file it would rewrite has uncommitted changes in Git;
- a target skill directory exists but is not recorded in that target's
  `skill-sync.receipt`, and its content differs from the source;
- the selected skills contain symlinks or special files;
- the configured `rev` is not present in the local checkout.

There is no force flag. Resolve the cause instead: commit the pending work, move
a hand-written file out of a generated directory, delete a locally edited file to
restore it, or remove an unmanaged directory (`git rm -r <path>`) so the adoption
lands as a reviewable Git diff.

## What apply owns

Deletion is scoped to one skill directory at a time. Anything else under a
target — project-owned skills, `skill-sync.config.yaml`, loader-owned `.system/`
— is out of range and is never removed.

Each target gets a `skill-sync.receipt` recording, per source, the repository
identity, the resolved commit, and the selected skills, followed by every file
skill-sync wrote. It carries no timestamp, so a repeated sync of the same
revision produces no Git diff, and no hashes, so it attests nothing about the
current contents. `skill-sync.manifest` beside it carries the SHA-256 and mode of
each of those files, and is what `verify` reads. The `file` lines are an
ownership record: they are what lets
`apply` refuse to overwrite or delete content it did not write, including content
Git ignores and therefore never reports.

For a gitignored target, that protection is bounded. A local edit is caught while
the recorded revision still stands. Once the catalog moves on, an edited file and
an updated one look the same and Git holds no baseline, so the edit is lost.

The receipt is written last. A failed run leaves the previous receipt in place
rather than claiming a sync that did not finish.

## Project settings

Skills read `<target>/skill-sync.config.yaml`. skill-sync does not generate or
overwrite it; maintain it by hand and keep project-specific values there rather
than editing canonical skills.

## Replacements for retired commands

| Retired | Now |
|---|---|
| `sync` | `apply` |
| `diff`, `status` | `preview` |
| `verify` | Review the Git diff; `check` locally where the catalog exists |
| `validate` | `preview` fails on a malformed config |
| `prune` | Remove the skill from `skill-sync.conf`; `apply` deletes it |
| `pin`, `unpin` | Edit `rev` in `skill-sync.conf` |
| `promote` | Commit and push in the catalog checkout |
| `doctor` | `preview` |
| `settings` | Maintain `skill-sync.config.yaml` by hand |
| `align-agents`, `agent-config` | Not replaced; see `MIGRATION.md` |
