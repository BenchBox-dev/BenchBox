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
`importlib.import_module` and `patch` targets. The root package facade gives no
evidence. A test with no reference, mixed owners, an unowned module, or a source
that does not parse keeps the owner of its directory rule. A rule or exact path
with a higher priority is never overridden, and an ownership collision stays a
finding. A notice path belongs to its notice owner unless another rule names a
different owner, which is a finding. A payload record names the single region of
a file that an earlier task may edit; the file's rule still names the later
owner.

The validator also scans every tracked Python source at the base for docstring
carriers and lists them in the local manifest with the owner of each path. A
carrier is a read of a module or object docstring, a `getdoc`, `getsource` or
`getcomments` call, or a write to `__doc__`. A module docstring passed to a
command-line parser is a reader, so that text must move into an explicit
constant before the docstring is deleted. Every runtime docstring write must
have a payload record for its file, otherwise validation reports it. An exact
path rule that a derived rule could override is invalid.

The scan finds only explicit references. It does not see readers that take a
docstring implicitly, such as Click and FastMCP command decorators, nor
assignments through `vars`, tuple targets, class bodies, `functools.wraps`, or a
variable attribute name. Owners of those modules must inventory them by hand
before deleting a docstring.

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
runtime. An external entry names the exact path, provenance source, governing
requirement, owner, and blocking disposition. A notice records the immutable
blob SHA-256, retained byte range, retained-byte SHA-256, source identity,
governing requirement, owner, and blocking disposition. Do not infer either
from a vendor directory or replace it with a blanket SPDX label.

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
