#!/usr/bin/env bash
# cloud-claude-setup.sh — activate committed Claude Code plugins in a cloud
# (claude.ai/code) or other fresh/headless session.
#
# Why this exists: a committed .claude/settings.json DECLARES plugins
# (enabledPlugins + extraKnownMarketplaces) but Claude Code does NOT auto-install
# marketplace plugins in a fresh clone — plugins run arbitrary code, so install
# is gated behind an explicit step (docs: Discover/Install plugins, >= v2.1.195).
# Skills and commands load from .claude/ on their own; plugins do not. This
# script performs the per-environment install step. Wire it up as the BenchBox
# claude.ai/code environment setup script.
#
# Scope: PLUGINS ONLY. Project hooks are intentionally NOT provisioned here — the
# PostToolUse ruff/ty hooks are an edit-time convenience already enforced by CI
# (make lint / make typecheck / pr-preflight), and cloud may block project hooks
# via allowManagedHooksOnly. See
# _project/decisions/claude-settings-cloud-ownership-2026-06-29.md (cloud addendum).
#
# Idempotent and safe to re-run. No-op when the `claude` CLI or python is absent.
#
# Staleness caveat: claude.ai/code caches environment setup scripts and runs
# them once per environment BUILD, not once per session. If .claude/settings.json
# changes (plugin added/removed) after an environment was built, existing
# sessions in that environment will NOT pick up the change automatically —
# there is no supported per-session hook to bust this cache (project hooks are
# unreliable/blocked in cloud web execution; see the cloud addendum in
# _project/decisions/claude-settings-cloud-ownership-2026-06-29.md). Rebuild
# the claude.ai/code environment (or otherwise force a fresh environment build)
# after changing enabledPlugins/extraKnownMarketplaces, then verify with
# `claude plugin list` in the new session.
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
SETTINGS="$ROOT/.claude/settings.json"

if ! command -v claude >/dev/null 2>&1; then
  echo "cloud-claude-setup: 'claude' CLI not found; skipping plugin install." >&2
  exit 0
fi

PY=python3
command -v "$PY" >/dev/null 2>&1 || PY=python
if ! command -v "$PY" >/dev/null 2>&1; then
  echo "cloud-claude-setup: no python interpreter; skipping." >&2
  exit 0
fi

if [ ! -f "$SETTINGS" ]; then
  echo "cloud-claude-setup: $SETTINGS not found; nothing to do." >&2
  exit 0
fi

# 1. Register declared marketplaces (name<TAB>github-repo) from settings.json.
while IFS=$'\t' read -r name repo; do
  [ -n "${repo:-}" ] || continue
  echo "cloud-claude-setup: marketplace add ${name} (${repo})"
  claude plugin marketplace add "$repo" || true
done < <("$PY" - "$SETTINGS" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for n, cfg in (d.get("extraKnownMarketplaces") or {}).items():
    src = cfg.get("source", {})
    if src.get("source") == "github" and src.get("repo"):
        print(f"{n}\t{src['repo']}")
PY
)

# 2. Install every enabled plugin (key form: plugin@marketplace) to user scope.
fail=0
while IFS= read -r plugin; do
  [ -n "$plugin" ] || continue
  echo "cloud-claude-setup: install ${plugin}"
  if ! claude plugin install "$plugin" --scope user; then
    echo "  (install failed: ${plugin})" >&2
    fail=1
  fi
done < <("$PY" - "$SETTINGS" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for key, enabled in (d.get("enabledPlugins") or {}).items():
    if enabled:
        print(key)
PY
)

echo "cloud-claude-setup: done. Verify with 'claude plugin list'."
exit "$fail"
