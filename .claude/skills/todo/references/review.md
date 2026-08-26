# TODO Review

Run `todo lint <id>` or `todo lint --all`. It checks command-based verification,
code scope, `prior_art` for new modules, environment variables, file
conventions, and runnable evidence for pinned upstream behavior. Use
`todo show <id>` to check clarity and current premises, then apply Layer 2 of
`shared-review-protocol/SKILL.md`.

Own-edit-target freshness: when `only_modify` includes a living policy, spec,
or goal document and the description quotes that document, require a `w0` that
re-reads current text and diffs it against the quoted claims. Line-number
citations are not durable evidence. Score evidence durability 0 if that re-read
is absent. Do not treat this as the semantic-guardrail item
(`todo-review-semantic-guardrails`).
