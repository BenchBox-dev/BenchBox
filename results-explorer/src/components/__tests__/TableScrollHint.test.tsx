import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/preact";
import { createRef } from "preact";
import { TableScrollHint } from "@/components/TableScrollHint";

function renderHint(props: Omit<Parameters<typeof TableScrollHint>[0], "scrollerRef">) {
  const scrollerRef = createRef<HTMLDivElement>();
  return render(
    <>
      <TableScrollHint {...props} scrollerRef={scrollerRef} />
      <div ref={scrollerRef} class="overflow-x-auto">
        <table />
      </div>
    </>,
  );
}

describe("TableScrollHint", () => {
  it("renders the default arrow label inside the standard wrapper", () => {
    const { container } = renderHint({ testId: "default-hint" });
    const span = screen.getByTestId("default-hint");
    expect(span.tagName).toBe("SPAN");
    expect(span.classList.contains("bb-scroll-affordance")).toBe(true);
    expect(span.textContent).toBe("← scroll →");
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.tagName).toBe("DIV");
    expect(wrapper.className).toBe("mb-2 flex justify-end");
  });

  it("renders a custom label and applies extra span classes", () => {
    renderHint({
      testId: "long-hint",
      label: "Scroll table for more cohorts →",
      className: "m-2",
    });
    const span = screen.getByTestId("long-hint");
    expect(span.textContent).toBe("Scroll table for more cohorts →");
    expect(span.classList.contains("bb-scroll-affordance")).toBe(true);
    expect(span.classList.contains("m-2")).toBe(true);
  });

  it("uses a custom wrapper class when provided", () => {
    const { container } = renderHint({
      testId: "custom-wrapper",
      wrapperClassName: "flex justify-end",
      className: "m-2",
    });
    const wrapper = container.firstChild as HTMLElement;
    expect(wrapper.tagName).toBe("DIV");
    expect(wrapper.className).toBe("flex justify-end");
  });

  it("renders a bare span when wrapperClassName is null", () => {
    const { container } = renderHint({ testId: "bare-hint", wrapperClassName: null });
    const root = container.firstChild as HTMLElement;
    expect(root.tagName).toBe("SPAN");
    expect(root.getAttribute("data-testid")).toBe("bare-hint");
  });

  it("omits the data-testid attribute when none is provided", () => {
    const { container } = renderHint({ label: "Scroll →", wrapperClassName: null });
    const span = container.firstChild as HTMLElement;
    expect(span.tagName).toBe("SPAN");
    expect(span.hasAttribute("data-testid")).toBe(false);
    expect(span.textContent).toBe("Scroll →");
  });

  it("renders when the target has horizontal overflow", () => {
    const scrollerRef = createRef<HTMLDivElement>();
    render(
      <>
        <TableScrollHint scrollerRef={scrollerRef} testId="overflow-hint" />
        <div ref={scrollerRef} data-client-width="800" data-scroll-width="1200">
          <table />
        </div>
      </>,
    );
    expect(screen.getByTestId("overflow-hint")).toBeVisible();
  });

  it("does not render when the target has no horizontal overflow", () => {
    const scrollerRef = createRef<HTMLDivElement>();
    render(
      <>
        <TableScrollHint scrollerRef={scrollerRef} testId="no-overflow-hint" />
        <div ref={scrollerRef} data-client-width="800" data-scroll-width="800">
          <table />
        </div>
      </>,
    );
    expect(screen.queryByTestId("no-overflow-hint")).toBeNull();
  });
});
