import { mergeDefinitionLists } from "./handlers/deflist.ts";
import type { Code, FootnoteDefinition, Html, Paragraph, PhrasingContent, Root, RootContent } from "mdast";
import { collectionOf, contentIdFor, DocsIndex, routeFor } from "./docs-index.ts";
import { ConverterError, UnknownConstructError, UnresolvedReferenceError } from "./errors.ts";
import { smarten } from "../lib/smartypants.ts";
import { IdAllocator } from "./ids.ts";
import type { Collection, DocInfo, LabelInfo, PageData, ResolvedDoc, ResolvedLabel, SourcePosition, TocNode, TocSection, ToctreeBlock } from "./model.ts";
import { parse as parseYaml } from "yaml";
import { parseFrontMatter, parseMarkdown, type FrontMatter } from "./parse.ts";
import { ATTRS_MARKER, COMMENT_MARKER, LABEL_MARKER, MISPLACED_MARKER, preprocess } from "./preprocess.ts";
import type { HandlerRegistry } from "./registry.ts";
import type { ComponentName, ConvertContext, DirectiveCall } from "./types.ts";

export type ConvertedDocument = {
  path: string;
  contentId: string;
  collection: Collection;
  data: PageData;
  root: Root;
  info: DocInfo;
  positions: WeakMap<RootContent, SourcePosition>;
  components: ReadonlySet<ComponentName>;
  errors: readonly ConverterError[];
};

export type ConvertRequest = {
  path: string;
  raw: string;
  index: DocsIndex;
  registry: HandlerRegistry;
  docsRoot: string;
  pass: "collect" | "emit";
  knownBroken: ReadonlySet<string>;
};

type Frame = { source: string; lineOffset: number };

type PendingLabel = { label: string; at: SourcePosition; node: Html };

type PendingFootnote = { label: string; node: Html };

const AUTOMATIC_ID = /^id\d+$/;
const ATTRS_ID = /^#([^\s#.=]+)$/;
const ATTRIBUTABLE = new Set(["paragraph", "list", "table", "code", "blockquote"]);
const DIRECTIVE_LANG = /^\{([^}\s]+)\}$/;
const ROLE_SUFFIX = /\{([A-Za-z0-9_:.+-]+)\}$/;
const OPTION_LINE = /^:([\w-]+):(?:\s+(.*))?$/;
const PHRASING_PARENTS = new Set(["paragraph", "heading", "emphasis", "strong", "delete", "link", "linkReference", "tableCell"]);
const BLOCK_PARENTS = new Set(["blockquote", "list", "listItem", "footnoteDefinition", "table", "tableRow"]);
const LEAF_TYPES = new Set(["thematicBreak", "inlineCode", "text", "break", "footnoteReference", "linkReference", "code"]);

function yamlOptions(lines: readonly string[], lang: string, at: SourcePosition): { options: Record<string, string>; consumed: number } {
  const close = lines.findIndex((line, index) => index > 0 && line.trim() === "---");
  if (close < 0) throw new UnknownConstructError(at.file, at.line, `directive-options:${lang}`, `${lang} option block opened with --- is not closed`);
  let parsed: unknown;
  try {
    parsed = parseYaml(lines.slice(1, close).join("\n"));
  } catch (error) {
    throw new UnknownConstructError(at.file, at.line, `directive-options:${lang}`, `${lang} option block is not valid YAML: ${(error as Error).message.split("\n")[0]}`);
  }
  if (parsed === null || parsed === undefined) return { options: {}, consumed: close + 1 };
  if (typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new UnknownConstructError(at.file, at.line, `directive-options:${lang}`, `${lang} option block must be a mapping of option names to values`);
  }
  const options: Record<string, string> = {};
  for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
    if (value !== null && typeof value === "object") {
      throw new UnknownConstructError(at.file, at.line, `directive-option:${lang}:${key}`, `${lang} option ${key} must be a scalar`);
    }
    options[key] = value === null ? "" : String(value);
  }
  return { options, consumed: close + 1 };
}

