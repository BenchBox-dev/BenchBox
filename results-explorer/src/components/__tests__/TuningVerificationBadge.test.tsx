import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import {
  TuningVerificationBadge,
  tuningVerificationLabel,
} from "@/components/TuningVerificationBadge";

describe("TuningVerificationBadge", () => {
  it("maps each ADR-1 verified-state to a distinct label", () => {
    expect(tuningVerificationLabel("applied_verified")).toBe("Verified");
    expect(tuningVerificationLabel("applied_unverified")).toBe("Applied (self-attested)");
    expect(tuningVerificationLabel("noop")).toBe("No-op");
    expect(tuningVerificationLabel("not_applicable")).toBe("Not Applicable");
    expect(tuningVerificationLabel("failed")).toBe("Failed");
  });

  it("treats null / unknown states as not-recorded, never as verified", () => {
    expect(tuningVerificationLabel(null)).toBe("Not Recorded");
    expect(tuningVerificationLabel(undefined)).toBe("Not Recorded");
    expect(tuningVerificationLabel("")).toBe("Not Recorded");
    // An unrecognized future status must not silently read as verified.
    expect(tuningVerificationLabel("some_new_status")).toBe("Not Recorded");
  });

  it("renders applied_verified with an introspection-corroboration tooltip", () => {
    render(<TuningVerificationBadge status="applied_verified" />);
    const badge = screen.getByText("Verified");
    expect(badge.getAttribute("title") ?? "").toContain("Introspection-corroborated");
  });
});
