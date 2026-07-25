# Consolidated prompt history for cloud sessions

Local Claude Code sessions leave their transcripts in `~/.claude/projects/`, so
a consolidated prompt history can be rebuilt from disk whenever you want. Cloud
sessions cannot: each runs in an ephemeral container that is reclaimed along
with its storage, and a container only ever holds *its own* transcript. There
is nothing to export after the fact.

`_project/scripts/cloud_prompt_log.py` closes that gap by capturing prompts
during the session and pushing them somewhere durable before the container goes
away.

**Capture starts when you install it.** Cloud sessions that ran before then are
gone and cannot be recovered from a container.

## How it works

| Hook | Subcommand | What it does |
| --- | --- | --- |
| `UserPromptSubmit` | `capture` | appends the prompt to `<history-dir>/sessions/<date>-<session-id>.jsonl` |
| `Stop` | `sync` | pushes what has accumulated so far to the sink repo |
| `SessionEnd` | `sync` | final flush |

Capture is local and unconditional. `sync` pushes **only** when
`CLAUDE_PROMPT_HISTORY_REMOTE` is set, so installing the hooks cannot publish
anything by itself — pointing that variable at a repository is the one explicit
act that starts sending prompts off the box.

Design points worth knowing:

- **One file per session.** Concurrent cloud sessions only ever *add* files to
  the sink, so a rebase can never hit a content conflict. Ref contention is
  handled by a re-fetch-and-retry loop (4 attempts, 1/2/4s backoff).
- **The sink clone lives under the history dir**, never inside the session's
  own checkout, so committing and pushing history never touches the working
  tree or index the agent is using.
- **Hooks never break a session.** Every hook entry point traps its own errors
  and exits 0; failures land in `<history-dir>/errors.log`.
- **Local sessions are skipped.** Capture no-ops unless
  `CLAUDE_CODE_REMOTE_ENVIRONMENT_TYPE` is set (the cloud runtime sets it, a
  Mac does not), so a hook installed from shared config will not double-capture
  sessions that already have durable transcripts.
- **Only `owner/name` is recorded for the repo.** A cloud container's remote URL
  is a session-scoped local proxy carrying credentials; the rest is discarded.

## Setup

### 1. Create a private sink repository

Prompt history is personal metadata. Use a **private** repo — a public one
publishes it permanently, and deleting the branch later does not unpublish it.
Do not use `joeharris76/BenchBox`; it is public.

### 2. Make the sink reachable from cloud containers

A cloud container can only push to repositories in its session scope, served by
the session's git proxy. Add the sink repo as a source on the cloud
environment(s) you use, in the environment settings at claude.ai/code.

### 3. Install the hooks

For **every cloud session, on any repo** — generate a standalone installer and
paste it into the environment's setup script field:

```bash
uv run --project _project/scripts -- python _project/scripts/cloud_prompt_log.py emit-setup
```

The installer embeds the script (base64) rather than referencing a path, since
the setup script runs for sessions on repos that do not carry this file. It is
generated from the script itself and cannot drift from it.

Also set on the environment:

```
CLAUDE_PROMPT_HISTORY_REMOTE=<git URL of the private sink repo>
CLAUDE_PROMPT_HISTORY_BRANCH=main          # optional, defaults to main
```

For **BenchBox cloud sessions only**, skip the environment setup script and add
the same three hooks to `.claude/settings.json` — the local-session gate keeps
them inert on your Mac.

### 4. Consolidate on your machine

```bash
git clone <sink repo> ~/claude-prompt-history
python3 _project/scripts/cloud_prompt_log.py merge \
    --cloud ~/claude-prompt-history/sessions \
    --local ~/.claude/projects \
    --out ~/.claude/prompt-history-consolidated.jsonl
```

`merge` is idempotent and additive: it reads the output file back in, unions it
with both sources, dedupes on `(session_id, ts, prompt)`, and writes the result
in chronological order. Re-running it after a `git pull` folds in new cloud
sessions without disturbing what is already there. Point `--out` at your
existing consolidated file if its records carry the same fields, or keep this
one alongside it.

Each record is:

```json
{"ts": "...", "source": "cloud", "session_id": "...", "prompt": "...",
 "cwd": "...", "repo": "owner/name", "branch": "...",
 "env_type": "cloud_default", "container_id": "..."}
```

Records extracted from local transcripts use `"source": "local"` and omit the
cloud-only fields.

## Verified

Exercised end to end against a throwaway sink repo: capture (including
multi-line prompts, empty and malformed hook input), no-op sync when no sink is
configured, first push into an empty sink, incremental pushes with no empty
commits, a second session pushing concurrently (both sessions' files preserved),
a forced non-fast-forward rejection recovered by the retry loop, idempotent
install that preserves unrelated hooks, a byte-identical round trip through the
emitted installer, and repeated merges that dedupe rather than double.
