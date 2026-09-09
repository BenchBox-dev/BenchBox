/**
 * The shared metadata label treatments: a run date and a platform version.
 *
 * Both exist because the same value was previously spelled out in full in
 * every table cell and chart label that carried it, wrapping mid-value and
 * crowding out the measurement. Each keeps its full value in the accessible
 * name and behind one interaction, so nothing is lost by leading with the
 * short form.
 */

import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect } from "vitest";

import { RunDateChip } from "@/components/RunAge";
import { VersionLabel } from "@/components/VersionLabel";
import { splitVersion } from "@/lib/versionLabel";

const REFERENCE = new Date("2026-09-08T00:00:00Z");

describe("RunDateChip", () => {
  it("leads with the calendar date and carries the age in its accessible name", () => {
    render(<RunDateChip runDate="2026-09-01" reference={REFERENCE} />);
    const chip = screen.getByTestId("run-date-chip");
    expect(chip.textContent).toBe("2026-09-01");
    expect(chip.getAttribute("aria-label")).toContain("2026-09-01 (7 days ago)");
    expect(chip.getAttribute("title")).toBe("2026-09-01 (7 days ago)");
  });

  it("swaps to the age when activated, and back", () => {
    render(<RunDateChip runDate="2026-09-01" reference={REFERENCE} />);
    const chip = screen.getByTestId("run-date-chip");
    fireEvent.click(chip);
    expect(screen.getByTestId("run-date-chip").textContent).toBe("7 days ago");
    fireEvent.click(screen.getByTestId("run-date-chip"));
    expect(screen.getByTestId("run-date-chip").textContent).toBe("2026-09-01");
  });

  it("never wraps mid-value", () => {
    render(<RunDateChip runDate="2026-09-01" reference={REFERENCE} />);
    expect(screen.getByTestId("run-date-chip").className).toContain("bb-meta-chip");
  });

  it("renders a plain, non-interactive chip when no age can be computed", () => {
    render(<RunDateChip runDate={null} />);
    const chip = screen.getByTestId("run-date-chip");
    expect(chip.tagName).toBe("SPAN");
    expect(chip.textContent).toBe("Not recorded");
  });
});

describe("splitVersion", () => {
  it("separates the release core from a prerelease or build suffix", () => {
    expect(splitVersion("2.0.0-alpha38615")).toEqual({
      core: "v2.0.0",
      suffix: "-alpha38615",
      full: "v2.0.0-alpha38615",
    });
    expect(splitVersion("v1.3.2")).toEqual({ core: "v1.3.2", suffix: null, full: "v1.3.2" });
    expect(splitVersion("1.0.0+build.7")).toEqual({
      core: "v1.0.0",
      suffix: "+build.7",
      full: "v1.0.0+build.7",
    });
  });

  it("leaves a version it cannot parse whole rather than guessing", () => {
    expect(splitVersion("nightly")).toEqual({ core: "vnightly", suffix: null, full: "vnightly" });
    expect(splitVersion(null)).toBeNull();
    expect(splitVersion("  ")).toBeNull();
  });
});

describe("VersionLabel", () => {
  it("elides the build suffix but keeps it one click and one title away", () => {
    render(<VersionLabel version="2.0.0-alpha38615" />);
    const label = screen.getByTestId("version-label");
    expect(label.textContent).toBe("v2.0.0…");
    expect(label.getAttribute("title")).toBe("v2.0.0-alpha38615");
    expect(label.getAttribute("aria-label")).toContain("v2.0.0-alpha38615");
    fireEvent.click(label);
    expect(screen.getByTestId("version-label").textContent).toBe("v2.0.0-alpha38615");
  });

  it("shows a plain version without an expansion affordance", () => {
    render(<VersionLabel version="1.3.2" />);
    const label = screen.getByTestId("version-label");
    expect(label.tagName).toBe("SPAN");
    expect(label.textContent).toBe("v1.3.2");
  });

  it("renders nothing when there is no version to show", () => {
    const { container } = render(<VersionLabel version={null} />);
    expect(container.textContent).toBe("");
  });
});
