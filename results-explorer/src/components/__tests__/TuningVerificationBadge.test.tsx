import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import {
  TuningVerificationBadge,
  tuningVerificationLabel,
} from "@/components/TuningVerificationBadge";

describe("TuningVerificationBadge", () => {
  it("maps each ADR-1 verified-state to a distinct label", () => {
    expect(tuningVerificationLabel("applied_verified")).toBe("Verified");
    expect(tuningVerificationLabel("applied_unverified")).toBe("Applied; no live-database check recorded");
    expect(tuningVerificationLabel("noop")).toBe("Nothing applied");
    expect(tuningVerificationLabel("not_applicable")).toBe("Not applicable");
    expect(tuningVerificationLabel("failed")).toBe("Failed");
  });

  it("treats null / unknown states as not-recorded, never as verified", () => {
    expect(tuningVerificationLabel(null)).toBe("Not recorded");
    expect(tuningVerificationLabel(undefined)).toBe("Not recorded");
    expect(tuningVerificationLabel("")).toBe("Not recorded");
    // An unrecognized future status must not silently read as verified.
    expect(tuningVerificationLabel("some_new_status")).toBe("Not recorded");
  });

  it("renders applied_verified with an introspection-corroboration tooltip", () => {
    render(<TuningVerificationBadge status="applied_verified" />);
    const badge = screen.getByText("Verified");
    expect(badge.getAttribute("title") ?? "").toContain("checked the live database");
  });

  it("labels applied_unverified with a failed check as checked but not corroborated, with counts", () => {
    const receipt = JSON.stringify({
      corroborated: false,
      summary: { corroborated: 1, mismatch: 2, unverifiable: 3, gate_relevant_total: 6 },
      entries: [],
    });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe(
      "Checked; not corroborated (2 mismatches, 3 unverifiable)",
    );
    render(<TuningVerificationBadge status="applied_unverified" receipt={receipt} />);
    const badge = screen.getByText("Checked; not corroborated (2 mismatches, 3 unverifiable)");
    expect(badge.getAttribute("title") ?? "").toContain("checked the live database");
    expect(badge.getAttribute("title") ?? "").not.toContain("did not check");
  });

  it("counts absent tuning first, since a setting missing from the catalog is the most serious verdict", () => {
    const receipt = JSON.stringify({
      corroborated: false,
      summary: { absent: 2, corroborated: 1, mismatch: 1, unverifiable: 4, gate_relevant_total: 8 },
      entries: [],
    });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe(
      "Checked; not corroborated (2 absent, 1 mismatch, 4 unverifiable)",
    );
  });

  it("reports only absent tuning when the summary omits every other failing verdict", () => {
    const receipt = JSON.stringify({
      corroborated: false,
      summary: { absent: 3, corroborated: 2, gate_relevant_total: 5 },
      entries: [],
    });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe("Checked; not corroborated (3 absent)");
  });

  it("treats verdicts missing from a real summary as zero", () => {
    const receipt = JSON.stringify({
      corroborated: false,
      summary: { corroborated: 4, mismatch: 1, gate_relevant_total: 5 },
      entries: [],
    });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe("Checked; not corroborated (1 mismatch)");
  });

  it("tallies absent, mismatch and unverifiable verdicts from complete entries when the receipt has no summary", () => {
    const receipt = JSON.stringify({
      corroborated: false,
      entries: [
        { verdict: "mismatch" },
        { verdict: "corroborated" },
        { verdict: "unverifiable" },
        { verdict: "absent" },
        { verdict: "absent" },
      ],
    });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe(
      "Checked; not corroborated (2 absent, 1 mismatch, 1 unverifiable)",
    );
  });

  it("omits counts instead of guessing when a truncated receipt has no summary", () => {
    const receipt = JSON.stringify({ corroborated: false, entries: [{ verdict: "mismatch" }], truncated: true });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe("Checked; not corroborated");
  });

  it("keeps the summary counts and says so when a real receipt was truncated", () => {
    const receipt = JSON.stringify({
      corroborated: false,
      summary: { absent: 1, mismatch: 2 },
      entries: [{ verdict: "mismatch" }],
      truncated: true,
      truncation_reason: "entry_limit",
      original_entry_count: 10500,
    });
    render(<TuningVerificationBadge status="applied_unverified" receipt={receipt} />);
    const badge = screen.getByText("Checked; not corroborated (1 absent, 2 mismatches)");
    expect(badge.getAttribute("title") ?? "").toContain("truncated");
  });

  it("omits the counts when the checked receipt records no failing verdicts", () => {
    const receipt = JSON.stringify({ corroborated: false, summary: { transient: 2 }, entries: [] });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe("Checked; not corroborated");
  });

  it.each([
    ["the byte-limit truncation marker", { entries: [], original_byte_count: 9000000, truncated: true, truncation_reason: "byte_limit" }],
    ["the redaction marker", { redacted: true, reason: "unexpected_shape" }],
    ["an object without a recorded verdict", { summary: { mismatch: 2 }, entries: [] }],
    ["a receipt whose verdict is not boolean", { corroborated: "false", summary: { mismatch: 2 }, entries: [] }],
    ["a corroborated receipt on an unverified status", { corroborated: true, entries: [] }],
  ])("does not claim a failed check for %s", (_label, placeholder) => {
    expect(tuningVerificationLabel("applied_unverified", JSON.stringify(placeholder))).toBe(
      "Applied; no live-database check recorded",
    );
  });

  it.each([null, undefined, "", "not json", "[]", "null"])(
    "reports no recorded check for applied_unverified when the receipt is %j",
    (receipt) => {
      expect(tuningVerificationLabel("applied_unverified", receipt as string | null | undefined)).toBe(
        "Applied; no live-database check recorded",
      );
    },
  );

  it("says no check result was recorded without claiming the platform cannot check", () => {
    render(<TuningVerificationBadge status="applied_unverified" />);
    const badge = screen.getByText("Applied; no live-database check recorded");
    const title = badge.getAttribute("title") ?? "";
    expect(title).toContain("no check result was recorded");
    expect(title).not.toContain("did not check");
    expect(title).not.toContain("platform");
  });

  it("ignores the receipt for statuses other than applied_unverified", () => {
    const receipt = JSON.stringify({ summary: { mismatch: 4, unverifiable: 0 }, entries: [] });
    expect(tuningVerificationLabel("applied_verified", receipt)).toBe("Verified");
    expect(tuningVerificationLabel("noop", receipt)).toBe("Nothing applied");
  });
});
