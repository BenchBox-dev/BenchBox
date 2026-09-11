# External Harnesses

Use these known-good direct configurations whenever an external harness is
selected. Choose the documented command for the delegated role and use it
directly. Only after an actual command failure may reactive diagnosis use
`command -v` and the installed `--help` output to distinguish a missing binary
from flag drift. Do not run those checks proactively.

- Worker commands require already-authorized write scope bounded by a sandbox,
  workspace, or dedicated worktree. Confirmation automation in a documented
  Worker command is allowed only within that bounded scope.
- Reviewer commands use the declared **Hard Read-Only** or **Soft Read-Only**
  classification. Reinforce Soft Read-Only with findings-only instructions that
  forbid edits, commits, pushes, and other mutations.
- Do not add flags that remove workspace, sandbox, or tool boundaries.

## Frontier Lab Harnesses

- **codex**
  - Worker (Write): `codex exec -C "$WORKSPACE" --model "$MODEL" --sandbox workspace-write "$PROMPT"`
  - Reviewer (Hard Read-Only): `codex exec -C "$WORKSPACE" --model "$MODEL" --sandbox read-only "$PROMPT"`
  - Known-good models: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`
  - Effort: Optional `-c model_reasoning_effort="<level>"`
- **claude**
  - Worker (Write): `(cd "$WORKSPACE" && claude --print --model "$MODEL" --effort "$EFFORT" "$PROMPT")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && claude --print --tools Read,Grep,Glob --model "$MODEL" --effort "$EFFORT" "$PROMPT")`
  - Known-good models: `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`
- **agy**
  - Worker (Write): `(cd "$WORKSPACE" && agy --model "$MODEL" --effort "$EFFORT" --print="$PROMPT")`
  - Reviewer (Soft Read-Only): `(cd "$WORKSPACE" && agy --model "$MODEL" --effort "$EFFORT" --mode plan --print="$PROMPT")`
  - Known-good models: `gemini-3.7-flash-high`, `gemini-3.7-flash-medium`, `gemini-3.7-flash-low`
- **grok**
  - Worker (Write): `grok --cwd "$WORKSPACE" --single "$PROMPT" --model "$MODEL" --reasoning-effort "$EFFORT"`
  - Reviewer (Soft Read-Only): `grok --cwd "$WORKSPACE" --single "$PROMPT" --model "$MODEL" --reasoning-effort "$EFFORT" --permission-mode plan`
  - Known-good models: `grok-4.6`, `grok-4.5`
- **muse**
  - Worker (Write): `muse exec --workspace "$WORKSPACE" --disable-approval --model "$MODEL" --reasoning-effort "$EFFORT" "$PROMPT"`
  - Reviewer (Hard Read-Only): `muse exec --workspace "$WORKSPACE" --disable-approval --disable-write --disable-shell --model "$MODEL" --reasoning-effort "$EFFORT" "$PROMPT"`
  - Known-good models: `muse-spark-1.2-contributor`, `muse-spark-1.2`
  - Note: Unset invalid credentials with `env -u META_API_KEY` before execution.

## Extensible and Community Harnesses

- **pi**
  - Worker (Write): `(cd "$WORKSPACE" && pi --print --model "$MODEL" --thinking "$EFFORT" "$PROMPT")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && pi --print --tools read,grep,find,ls --model "$MODEL" --thinking "$EFFORT" "$PROMPT")`
  - Known-good models: `openai-codex/gpt-5.6-sol`, `openai-codex/gpt-5.6-terra`, `openai-codex/gpt-5.6-luna`, `anthropic/claude-fable-5`, `anthropic/claude-opus-5`, `anthropic/claude-sonnet-5`, `xai/grok-4.6`, `xai/grok-4.5`, `muse-spark/muse-spark-1.2-contributor`
- **jcode**
  - Worker (Write): `jcode run -C "$WORKSPACE" --model "$MODEL" "$PROMPT"`
  - Reviewer (Hard Read-Only): `jcode run -C "$WORKSPACE" --disable-base-tools --tools read --model "$MODEL" "$PROMPT"`
  - Known-good models: `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`, `claude-fable-5`, `claude-opus-5`, `claude-sonnet-5`, `gemini-3.7-flash-tiered`, `muse-spark-1.2-contributor`
- **goose**
  - Worker (Write): `(cd "$WORKSPACE" && goose run --text "$PROMPT" --no-session --provider "$PROVIDER" --model "$MODEL")`
  - Reviewer (Soft Read-Only): `(cd "$WORKSPACE" && goose review --prompt "$CRITERIA_FILE" --model "$MODEL")`
- **prime-agent**
  - Worker (Write): `prime-agent -p --cwd "$WORKSPACE" --provider "$PROVIDER" --model "$MODEL" --thinking "$EFFORT" "$PROMPT"`
  - Reviewer (Hard Read-Only): `prime-agent -p --tools read,grep,find,ls --cwd "$WORKSPACE" --provider "$PROVIDER" --model "$MODEL" --thinking "$EFFORT" "$PROMPT"`
- **opencode**
  - Worker (Write): `(cd "$WORKSPACE" && opencode run -m "$MODEL" "$PROMPT")`
  - Reviewer (Soft Read-Only): `(cd "$WORKSPACE" && opencode run --agent plan -m "$MODEL" "$PROMPT")`
  - Note: Model format is `<provider>/<model>`.
- **hermes**
  - Worker (Write): `(cd "$WORKSPACE" && hermes chat -q "$PROMPT")`
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && hermes chat -q --tools read,search "$PROMPT")`
- **aider**
  - Worker (Write): `(cd "$WORKSPACE" && aider --model "$MODEL" --message "$PROMPT" --yes-always --no-auto-commits)`
  - Reviewer (Soft Read-Only): `(cd "$WORKSPACE" && aider --model "$MODEL" --message "$PROMPT" --chat-mode ask)`

