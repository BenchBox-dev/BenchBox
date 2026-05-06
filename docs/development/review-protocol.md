# Review Protocol

The contract for review-shaped actions: code reviews, audits, research,
compare, to-spec, security reviews, and any L2 blind-spot audit performed
within them. Wrappers (skills, slash commands, AGENTS.md, CLAUDE.md, and
GEMINI.md files) reference this file rather than restating its rules. **If
a wrapper appears to conflict with this file, this file wins.**

---

## Section 1 - Scope of authorization

Review-shaped actions are **read-only plus local capture**. They MAY:

- Read code, run analyses, produce findings, render output in chat.
- Write *capture files* to the project's designated locations (TODOs,
  blind-spots, audits, decisions, handoffs).

They MUST NOT, as a side-effect of the review:

- Commit any file, including the capture file.
- Push to a remote.
- Run `make pr-open`, `gh pr create`, or any PR-creation command.
- Enable `--auto` merge on any PR.
- Chain into a write-shaped skill action (`/code commit`, `/code fix`,
  `/pr`, etc.) without explicit user authorization in a separate turn.

A review's authorization is to **produce findings**. Landing changes -
including landing the capture files themselves to `develop` - requires
the user to authorize remediation in a separate turn. "Authorization"
means a direct user instruction in *this* conversation, not an inference
from a previous standing rule or an earlier turn's blanket approval.

This rule fires *before* any "auto-commit" or "file-first capture"
mandate elsewhere. Conflicts resolve in favor of this section.

---

## Section 2 - Defect gate

A finding that **materially affects correctness, performance, or
security** of the code under review is a **defect**, not a blind spot.
Apply this gate before classifying any finding:

> *If this finding is left as-is, will the code under review behave
> incorrectly, leak data, or miss its performance budget?*

Apply the gate to the **instance you actually observed**, not to a
hypothetical sibling case.

If yes - defect. Defects belong in:

- The severity table / action items of the review (Critical or
  Required), **and**
- A TODO with an owner if the user authorizes follow-up, or an inline
  fix if the review is touching that code, or an explicit escalation
  to the user.

Defects do **not** belong in any blind-spot directory, under any
`finding_kind`. The kinds `bug-class`, `assumption`, and `scope-creep`
are **not loopholes**:

- `bug-class` requires that the symptom **has already landed a fix** on
  this branch (or in a referenced commit). An unfixed defect is never
  a `bug-class` finding.
- `scope-creep` is for work that wasn't requested but might be
  load-bearing for *future* changes. Not for incomplete work whose
  absence breaks the current branch.
- `assumption` is for things true at audit time that might decay. Not
  for assumptions already known false in the code under review.

If unsure whether a finding is a defect or a framework gap, **assume
defect** and file a TODO. Over-capturing as TODOs is recoverable
(close-as-wontfix is cheap); over-capturing as blind spots is not (the
directory loses its signal).

---

## Section 3 - L2 audit scope

The Layer 2 question from `SHARED/plan-deepening-framework`:

> *What class of issue does my framework fail to catch for this type
> of change/bug/decision?*

L2 surfaces **what the framework didn't ask you to look at**. The
output of L2 is a list of *dimensions the framework missed*, not a
list of *defects the framework caught*.

Therefore:

- Anything already in your severity table is, by definition, something
  the framework *did* catch. It stays in the severity table and feeds
  action items. It does not get "abstracted up" into a class
  observation and relocated to a blind-spot file.
- Critical and Required findings remain in action items. The L2 step
  is allowed to *also* point at a class of the same defect (with a
  `Recorded:` chat pointer to the captured file), but the instance
  must still be owned in action items. L2 without an instance-level
  owner for any defect-shaped finding is protocol drift.
- If L2 surfaces a *new concrete defect* (not a framework gap), file
  it as a Required action item. Do not route it to blind-spots.

---

## Section 4 - Capture is local-only

When this protocol authorizes a write (to a TODO, a blind-spot
directory, an audits folder, a handoff file), the file lives on the
local branch in the worktree. The disk-write authorizes the file
creation and **nothing else**. Specifically, it does not authorize:

- Committing any file, including the capture file.
- A push.
- `make pr-open` or any PR-creation command.
- Enabling auto-merge.

The agent's terminal action is to **surface the capture in chat with
a `Recorded: <path>` line** and stop. The user decides whether to PR.
This applies whether the capture happened during `/code review`, via
the `/blind-spot` slash command, or as a side-effect of any other
review-shaped action.

---

## Section 5 - Project bindings

A project that adopts this protocol provides:

- A storage location for blind spots (e.g., `_project/blind-spots/`).
- A storage spec defining frontmatter, file naming, validation -
  typically a `README.md` in that directory.
- A sweep workflow (e.g., `make blind-spots-{list,report,sweep}`).

See the project's agent instructions and the blind-spot directory's
`README.md` for project-specific bindings. **This file governs
*behavior*; the project README governs *storage*.** The two should
never restate each other; if you find duplicated rules, the
behavior-side belongs here.
