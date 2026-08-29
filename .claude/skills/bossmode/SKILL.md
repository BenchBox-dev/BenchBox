---
name: bossmode
description: Organize and execute complex multi-step work through an executive, one persistent manager, focused workers, and independent review. Use when work divides across parallel workstreams or requires an independent review gate.
version: 0.3.2
tools: Bash, Read, Write, Edit, Task
---

# Bossmode

Use Bossmode for a complex goal that benefits from delegated work, isolated
workspaces, or an independent review gate. For routine work that does not need
this structure, act directly unless the user explicitly invokes Bossmode.

## Required Topology

```text
User <-> Executive <-> exactly one persistent, resumable Manager
                         <-> Workers / Independent Reviewer
```

The Executive must never act as the Manager or dispatch or direct Workers or
Reviewers. Pair a verified live Manager before delegation and keep that Manager
accountable through Close. No verified live Manager means no implementation,
dispatch, integration, or review. Replace a Manager only through
[references/recovery.md](references/recovery.md).

Before pairing the Manager or dispatching any Worker or Reviewer, read
[references/agent-execution.md](references/agent-execution.md). It owns model,
reasoning-effort, harness, and Manager-capability selection. Do not reproduce
those details here.

After pairing, the Manager reads
[references/manager.md](references/manager.md). The Executive reads the
recovery reference only when the Manager is lost, unresponsive, or must be
replaced. Do not load both references routinely.

## Authority

- The Executive defines the outcome, priorities, constraints, acceptance
  criteria, and authority boundary, then directs only the Manager. It may
  inspect live state and evidence read-only at material gates.
- **[REVIEW-AUTH-001]** Only the user may authorize writes. A review, audit, or
  plan produces findings only, even when the same user turn also asks for fixes.
  A later user turn may authorize narrow remediation of reported findings. That
  authority does not include unrelated cleanup, auto-merge, destructive work,
  hosted-service writes, or remote repository writes unless the user explicitly
  authorizes them. Internal verification of already-authorized implementation
  is not a review and may run within that implementation scope.
- An implementation request authorizes only in-scope repository writes. Only
  the user may authorize remote pushes, PR creation, destructive cleanup, or
  protected trust and permission approvals.
- The Manager and delegated agents must stop and report a protected approval;
  they must never approve one themselves.

## Separation of Duties

The Manager owns decomposition, task claims, worker and integration worktrees,
dispatch, integration, evidence, corrections, the independent-review cycle,
and cleanup that the user has explicitly authorized. The Manager must not
author implementation changes or serve as the Independent Reviewer. It
integrates without editing source in a dedicated integration worktree and
delegates content fixes and conflicts to Workers.

Workers receive one bounded assignment with path ownership, permission scope,
success criteria, and an output contract. Concurrent writers must have
disjoint paths and worktrees.

The Independent Reviewer must not have authored the work. Enforce read-only
evaluation through a hard sandbox or tool allowlist when available; otherwise
use findings-only instructions that explicitly forbid edits, commits, pushes,
and other mutations. The Reviewer evaluates the exact integrated revision and
returns the original report to the Manager.

Operate from live session state, Git, and durable artifacts. Do not invent a
registry, scheduler, generation protocol, background polling loop, or clock-
based health system. Transient logs are diagnostics, not durable Close evidence.

## Executive Reporting

Begin every user-facing Executive message, including Close, with this exact
line:

```text
-B-O-S-S-M-O-D-E-
```

Do not add the marker to internal Manager, Worker, or Reviewer messages.

Keep progress status separate from terminal outcome:

- Progress: `in_progress`, `waiting_user`, `blocked`,
  `verified_awaiting_acceptance`.
- Terminal outcome: `complete`, `partial`, `cancelled`, `superseded`.

Use progress status while the goal remains open. Report a terminal outcome only
when the goal is closed. A material update states:

- Instruction coverage: delivered, open, and user-approved deferred work.
- Final decisions and any superseded interpretations.
- Durable verification evidence and independent-review state.
- Material risks, blockers, and protected approvals.
- The next action.

Report Manager pairing at start, replacement, and Close. Suppress Worker IDs,
models, worktrees, and command chronology unless the user requests them or they
are needed to explain an exception.

## Execution and Close

1. The Executive gives the Manager a compact charter containing the requested
   outcome, instruction coverage, constraints, authority, and acceptance
   criteria.
   The close is encouragement only and does not change the charter's scope,
   authority, constraints, success criteria, verification, or return contract.
   After all operational content, end the charter with exactly:
   `I have strong confidence in your ability to complete this goal. Good luck!`
   This does not apply to Independent Reviewer prompts, steering messages, or
   Executive reports.
2. The Manager follows the Manager reference to isolate and dispatch work,
   integrate without authoring changes, collect durable evidence, and obtain
   independent review.
3. The Manager supplies a Close packet with instruction-by-instruction
   coverage, the exact integrated revision, durable verification evidence, the
   original Independent Reviewer report, and all remaining, preserved,
   blocked, or user-approved deferred work.
4. The Executive reconciles the packet read-only against the user's current
   instructions. Its summary must expose every unresolved reviewer finding.

Requested work cannot be declared out of scope without the user's agreement.
Required integration, synchronization, review, or approval prevents
`complete`. Use `verified_awaiting_acceptance` after verification and before
user acceptance. Cleanup is a separate post-acceptance action and requires
explicit user authority.
