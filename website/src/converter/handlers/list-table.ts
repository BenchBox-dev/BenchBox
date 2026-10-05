import type { Html, List, ListItem, PhrasingContent, RootContent, Table, TableCell, TableRow } from "mdast";
import { ConverterError } from "../errors.ts";
import type { ConvertContext, DirectiveCall, DirectiveHandler } from "../types.ts";

type Cell = RootContent[];

type Row = Cell[];

function fail(call: DirectiveCall, message: string): ConverterError {
  return new ConverterError(call.at.file, call.at.line, `list-table: ${message}`);
}

function parseRows(call: DirectiveCall, context: ConvertContext): Row[] {
  const blocks = context.convertMarkdown(call.body, call.bodyAt);
  if (blocks.length !== 1 || blocks[0].type !== "list") throw fail(call, "content must be a single bullet list of rows");
  return (blocks[0] as List).children.map((item: ListItem) => {
    const [inner, ...extra] = item.children;
    if (extra.length > 0 || inner?.type !== "list") throw fail(call, "every row must be a nested bullet list of cells");
    return inner.children.map((cell: ListItem) => cell.children);
  });
}

function intOption(call: DirectiveCall, name: string, fallback: number): number {
  const raw = call.options[name];
  if (raw === undefined || raw.trim() === "") return fallback;
  if (!/^\d+$/.test(raw.trim())) throw fail(call, `:${name}: must be a non-negative integer`);
  return Number(raw.trim());
}

function checkWidths(call: DirectiveCall, columns: number): void {
  const raw = call.options.widths;
  if (raw === undefined || raw.trim() === "" || raw.trim() === "auto" || raw.trim() === "grid") return;
  const widths = raw.trim().split(/[\s,]+/);
  if (widths.length !== columns || widths.some((width) => !/^\d+$/.test(width))) {
    throw fail(call, `:widths: must list ${columns} positive integers`);
  }
}

function flatten(children: PhrasingContent[]): PhrasingContent[] {
  const out: PhrasingContent[] = [];
  for (const child of children) {
    if (child.type === "text") out.push({ ...child, value: child.value.replace(/\s*\n\s*/g, " ") });
    else if (child.type === "break") out.push({ type: "html", value: "<br />" });
    else if (child.type === "inlineCode") out.push({ ...child, value: child.value.replace(/\s*\n\s*/g, " ") });
    else if ("children" in child) out.push({ ...child, children: flatten(child.children as PhrasingContent[]) } as PhrasingContent);
    else out.push(child);
  }
  return out;
}

function inlineCell(cell: Cell): PhrasingContent[] | undefined {
  if (cell.length === 0) return [];
  if (cell.length === 1 && cell[0].type === "paragraph") return flatten(cell[0].children);
  return undefined;
}

function toGfm(rows: Row[]): Table | undefined {
  const converted: TableRow[] = [];
  for (const row of rows) {
    const cells: TableCell[] = [];
    for (const cell of row) {
      const children = inlineCell(cell);
      if (!children) return undefined;
      cells.push({ type: "tableCell", children });
    }
    converted.push({ type: "tableRow", children: cells });
  }
  return { type: "table", align: converted[0].children.map(() => null), children: converted };
}

function tag(value: string): Html {
  return { type: "html", value };
}

function toHtml(rows: Row[], headerRows: number): RootContent[] {
  const out: RootContent[] = [tag("<table>")];
  const section = (name: "thead" | "tbody", cell: "th" | "td", slice: Row[]): void => {
    if (slice.length === 0) return;
    out.push(tag(`<${name}>`));
    for (const row of slice) {
      out.push(tag("<tr>"));
      for (const content of row) out.push(tag(`<${cell}>`), ...content, tag(`</${cell}>`));
      out.push(tag("</tr>"));
    }
    out.push(tag(`</${name}>`));
  };
  section("thead", "th", rows.slice(0, headerRows));
  section("tbody", "td", rows.slice(headerRows));
  out.push(tag("</table>"));
  return out;
}

export const listTableDirective: DirectiveHandler = {
  kind: "directive",
  names: ["list-table"],
  options: ["header-rows", "widths"],
  argument: "none",
  handle(call, context) {
    const rows = parseRows(call, context);
    if (rows.length === 0) throw fail(call, "table has no rows");
    const columns = rows[0].length;
    if (columns === 0 || rows.some((row) => row.length !== columns)) throw fail(call, "every row must have the same number of cells");
    const headerRows = intOption(call, "header-rows", 0);
    if (headerRows > rows.length) throw fail(call, ":header-rows: exceeds the number of rows");
    checkWidths(call, columns);
    if (headerRows === 1) {
      const table = toGfm(rows);
      if (table) return [table];
    }
    return toHtml(rows, headerRows);
  },
};
