# results-explorer browser-functional tests

Playwright suite that exercises the built explorer (`dist/`) against a
per-run generated fixture corpus. Architecture decisions live in
[`docs/development/browser-test-architecture.md`](../../docs/development/browser-test-architecture.md).

## One-shot local run

```bash
cd results-explorer
npm ci
npm run test:e2e:install          # once; downloads browser binaries
npm run test:e2e:chromium         # writes fixtures, rebuilds dist, runs Chromium
npm run test:e2e:full             # local full-matrix convenience entrypoint
```

For a brand-new machine, `npm run test:e2e:chromium:setup` wraps the browser
install and then runs the same deterministic Chromium entrypoint.

The browser scripts regenerate `test-fixtures/.generated/`, rebuild `dist/`,
and then invoke Playwright, which starts the static server in
`scripts/serve-browser-tests.mjs`. The server mounts `dist/` at `/results/`
and routes `/results/data/` to `test-fixtures/.generated/data/`.

## Project layout

- `smoke/` - shell-level sanity checks tagged `@smoke`; also run under
  Firefox and WebKit projects.
- `routes/` - per-route happy-path coverage (w4-w6).
- `failures/` - injected-failure coverage against user-visible error
  states (w7).
- `capability/` - server/runtime contract checks that are not user
  failure paths (e.g. the RG-2 range-read gate).
- `support/` - helpers for fixture-routing, clipboard, and download flows.

## Writing a new test

- Tag anything that must run on all three browsers with `@smoke`; new
  tests are Chromium-only by default.
- Prefer user-visible assertions (rendered copy, visible error banner)
  over internal state or console noise.
- Never mutate `results-explorer/public/data/` or `results-data/bundles/`;
  use the fixture generator or Playwright route interception instead.

## See also

- [docs/operations/results-explorer-qa.md](../../docs/operations/results-explorer-qa.md)
  — the manual end-to-end QA test plan that pairs with this automated
  suite. Run it before declaring a release candidate green.
