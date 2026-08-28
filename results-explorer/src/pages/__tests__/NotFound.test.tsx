import { render, screen } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { NotFound } from "@/pages/NotFound";

describe("NotFound", () => {
  it("sets the not-found document title", () => {
    render(<NotFound />);

    expect(screen.getByRole("heading", { name: "404" })).toBeTruthy();
    expect(document.title).toBe("Not found · BenchBox Results");
  });
});
