"""Aggregate the fail-closed Results Explorer browser gate policy."""

from __future__ import annotations

import os


def evaluate_gate(changes_result: str, chromium_result: str, needed: str) -> tuple[bool, str]:
    """Return whether the required browser gate may pass and why."""
    if changes_result != "success":
        return False, f"explorer-changes did not succeed ({changes_result}); refusing to pass the gate."

    if chromium_result == "success":
        return True, "Chromium suite passed."

    if chromium_result == "skipped" and needed == "false":
        return True, "No explorer-relevant changes; Chromium suite not required."

    if chromium_result == "skipped":
        return False, f"Chromium was skipped with invalid needed={needed!r}; refusing to pass the gate."

    return False, f"Chromium suite result was {chromium_result!r}."


def main() -> int:
    changes_result = os.environ.get("CHANGES_RESULT", "")
    chromium_result = os.environ.get("CHROMIUM_RESULT", "")
    needed = os.environ.get("NEEDED", "")
    print(f"explorer-changes: {changes_result} (needed={needed or 'unset'})")
    print(f"chromium:         {chromium_result}")

    passes, message = evaluate_gate(changes_result, chromium_result, needed)
    if passes:
        print(message)
        return 0

    print(f"::error::{message}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
