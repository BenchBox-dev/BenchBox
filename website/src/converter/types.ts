import type { TitleNode } from "../lib/smartypants.ts";
import type { Definition, Heading, Html, Image, ImageReference, Link, Paragraph, PhrasingContent, RootContent } from "mdast";
import type { DocsIndex } from "./docs-index.ts";
import type { Collection, ResolvedDoc, ResolvedLabel, SourcePosition, ToctreeBlock } from "./model.ts";

export type ComponentName = "Callout" | "Mermaid" | "Embed";

export type DirectiveCall = {
  name: string;
  argument: string;
  options: Readonly<Record<string, string>>;
  body: string;
  at: SourcePosition;
  bodyAt: SourcePosition;
};

export type RoleCall = {
  name: string;
  content: string;
  at: SourcePosition;
};

export interface ConvertContext {
  readonly file: string;
  readonly docsRoot: string;
  readonly collection: Collection;
  readonly pass: "collect" | "emit";
  readonly extensions: ReadonlySet<string>;
  readonly index: DocsIndex;
  convertMarkdown(source: string, at: SourcePosition): RootContent[];
  resolveDoc(target: string, at: SourcePosition, kind?: string): ResolvedDoc;
  findDoc(target: string): ResolvedDoc | undefined;
  checkFragment(path: string, fragment: string, at: SourcePosition): void;
  knownBroken(target: string): boolean;
  resolveLabel(label: string, at: SourcePosition): ResolvedLabel;
  queueLabel(label: string, at: SourcePosition): Html;
  releaseLabels(): void;
  needsTitle(): boolean;
  allocateHeadingId(text: string, title: TitleNode[]): string;
  claimTitle(title: TitleNode[], id: string): void;
  recordHeadingId(id: string): void;
  recordRawId(id: string, at: SourcePosition): void;
  addTags(tags: readonly string[]): void;
  addToctree(block: ToctreeBlock): void;
  addSection(depth: number, title: TitleNode[], id: string): void;
  setPageData(key: string, value: unknown): void;
  useComponent(name: ComponentName): void;
}

export type DirectiveHandler = {
  kind: "directive";
  names: readonly string[];
  options: readonly string[] | "any";
  argument: "none" | "accepted";
  handle(call: DirectiveCall, context: ConvertContext): RootContent[];
};

export type RoleHandler = {
  kind: "role";
  names: readonly string[];
  handle(call: RoleCall, context: ConvertContext): PhrasingContent[];
};

export type FrontMatterHandler = {
  kind: "front-matter";
  keys: readonly string[];
  handle(key: string, value: unknown, at: SourcePosition, context: ConvertContext): void;
};

export type SyntaxNodes = {
  label: Html;
  heading: Heading;
  link: Link | Definition;
  image: Image | ImageReference;
  comment: Html;
  "html-comment": Html;
  "raw-html": Html;
  "raw-html-inline": Html;
  deflist: Paragraph;
  "colon-fence": Paragraph;
};

export type SyntaxName = keyof SyntaxNodes;

export type SyntaxHandler<N extends SyntaxName = SyntaxName> = {
  kind: "syntax";
  name: N;
  handle(node: SyntaxNodes[N], at: SourcePosition, context: ConvertContext): RootContent[];
};

export type Handler = DirectiveHandler | RoleHandler | FrontMatterHandler | SyntaxHandler;
