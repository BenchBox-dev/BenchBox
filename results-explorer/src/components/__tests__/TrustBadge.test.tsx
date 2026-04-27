/**
 * Tests for TrustBadge component.
 *
 * Cases:
 *   (a) Known trust labels render expected text and CSS class
 *   (b) compact=true shows only the first word
 *   (c) Unknown trust labels fall back gracefully (show the raw label)
 *   (d) All known tiers have title attributes (tooltip)
 *   (e) Color semantics: maintainer=green, community=blue, others=gray
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { TrustBadge } from "@/components/TrustBadge";

describe("TrustBadge", () => {
  // -----------------------------------------------------------------------
  // (a) Known trust labels
  // -----------------------------------------------------------------------

  it("maintainer-run renders with green badge class", () => {
    const { container } = render(<TrustBadge trustLabel="maintainer-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-green");
    expect(badge?.textContent).toBe("Maintainer");
  });

  it("community-submission renders with blue badge class", () => {
    const { container } = render(<TrustBadge trustLabel="community-submission" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-blue");
    expect(badge?.textContent).toBe("Community");
  });

  it("ci-verified renders with gray badge class", () => {
    const { container } = render(<TrustBadge trustLabel="ci-verified" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-gray");
  });

  it("ci-validated (legacy label) renders with gray badge class", () => {
    const { container } = render(<TrustBadge trustLabel="ci-validated" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-gray");
  });

  it("local-run renders with gray badge class", () => {
    const { container } = render(<TrustBadge trustLabel="local-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-gray");
  });

  // -----------------------------------------------------------------------
  // (b) compact mode
  // -----------------------------------------------------------------------

  it("compact=true shows first word only for maintainer-run", () => {
    render(<TrustBadge trustLabel="maintainer-run" compact />);
    // "Maintainer" → first word is "Maintainer"
    expect(screen.getByText("Maintainer")).toBeTruthy();
  });

  it("compact=true shows first word only for community-submission", () => {
    render(<TrustBadge trustLabel="community-submission" compact />);
    expect(screen.getByText("Community")).toBeTruthy();
  });

  it("compact=false shows full label", () => {
    render(<TrustBadge trustLabel="maintainer-run" compact={false} />);
    expect(screen.getByText("Maintainer")).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // (c) Unknown trust labels fallback gracefully
  // -----------------------------------------------------------------------

  it("unknown label falls back to gray badge with raw label as text", () => {
    const { container } = render(<TrustBadge trustLabel="some-new-tier" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-gray");
    // Shows the raw label when unknown (not "Unknown" - shows actual value)
    expect(badge?.textContent).toBe("some-new-tier");
  });

  it("unknown label tooltip explains it is unrecognised", () => {
    const { container } = render(<TrustBadge trustLabel="some-new-tier" />);
    const badge = container.querySelector(".badge");
    const title = badge?.getAttribute("title") ?? "";
    expect(title).toContain("some-new-tier");
    expect(title).toContain("unrecognised");
  });

  it("empty trustLabel renders nothing", () => {
    const { container } = render(<TrustBadge trustLabel="" />);
    expect(container.querySelector(".badge")).toBeNull();
  });

  // -----------------------------------------------------------------------
  // (d) Tooltips via title attribute
  // -----------------------------------------------------------------------

  it("maintainer-run badge has a title attribute for tooltip", () => {
    const { container } = render(<TrustBadge trustLabel="maintainer-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("title")).toBeTruthy();
    expect(badge?.getAttribute("title")).toContain("maintainer");
  });

  it("community-submission badge has a title attribute for tooltip", () => {
    const { container } = render(<TrustBadge trustLabel="community-submission" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("title")).toBeTruthy();
  });

  // -----------------------------------------------------------------------
  // (e) Color semantics - community is NOT yellow/amber (not cautionary)
  // -----------------------------------------------------------------------

  it("community-submission does not use yellow or amber badge class", () => {
    const { container } = render(<TrustBadge trustLabel="community-submission" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).not.toContain("badge-yellow");
    expect(badge?.className).not.toContain("badge-amber");
  });

  it("maintainer-run does not use gray (not de-emphasised)", () => {
    const { container } = render(<TrustBadge trustLabel="maintainer-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).not.toContain("badge-gray");
  });
});
