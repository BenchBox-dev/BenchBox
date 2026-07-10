/**
 * Tests for FundingChip component.
 *
 * Cases:
 *   (a) Every FUNDING_SOURCES value except `unspecified` renders a curated chip
 *   (b) `unspecified` / empty / null render nothing (chip omitted)
 *   (c) Unrecognised values render verbatim rather than being dropped
 *   (d) Tone is uniformly neutral - funding is a disclosure, not a trust signal
 *   (e) data-role="funding" so pages and e2e can target funding chips
 *       independently of the orthogonal trust badge
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { FundingChip } from "@/components/FundingChip";

// Mirror of benchbox/core/results/provenance.py::FUNDING_SOURCES; keep in sync.
const FUNDING_SOURCES = [
  "employer",
  "personal",
  "free-trial",
  "vendor-sponsored",
  "grant",
  "unspecified",
] as const;

const DISCLOSED_SOURCES = FUNDING_SOURCES.filter((value) => value !== "unspecified");

describe("FundingChip", () => {
  // -----------------------------------------------------------------------
  // (a) Known funding values
  // -----------------------------------------------------------------------

  it.each(DISCLOSED_SOURCES)("%s renders a curated (non-unrecognised) chip", (funding) => {
    const { container } = render(<FundingChip funding={funding} />);
    const chip = container.querySelector(".badge");
    expect(chip).not.toBeNull();
    expect(chip?.getAttribute("title") ?? "").not.toContain("unrecognised");
    // Curated values never echo the raw slug back as their visible text.
    expect(chip?.textContent).not.toBe(funding);
  });

  it("employer renders its human label", () => {
    render(<FundingChip funding="employer" />);
    expect(screen.getByText("Employer funded")).toBeTruthy();
  });

  it("vendor-sponsored renders its human label", () => {
    render(<FundingChip funding="vendor-sponsored" />);
    expect(screen.getByText("Vendor sponsored")).toBeTruthy();
  });

  it.each(DISCLOSED_SOURCES)("%s has a descriptive title tooltip", (funding) => {
    const { container } = render(<FundingChip funding={funding} />);
    const title = container.querySelector(".badge")?.getAttribute("title") ?? "";
    expect(title.length).toBeGreaterThan(0);
  });

  // -----------------------------------------------------------------------
  // (b) `unspecified` and missing values render nothing
  // -----------------------------------------------------------------------

  it("unspecified renders no chip", () => {
    const { container } = render(<FundingChip funding="unspecified" />);
    expect(container.querySelector(".badge")).toBeNull();
  });

  it("empty string renders no chip", () => {
    const { container } = render(<FundingChip funding="" />);
    expect(container.querySelector(".badge")).toBeNull();
  });

  it("null renders no chip", () => {
    const { container } = render(<FundingChip funding={null} />);
    expect(container.querySelector(".badge")).toBeNull();
  });

  it("undefined renders no chip", () => {
    const { container } = render(<FundingChip funding={undefined} />);
    expect(container.querySelector(".badge")).toBeNull();
  });

  // -----------------------------------------------------------------------
  // (c) Unrecognised values surface rather than disappear
  // -----------------------------------------------------------------------

  it("unrecognised value renders verbatim with an explanatory tooltip", () => {
    const { container } = render(<FundingChip funding="crowdfunded" />);
    const chip = container.querySelector(".badge");
    expect(chip?.textContent).toBe("crowdfunded");
    const title = chip?.getAttribute("title") ?? "";
    expect(title).toContain("crowdfunded");
    expect(title).toContain("unrecognised");
  });

  // -----------------------------------------------------------------------
  // (d) Tone is uniformly neutral (no trust gradient)
  // -----------------------------------------------------------------------

  it.each(DISCLOSED_SOURCES)("%s uses the neutral tone", (funding) => {
    const { container } = render(<FundingChip funding={funding} />);
    const chip = container.querySelector(".badge");
    expect(chip?.getAttribute("data-tone")).toBe("neutral");
    expect(chip?.className).toContain("tone-neutral");
  });

  it("vendor-sponsored is not styled as a warning (funding is not a trust signal)", () => {
    const { container } = render(<FundingChip funding="vendor-sponsored" />);
    const chip = container.querySelector(".badge");
    expect(chip?.getAttribute("data-tone")).toBe("neutral");
    expect(chip?.className).not.toContain("tone-warning");
  });

  // -----------------------------------------------------------------------
  // (e) role wiring
  // -----------------------------------------------------------------------

  it('sets data-role="funding" so it is targetable apart from the trust badge', () => {
    const { container } = render(<FundingChip funding="grant" />);
    expect(container.querySelector(".badge")?.getAttribute("data-role")).toBe("funding");
  });
});
