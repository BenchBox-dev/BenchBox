# Comments and docstrings

Maintained first-party code must contain no explanatory comments or docstrings.
Clarify the code by simplifying it, removing unnecessary branches, or improving
names and types. Put a useful public contract in the canonical API reference.
Retain design rationale outside source only when future work needs the reason.
Do not move removed prose into inert strings, fake metadata, or runtime `__doc__`
assignments. A help string or protocol record must have an actual reader.

## Checks

- `make comment-policy-check` rejects new violations against `origin/develop`.
  Set `BASE_REF` to an immutable commit SHA to reproduce a CI comparison.
- `make comment-policy-strict` checks the full maintained source inventory.
  It will fail until the module cleanup is complete.
- `make comment-policy-report` reports remaining violations without rejecting
  legacy debt. Configuration and parser setup failures still fail.
- The pre-commit hook checks staged content. Install the existing hooks and
  install the Explorer parser with `npm ci --prefix results-explorer`.

The CI job runs on every pull request and merge group. The required tooling
result consumes it even when other code lint is skipped. CI takes its base SHA
from the platform event and rejects an override. After the initial rollout, the
launcher, checker and language adapter scripts come from that immutable base
commit. Their third-party parser libraries use the repository's installed and
locked dependencies. Bootstrap is
restricted to the explicitly pinned initial commit; a missing checker elsewhere
fails. Changes to this wiring remain subject to the repository's independent
soundness review.

## Mechanical exceptions

`quality/comment-policy.json` records exact exceptions. An entry identifies the
file, qualified symbol or payload, and complete comment text. It names an actual
consumer file, explains necessity and the smaller alternative considered, and
records an owner and removal condition. Suppressions also need an unexpired
review date. Line numbers are not exception identities.

Only three exception kinds exist:

- **Directive:** the whole token must match a registered grammar. Examples are
  specific `noqa` codes, specific type-ignore codes, formatting and coverage
  directives, ShellCheck codes, TypeScript references, and registered SQL hints.
  Extra explanatory text fails. A matching spelling alone grants no exception.
- **Notice:** retain only the exact required text, with its governing source
  named as the consumer. Do not substitute a shorter notice without checking
  that governing source.
- **Fixture:** exact comment tokens deliberately read by a parser test. Record
  the test consumer and fixture identity; ordinary test explanations do not
  qualify.

A first-line interpreter shebang is accepted without registry metadata. A
valid encoding cookie is accepted only in the first two lines and only for a
non-UTF-8 Python source encoding. UTF-8 cookies are unnecessary.

New exceptions cannot authorize source in the same change: transition checks
use the base policy. Introduce and review the evidence first, then use the
approved exception in a later change. The initial registry contains only exact
SQL inputs consumed by the scanner's regression tests.
Unused and unnecessary exceptions must be removed during module review.

## Transition and ownership

The checker compares a multiset of exact file, kind, symbol and text identities.
Deleting an unrelated comment does not pay for a new comment. Adding another
copy, changing text, or moving prose into a different symbol fails. Unchanged
legacy content in checked scopes is reported. Transition checks inspect changed
files and every completed scope; report and strict modes inspect the full
inventory. No permanent archive of removed prose is stored. Use `--path` with
the checker to select an exact file or directory prefix for a local check.

Add a cleaned file or directory prefix to `completed`. Every violation in that
scope then fails, including inherited violations. Completed scopes cannot be
removed. Candidate policies cannot expand the external exclusions. Exclusions
name canonical upstream owners and provenance. Compilation scripts under
`_sources/compilation` are included; TPC templates and catalog-owned skill
mirrors have separate provenance. Generated first-party code is included.

The existing 90% docstring gate remains in force until useful API contracts have
been migrated and its replacement is approved. Existing module docstrings are
transition debt, not an endorsement that they are useful.

## Coverage and limits

Python uses its AST and tokenizer; standalone literal strings and direct runtime
docstring assignment forms are rejected too. Recognizable SQL literals are
scanned as SQL. JavaScript and TypeScript use the installed TypeScript parser,
protecting strings, regular expressions, template text and JSX text while
examining executable expressions. SQL scanning handles quoted values, dollar
strings and nested block comments. Other registered source formats use Pygments
lexers, with explicit coverage failures for unrecognized syntax. YAML `run`,
`sql` and `query` values, HTML script/style bodies, notebook code cells, and
recognized interpreter-fed shell heredocs and language-tagged Markdown/RST
examples in maintained documentation are routed to
their language checks.

This is a syntax rule, not proof that arbitrary strings have readers or that code
is simple. Dynamic SQL construction, notebook magics, custom template languages,
and unusual shell or Make constructs require module review and adapter work.
An unsupported or malformed source produces a coverage error. Changed files and
completed scopes always reject these errors; report mode exposes inherited
errors elsewhere. Highlighting without an error is not full grammar validation.
Add regression fixtures when extending a language adapter. Never treat an
unrecognized runnable format as successfully checked.
