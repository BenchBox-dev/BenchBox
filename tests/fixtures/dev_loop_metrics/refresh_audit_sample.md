# Exact-refresh eligibility audit (sample)

Sample audit for validator tests. Window and identities reconcile with
`lifecycle_sample.json`.

```json
{
  "schema": "refresh_audit_v1",
  "window_start": "2026-08-11T00:00:00+00:00",
  "window_end": "2026-09-08T00:00:00+00:00",
  "denominator_prs": [101, 102],
  "observations": [
    {
      "pr": 101,
      "head_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
      "run_id": 11,
      "attempt": 1,
      "verdict": "full_required",
      "reason": "prior_check_not_success"
    },
    {
      "pr": 101,
      "head_sha": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      "run_id": 12,
      "attempt": 1,
      "verdict": "shadow_eligible",
      "reason": "not_synchronize"
    }
  ],
  "reason_counts": {
    "prior_check_not_success": 1,
    "prior_check_unbound": 0,
    "not_synchronize": 1
  },
  "timing_only_share": 1.0,
  "missing": [
    {
      "pr": 102,
      "head_sha": "cccccccccccccccccccccccccccccccccccccccc",
      "status": "missing-artifact"
    }
  ]
}
```
