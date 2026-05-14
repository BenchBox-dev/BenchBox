# BenchBox Site Header Contract

Checked on 2026-05-14 from `fix/site-header-unification`, rebased on `origin/develop`.

## Current Variants

| Surface | Source | Links | CTA | Width / height | Position | Mobile | Active state |
|---|---|---|---|---|---|---|---|
| Landing | `landing/index.html`, `landing/style.css`, `landing/script.js` | Home, Docs, Blog, Results, Instruct an agent, GitHub, plus in-page section anchors | None | 1200px, padded fixed bar | Fixed | JS-created hamburger, hides section anchors | None |
| Docs/blog | `docs/_templates/page.html`, `docs/_static/custom.css` | Home, Docs, Blog, Results, Instruct an agent, GitHub | None | 1200px, 0.75rem vertical padding | Sticky | Hides all links | None |
| Results | `results-explorer/src/components/Layout.tsx` | Docs, Blog, Results, GitHub | Run benchmark | 1280px, min 3.5rem | Static | Flex wrap | Results active |

## Chosen Contract

| Attribute | Contract |
|---|---|
| Source of truth | `landing/shared/site-header.css` and `landing/shared/site-header.js` for static pages. Results uses a Preact wrapper with tests enforcing the same semantic contract. |
| Global link order | Home, Docs, Blog, Results, Instruct an agent, GitHub, Run benchmark |
| URLs | `https://benchbox.dev/`, `/docs/`, `/blog/`, `/results/`, `/prompts/`, `https://github.com/joeharris76/BenchBox`, and `https://benchbox.dev/docs/usage/installation.html` |
| CTA | `Run benchmark`, after GitHub |
| Active state | `aria-current="page"` on the active global section: Home, Docs, Blog, or Results |
| Width / height | 1200px max width, 4rem minimum desktop height, 1.5rem desktop link gap |
| Visual theme | Existing dark BenchBox header colors only; no full light/dark retheme in this phase |
| Position | Sticky top header. This preserves the landing shape but avoids fixed-header overlap with Furo controls, search, keyboard navigation, and anchor targets. |
| Mobile | A disclosure button reveals the same global links in the same order; links close the static menu after activation |
| Landing section anchors | Removed from global navigation. They are not part of the site-wide shell contract. |
| Results secondary nav | Remains separate under `aria-label="Results Explorer"` and is not part of the global header contract. |

## Rejected Alternatives

- Keep landing section anchors in the global header: rejected because docs/blog/results cannot share those anchors, and the defect is global nav drift.
- Keep three independent CSS implementations: rejected because it preserves the drift mechanism.
- Make Results the canonical header: rejected because it was missing Home and Instruct links and used a different max width.
- Keep docs mobile behavior that hides every link: rejected because mobile users need the same global navigation.
