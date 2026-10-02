# Comments and docstrings

Maintained first-party code has no explanatory comments or docstrings. When the
check fails, delete the text and clarify the code: simplify it, or improve names
and types. A useful public contract goes in the canonical API reference. Keep
design rationale outside source only when future work needs the reason. Do not
move removed prose into inert strings, fake metadata or runtime `__doc__`
assignments. A help string or protocol record needs an actual reader.

## Commands

- `make comment-policy-check` compares against `origin/develop`, then runs the
  native parser regressions. While enforcement is advisory it lists new
  violations without failing; once enforcement is blocking it rejects them. Set `BASE_REF` to an immutable
  commit SHA to reproduce a CI comparison.
- `make comment-policy-strict` checks the whole inventory. It fails until
  cleanup is complete.
- `make comment-policy-report` lists remaining violations without rejecting
  legacy debt. Configuration and parser setup failures still fail.
- The pre-commit hook checks staged content, with the same advisory or blocking
  result as the check target.
- `scripts/check_comment_policy.py --path` checks one file or directory prefix.

The check target and hook need Python, `uv`, Node and npm. Without `BASE_REF`,
if `origin/develop` is not an ancestor of `HEAD`, a local run uses their merge
base; an explicit or CI base must be an ancestor. Native tests run only after
the source check passes, so they cannot replace the checker, but they can still
fail the command.

## Enforcement

`quality/comment-policy.json` sets `enforcement` to `advisory` or `blocking`. A
comparison against a base (the check target, the hook and CI) reads the mode
from the base policy. While it is `advisory`, the check prints every new
violation, and in CI marks each as a warning on the changed line, but exits
successfully, so a pull request is never blocked for a comment. Parser and
configuration failures still fail in both modes, and `comment-policy-strict` and
`comment-policy-report` ignore the mode.

Moving from `advisory` to `blocking` is a one-line change to the policy. It is
checked against the base policy, so that change is not blocked by itself, and
the next pull request is. A policy cannot be moved back from `blocking` to
`advisory`. Flip it after the open pull requests have merged or been cleaned,
so that no one meets the new rule on a branch that was started before it
existed.

## Exceptions

`quality/comment-policy.json` lists exceptions. Each names the file, qualified
symbol or payload, complete text, actual consumer, necessity, smaller
alternative considered, owner and removal condition; suppressions need an
unexpired `expires` date. Line numbers are not identities. An entry permits one
occurrence unless an approved positive `count` says otherwise. Three kinds:

- **Directive:** a whole registered token, such as `# noqa: E501`, with no
  explanatory text.
- **Notice:** exact required text, with its governing source as consumer.
- **Fixture:** exact parser input that a named test consumes.

A first-line shebang needs no entry; an encoding cookie is accepted only in the
first two lines for a non-UTF-8 Python encoding. The check target, hook and CI
use the base policy, so add an exception in an earlier change than the source
it permits. Review its real need and reader first; syntax checks cannot. Remove
unused exceptions during module review. The one current fixture lets a test run
Makefile-derived conditions to prove a broken gate still runs the guard. It
grants no comment text, and changing its consumer code invalidates it (the AST
digest ignores only empty type-parameter lists, so Python versions agree).

## Scopes and comparison

The checker compares a multiset of exact file, kind, symbol and text
identities. Deleting an unrelated comment does not pay for a new one; adding a
copy, changing text or moving prose to another symbol fails. No archive of
removed prose is kept. Base comparisons inspect changed files and completed
scopes; report and strict modes inspect everything.

- Add a cleaned file or directory prefix to `completed`. Every violation there
  then fails, including inherited ones. Completed scopes cannot be removed.
- External exclusions name upstream owners and provenance files. A candidate
  policy cannot expand them or overlap them with completed scopes, and new
  files under them are not exempt in a base comparison.
- Generated first-party code and `_sources/compilation` scripts are included;
  TPC templates and catalog-owned skill mirrors have separate provenance.
- The 90% docstring gate stays until useful API contracts move and a
  replacement is approved. Existing module docstrings are transition debt, not
  an endorsement.

## CI trust model

The `comment-policy` job runs on every pull request and merge group and feeds
the required tooling result. While enforcement is advisory its only failures
are parser and configuration failures. Its base SHA comes from the platform event and
cannot be overridden. The launcher, checker, adapters and hash-pinned parser
dependency specifications come from that immutable base. For a pull request,
the comparison is against the first parent of the merge commit CI checks out,
which is the target branch tip, so changes that reached the target after the
event are not charged to the pull request. A merge group keeps the event base. The checker runs
isolated from project configuration, import and installer overrides, candidate
`node_modules` and candidate Python environments. The candidate's own checker is used only to bootstrap a
base that contains the rollout commit `ed5c263c513ba65499f4918d3a7de607f280c65b`
and holds no trusted checker files, launcher or policy registry; on any other
base, a missing checker fails. `.github/soundness-paths.txt` and
`.github/CODEOWNERS` protect these files, and changes to this wiring need the
repository's independent soundness review.

## Coverage and limits

Python is read with its AST and tokenizer, including standalone strings and
runtime docstring assignments; JavaScript and TypeScript with the isolated
TypeScript parser; SQL-valued strings and execution-sink arguments as SQL; other
formats with Pygments lexers; embedded code with its own language check.
Unknown input is a coverage error, never a pass, and changed files and
completed scopes always reject it. Parsers are used because text search would
confuse strings with comments, and Ruff has no cross-language ban.

This syntax rule cannot prove a string has a reader or that code is simple.
Dynamic SQL, notebook magics, custom template languages and unusual shell or
Make constructs need review and adapter work. Details are in
`scripts/comment_syntax.py`, `comment_payloads.py` and `comment_execution.py`;
add a regression fixture to `tests/unit/scripts/test_comment_policy.py` when
extending an adapter.
