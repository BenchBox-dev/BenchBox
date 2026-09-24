/**
 * Tests for TuningBadge component.
 *
 * Cases:
 *   (a) Known tuning modes render expected label and CSS class
 *   (b) Unknown tuning modes fall back to "Custom tuning" yellow badge
 *   (c) All modes have a title attribute (tooltip)
 *   (d) tuningLabel() helper returns correct label for dropdown reuse
 *   (e) Color semantics: tuned=green, notuning=gray, auto=blue
 *   (f) null/undefined and the not-recorded sentinel render the neutral
 *       "Not recorded" badge (never "Custom tuning")
 *   (g) tuned-fallback (ADR-2) renders its own warning-tone badge, distinct
 *       from both "Tuned" and the generic unknown-mode fallback
 *   (h) custom is a pinned vocabulary entry, but its public claim depends on
 *       execution-derived applied tuning evidence
 */

import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { TuningBadge, tuningLabel } from "@/components/TuningBadge";
import { NOT_RECORDED_TUNING_MODE } from "@/lib/facetMatching";

describe("TuningBadge", () => {
  it("tuned renders with success tone and 'Tuned' label", () => {
    const { container } = render(<TuningBadge tuningMode="tuned" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("success");
    expect(badge?.textContent).toBe("Tuned");
  });

  it("notuning renders with neutral tone and 'No tuning' label", () => {
    const { container } = render(<TuningBadge tuningMode="notuning" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
    expect(badge?.textContent).toBe("No tuning");
  });

  it("auto renders with info tone and 'Auto' label", () => {
    const { container } = render(<TuningBadge tuningMode="auto" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("info");
    expect(badge?.textContent).toBe("Automatic tuning");
  });

  it("unknown mode falls back to warning 'Custom tuning' badge", () => {
    const { container } = render(<TuningBadge tuningMode="bespoke-tweaks" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("warning");
    expect(badge?.textContent).toBe("Custom tuning");
  });

  it("emits data-role=computed for downstream targeting", () => {
    const { container } = render(<TuningBadge tuningMode="tuned" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-role")).toBe("computed");
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
    expect(tuningLabel("notuning")).toBe("No tuning");
    expect(tuningLabel("auto")).toBe("Automatic tuning");
  });

  it("tuningLabel() returns 'Custom tuning' for unknown modes", () => {
    expect(tuningLabel("mystery")).toBe("Custom tuning");
  });

  it("null tuning mode renders the neutral 'Not recorded' badge, not 'Custom tuning'", () => {
    const { container } = render(<TuningBadge tuningMode={null} />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
    expect(badge?.textContent).toBe("Not recorded");
    expect(badge?.getAttribute("title")).toMatch(/predates tuning metadata|did not record/);
  });

  it("undefined tuning mode renders the neutral 'Not recorded' badge", () => {
    const { container } = render(<TuningBadge tuningMode={undefined} />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
    expect(badge?.textContent).toBe("Not recorded");
  });

  it("the not-recorded sentinel token renders the same 'Not recorded' badge", () => {
    const { container } = render(<TuningBadge tuningMode={NOT_RECORDED_TUNING_MODE} />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
    expect(badge?.textContent).toBe("Not recorded");
    expect(badge?.getAttribute("title")).toBeTruthy();
  });

  it("tuningLabel() returns 'Not recorded' for null/undefined/sentinel", () => {
    expect(tuningLabel(null)).toBe("Not recorded");
    expect(tuningLabel(undefined)).toBe("Not recorded");
    expect(tuningLabel(NOT_RECORDED_TUNING_MODE)).toBe("Not recorded");
  });

  it("tuned-fallback (ADR-2) renders its own warning-tone badge, distinct from 'Tuned'", () => {
    const { container } = render(<TuningBadge tuningMode="tuned-fallback" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("warning");
    expect(badge?.textContent).toBe("Tuned with fallback settings");
    expect(badge?.getAttribute("title")).toMatch(/no recommended settings/i);
  });

  it("custom with applied evidence renders the pinned Custom tuning badge", () => {
    const { container } = render(
      <TuningBadge tuningMode="custom" tuningValidationStatus="applied_unverified" />,
    );
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("warning");
    expect(badge?.textContent).toBe("Custom tuning");
    expect(badge?.getAttribute("title")).toBe("This run used tuning settings supplied by the person who ran it.");
  });

  it("custom noop does not claim Custom tuning was applied", () => {
    const { container } = render(<TuningBadge tuningMode="custom" tuningValidationStatus="noop" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("neutral");
    expect(badge?.textContent).toBe("No tuning applied");
    expect(badge?.getAttribute("title")).toMatch(/recorded no applied tuning settings/i);
  });

  it("custom without applied evidence is labeled as requested rather than applied", () => {
    const { container } = render(<TuningBadge tuningMode="custom" />);
    const badge = container.querySelector(".badge");
    expect(badge?.getAttribute("data-tone")).toBe("warning");
    expect(badge?.textContent).toBe("Custom tuning requested");
  });

  it("tuningLabel() recognizes tuned-fallback and custom as pinned vocabulary", () => {
    expect(tuningLabel("tuned-fallback")).toBe("Tuned with fallback settings");
    expect(tuningLabel("custom")).toBe("Custom tuning");
  });
});