## Reviewer panels

A panel is several Reviewer dispatches over one revision, used when the user
asks for independent cross-model critique or when one harness is rate-limited.
Each panel member follows the Reviewer rules above; the panel adds isolation,
diversity, and delivery requirements.

### Isolation

Classify each member before dispatch:

| Classification | Harnesses | Workspace |
|---|---|---|
| Hard Read-Only | `codex --sandbox read-only`, `claude --tools Read,Grep,Glob`, `muse --disable-write --disable-shell`, `pi --tools read,...`, `jcode --tools read`, `prime-agent --tools read,...`, `hermes --tools read,search` | The reviewed worktree is acceptable. |
| Soft Read-Only | `agy --mode plan`, `grok --permission-mode plan`, `opencode --agent plan`, `goose review`, `aider --chat-mode ask` | A dedicated detached worktree at the reviewed revision. |

A Soft Read-Only mode is an instruction, not an enforced sandbox. Never run
two Soft Read-Only members, or a Soft Read-Only member and any writer, in the
same worktree at the same time. Create the isolation worktree from the exact
revision under review and remove it after the panel reports:

```bash
REVIEW_WT="$WORKSPACE/.wt-review-$(date +%s)"
git -C "$WORKSPACE" worktree add --detach "$REVIEW_WT" "$REVISION"

# Dispatch Soft Read-Only member in background and capture PID:
# (cd "$REVIEW_WT" && ...) &
# REVIEW_PID=$!
# wait "$REVIEW_PID" || true

# Terminate process before worktree removal to prevent file descriptor races:
if [ -n "$REVIEW_PID" ] && kill -0 "$REVIEW_PID" 2>/dev/null; then
    kill -TERM "$REVIEW_PID" 2>/dev/null
    sleep 1
    kill -0 "$REVIEW_PID" 2>/dev/null && kill -KILL "$REVIEW_PID" 2>/dev/null
    wait "$REVIEW_PID" 2>/dev/null || true
fi

git -C "$WORKSPACE" worktree remove --force "$REVIEW_WT"
```

Members must stay inside the worktree they were given. A member that cannot be
constrained to findings-only output is dropped from the panel rather than
re-dispatched with weaker boundaries.

### Diversity

Exclude models from the authoring agent's own family, because self-review does
not add an independent viewpoint. When the author is a Claude model, review with
`codex`, `grok`, `muse`, or `agy`. Keep the tier the work needs: Tier 1 for a
final adversarial gate, Tier 2 for routine review. A user-named reviewer or a
user-set effort overrides this default.

### Brief delivery

An external harness cannot read the dispatching agent's memory or an unsaved
chat plan. Serialize what the member must judge to an atomically created,
private file and pass the path:

```bash
BRIEF=$(mktemp /tmp/review-brief.XXXXXX.md)
chmod 0600 "$BRIEF"
# write brief content to "$BRIEF"
# pass "$BRIEF" to reviewer commands
# clean up when panel concludes:
rm -f "$BRIEF"
```

The brief states the requested outcome, the exact revisions or paths under
review, the constraints that bind the work, and the output contract (severity
table with `file:line` evidence, per the adversarial-review reference in
`shared-review-protocol`). It does not contain the author's preferred
conclusions.

### Failure and quorum

Dispatch members in parallel and bound each with a timeout. A member that
fails, times out, or returns no findings is reported as absent, not as
agreeing. State which members reported and which did not. When the user asked
for a specific reviewer, a missing member is a blocker to report rather than a
reason to substitute a different model silently; offer the substitution and
continue with the members that reported.

Attribution, consensus, and dissent handling for the merged report are owned by
`shared-review-protocol/references/adversarial-review.md`.
