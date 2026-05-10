import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/preact";
import { TableScrollHint } from "@/components/TableScrollHint";

describe("TableScrollHint", () => {
  it("renders the default arrow label inside the standard wrapper", () => {
    const { container } = render(<TableScrollHint testId="default-hint" />);
    const span = screen.getByTestId("default-hint");
    expect(span.tagName).toBe("SPAN");
    expect(span.classList.contains("bb-scroll-affordance")).toBe(true);
    expect(span.textContent).toBe("← scroll →");
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.tagName).toBe("DIV");
    expect(wrapper.className).toBe("mb-2 flex justify-end");
  });

  it("renders a custom label and applies extra span classes", () => {
    render(
      <TableScrollHint
        testId="long-hint"
        label="Scroll table for more cohorts →"
        className="m-2"
      />,
    );
    const span = screen.getByTestId("long-hint");
    expect(span.textContent).toBe("Scroll table for more cohorts →");
    expect(span.classList.contains("bb-scroll-affordance")).toBe(true);
    expect(span.classList.contains("m-2")).toBe(true);
  });

  it("uses a custom wrapper class when provided", () => {
    const { container } = render(
      <TableScrollHint
        testId="custom-wrapper"
        wrapperClassName="flex justify-end"
        className="m-2"
      />,
    );
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.tagName).toBe("DIV");
    expect(wrapper.className).toBe("flex justify-end");
  });

  it("renders a bare span when wrapperClassName is null", () => {
    const { container } = render(
      <TableScrollHint testId="bare-hint" wrapperClassName={null} />,
    );
    const root = container.firstChild as HTMLElement;
    expect(root.tagName).toBe("SPAN");
    expect(root.getAttribute("data-testid")).toBe("bare-hint");
  });

  it("omits the data-testid attribute when none is provided", () => {
    const { container } = render(
      <TableScrollHint label="Scroll →" wrapperClassName={null} />,
    );
    const span = container.firstChild as HTMLElement;
    expect(span.tagName).toBe("SPAN");
    expect(span.hasAttribute("data-testid")).toBe(false);
    expect(span.textContent).toBe("Scroll →");
  });
});