function parseDirectiveBody(code: Code, lang: string, lineOffset: number, file: string): DirectiveCall {
  const lines = code.value === "" ? [] : code.value.split("\n");
  const fenceLine = (code.position?.start.line ?? 1) + lineOffset;
  let options: Record<string, string> = {};
  let consumed = 0;
  if (lines[0]?.trim() === "---") ({ options, consumed } = yamlOptions(lines, lang, { file, line: fenceLine + 1 }));
  else
    while (consumed < lines.length) {
      const option = lines[consumed].match(OPTION_LINE);
      if (!option) break;
      options[option[1]] = option[2] ?? "";
      consumed += 1;
    }
  if (consumed > 0 && lines[consumed] !== undefined && lines[consumed].trim() === "") consumed += 1;
  return {
    name: lang,
    argument: (code.meta ?? "").trim(),
    options,
    body: lines.slice(consumed).join("\n"),
    at: { file, line: fenceLine },
    bodyAt: { file, line: fenceLine + 1 + consumed },
  };
}

class DocumentConverter implements ConvertContext {
  readonly file: string;
  readonly docsRoot: string;
  readonly collection: Collection;
  readonly pass: "collect" | "emit";
  readonly index: DocsIndex;
  private readonly knownBrokenLinks: ReadonlySet<string>;
  extensions: ReadonlySet<string> = new Set();
  readonly errors: ConverterError[] = [];
  readonly components = new Set<ComponentName>();
  readonly pageData = new Map<string, unknown>();
  readonly tags: string[] = [];
  readonly toctrees: ToctreeBlock[] = [];
  readonly toc: TocNode[] = [];
  private sections: { depth: number; node: TocSection }[] = [];
  private nesting = 0;
  readonly labels = new Map<string, LabelInfo>();
  readonly headingIds: string[] = [];
  title: string | undefined;
  titleId: string | undefined;
  private readonly registry: HandlerRegistry;
  private readonly ids = new IdAllocator();
  private pending: PendingLabel[] = [];
  private footnotes: PendingFootnote[] = [];
  private depth = 0;
  private attrs: { id: string; at: SourcePosition } | undefined;
  private explicitId: string | undefined;
  private readonly rawIds = new Map<string, SourcePosition>();
  readonly positions = new WeakMap<RootContent, SourcePosition>();

  constructor(request: ConvertRequest) {
    this.file = request.path;
    this.docsRoot = request.docsRoot;
    this.collection = collectionOf(request.path);
    this.pass = request.pass;
    this.index = request.index;
    this.registry = request.registry;
    this.knownBrokenLinks = request.knownBroken;
  }

  convertMarkdown(source: string, at: SourcePosition): RootContent[] {
    this.depth += 1;
    try {
      return this.convertSource(source, at.line - 1);
    } finally {
      this.depth -= 1;
    }
  }

  private convertSource(source: string, lineOffset: number): RootContent[] {
    const masked = preprocess(source);
    const tree = parseMarkdown(masked);
    return this.blocks(tree.children, { source: masked, lineOffset });
  }

  resolveDoc(target: string, at: SourcePosition, kind = "doc"): ResolvedDoc {
    let resolved: ResolvedDoc;
    try {
      resolved = this.index.resolveDoc(this.file, target, at, kind);
    } catch (error) {
      if (this.pass === "collect" && error instanceof UnresolvedReferenceError) return { path: target, route: "#", title: target };
      throw error;
    }
    return resolved;
  }

  findDoc(target: string): ResolvedDoc | undefined {
    return this.index.findDoc(this.file, target);
  }

  knownBroken(target: string): boolean {
    return this.knownBrokenLinks.has(`${routeFor(this.file)} ${target}`);
  }

  checkFragment(path: string, fragment: string, at: SourcePosition): void {
    if (this.pass === "collect") return;
    const info = this.index.get(path);
    if (!info) throw new UnresolvedReferenceError(at.file, at.line, `link:${path}#${fragment}`, "points at a missing document");
    if (info.ids.includes(fragment) || this.knownBroken(`${info.route}#${fragment}`)) return;
    throw new UnresolvedReferenceError(at.file, at.line, `link:${path}#${fragment}`, `is not an id on ${info.path}`);
  }

  resolveLabel(label: string, at: SourcePosition): ResolvedLabel {
    try {
      return this.index.resolveLabel(label, at);
    } catch (error) {
      if (this.pass === "collect" && error instanceof UnresolvedReferenceError) return { route: "#", id: label, title: label };
      throw error;
    }
  }

