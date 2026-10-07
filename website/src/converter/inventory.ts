export type Counter = Map<string, number>;

export type Inventory = {
  files: number;
  directives: Counter;
  directiveOptions: Counter;
  directivesByFence: Counter;
  roles: Counter;
  labels: number;
  frontMatterKeys: Counter;
  mystKeys: Counter;
  enabledExtensions: Counter;
  comments: number;
  htmlBlocks: Counter;
  htmlInline: Counter;
  evalRstDirectives: Counter;
  evalRstRoles: Counter;
  evalRstOther: Counter;
  syntax: Counter;
  links: Counter;
  filesByConstruct: Map<string, Set<string>>;
};

const LITERAL_DIRECTIVES = new Set([
  "code-block",
  "code",
  "sourcecode",
  "mermaid",
  "eval-rst",
  "raw",
  "literalinclude",
  "csv-table",
  "toctree",
  "tags",
]);

const FENCE_OPEN = /^(\s*)(`{3,}|~{3,}|:{3,})\s*(?:\{([^}\s]+)\})?\s*(.*)$/;
const LABEL = /^\(([^)\s][^)]*)\)=\s*$/;
const OPTION = /^\s*:([A-Za-z][\w-]*):/;
const HTML_BLOCK = /^\s{0,3}<(\/?[A-Za-z][\w-]*|!--)/;
const HTML_INLINE = /<([A-Za-z][\w-]*)(?:\s[^<>]*)?>/g;
const RST_DIRECTIVE = /^\s*\.\.\s+([A-Za-z][\w:-]*)::/;
const RST_ROLE = /:([A-Za-z][\w:.-]*):`/g;
const RST_TARGET = /^\s*\.\.\s+_[^:]+:/;
const RST_COMMENT = /^\s*\.\.(\s|$)(?![A-Za-z_[|])/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$/;

function bump(counter: Counter, key: string, by = 1): void {
  counter.set(key, (counter.get(key) ?? 0) + by);
}

export function emptyInventory(): Inventory {
  return {
    files: 0,
    directives: new Map(),
    directiveOptions: new Map(),
    directivesByFence: new Map(),
    roles: new Map(),
    labels: 0,
    frontMatterKeys: new Map(),
    mystKeys: new Map(),
    enabledExtensions: new Map(),
    comments: 0,
    htmlBlocks: new Map(),
    htmlInline: new Map(),
    evalRstDirectives: new Map(),
    evalRstRoles: new Map(),
    evalRstOther: new Map(),
    syntax: new Map(),
    links: new Map(),
    filesByConstruct: new Map(),
  };
}

type Fence = { marker: string; length: number; directive: string | null; literal: boolean; optionsOpen: boolean };

type Context = { inventory: Inventory; file: string };

function noteFile(context: Context, construct: string): void {
  const files = context.inventory.filesByConstruct.get(construct) ?? new Set<string>();
  files.add(context.file);
  context.inventory.filesByConstruct.set(construct, files);
}

function scanFrontMatter(context: Context, lines: string[]): number {
  if (lines[0]?.trim() !== "---") return 0;
  const end = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
  if (end < 0) return 0;
  let section = "";
  let listKey = "";
  for (const line of lines.slice(1, end)) {
    const top = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
    if (top) {
      section = top[1];
      listKey = "";
      bump(context.inventory.frontMatterKeys, top[1]);
      noteFile(context, `front-matter:${top[1]}`);
      continue;
    }
    const nested = line.match(/^\s+([A-Za-z_][\w-]*):\s*(.*)$/);
    if (nested && section === "myst") {
      listKey = nested[1];
      bump(context.inventory.mystKeys, nested[1]);
      continue;
    }
    const item = line.match(/^\s+-\s+(\S+)/);
    if (item && section === "myst" && listKey === "enable_extensions") {
      bump(context.inventory.enabledExtensions, item[1]);
      noteFile(context, `extension:${item[1]}`);
    }
  }
  return end + 1;
}

function scanInline(context: Context, line: string): void {
  const { inventory } = context;
  const stripped: string[] = [];
  let index = 0;
  while (index < line.length) {
    if (line[index] !== "`") {
      stripped.push(line[index]);
      index += 1;
      continue;
    }
    let run = 0;
    while (line[index + run] === "`") run += 1;
    const ticks = "`".repeat(run);
    const close = line.indexOf(ticks, index + run);
    if (close < 0) {
      stripped.push(ticks);
      index += run;
      continue;
    }
    const role = line.slice(0, index).match(/\{([A-Za-z0-9_:.+-]+)\}$/);
    if (role) {
      bump(inventory.roles, role[1]);
      noteFile(context, `role:${role[1]}`);
    }
    stripped.push(" ");
    index = close + run;
  }
  const text = stripped.join("");
  for (const match of text.matchAll(HTML_INLINE)) {
    const tag = match[1].toLowerCase();
    bump(inventory.htmlInline, tag);
    noteFile(context, `html-inline:${tag}`);
  }
  for (const match of text.matchAll(/(!?)\[[^\]]*\]\(([^)\s]+)(?:\s+"[^"]*")?\)/g)) {
    const target = match[2];
    let kind: string;
    if (/^[a-z][a-z0-9+.-]*:/i.test(target)) kind = "external";
    else if (target.startsWith("#")) kind = "fragment";
    else if (target.startsWith("/")) kind = "absolute";
    else if (/\.md(#|$)/.test(target)) kind = "relative-md";
    else if (/\.rst(#|$)/.test(target)) kind = "relative-rst";
    else kind = "relative-other";
    bump(inventory.links, `${match[1] ? "image" : "link"}:${kind}`);
  }
  if (/\[\^[^\]]+\]/.test(text)) bump(inventory.syntax, "footnote");
  if (/\{\{[^}]+\}\}/.test(text)) bump(inventory.syntax, "substitution");
  if (/\$\$|(^|[^\\$])\$[^$\s][^$]*\$/.test(text)) bump(inventory.syntax, "math");
  if (/~~[^~]+~~/.test(text)) bump(inventory.syntax, "strikethrough");
  if (/<(https?:\/\/|mailto:)[^>]+>/.test(text)) bump(inventory.syntax, "autolink");
}

function scanEvalRst(context: Context, lines: string[]): void {
  const { inventory } = context;
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const directive = line.match(RST_DIRECTIVE);
    if (directive) {
      bump(inventory.evalRstDirectives, directive[1]);
      noteFile(context, `eval-rst:${directive[1]}`);
      continue;
    }
    if (RST_TARGET.test(line)) {
      bump(inventory.evalRstOther, "target");
      continue;
    }
    if (RST_COMMENT.test(line)) {
      bump(inventory.evalRstOther, "comment");
      continue;
    }
    for (const role of line.matchAll(RST_ROLE)) {
      bump(inventory.evalRstRoles, role[1]);
      noteFile(context, `eval-rst-role:${role[1]}`);
    }
    if (/^\s*:[A-Za-z][\w-]*:(\s|$)/.test(line)) bump(inventory.evalRstOther, "field-or-option");
    if (index > 0 && /^([=\-~^"#*+])\1{2,}\s*$/.test(line) && lines[index - 1].trim()) bump(inventory.evalRstOther, "section-underline");
    if (/^\s*([-*+]|\d+\.)\s/.test(line)) bump(inventory.evalRstOther, "list");
    if (/^\s*\+[-=+]+\+\s*$/.test(line)) bump(inventory.evalRstOther, "grid-table");
  }
}

function describeFence(marker: string): string {
  if (marker === "`") return "backtick";
  if (marker === "~") return "tilde";
  return "colon";
}

export function scanFile(inventory: Inventory, file: string, raw: string): void {
  const context: Context = { inventory, file };
  inventory.files += 1;
  const lines = raw.split("\n");
  const stack: Fence[] = [];
  let evalRst: string[] | null = null;
  let previousBlank = true;
  let hasH1 = false;
  let tableOpen = false;
  for (let index = scanFrontMatter(context, lines); index < lines.length; index += 1) {
    const line = lines[index];
    const open = stack.length > 0 ? stack[stack.length - 1] : null;
    if (open) {
      const closing = line.trim();
      if (closing.length >= open.length && closing === open.marker.repeat(closing.length)) {
        if (open.directive === "eval-rst" && evalRst) {
          scanEvalRst(context, evalRst);
          evalRst = null;
        }
        stack.pop();
        previousBlank = false;
        continue;
      }
      if (open.directive === "eval-rst") {
        evalRst?.push(line);
        continue;
      }
      if (open.directive && open.optionsOpen) {
        const option = line.match(OPTION);
        if (option) {
          bump(inventory.directiveOptions, `${open.directive}:${option[1]}`);
          continue;
        }
        open.optionsOpen = false;
      }
      if (open.literal) continue;
    }
    const fence = line.match(FENCE_OPEN);
    if (fence) {
      const marker = fence[2][0];
      const directive = fence[3] ?? null;
      const insideColon = stack.some((entry) => entry.marker === ":");
      if (marker !== ":" || directive !== null || insideColon) {
        if (directive) {
          bump(inventory.directives, directive);
          bump(inventory.directivesByFence, `${directive} (${describeFence(marker)})`);
          noteFile(context, `directive:${directive}`);
        }
        const literal = directive ? LITERAL_DIRECTIVES.has(directive) : marker !== ":";
        stack.push({ marker, length: fence[2].length, directive, literal, optionsOpen: directive !== null });
        if (directive === "eval-rst") evalRst = [];
        previousBlank = false;
        continue;
      }
    }
    if (LABEL.test(line)) {
      inventory.labels += 1;
      noteFile(context, "label");
      previousBlank = false;
      continue;
    }
    if (/^\s*%/.test(line)) {
      inventory.comments += 1;
      noteFile(context, "comment");
      continue;
    }
    if (line.trim() === "") {
      previousBlank = true;
      tableOpen = false;
      continue;
    }
    const html = line.match(HTML_BLOCK);
    if (html && previousBlank) {
      const tag = html[1].toLowerCase();
      bump(inventory.htmlBlocks, tag);
      noteFile(context, `html-block:${tag}`);
    }
    if (/^#\s/.test(line)) hasH1 = true;
    if (!previousBlank && /^:\s{1,3}\S/.test(line)) {
      bump(inventory.syntax, "deflist-item");
      noteFile(context, "deflist");
    }
    if (/^\s*[-*+]\s+\[[ xX]\]\s/.test(line)) bump(inventory.syntax, "task-list");
    if (/\{[#.][^}]*\}\s*$/.test(line)) bump(inventory.syntax, "attributes");
    if (/^\+\+\+/.test(line)) bump(inventory.syntax, "block-break");
    if (/^(=+|-+)\s*$/.test(line) && !previousBlank && !/^-{3,}\s*$/.test(line)) bump(inventory.syntax, "setext-heading");
    if (/^\s{0,3}>\s/.test(line)) bump(inventory.syntax, "blockquote-line");
    if (/^\s*\|.*\|\s*$/.test(line) && !tableOpen && TABLE_SEPARATOR.test(lines[index + 1] ?? "")) {
      bump(inventory.syntax, "pipe-table");
      noteFile(context, "pipe-table");
      tableOpen = true;
    }
    scanInline(context, line);
    previousBlank = false;
  }
  if (!hasH1) bump(inventory.syntax, "file-without-h1");
  if (stack.length > 0) bump(inventory.syntax, "unclosed-fence");
}
