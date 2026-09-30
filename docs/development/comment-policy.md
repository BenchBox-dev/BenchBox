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
- The pre-commit hook checks staged content. The transition runner needs Python,
  `uv`, Node and npm. It installs a small isolated parser environment from
  reviewed, hash-pinned specifications. `comment-policy-check` also runs the
  native parser regressions.

Source enforcement completes before any candidate native test executes. A
rejection exits without running those tests, so a test cannot replace the
trusted checker or hide source before it is checked. Native test failures still
fail the command after a successful source check.

The CI job runs on every pull request and merge group. The required tooling
result consumes it even when other code lint is skipped. CI takes its base SHA
from the platform event and rejects an override. After the initial rollout, the
launcher, checker and language adapter scripts come from that immutable base
commit. Parser dependency specifications also come from the base: Python wheels
require exact versions and hashes; TypeScript uses a separate npm integrity lock.
The isolated process clears import and installer overrides, ignores project
configuration, and never loads candidate `node_modules` or a candidate Python
environment. Bootstrap is
restricted to the explicitly pinned initial commit; a missing checker elsewhere
fails. Changes to this wiring remain subject to the repository's independent
soundness review.

## Mechanical exceptions

`quality/comment-policy.json` records exact exceptions. An entry identifies the
file, qualified symbol or payload, and complete comment text. It names an actual
consumer file, explains necessity and the smaller alternative considered, and
records an owner and removal condition. Suppressions also need an unexpired
review date. Line numbers are not exception identities. Each entry permits one occurrence
unless an explicit positive `count` has been approved. Extra copies fail.

Only three exception kinds exist:

- **Directive:** the whole token must match a registered grammar. Examples are
  specific `noqa` codes, specific type-ignore codes, formatting and coverage
  directives, ShellCheck codes, TypeScript references, and registered SQL hints.
  Extra explanatory text fails. A matching spelling alone grants no exception.
- **Notice:** retain only the exact required text, with its governing source
  named as the consumer. Do not substitute a shorter notice without checking
  that governing source.
- **Fixture:** exact parser inputs or tokens deliberately consumed by a test. Record
  the test consumer, complete `payload` or consumer AST digest, `finding_kind`,
  and exact token or parser-error `text`; ordinary test explanations do not qualify.

A first-line interpreter shebang is accepted without registry metadata. A
valid encoding cookie is accepted only in the first two lines and only for a
non-UTF-8 Python source encoding. UTF-8 cookies are unnecessary.

New exceptions cannot authorize source in the same change: transition checks
use the base policy. Introduce and review the evidence first, then use the
approved exception in a later change. The initial registry contains one mechanical fixture permission: a test executes
conditions derived from the checked Makefile to prove a broken gate still runs
the guard. Its unresolved program argument is bound to the entire consumer AST
digest. The digest preserves every AST field except empty type-parameter lists
introduced in Python 3.12, so supported Python versions agree. Nonempty type
parameters remain part of the identity. Changing contributing consumer code
invalidates that permission.
It permits no comment or docstring text.
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
name canonical upstream owners and existing provenance files. New files under an
excluded directory do not inherit its exemption in a transition comparison.
Completed and external scopes cannot overlap. Compilation scripts under
`_sources/compilation` are included; TPC templates and catalog-owned skill
mirrors have separate provenance. Generated first-party code is included.

The existing 90% docstring gate remains in force until useful API contracts have
been migrated and its replacement is approved. Existing module docstrings are
transition debt, not an endorsement that they are useful.

## Coverage and limits

Python uses its AST and tokenizer; standalone literal strings and direct runtime
docstring assignment forms are rejected too. SQL strings assigned to SQL-valued names or passed to registered execution
sinks are scanned once, including static portions of f-strings. Ordinary
docstrings are not interpreted as SQL. JavaScript and TypeScript use the isolated TypeScript parser,
protecting strings, regular expressions, template text and JSX text while
examining executable expressions and retaining qualified symbol identities.
Registered process and query sinks route reconstructable strings to their
language adapters; unresolved executable payloads fail coverage. SQL scanning handles quoted values, dollar
strings and nested block comments. Bracket syntax containing comment delimiters
requires an explicit dialect when its meaning is ambiguous. Other registered source formats use Pygments
lexers, with explicit coverage failures for unrecognized syntax. YAML/JSON SQL fields, platform SQL overrides, GitHub Script bodies, shell `run`
values, HTML script/style bodies, notebook code cells, interpreter-fed shell
heredocs, and language-tagged Markdown/RST examples are routed to their language
checks. Shell ASTs identify redirection consumers and supported pipelines.
MyST metadata directives are distinguished from code and nested examples.
Unknown formats in maintained code roots fail coverage; named configuration
files and interpreter scripts are included.

This is a syntax rule, not proof that arbitrary strings have readers or that code
is simple. Direct JavaScript `eval`/`Function`, known Node command-execution imports,
Python `exec`/`eval`/`compile`, and supported subprocess or shell command strings
are routed too. Unknown executable strings produce errors.
Dynamic SQL construction, notebook magics, custom template languages,
and unusual shell or Make constructs require module review and adapter work.
An unsupported or malformed source produces a coverage error. Changed files and
completed scopes always reject these errors; report mode exposes inherited
errors elsewhere. Highlighting without an error is not full grammar validation.
Add regression fixtures when extending a language adapter. Never treat an
unrecognized runnable format as successfully checked.


## Prior art and maintenance

`scripts/check_windows_antipatterns.py` already uses Python AST inspection for a
repository policy. This checker extends that pattern with token inspection.
The hosted soundness job in `.github/workflows/ci.yml` already extracts its
checker from the immutable base; comment enforcement extends that trust model
to parser libraries. `.github/soundness-paths.txt` and `.github/CODEOWNERS`
protect the policy, adapters, launcher and dependency specifications.

The new multiset comparison allows module cleanup to proceed independently
without a permanent archive of deleted prose. A plain text search would confuse
strings with comments; existing Ruff rules do not implement the required
cross-language ban. Native syntax parsers and established lexers supply grammar
handling; custom code routes repository payloads and checks the policy.

When introducing a language, executable carrier, interpreter wrapper, parser
version or new upstream artifact, extend its adapter or reviewed inventory and
add a reproducing regression. Review an exception's actual necessity and reader
before registration. Syntax checks cannot establish those facts themselves.
