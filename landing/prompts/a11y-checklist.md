# /prompts/ — accessibility checklist

Owner: maintainer who lands changes to `landing/prompts/`. Run the manual
items on every nontrivial change to `index.html`, `prompts.js`, or
`prompts.css`. Sign off in the PR description with the date checked.

Items marked **[auto]** are asserted by `website/e2e/landing.mjs`
(`npm --prefix website run verify:landing`) against the built `/prompts/`
page, together with an axe-core scan in light and dark at several widths.
Items marked **[auto + manual]** are asserted in part; the parenthetical names the remainder. Items marked **[manual]** need a human or a real assistive technology.

## Keyboard

- [ ] **[auto]** Every selector and copy button is reachable via Tab in source order.
      (auto: tab order check)
- [ ] **[auto]** Shift+Tab returns through the same order.
      (auto: shift+tab order check)
- [ ] **[auto + manual]** All focusable elements show a visible focus ring (default uses
      `--accent-primary` outline at 2px offset).
      (auto: focus indicator check on a selector and the copy button; manual for the exact ring colour and offset)
- [ ] **[auto]** Enter / Space activates copy buttons.
      (auto: Enter and Space copy check)
- [ ] **[auto]** No keyboard traps (nothing requires a mouse to escape).
      (auto: bounded tab cycle repeats and reaches the theme control)

## Screen reader (VoiceOver on macOS or NVDA on Windows)

- [ ] **[auto + manual]** Page H1 is announced as "Instruct a coding agent to use BenchBox".
      (auto: h1 text; manual for the spoken announcement)
- [ ] **[auto]** Each `<select>` is announced with its label (Goal, Surface, Interface,
      Deployment, Platform / Platform A / Platform B, Benchmark, Scale).
      (auto: combobox accessible-name check for all seven selects)
- [ ] **[auto + manual]** After clicking a copy button, the `aria-live` region at
      `#copy-status` announces "Copied <block-name>".
      (auto: polite status role and status text history; manual for the spoken announcement)
- [ ] **[auto + manual]** When goal switches between "Test one platform" and
      "Compare platforms", the Platform vs Platform A/B fields show or
      hide cleanly (no orphaned announcements).
      (auto: Platform and Platform A/B exposure in both goals; manual for orphaned announcements)
- [ ] **[auto + manual]** The "Credential safety" block is reachable and readable when selected
      self-hosted or managed platforms need connection credentials.
      (auto: heading role, rendered block, list content; manual for readability with a screen reader)

## Visual

- [ ] **[auto + manual]** At 400px width (mobile narrow): form selectors stack to one
      column; copy buttons remain reachable; long platform names wrap.
      (auto: field stacking, copy button bounds, no horizontal overflow; manual for long platform name wrapping)
- [ ] **[auto]** At 768px width (tablet): grid reflows without overlap.
      (auto: field overlap check)
- [ ] **[auto]** At 1280px width (desktop): output blocks span full content
      column.
      (auto: output block width matches the form)
- [ ] **[auto]** Contrast ratio: body text ≥ 4.5:1 against `--bg-primary`; copy
      button text ≥ 4.5:1 against both default and `:hover` background.
      (auto: computed contrast for lede, labels and copy button idle and hover, light and dark)
- [ ] **[auto]** Yellow `Credential safety` border (`#d29922`) is also paired
      with a "⚠" glyph so colour is not the sole signal.
      (auto: warning glyph on the heading)

## No-JS fallback

- [ ] **[auto]** With JavaScript disabled, `<noscript>` content renders a working
      `uv add ... && uv run benchbox run ...` recipe.
      (auto: noscript block renders with the recipe)

## Copy behaviour

- [ ] **[auto]** Copy on a modern browser uses `navigator.clipboard.writeText`.
      (auto: clipboard write check)
- [ ] **[auto]** Copy fallback (older browsers) creates a hidden textarea + execCommand.
      (auto: execCommand copy fallback check)
- [ ] **[auto]** Copy status text auto-clears after 1.5s; button label resets to "Copy".
      (auto: status visible 1.0 to 2.5 seconds then cleared, label reset)

## Last checked

- 2026-05-13 — initial MVP land. ✅
