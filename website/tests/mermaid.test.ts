import { afterEach, describe, expect, it } from "vitest";
import { UnknownConstructError } from "../src/converter/errors.ts";
import { build, bodyOf, cleanup, pageOf } from "./support.ts";

afterEach(cleanup);

describe("mermaid", () => {
  it("emits the Mermaid component with the diagram source", () => {
    const result = build({ "a.md": '# A\n\n```{mermaid}\ngraph TD\n  A["x"] --> B{y}\n```\n' });
    expect(result.errors).toEqual([]);
    const body = bodyOf(result, "docs/a.mdx");
    expect(body).toContain("<Mermaid diagram={");
    expect(body).toContain(String.raw`graph TD\n  A[\"x\"] --> B{y}`);
    expect(pageOf(result, "docs/a.mdx")).toContain('import Mermaid from "../../../src/components/docs/Mermaid.astro";');
  });

  it("rejects options and empty bodies", () => {
    const withOption = build({ "a.md": "# A\n\n```{mermaid}\n:align: center\ngraph TD\n```\n" });
    expect(withOption.errors[0]).toBeInstanceOf(UnknownConstructError);
    expect(withOption.errors[0].line).toBe(3);
  });

  it("rejects an empty body with the directive line", () => {
    const empty = build({ "b.md": "# B\n\n```{mermaid}\n```\n" });
    expect(empty.errors[0]).toBeInstanceOf(UnknownConstructError);
    expect(empty.errors[0].message).toContain("b.md:3");
  });
});