  queueLabel(label: string, at: SourcePosition): Html {
    const node: Html = { type: "html", value: "" };
    this.pending.push({ label, at, node });
    return node;
  }

  releaseLabels(): void {
    this.flushLabels(undefined);
  }

  needsTitle(): boolean {
    return this.title === undefined && this.depth === 0;
  }

  allocateHeadingId(text: string): string {
    const labels = this.flushLabels(text);
    const explicit = this.explicitId;
    this.explicitId = undefined;
    const own = this.ids.fromName(explicit ?? text);
    if (!AUTOMATIC_ID.test(own)) return own;
    const primary = [...labels].reverse().find((entry) => !AUTOMATIC_ID.test(entry.id));
    if (!primary) return own;
    primary.node.value = `<span id="${own}"></span>`;
    return primary.id;
  }

  claimTitle(text: string, id: string): void {
    this.title = text;
    this.titleId = id;
  }

  recordRawId(id: string, at: SourcePosition): void {
    if (this.rawIds.has(id)) throw new ConverterError(at.file, at.line, `raw html id ${JSON.stringify(id)} is already used on this page`);
    this.rawIds.set(id, at);
  }

  recordHeadingId(id: string): void {
    this.headingIds.push(id);
  }

  addTags(tags: readonly string[]): void {
    for (const tag of tags) if (!this.tags.includes(tag)) this.tags.push(tag);
  }

  addToctree(block: ToctreeBlock): void {
    this.tocParent().push({ kind: "toctree", block: this.toctrees.length });
    this.toctrees.push(block);
  }

  addSection(depth: number, title: string, id: string): void {
    if (this.depth > 0 || this.nesting > 0) return;
    while (this.sections.length > 0 && this.sections[this.sections.length - 1].depth >= depth) this.sections.pop();
    const first = this.sections.length === 0 && !this.toc.some((node) => node.kind === "section");
    const node: TocSection = { kind: "section", title, anchor: first ? "" : id, children: [] };
    this.tocParent().push(node);
    this.sections.push({ depth, node });
  }

  private tocParent(): TocNode[] {
    return this.sections.length > 0 ? this.sections[this.sections.length - 1].node.children : this.toc;
  }

  setPageData(key: string, value: unknown): void {
    this.pageData.set(key, value);
  }

  useComponent(name: ComponentName): void {
    this.components.add(name);
  }

  flushLabels(title: string | undefined): { id: string; node: Html }[] {
    const queued = this.pending;
    this.pending = [];
    return queued.map((entry) => {
      const id = this.ids.fromName(entry.label);
      entry.node.value = `<span id="${id}"></span>`;
      const info: LabelInfo = title === undefined ? { label: entry.label, id } : { label: entry.label, id, title };
      this.labels.set(entry.label, info);
      return { id, node: entry.node };
    });
  }

  private at(node: RootContent | PhrasingContent, frame: Frame): SourcePosition {
    return { file: this.file, line: (node.position?.start.line ?? 1) + frame.lineOffset };
  }

  private guard(run: () => RootContent[]): RootContent[] {
    try {
      return run();
    } catch (error) {
      if (error instanceof ConverterError) {
        this.errors.push(error);
        return [];
      }
      throw error;
    }
  }

  private blocks(children: RootContent[], frame: Frame): RootContent[] {
    const out: RootContent[] = [];
    const top = frame.lineOffset === 0 && this.depth === 0 && this.nesting === 0;
    for (const child of children) {
      const produced = this.guard(() => this.attributed(child, frame));
      if (top) for (const node of produced) this.positions.set(node, this.at(child, frame));
      out.push(...produced);
    }
    const dangling = this.attrs;
    this.attrs = undefined;
    if (dangling) this.errors.push(new UnknownConstructError(dangling.at.file, dangling.at.line, "syntax:attrs-block", "attrs block is not followed by a block it can attach to"));
    return mergeDefinitionLists(out);
  }

