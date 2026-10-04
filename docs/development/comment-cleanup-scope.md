# Comment cleanup scope policy

The scope policy freezes ownership before comment cleanup begins. It does not scan
comment syntax, decide whether a deletion is safe, or replace the checker.
Those remain separate prerequisites.

## Policy and evidence

`quality/comment-cleanup-scope.json` holds reusable classifications:

- maintained roots and file classes;
- prioritized ownership rules and explicit shared overrides;
- external, notice, directive, and TODO/FIXME evidence requirements;
- known runtime and source-text carriers;
- consumer-to-producer dependencies; and
- the accepted, narrowed, or rebutted dispositions for R1 through R18.

Rules classify a path as `ready` or `blocked`. A blocked entry has an owner and
specific disposition. An unclassified maintained path is reported as blocked
without an owner and fails validation. A same-priority ownership collision also
remains in the local manifest with every competing rule and owner, then fails.
When roots overlap, the most specific selector wins; equal-specificity roots are
invalid. An unclassified path is not an external exclusion.

A derived rule assigns a Python test to a module owner only when every
`benchbox` module it references belongs to that one owner. References are static
imports and string literals that are entirely a dotted module name, such as
`importlib.import_module` and `patch` targets. A reference through the root
package facade, such as `from benchbox import Name`, cannot be traced to one
module, so the test keeps the owner of its directory rule. So does a test with
no reference, mixed owners, an unowned module, or a source that does not parse. A rule or exact path
with a higher priority is never overridden, and an ownership collision stays a
finding. A notice path belongs to its notice owner unless another rule names a
different owner, which is a finding. A payload record names the single region of
a file that an earlier task may edit; the file's rule still names the later
owner.

The validator also scans every tracked Python source at the base for docstring
carriers and lists them in the local manifest with the owner of each path. A
carrier is a read of a module or object docstring, a `getdoc`, `getsource`,
`getcomments` or `cleandoc` call, a write to `__doc__`, or a function with a
docstring under a Click or FastMCP `command`, `group`, `tool`, `resource` or
`prompt` decorator that sets no `help` or `description`, since the framework
reads the docstring as help text. A module docstring passed to a
command-line parser is a reader, so that text must move into an explicit
constant before the docstring is deleted. Every runtime docstring write must
have a payload record for its file whose carrier names the written object,
otherwise validation reports it. An exact
path rule that a derived rule could override is invalid.

The scan finds only references it can name. It does not see assignments through
`vars`, tuple targets, class bodies, `functools.wraps`, or a variable attribute
name, and the decorator check is a name heuristic. Owners of those modules must
inventory such cases by hand before deleting a docstring.

The directive and TODO/FIXME registers are incomplete. A directive or TODO/FIXME
that is not registered keeps its text: no task may delete it until it is
registered with its consumer, necessity and owner, or an existing tracker item.
The validator counts the Python comments that are not yet registered and prints
the totals; the base has about 1,100 directive comments, and every TODO/FIXME
marker is registered. A TODO/FIXME marker is a comment that starts with the
word, or has it after `#`, `;` or two spaces followed by a colon, such as
`# TODO: link the issue` or `# noqa: E501  TODO: later`. A comment that only
mentions the word in prose, such as "see the renderer TODO", is an ordinary
comment that its owner removes with the rest, and the same goes for a mention
that is part of a sentence. Other languages need the grammar-aware checker
before they can be counted.

The policy does not create a permanent path ledger. Before dispatch, run the
validator against the immutable source commit and write the resolved manifest to
an ignored local path:

```console
uv run -- python scripts/check_comment_cleanup_scope.py \
  --base <40-character-commit> \
  --task-set .todo-batch/comment-cleanup-task-set.txt \
  --output .todo-batch/comment-cleanup-scope-<commit>.json
```

The output includes every classified maintained path, its owner, state, rule,
and blocking disposition with a digest. Freeze that ignored output before
parallel work. Run it again after integration and allow only authorized path or
dependency changes. The policy, validator, focused test, dispatch page, index
link, and the one development-loop ledger row that lists the test are a
singleton scope-policy slice. The pre-change base proves the
starting tree; run a second immutable snapshot after that slice is committed so
those artifacts receive the same ownership check before dispatch.

## Evidence rules

An ignored local task-set file freezes the live task IDs used by this run. The
validator rejects any owner outside that set, without querying the tracker at
runtime. A notice records the immutable blob SHA-256, retained byte range,
retained-byte SHA-256, source identity, governing requirement, owner, and
blocking disposition. Do not replace a notice with a blanket SPDX label.

An external entry excludes a path or directory prefix that another party owns.
It records the selector, provenance, the governing owner decision, the owner,
and the disposition, and its selector must match a tracked path. It applies only
to paths that no ownership rule, notice, or derived rule claims, and it marks
them `excluded`. The TPC vendor trees are excluded this way as a whole, including
the BenchBox patches inside them; the retained-notice rule still protects the
exact bytes of their licence, notice, and patch records.

