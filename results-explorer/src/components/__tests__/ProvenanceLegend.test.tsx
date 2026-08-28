/**
 * Tests for ProvenanceLegend.
 *
 * The legend satisfies docs/reference/hosted-results-contract.md
 * (§ Trust label rendering rules): "a legend explaining all trust labels is
 * accessible from every page that displays them". These tests pin:
 *   (a) it starts collapsed and toggles
 *   (b) it explains both axes, including the chip-less `unspecified` case
 *   (c) its prose comes from the badge components, so it cannot drift
 */

import { fireEvent, render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { ProvenanceLegend } from "@/components/ProvenanceLegend";
import { fundingDescription } from "@/components/FundingChip";
import { trustLabelDescription } from "@/components/TrustBadge";

const toggle = () => screen.getByRole("button", { name: /What do these labels mean\?/i });

describe("ProvenanceLegend", () => {
  // -----------------------------------------------------------------------
  // (a) collapsed by default, expandable
  // -----------------------------------------------------------------------

  it("renders collapsed with an accessible toggle", () => {
    render(<ProvenanceLegend />);
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByRole("heading", { name: "Funding" })).toBeNull();
  });

  it("expands to show both axes", () => {
    render(<ProvenanceLegend />);
    fireEvent.click(toggle());
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByRole("heading", { name: "Trust label" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Funding" })).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // (b) content
  // -----------------------------------------------------------------------

  it("lists every disclosed funding source", () => {
    render(<ProvenanceLegend />);
    fireEvent.click(toggle());
    for (const label of [
      "Employer funded",
      "Personally funded",
      "Free trial",
      "Vendor sponsored",
      "Grant funded",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("explains the omitted `unspecified` case rather than leaving a silent gap", () => {
    render(<ProvenanceLegend />);
    fireEvent.click(toggle());
    expect(screen.getByText("(no chip)")).toBeTruthy();
    expect(screen.getByText(/Funding was not disclosed for this run/i)).toBeTruthy();
  });

  it("states that funding is orthogonal to trust", () => {
    render(<ProvenanceLegend />);
    fireEvent.click(toggle());
    expect(screen.getByText(/disclosure, not a trust signal/i)).toBeTruthy();
  });

  it("lists canonical trust labels without duplicating their alias spellings", () => {
    render(<ProvenanceLegend />);
    fireEvent.click(toggle());
    // `ci`/`ci-verified`/`ci-validated` all render the badge text "CI"; the
    // legend must name it once, not three times.
    expect(screen.getAllByText("CI")).toHaveLength(1);
    expect(screen.getAllByText("Local")).toHaveLength(1);
  });

  // -----------------------------------------------------------------------
  // (c) single source for prose
  // -----------------------------------------------------------------------

  it("uses the badge components' own descriptions", () => {
    render(<ProvenanceLegend />);
    fireEvent.click(toggle());
    expect(screen.getByText(trustLabelDescription("vendor-supplied"))).toBeTruthy();
    expect(screen.getByText(fundingDescription("vendor-sponsored"))).toBeTruthy();
  });
});
