import { describe, expect, it } from "vitest";
import { formatRunAge } from "@/lib/runAge";

describe("formatRunAge", () => {
  const reference = new Date("2026-09-05T00:30:00Z");

  it.each([
    ["2026-09-05", "today"],
    ["2026-09-04T23:59:59-12:00", "1 day ago"],
    ["2026-09-03T00:00:00Z", "2 days ago"],
    ["2026-09-06", "in 1 day"],
  ])("uses UTC calendar-day boundaries for %s", (runDate, expected) => {
    expect(formatRunAge(runDate, reference)).toBe(expected);
  });

  it.each([undefined, null, "", "not-a-date", "2026-02-30", "2026-9-05", "2026-09-05 12:00:00"])(
    "omits malformed input safely: %j",
    (runDate) => {
      expect(formatRunAge(runDate, reference)).toBeNull();
    },
  );

  it("omits age when the injected reference is invalid", () => {
    expect(formatRunAge("2026-09-05", new Date("invalid"))).toBeNull();
  });
});
