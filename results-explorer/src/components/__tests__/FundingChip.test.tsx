import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { FundingChip } from "@/components/FundingChip";

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

  it.each(DISCLOSED_SOURCES)("%s renders a curated (non-unrecognised) chip", (funding) => {
    const { container } = render(<FundingChip funding={funding} />);
    const chip = container.querySelector(".badge");
    expect(chip).not.toBeNull();
    expect(chip?.getAttribute("title") ?? "").not.toContain("unrecognised");
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

  it("unrecognised value renders verbatim with an explanatory tooltip", () => {
    const { container } = render(<FundingChip funding="crowdfunded" />);
    const chip = container.querySelector(".badge");
    expect(chip?.textContent).toBe("crowdfunded");
    const title = chip?.getAttribute("title") ?? "";
    expect(title).toContain("crowdfunded");
    expect(title).toContain("unrecognised");
  });

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

  it('sets data-role="funding" so it is targetable apart from the trust badge', () => {
    const { container } = render(<FundingChip funding="grant" />);
    expect(container.querySelector(".badge")?.getAttribute("data-role")).toBe("funding");
  });

  it("uses explicit compact labels rather than truncating to the first word", () => {
    const { container } = render(<FundingChip funding="vendor-sponsored" compact />);
    expect(container.textContent).toContain("Sponsored");
    expect(container.textContent).not.toContain("Vendor");
  });

  it("keeps the full label when not compact", () => {
    const { container } = render(<FundingChip funding="vendor-sponsored" />);
    expect(container.textContent).toContain("Vendor sponsored");
  });

  it("omits the compact chip for the unspecified default", () => {
    const { container } = render(<FundingChip funding="unspecified" compact />);
    expect(container.querySelector(".badge")).toBeNull();
  });

  it("renders an unrecognised token verbatim in compact form", () => {
    const { container } = render(<FundingChip funding="mystery-fund" compact />);
    expect(container.textContent).toContain("mystery-fund");
  });
});