A format class marks files `comment-free` when a verifier finds no comment
syntax. The checks are deliberately conservative: a file that fails stays
unowned, and ambiguity counts as failure.

- `strict-json`: the file, or each line of a JSON-lines file, parses as JSON with
  no duplicate keys, no `NaN` or `Infinity`, and no `comment`, `_comment`,
  `__comment`, `$comment` or `//` key.
- `png-signature`: the file starts with the PNG signature. It does not validate
  the image or its metadata chunks.
- `markdown-prose`: no code fence (also inside quotes and lists), indented line,
  `<pre>`, `<code>`, `<script>` or `<style>` tag, HTML, MDX, MyST, Liquid or
  Jinja comment marker, link reference definition (any label, because its title
  can hold hidden text), or commented front matter. Footnote definitions and
  inline links are allowed.
- `sql-without-comment-markers`: no `--`, `/*` or `#` anywhere in the file.
- `empty-file`: the file has zero bytes, such as a `.gitkeep` placeholder.

A class applies only to unclaimed paths under its selectors with a listed
extension. A file with no suffix, such as `.gitkeep`, matches by its whole name.
The final-enforcement task owns the comment-free files and confirms that none
gained comments.

A class with `"state": "blocked"` does the opposite: it hands a file that no
verifier can clear to a named owner, with a specific disposition, instead of
leaving it unowned. It must use `markdown-needs-review` (the Markdown file fails
`markdown-prose`) or `any-content` (every file with a listed extension under the
selectors). A comment-free class must use a verifier that proves cleanliness, and
a blocked class must not, so a blocked class can never mark a file clean. List
the clean classes first, because a class claims only paths that earlier classes
left unowned. Owners of a blocked class decide by provenance whether each file is
maintained, frozen evidence or an external source before any edit.

A directive records its exact token, the number of occurrences in the file, its
actual consumer, necessity, smaller alternative considered, owner, and removal
trigger. A TODO or FIXME records its path, token, owner, blocking disposition,
and an existing tracker reference or approved destination. The validator
requires the token to appear in the file at the base, and the directive count to
match it. A directive or obligation owner that differs from the owner of its
path is reported. Deletion alone does not satisfy the obligation.

Known runtime and source-text carriers are recorded only with source proof. New
or unresolved carriers stay blocked until their owner establishes the necessary
reader, producer, and behavior evidence. This policy does not claim parser,
syntax, safe-deletion, strict/report, raw-payload parity, or algorithmic
assurance.

## Dispatch boundaries

Consumer migration precedes deletion of its producer. An edge with a blocked
consumer blocks the producer.

The committed edges cover two kinds of reader, each traced to its source. Three
production readers (`benchbox/core/query_catalog.py`, `benchbox/core/dryrun.py`
and `benchbox/mcp/tools/benchmark.py`) return `inspect.getsource` of the
registered DataFrame implementations, so each of the 38 files that define them
(resolved from the live registry) is a producer for all three. Three tests
assert that specific docstring text is present. Sphinx autodoc renders the
docstring of every object named by an `auto*` directive in `docs/`, so each
defining file, found by importing the object and calling `inspect.getsourcefile`,
is a producer for the page that names it. A test that only asserts absence or a
code token cannot be broken by deleting a comment, so it is not an edge. The
list is not exhaustive: Click and FastMCP help read a docstring in the same
file, which an edge cannot express, and readers reached through dynamic names
are still the owners' to inventory. Scope validation is limited to ownership, evidence,
and dependency data. The checker owns deletion comparison, syntax and parser
coverage, directive grammar, and strict/report enforcement. Shared tooling owns
public command and CI wiring.

Do not change TPC-DS stream ordering, RNG, timing, missing-count behavior, query
algorithms, or payload identity under this policy. Do not rewrite historical
results. Preserve useful nonempty query references, and record unsupported
assurance as a blocker rather than adding inert replacement prose.

## Delivery by integration branch

Module cleanup lands through a small number of integration branches, not one
pull request per task. An integration branch is cut from `develop`, has one
integrator, carries a fixed set of module tasks (its members), and lands as one
pull request into `develop`. Members own disjoint paths because the scope policy
gives each path exactly one owner. A branch lives about two working days, because
`develop` merges about eighteen pull requests a day and a long-lived branch would
always conflict with someone's open work. Foundation work, soundness-path files,
payload changes, the exception register and the switch to blocking enforcement
land as their own pull requests.

### An exception to the delivery-mode rule

This is a deliberate exception, approved by the repository owner on 2026-10-02,
to the delivery-mode rule in `AGENTS.md`. That rule reserves a shared
integration branch with one final pull request for the tracker's
registered-batch capability, and says to stay in serial mode, with one pull
request per task, while the capability is absent. The program cannot use the
capability today: its first use is a one-way schema migration that every client
of the tracker must be stopped or upgraded for, the final pull request head can
be bound only once so a single review fix would abort a branch, and a batch
cannot be refreshed from `develop`. Serial mode with a pull request per task
would mean over a hundred pull requests and as many reviews, which is the cost
this contract avoids.