  private attributed(node: RootContent, frame: Frame): RootContent[] {
    const at = this.at(node, frame);
    const marker = node.type === "html" ? node.value.match(ATTRS_MARKER) : null;
    if (marker) {
      const pending = this.attrs;
      this.attrs = undefined;
      if (pending) throw new UnknownConstructError(pending.at.file, pending.at.line, "syntax:attrs-block", "attrs block is followed by another attrs block, which Sphinx would drop");
      if (!this.extensions.has("attrs_block")) throw new UnknownConstructError(at.file, at.line, "syntax:attrs-block", "attrs blocks need myst.enable_extensions: attrs_block");
      const id = marker[1].match(ATTRS_ID);
      if (!id) throw new UnknownConstructError(at.file, at.line, "syntax:attrs-block", `attrs block {${marker[1]}} is not supported; only a single {#id} is`);
      this.attrs = { id: id[1], at };
      return [];
    }
    const attrs = this.attrs;
    if (!attrs) return this.block(node, frame);
    this.attrs = undefined;
    if (node.type === "heading") {
      this.explicitId = attrs.id;
      return this.block(node, frame);
    }
    const directive = node.type === "code" && DIRECTIVE_LANG.test(node.lang ?? "");
    if (!ATTRIBUTABLE.has(node.type) || directive) {
      const target = directive ? "a directive" : node.type === "html" && LABEL_MARKER.test(node.value) ? "a label" : node.type;
      throw new UnknownConstructError(attrs.at.file, attrs.at.line, "syntax:attrs-block", `attrs block cannot attach to ${target}; Sphinx would drop it`);
    }
    this.releaseOnContent();
    const anchor: Html = { type: "html", value: `<span id="${this.ids.fromName(attrs.id)}"></span>` };
    return [anchor, ...this.block(node, frame)];
  }

  private block(node: RootContent, frame: Frame): RootContent[] {
    const at = this.at(node, frame);
    switch (node.type) {
      case "html":
        return this.html(node, at);
      case "heading": {
        if (this.depth > 0 || this.nesting > 0) {
          throw new UnknownConstructError(at.file, at.line, "syntax:nested-heading", "a heading inside a blockquote, list or directive body is a rubric in Sphinx, not a section; use bold text or move it out");
        }
        node.children = this.phrasing(node.children, frame);
        return this.registry.syntaxHandler("heading", at).handle(node, at, this);
      }
      case "paragraph":
        this.releaseOnContent();
        return this.paragraph(node, at, frame);
      case "code":
        this.releaseOnContent();
        return this.code(node, at, frame);
      case "definition":
        return this.registry.syntaxHandler("link", at).handle(node, at, this);
      case "yaml":
        return [];
      case "footnoteDefinition":
        this.releaseOnContent();
        return this.footnoteDefinition(node, at, frame);
      default:
        this.releaseOnContent();
        return this.container(node, at, frame);
    }
  }

  private footnoteDefinition(node: FootnoteDefinition, at: SourcePosition, frame: Frame): RootContent[] {
    const anchor: Html = { type: "html", value: "" };
    this.footnotes.push({ label: node.label ?? node.identifier, node: anchor });
    const [converted] = this.container(node, at, frame) as FootnoteDefinition[];
    const first = converted.children[0];
    if (first?.type === "paragraph") first.children.unshift(anchor);
    else converted.children.unshift(anchor);
    return [converted];
  }

  private releaseFootnotes(): void {
    for (const entry of this.footnotes.splice(0)) {
      const id = this.ids.fromName(entry.label);
      entry.node.value = `<span id="${id}"></span>`;
    }
  }

  private releaseOnContent(): void {
    if (this.pending.length > 0) this.flushLabels(undefined);
  }

  private html(node: Html, at: SourcePosition): RootContent[] {
    const misplaced = node.value.match(MISPLACED_MARKER);
    if (misplaced) {
      throw new UnknownConstructError(at.file, at.line, `syntax:misplaced-${misplaced[1]}`, `${misplaced[1]} line is indented four or more columns past its paragraph, where MyST reads it as plain text`);
    }
    if (node.value === COMMENT_MARKER) return this.registry.syntaxHandler("comment", at).handle(node, at, this);
    if (LABEL_MARKER.test(node.value)) return this.registry.syntaxHandler("label", at).handle(node, at, this);
    this.releaseOnContent();
    const name = node.value.startsWith("<!--") ? "html-comment" : "raw-html";
    return this.registry.syntaxHandler(name, at).handle(node, at, this);
  }

