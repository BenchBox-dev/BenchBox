# PR review evidence contract

A review that closes on a collective premise ("each X has property P",
"all instances fixed", "no downstream impact") must re-derive the premise
instance by instance from the source of truth. Reading the author's claim
text inherits the author's framing and checks the aggregate; the SCD2 N2
miss (three review passes accepted "each op backstops existence", false for
`merge_scd_type2_no_change`) is the standing counterexample.

## Rules

1. **Mechanical enumeration over rereading.** List every member first with one
   query or grep per member (one pytest node per op, one SQL check per table,
   one consumer per producer). The enumeration itself is review evidence.
2. **Successful and rejected case per instance.** For each member, show the
   intended behavior passing and a negative control failing: delete the
   guarded rows, tamper the digest, advance the ref, replay the incident
   fixture. A member with only a passing case is unverified.
3. **Producer-to-persistence-to-consumer trace.** For each accepted defect
   class, name the producer that writes the evidence, the persistence that
   holds it, and every downstream consumer that reads it; exercise the seam
   with the smallest integration fixture covering it.
4. **Exact identities, not counts.** Record test node IDs, query IDs, SHAs,
   and control outcomes. A high test count, a static wording check, or zero
   open threads is not an integrated outcome.
5. **Vacuous-success guard.** Any check that passes on an empty or deleted
   input must be paired with a positive companion that fails on that input;
   the pairing is proven by removing the guarded content in an isolated
   fixture and observing old-pass plus companion-fail.

## Records

Per-remediation records live in `_project/audits/remediation-contract-evidence.md`:
enumerated instances, node IDs, control outcomes, and the seam trace.
