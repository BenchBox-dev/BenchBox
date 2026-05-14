# /prompts/ — accessibility checklist (manual)

Owner: maintainer who lands changes to `landing/prompts/`. Run this list
on every nontrivial change to `index.html`, `prompts.js`, or
`prompts.css`. Sign off in the PR description with the date checked.

Automated tooling (pa11y, axe-core) is deferred per
`landing-prompts-launch-gates` deferred list — file a follow-up TODO if
you decide to add it.

## Keyboard

- [ ] Every selector and copy button is reachable via Tab in source order.
- [ ] Shift+Tab returns through the same order.
- [ ] All focusable elements show a visible focus ring (default uses
      `--accent-primary` outline at 2px offset).
- [ ] Enter / Space activates copy buttons.
- [ ] No keyboard traps (nothing requires a mouse to escape).

## Screen reader (VoiceOver on macOS or NVDA on Windows)

- [ ] Page H1 is announced as "Instruct a coding agent to use BenchBox".
- [ ] Each `<select>` is announced with its label (Goal, Agent, Surface,
      Interface, Deployment, Platform / Platform A / Platform B,
      Benchmark, Scale).
- [ ] After clicking a copy button, the `aria-live` region at
      `#copy-status` announces "Copied <block-name>".
- [ ] When goal switches between "Test one platform" and
      "Compare platforms", the Platform vs Platform A/B fields show or
      hide cleanly (no orphaned announcements).
- [ ] The "Managed cloud safety" block is reachable and readable when
      deployment=managed.

## Visual

- [ ] At 400px width (mobile narrow): form selectors stack to one
      column; copy buttons remain reachable; long platform names wrap.
- [ ] At 768px width (tablet): grid reflows without overlap.
- [ ] At 1280px width (desktop): output blocks span full content
      column.
- [ ] Contrast ratio: body text ≥ 4.5:1 against `--bg-primary`; copy
      button text ≥ 4.5:1 against both default and `:hover` background.
- [ ] Yellow `Managed cloud safety` border (`#d29922`) is also paired
      with a "⚠" glyph so colour is not the sole signal.

## No-JS fallback

- [ ] With JavaScript disabled, `<noscript>` content renders a working
      `uv add ... && uv run benchbox run ...` recipe.

## Copy behaviour

- [ ] Copy on a modern browser uses `navigator.clipboard.writeText`.
- [ ] Copy fallback (older browsers) creates a hidden textarea + execCommand.
- [ ] Copy status text auto-clears after 1.5s; button label resets to "Copy".

## Last checked

- 2026-05-13 — initial MVP land. ✅
