/**
 * Tests for TrustBadge component.
 *
 * Cases:
 *   (a) Known trust labels render expected text and tone
 *   (b) compact=true shows only the first word
 *   (c) Unknown trust labels fall back gracefully (show the raw label)
 *   (d) All known tiers have title attributes (tooltip)
 *   (e) Color semantics: maintainer=success, community=info, others=neutral
 *   (f) data-role="trust" is set so downstream pages can target trust badges
 */

import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { TrustBadge, ValidationBadge } from "@/components/TrustBadge";

describe("TrustBadge", () => {
  // -----------------------------------------------------------------------
  // (a) Known trust labels
  // -----------------------------------------------------------------------

  it("maintainer-run renders with success tone", () => {
    const { container } = render(<TrustBadge trustLabel="maintainer-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("success");
    expect(badge?.className).toContain("tone-success");
    expect(badge?.textContent).toBe("Maintainer");
  });

  it("community-submission renders with info tone", () => {
    const { container } = render(<TrustBadge trustLabel="community-submission" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("info");
    expect(badge?.className).toContain("tone-info");
    expect(badge?.textContent).toBe("Community");
  });

  it("ci-verified renders with neutral tone", () => {
    const { container } = render(<TrustBadge trustLabel="ci-verified" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
    expect(badge?.className).toContain("tone-neutral");
  });

  it("ci-validated (legacy label) renders with neutral tone", () => {
    const { container } = render(<TrustBadge trustLabel="ci-validated" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
  });

  it("local-run renders with neutral tone", () => {
    const { container } = render(<TrustBadge trustLabel="local-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
  });

  // -----------------------------------------------------------------------
  // (b) compact mode
  // -----------------------------------------------------------------------

  it("compact=true shows first word only for maintainer-run", () => {
    render(<TrustBadge trustLabel="maintainer-run" compact />);
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

  it("unknown label falls back to neutral tone with raw label as text", () => {
    const { container } = render(<TrustBadge trustLabel="some-new-tier" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
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

  it("empty trustLabel renders an explicit Unknown badge (not nothing)", () => {
    const { container } = render(<TrustBadge trustLabel="" />);
    const badge = container.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge?.textContent).toBe("Unknown");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
  });

  // Mirror of bundle_publisher.py VALID_LABELS; keep in sync.
  const PUBLISHER_VALID_LABELS = [
    "maintainer-run",
    "community-submission",
    "ci",
    "local",
    "unofficial-research",
  ] as const;

  it.each(PUBLISHER_VALID_LABELS)("publisher label %s renders a curated (non-unrecognised) badge", (label) => {
    const { container } = render(<TrustBadge trustLabel={label} />);
    const badge = container.querySelector(".badge");
    expect(badge).not.toBeNull();
    expect(badge?.getAttribute("title") ?? "").not.toContain("unrecognised");
    // Curated labels never echo the raw slug back as their visible text.
    expect(badge?.textContent).not.toBe(label);
  });

  it("unofficial-research uses a cautionary warning tone", () => {
    const { container } = render(<TrustBadge trustLabel="unofficial-research" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("warning");
    expect(badge?.textContent).toBe("Unofficial");
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
  // (e) Tone semantics - community is NOT warning/danger
  // -----------------------------------------------------------------------

  it("community-submission does not use warning or danger tone", () => {
    const { container } = render(<TrustBadge trustLabel="community-submission" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).not.toContain("tone-warning");
    expect(badge?.className).not.toContain("tone-danger");
  });

  it("maintainer-run does not use neutral tone (not de-emphasised)", () => {
    const { container } = render(<TrustBadge trustLabel="maintainer-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).not.toContain("tone-neutral");
  });

  // -----------------------------------------------------------------------
  // (f) data-role
  // -----------------------------------------------------------------------

  it("emits data-role=trust for downstream targeting", () => {
    const { container } = render(<TrustBadge trustLabel="maintainer-run" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-role")).toBe("trust");
  });
});

describe("ValidationBadge", () => {
  it("renders exact validation with info tone distinct from trust success", () => {
    const { container } = render(<ValidationBadge validationStatus="exact" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("info");
    expect(badge?.textContent).toBe("exact");
    expect(badge?.getAttribute("title")).toContain("Validation status: exact");
  });

  it("emits data-role=validation", () => {
    const { container } = render(<ValidationBadge validationStatus="exact" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-role")).toBe("validation");
  });

  it("suppresses missing status unless requested", () => {
    const hidden = render(<ValidationBadge validationStatus={null} />);
    expect(hidden.container.querySelector(".badge")).toBeNull();

    const shown = render(<ValidationBadge validationStatus={null} showMissing />);
    expect(shown.getByText("validation n/a")).toBeTruthy();
  });
});