  private paragraph(node: Paragraph, at: SourcePosition, frame: Frame): RootContent[] {
    const raw = node.position ? frame.source.slice(node.position.start.offset, node.position.end.offset) : "";
    if (raw.split("\n").some((line) => line.trimStart().startsWith(":::"))) {
      node.children = this.phrasing(node.children, frame);
      return this.registry.syntaxHandler("colon-fence", at).handle(node, at, this);
    }
    if (this.extensions.has("deflist") && raw.split("\n").some((line, index) => index > 0 && /^:\s/.test(line))) {
      node.children = this.phrasing(node.children, frame);
      return this.registry.syntaxHandler("deflist", at).handle(node, at, this);
    }
    node.children = this.phrasing(node.children, frame);
    return [node];
  }

  private code(node: Code, at: SourcePosition, frame: Frame): RootContent[] {
    const directive = node.lang?.match(DIRECTIVE_LANG);
    if (!directive) return [node];
    const call = parseDirectiveBody(node, directive[1], frame.lineOffset, this.file);
    const handler = this.registry.directive(call.name, at);
    if (handler.argument === "none" && call.argument !== "") {
      throw new UnknownConstructError(at.file, at.line, `directive-argument:${call.name}`, `${call.name} takes no argument, got ${JSON.stringify(call.argument)}`);
    }
    if (handler.options !== "any") {
      for (const option of Object.keys(call.options)) {
        if (!handler.options.includes(option)) throw new UnknownConstructError(at.file, at.line, `directive-option:${call.name}:${option}`);
      }
    }
    return handler.handle(call, this);
  }

  private container(node: RootContent, at: SourcePosition, frame: Frame): RootContent[] {
    if (LEAF_TYPES.has(node.type)) return [node];
    if (node.type === "image" || node.type === "imageReference") return this.registry.syntaxHandler("image", at).handle(node, at, this);
    if (node.type === "thematicBreak") return [node];
    if (BLOCK_PARENTS.has(node.type) && "children" in node) {
      this.nesting += 1;
      try {
        (node as { children: RootContent[] }).children = this.blocks((node as { children: RootContent[] }).children, frame);
      } finally {
        this.nesting -= 1;
      }
      return [node];
    }
    if (PHRASING_PARENTS.has(node.type) && "children" in node) {
      (node as { children: PhrasingContent[] }).children = this.phrasing((node as { children: PhrasingContent[] }).children, frame);
      return [node];
    }
    throw new UnknownConstructError(at.file, at.line, `syntax:mdast-${node.type}`);
  }

  private phrasing(children: PhrasingContent[], frame: Frame): PhrasingContent[] {
    const out: PhrasingContent[] = [];
    for (let index = 0; index < children.length; index += 1) {
      const child = children[index];
      const next = children[index + 1];
      if (child.type === "text" && next?.type === "inlineCode") {
        const role = child.value.match(ROLE_SUFFIX);
        if (role) {
          const prefix = child.value.slice(0, child.value.length - role[0].length);
          const before = child.value.slice(0, prefix.length);
          const line = (child.position?.start.line ?? 1) + frame.lineOffset + before.split("\n").length - 1;
          if (prefix) out.push({ type: "text", value: prefix });
          out.push(...this.phrasingGuard(() => this.registry.role(role[1], { file: this.file, line }).handle({ name: role[1], content: next.value, at: { file: this.file, line } }, this)));
          index += 1;
          continue;
        }
      }
      out.push(...this.phrasingGuard(() => this.phrasingNode(child, frame)));
    }
    return out;
  }

  private phrasingGuard(run: () => PhrasingContent[]): PhrasingContent[] {
    try {
      return run();
    } catch (error) {
      if (error instanceof ConverterError) {
        this.errors.push(error);
        return [];
      }
      throw error;
    }
  }

