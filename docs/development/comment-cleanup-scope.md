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
the totals; the base has 1,093 directive comments and 35 TODO/FIXME comments in
Python sources. Other languages need the grammar-aware checker before they can
be counted.

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
consumer blocks the producer. Scope validation is limited to ownership, evidence,
and dependency data. The checker owns deletion comparison, syntax and parser
coverage, directive grammar, and strict/report enforcement. Shared tooling owns
public command and CI wiring.

Do not change TPC-DS stream ordering, RNG, timing, missing-count behavior, query
algorithms, or payload identity under this policy. Do not rewrite historical
results. Preserve useful nonempty query references, and record unsupported
assurance as a blocker rather than adding inert replacement prose.
