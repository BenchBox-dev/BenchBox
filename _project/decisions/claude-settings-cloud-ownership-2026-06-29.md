# Claude Code Settings Ownership & Cloud Parity - 2026-06-29

## Decision

The project owns `.claude/settings.json` directly (no skill-sync feature
manages it). Three classes of Claude Code configuration are handled distinctly
so that cloud/web (`claude.ai/code`) and CI — which clone only the repo — get
the same agent behavior as a local machine, without leaking machine- or
policy-specific configuration into the shared tree:

1. **Plugins + marketplaces** — committed to `.claude/settings.json`
   (`extraKnownMarketplaces` + `enabledPlugins`). Done in #895.
2. **Skills** — committed via skill-sync's tracked `claude` target
   (`.claude/skills/**`, `ignore: [blog]`). Done in #898.
3. **Hooks** — only *portable, project-scoped* hooks are committed to
   `.claude/settings.json`. *Machine/policy-specific* hooks stay in the user's
   global `~/.claude/settings.json` and are never committed.

### Hook portability split

Committed (portable — `uv run`, non-blocking `exit 0`, no machine paths, no
private-repo coupling):

| Hook | Command |
|---|---|
| `PostToolUse` `Edit\|Write` `*.py` | `ruff check --fix` + `ruff format` |
| `PostToolUse` `Edit\|Write` `*.py` | `ty check` |

Deliberately **excluded** (machine/policy-specific):

| Hook | Why excluded |
|---|---|
| `PreToolUse` `Bash` push/PR guard | References a private remote (`benchbox-private`) and blocks pushes. Committing it would break legitimate pushes in any clone — including cloud — and encodes a personal policy, not a project invariant. |

### Untracked mirrors (deliberate, guarded)

`.codex/skills`, `.gemini/skills`, `.antigravity/skills`, and the curated-out
`.claude/skills/blog/` stay untracked: cloud is Claude-only (the other CLIs'
mirrors add no value there) and `blog` is curated/published separately. These
rely on the skill-sync-managed `.gitignore` block, which `skill-sync verify`
does **not** police (it only inspects the tracked `claude` target). A dedicated
CI step (`Untracked skill-mirror drift guard` in `.github/workflows/pr.yml`)
fails the build if any of these become git-tracked.

## Rationale

- **Why the project owns settings.json, not skill-sync.** skill-sync manages
  `.gitignore`/`.gitattributes` blocks and the tracked skill snapshot; it has no
  settings.json/hooks feature, and it is an unpublished side-tool. Coupling
  hooks to it would be heavier and add a dependency for no benefit. #895 already
  set the precedent of the project committing `.claude/settings.json` directly.
- **Why duplicating portable hooks into the project file is safe.** Claude Code
  merges hooks across user + project + local settings and **deduplicates
  identical command hooks** (by exact command string). The committed commands
  are byte-identical to the global ones, so locally they run **once** (deduped)
  and in cloud only the project copy exists (runs once). The user's global
  `~/.claude/settings.json` is therefore left untouched.
- **Why the push-guard is excluded.** It is non-portable by construction: it
  hard-codes `benchbox-private` and blocks `git push`. In a public clone or
  cloud session it would either no-op confusingly or actively break pushes.
  Push/branch protection is enforced server-side (branch rules, CI) — the local
  hook is a convenience for one machine, not a project invariant.
- **Why a separate drift guard for the mirrors.** `verifyTrackedTargets` in
  skill-sync iterates only targets with `tracked: true` (it `continue`s past
  untracked targets) and skips `ignore`d paths. So a `git add -f .codex/skills`
  or a regression in the `.gitignore` managed block would be invisible to the
  existing integrity gate. The guard is a 3-line `git ls-files` check — no new
  dependency.

## Evidence

- Global `~/.claude/settings.json` (2026-06-29) contained exactly three hooks:
  the two `PostToolUse` `.py` formatters/type-checks (portable) and one
  `PreToolUse` `Bash` push/PR guard referencing `benchbox-private` (non-portable).
- Claude Code hooks reference: "All matching hooks run in parallel, and
  identical handlers are deduplicated automatically. Command hooks are
  deduplicated by command string and `args`."
- skill-sync `verifyTrackedTargets` (dist `chunk-6V2RFA5R.js`, ~line 1486):
  `if (!cfg.tracked) continue;` and the `exclusions` skip at the stray-path
  check confirm untracked targets and `ignore`d paths are out of scope.
- `npm view skill-sync` → 404 (not published); CI pins
  `github:joeharris76/skill-sync#d3c9c45`. Swap to `npx -y skill-sync@<ver>`
  tracked as a follow-up TODO.

## Alternatives rejected

- **Teach skill-sync to manage a hooks block in settings.json** (like its
  `.gitignore` block). Rejected: heavier, couples the project to an unpublished
  tool, and dedup already makes direct project ownership safe.
- **Move the portable hooks out of the user global file.** Unnecessary given
  dedup; would mutate user-global config for no behavioral gain.
- **Commit all hooks including the push-guard.** Rejected: breaks cloud pushes
  and encodes personal policy as a project invariant.
