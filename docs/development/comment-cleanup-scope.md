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
dependency changes. The policy, validator, focused test, dispatch page, and
index link are a singleton scope-policy slice. The pre-change base proves the
starting tree; run a second immutable snapshot after that slice is committed so
those artifacts receive the same ownership check before dispatch.

## Evidence rules

An ignored local task-set file freezes the live task IDs used by this run. The
validator rejects any owner outside that set, without querying the tracker at
runtime. A notice records the immutable blob SHA-256, retained byte range,
retained-byte SHA-256, source identity, governing requirement, owner, and
blocking disposition. Do not replace a notice with a blanket SPDX label.

The validator checks each notice against the blob at the comparison base, so a
notice entry must stay true on every later base. Record a notice here only for
a file that changes rarely and whose exact bytes must be protected, such as a
licence, EULA or vendor patch record. Notice comments in maintained source are
registered individually in `quality/comment-policy.json` with their exact text,
consumer and necessity; a source edit must not invalidate trusted ownership for
later pull requests.

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

## Delivery on one integration branch

All remaining cleanup stays on one isolated integration branch until the whole
scope is complete and validated. One final pull request targets `develop`.
Foundation corrections, soundness paths, payload changes, the exception register
and blocking enforcement belong to that same pull request. Local chunks make
integration and review manageable; they do not create separate delivery units.

### Tracker lifecycle

The repository owner's exception to registered-batch delivery keeps the ordinary
serial tracker lifecycle. No schema migration or registered-batch cutover is
required. Record an immutable starting commit, an ordered task set and frozen
ownership before work. One integrator writes tracked files on the shared branch.
A task's validated local work may order dependent implementation, but the task
finishes only after the final pull request merges. Preserve claim ownership;
release an owned claim with notes identifying the work and evidence.

### Ownership and parallel work

Refresh live source, tracker requirements and open pull requests. Record conflicts
and their owners; reconcile them before final delivery rather than excluding
required files from the effort. Run the scope validator against a recorded
commit and task set, and keep its resolved manifest ignored under `.todo-batch/`.
Unknown paths, ambiguous ownership and unmigrated consumers block deletion.

Use a linked worktree and `make agent-write-preflight`. The integrator alone
edits tracked files. Parallel workers inspect bounded paths and write only
ignored proposals or review reports. They do not change Git configuration,
tracker state or the shared test lock. The integrator applies proposals in
consumer-before-producer order and serializes shared tests.

### Checks for each local chunk

Migrate readers before removing their source prose. Record separate evidence for
intentional behavior changes and pure deletion. Each chunk requires:

- deletion parity against an exact recorded base and path set;
- strict comment-policy checks for its owned paths, with retained text registered;
- ownership checks and evidence that every affected reader is migrated;
- applicable Ruff, formatting and compilation checks;
- bounded module and consumer tests under the shared test lock.

A mixed branch cannot pass as a deletion-only change. Review its reader, checker,
policy and payload changes separately. Preserve raw SQL/output identity unless
an intentional change has the required hash, token, order, parameter, hint and
applicable correctness, plan and timing evidence.

### Whole-scope acceptance and publication

Finish and measure the pilot before broad deletion. Use its authoring and review
cost to choose local chunk sizes and review budgets. A failing chunk is repaired;
required scope is not dropped to obtain a passing result.

Before publication, require zero unapproved prose and zero unresolved executable
coverage gaps across the complete scope. Reconcile retained notices/directives,
generators, contracts and decision records. Validate report, strict, staged,
transition and workflow behavior. Complete final-enforcement and register evidence
before setting the candidate policy to blocking; include strict CI wiring in the
same pull request. Advisory-base acceptance and post-merge blocking are separate
checks.

Assess open pull requests for enforcement impact. Give the repository owner the
impact list and any notification text; an authorized operator sends notifications
before activation. Tracker text alone does not authorize messages. Prove rejection
of an injected prohibited comment and acceptance of an unchanged clean candidate
with isolated tests of the actual workflow path. After merge, verify the fresh
trusted base and collect hosted enforcement evidence from the next legitimate
pull request. Do not create an extra probe pull request.

Reconcile current `develop` before final readiness and rebase when needed. Refresh
affected evidence after base or head changes. Enumerate every changed path with
Git; capped hosted file lists cannot establish complete review coverage.

Review the exact final head, resolve required findings and all Critical/High
findings, obtain the required independent Soundness review, and run canonical
preflight after content settles. Open one final pull request. Its durable
explanation describes the resulting behavior, preserved contracts, intentional
changes and validation. Detailed task and comparison receipts stay in local
evidence or the tracker.

Follow the active landing policy and exact-head hosted checks. Soundness changes
currently require the repository owner's manual merge; do not bypass that action.
After actual merge, verify the merged tree and trusted blocking enforcement,
then finish tasks in dependency order. Local checks and pilot results do not
certify UAT, deployment or production use.