The exception keeps what the rule is for. The cut commit, an explicit ordered
member list and frozen member scopes are recorded before work starts. One
integrator alone writes the branch. Each member's check evidence is listed in
the pull request. One final pull request goes through required CI, current-head
review and auto-merge, followed by post-merge trunk validation; there is never
a ready feature-base pull request, a skipped check, or a
bypass of review, merge or authority controls. The tracker lifecycle stays
serial: a member task is taken, worked on the integration branch, released with a
note naming the commit that carries its work, and finished only after the
integration pull request has merged. If the registered-batch capability is
installed later, the program can move to it; nothing here depends on that.

### Cutting a branch

1. Read live `develop`. List the files that every open pull request changes and
   leave out of the branch any file another open pull request touches; those
   files wait for the final sweep.
2. Run the scope validator at the cut commit. It must report no findings; fix
   ownership first, through the one writer of the scope policy.
3. Create a linked worktree with `make worktree-create` and run
   `make agent-write-preflight`. Record the member list, the cut commit and the
   excluded files in the ignored ledger under `.todo-batch/`.

### Members

Each member is taken by one worker in its own worktree, branched from the
integration head. A member makes only deletions and the reader migrations that
its task requires, with the reader migrations committed first. Before handing the
commits to the integrator, run, without the shared test lock:

- the parity comparator over the changed files, which allows only removed
  comments, removed leading docstrings and `pass` for a body left empty;
- `scripts/check_comment_policy.py --mode strict --path <prefix>` for each owned
  prefix, where only registered directives and notices may remain;
- a check that the changed files are a subset of the member's owned paths;
- a check that no deleted docstring has a reader that is not migrated in the same
  member or an earlier one;
- `ruff check`, `ruff format --check` and `compileall` on the changed files;
- the member's own tests and the consumer tests its edges name, once, under the
  shared lock and bounded to those tests.

### Integrating and landing

Only the integrator writes the integration branch, by cherry-picking member
commits in dependency order. It reruns the parity and ownership checks over the
whole branch and one full local preflight on the head; when the preflight cannot
finish in the available time, hosted CI is the gate, and the pull request says so.
The pull request is opened as a draft. Its body lists the areas cleaned, the
parity totals, every change that is not a pure deletion with file and line, the
contracts moved and where, the files left out because of open pull requests, and
the checker's summary line.

Before the pull request is marked ready, run one external read-only review over
the non-deletion diff, a sample of the deleted hunks and every public API file,
and fix what it finds. Then mark it ready and arm its exact head after required
CI and the current-head connector review are green and all threads are resolved.
If a review finding arrives after arming, withdraw auto-merge before editing,
fix it, push with an exact lease, wait for fresh CI and connector review, resolve
the threads and arm the new head.

The branch stays current by rebasing onto `develop`, never merging `develop` in,
when the pull request conflicts and once more before it is marked ready. A branch
never edits a file that an open pull request touches at cut time, and it does not
push to or comment on other people's pull requests.

### What stays out of an integration branch

- **Soundness-manifest paths.** Files that the repository's soundness predicate
  flags are carved out into their own pull requests. Each needs the required
  `oracle-review` check to pass on the current head and all review threads to be
  resolved before arming; the PR-body attestation and manual owner merge are
  retired. Keeping these files out makes each result-affecting change separately
  reviewable.
- **Payload changes.** A change to SQL text, generated output or an identity needs
  its own disclosed pull request with raw-hash, token, order, parameter and hint
  evidence and the correctness, plan and timing evidence the task requires.
- **The exception register and the switch to blocking.** The checker starts in
  advisory mode and reports without failing pull requests. The register of
  retained directives, notices and fixtures lands after the module work, and the
  setting moves to blocking only after a final whole-scope scan is clean.

### Sizing and failure handling

The first branch is a pilot that measures authoring time, parity failures, missed
readers, review findings and CI attempts, and sets the size limit for the rest.
Until it does, plan for about four hundred files and twenty thousand deleted lines
per branch, and at most about one thousand changed lines that are not deletions.

| Event | Action |
| --- | --- |
| A member fails parity or its tests | Fix it on the member branch, or drop it and rebuild the integration branch from the cut commit with the other members. |
| Branch CI fails because of one member | Fix or drop that member; do not hold the others. |
| The pull request conflicts with `develop` | Rebase, rerun parity, push with an exact lease. |
| A regression is found after merge | Revert the squash commit, or fix forward if one file is the cause. |
| The branch is abandoned | Close the pull request. Members keep their notes and are taken again later; nothing in the tracker needs undoing, because tasks finish only after merge. |
