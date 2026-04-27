import { render } from "@testing-library/preact";
import { describe, it, expect } from "vitest";
import { GroupedQueryChart } from "@/components/QueryTimingChart";

describe("GroupedQueryChart", () => {
  it("renders a dashed placeholder for null values without scaling maxValue to 0", () => {
    const { container } = render(
      <GroupedQueryChart
        groups={[
          {
            queryId: "Q1",
            values: [
              { label: "DuckDB", value: 100, color: "#0ea5e9" },
              { label: "SQLite", value: null, color: "#f97316" },
            ],
          },
        ]}
      />,
    );

    const rects = Array.from(container.querySelectorAll("rect"));
    const dashed = rects.find(
      (rect) =>
        rect.getAttribute("stroke-dasharray") !== null ||
        rect.getAttribute("strokeDasharray") !== null,
    );
    expect(dashed).toBeTruthy();
    expect(dashed?.getAttribute("fill")).toBe("none");
    expect(dashed?.getAttribute("height")).toBe("6");

    const solidBar = rects.find((rect) => rect.getAttribute("fill") === "#0ea5e9");
    expect(solidBar).toBeTruthy();
    expect(Number(solidBar?.getAttribute("height") ?? 0)).toBeGreaterThan(0);

    const titles = Array.from(container.querySelectorAll("title")).map((t) => t.textContent);
    expect(titles.some((t) => t?.includes("no data"))).toBe(true);
  });

  it("keeps a sensible y-axis scale when every value is null", () => {
    const { container } = render(
      <GroupedQueryChart
        groups={[
          {
            queryId: "Q1",
            values: [
              { label: "DuckDB", value: null, color: "#0ea5e9" },
              { label: "SQLite", value: null, color: "#f97316" },
            ],
          },
        ]}
      />,
    );

    // No NaN in any numeric attribute - would signal division-by-zero in the scale.
    const attrs = Array.from(container.querySelectorAll("*")).flatMap((el) =>
      Array.from(el.attributes).map((a) => a.value),
    );
    expect(attrs.some((v) => v.includes("NaN"))).toBe(false);
  });
});