  private phrasingNode(node: PhrasingContent, frame: Frame): PhrasingContent[] {
    const at = this.at(node, frame);
    switch (node.type) {
      case "text":
        if (node.value.includes("$$")) throw new UnknownConstructError(at.file, at.line, "syntax:math", "$$ math needs the dollarmath extension, which is not supported");
        return [node];
      case "inlineCode":
      case "break":
        return [node];
      case "footnoteReference":
        return [{ type: "html", value: `<span id="${this.ids.automatic()}"></span>` }, node];
      case "html": {
        if (MISPLACED_MARKER.test(node.value)) return this.html(node, at) as PhrasingContent[];
        if (node.value.startsWith("<!--benchbox-")) throw new UnknownConstructError(at.file, at.line, "syntax:inline-marker", "label, attrs or comment line in a position MyST does not read as a block");
        const name = node.value.startsWith("<!--") ? "html-comment" : "raw-html-inline";
        return this.registry.syntaxHandler(name, at).handle(node, at, this) as PhrasingContent[];
      }
      case "image":
      case "imageReference":
        return this.registry.syntaxHandler("image", at).handle(node, at, this) as PhrasingContent[];
      case "link": {
        node.children = this.phrasing(node.children, frame);
        return this.registry.syntaxHandler("link", at).handle(node, at, this) as PhrasingContent[];
      }
      case "emphasis":
      case "strong":
      case "delete":
      case "linkReference":
        node.children = this.phrasing(node.children, frame);
        return [node];
      default:
        throw new UnknownConstructError(at.file, at.line, `syntax:mdast-${(node as { type: string }).type}`);
    }
  }

  convertTree(tree: Root, source: string): RootContent[] {
    const body = this.blocks(tree.children, { source, lineOffset: 0 });
    this.releaseOnContent();
    this.releaseFootnotes();
    return body;
  }

  assemble(body: RootContent[]): ConvertedDocument {
    const generated = new Set(this.ids.all());
    for (const [id, at] of this.rawIds) {
      if (generated.has(id)) this.errors.push(new ConverterError(at.file, at.line, `raw html id ${JSON.stringify(id)} duplicates an id the page already generates`));
    }
    const frontTitle = this.pageData.get("title");
    const rawTitle = this.title ?? (typeof frontTitle === "string" ? frontTitle : undefined);
    const title = rawTitle === undefined ? undefined : smarten(rawTitle);
    if (title === undefined) {
      this.errors.push(new ConverterError(this.file, 1, "document has no title: add a first-level heading or a front matter title"));
    }
    this.pageData.delete("title");
    const tags = this.tags;
    const data: PageData = { title: title ?? this.file };
    const description = this.pageData.get("description");
    if (description !== undefined) data.description = description;
    this.pageData.delete("description");
    if (tags.length > 0) data.tags = [...tags];
    data.sourcePath = `docs/${this.file}`;
    if (this.titleId !== undefined) data.titleId = this.titleId;
    if (this.headingIds.length > 0) data.headingIds = [...this.headingIds];
    for (const key of [...this.pageData.keys()].sort()) data[key] = this.pageData.get(key);
    const info: DocInfo = {
      path: this.file,
      route: routeFor(this.file),
      title: title ?? this.file,
      collection: this.collection,
      labels: this.labels,
      ids: [...new Set([...this.ids.all(), ...this.rawIds.keys()])].sort(),
      toctrees: this.toctrees,
      toc: this.toc,
      tags: [...tags],
      orphan: this.pageData.get("orphan") === true,
    };
    return {
      path: this.file,
      contentId: contentIdFor(this.file),
      collection: this.collection,
      data,
      root: { type: "root", children: body },
      info,
      positions: this.positions,
      components: this.components,
      errors: this.errors,
    };
  }

  frontMatter(front: FrontMatter): void {
    const { data } = front;
    for (const [key, value] of Object.entries(data)) {
      const line = front.keyLines.get(key) ?? front.line;
      try {
        const at = { file: this.file, line };
        this.registry.frontMatterKey(key, at).handle(key, value, at, this);
      } catch (error) {
        if (!(error instanceof ConverterError)) throw error;
        this.errors.push(error);
      }
    }
    const myst = data.myst;
    const extensions = myst && typeof myst === "object" ? (myst as { enable_extensions?: unknown }).enable_extensions : undefined;
    this.extensions = new Set(Array.isArray(extensions) ? extensions.map(String) : []);
  }
}

export function convertDocument(request: ConvertRequest): ConvertedDocument {
  const converter = new DocumentConverter(request);
  const masked = preprocess(request.raw);
  const tree = parseMarkdown(masked);
  converter.frontMatter(parseFrontMatter(request.path, tree));
  const body = converter.convertTree(tree, masked);
  return converter.assemble(body);
}
