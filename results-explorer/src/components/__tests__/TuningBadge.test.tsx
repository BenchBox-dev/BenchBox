/**
 * Tests for TuningBadge component.
 *
 * Cases:
 *   (a) Known tuning modes render expected label and CSS class
 *   (b) Unknown tuning modes fall back to "Custom Tuning" yellow badge
 *   (c) All modes have a title attribute (tooltip)
 *   (d) tuningLabel() helper returns correct label for dropdown reuse
 *   (e) Color semantics: tuned=green, notuning=gray, auto=blue
 */

import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";

describe("TuningBadge", () => {
  it("tuned renders with green badge class and 'Tuned' label", () => {
    const { container } = render(<TuningBadge tuningMode="tuned" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-green");
    expect(badge?.textContent).toBe("Tuned");
  });

  it("notuning renders with gray badge class and 'No Tuning' label", () => {
    const { container } = render(<TuningBadge tuningMode="notuning" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-gray");
    expect(badge?.textContent).toBe("No Tuning");
  });

  it("auto renders with blue badge class and 'Auto' label", () => {
    const { container } = render(<TuningBadge tuningMode="auto" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-blue");
    expect(badge?.textContent).toBe("Auto");
  });

  it("unknown mode falls back to yellow 'Custom Tuning' badge", () => {
    const { container } = render(<TuningBadge tuningMode="bespoke-tweaks" />);
    const badge = container.querySelector(".badge");
    expect(badge?.className).toContain("badge-yellow");
    expect(badge?.textContent).toBe("Custom Tuning");
  });

  it("every known mode exposes a title tooltip", () => {
    for (const mode of ["tuned", "notuning", "auto"]) {
      const { container } = render(<TuningBadge tuningMode={mode} />);
      const badge = container.querySelector(".badge");
      expect(badge?.getAttribute("title")).toBeTruthy();
    }
  });

  it("custom-tuning fallback also has a title tooltip", () => {
    const { container } = render(<TuningBadge tuningMode="anything-else" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("title")).toBeTruthy();
  });

  it("tuningLabel() returns dropdown-friendly text for known modes", () => {
    expect(tuningLabel("tuned")).toBe("Tuned");
    expect(tuningLabel("notuning")).toBe("No Tuning");
    expect(tuningLabel("auto")).toBe("Auto");
  });

  it("tuningLabel() returns 'Custom Tuning' for unknown modes", () => {
    expect(tuningLabel("mystery")).toBe("Custom Tuning");
  });
});
