import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import {
  TuningVerificationBadge,
  tuningVerificationLabel,
} from "@/components/TuningVerificationBadge";

describe("TuningVerificationBadge", () => {
  it("maps each ADR-1 verified-state to a distinct label", () => {
    expect(tuningVerificationLabel("applied_verified")).toBe("Verified");
    expect(tuningVerificationLabel("applied_unverified")).toBe("Applied; no check available on this platform");
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

  it("labels applied_unverified with a receipt as checked but not corroborated, with counts", () => {
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

  it("uses the singular for one mismatch", () => {
    const receipt = JSON.stringify({ summary: { mismatch: 1, unverifiable: 0 }, entries: [] });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe(
      "Checked; not corroborated (1 mismatch, 0 unverifiable)",
    );
  });

  it("tallies recorded verdicts from complete entries when the receipt has no summary", () => {
    const receipt = JSON.stringify({
      entries: [{ verdict: "mismatch" }, { verdict: "corroborated" }, { verdict: "unverifiable" }],
    });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe(
      "Checked; not corroborated (1 mismatch, 1 unverifiable)",
    );
  });

  it("omits counts instead of guessing when a truncated receipt has no summary", () => {
    const receipt = JSON.stringify({ entries: [{ verdict: "mismatch" }], truncated: true });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe("Checked; not corroborated");
  });

  it("omits the counts when the receipt records neither mismatches nor unverifiable statements", () => {
    const receipt = JSON.stringify({ summary: { absent: 2, mismatch: 0, unverifiable: 0 }, entries: [] });
    expect(tuningVerificationLabel("applied_unverified", receipt)).toBe("Checked; not corroborated");
  });

  it.each([null, undefined, "", "not json", "[]", "null"])(
    "reports no check available for applied_unverified when the receipt is %j",
    (receipt) => {
      expect(tuningVerificationLabel("applied_unverified", receipt as string | null | undefined)).toBe(
        "Applied; no check available on this platform",
      );
    },
  );

  it("never claims the database was not checked when no check is available", () => {
    render(<TuningVerificationBadge status="applied_unverified" />);
    const badge = screen.getByText("Applied; no check available on this platform");
    expect(badge.getAttribute("title") ?? "").not.toContain("did not check");
  });

  it("ignores the receipt for statuses other than applied_unverified", () => {
    const receipt = JSON.stringify({ summary: { mismatch: 4, unverifiable: 0 }, entries: [] });
    expect(tuningVerificationLabel("applied_verified", receipt)).toBe("Verified");
    expect(tuningVerificationLabel("noop", receipt)).toBe("Nothing applied");
  });
});
