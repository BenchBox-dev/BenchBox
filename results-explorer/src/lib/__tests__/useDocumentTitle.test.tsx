import { render } from "@testing-library/preact";
import { describe, expect, it } from "vitest";
import { useDocumentTitle } from "@/lib/useDocumentTitle";

function TitleProbe({ title }: { title: string }) {
  useDocumentTitle(title);
  return null;
}

describe("useDocumentTitle", () => {
  it("sets the document title and resets it on cleanup", () => {
    const { rerender, unmount } = render(<TitleProbe title="First · BenchBox Results" />);
    expect(document.title).toBe("First · BenchBox Results");

    rerender(<TitleProbe title="Second · BenchBox Results" />);
    expect(document.title).toBe("Second · BenchBox Results");

    unmount();
    expect(document.title).toBe("BenchBox Results Explorer");
  });
});
