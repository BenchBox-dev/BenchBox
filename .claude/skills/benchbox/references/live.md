# Live Platform Test Reference

Run only with explicit approval, credentials, and cost awareness.

## Preflight

- Confirm platform, benchmark, scale, phases, output path, and query subset.
- Check required env vars without printing secrets.
- Prefer dry-run or smoke scale first.
- Normalize cloud output paths and record execution ID/artifacts.

## Output

Command, approval context, redacted environment checks, pass/fail, cost/runtime notes when available, artifacts, cleanup needs, and next local repro if failed.
