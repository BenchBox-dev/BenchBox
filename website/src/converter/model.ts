export type SourcePosition = { file: string; line: number };

export type Collection = "docs" | "blog";

export type ToctreeEntry =
  | { kind: "doc"; path: string; title?: string }
  | { kind: "url"; url: string; title: string }
  | { kind: "self"; title?: string };

export type ToctreeBlock = {
  at: SourcePosition;
  caption?: string;
  maxdepth?: number;
  hidden: boolean;
  titlesonly: boolean;
  includehidden: boolean;
  entries: ToctreeEntry[];
};

export type TocSection = { kind: "section"; title: string; anchor: string; children: TocNode[] };

export type TocNode = TocSection | { kind: "toctree"; block: number };

export type LabelInfo = { label: string; id: string; title?: string };

export type DocInfo = {
  path: string;
  route: string;
  title: string;
  format: "md" | "rst";
  collection: Collection;
  labels: Map<string, LabelInfo>;
  ids: string[];
  toctrees: ToctreeBlock[];
  toc: TocNode[];
  tags: string[];
  orphan: boolean;
};

export type ResolvedDoc = { path: string; route: string; title: string };

export type ResolvedLabel = { route: string; id: string; title?: string };

export type PageData = Record<string, unknown>;
