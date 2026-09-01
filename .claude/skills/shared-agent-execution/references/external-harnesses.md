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
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && goose review --prompt "$CRITERIA_FILE" --model "$MODEL")`
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
  - Reviewer (Hard Read-Only): `(cd "$WORKSPACE" && aider --model "$MODEL" --message "$PROMPT" --chat-mode ask)`
