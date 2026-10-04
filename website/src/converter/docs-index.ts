import { readFileSync } from "node:fs";
import { ConverterError, UnresolvedReferenceError } from "./errors.ts";
import type { Collection, DocInfo, LabelInfo, ResolvedDoc, ResolvedLabel, SourcePosition } from "./model.ts";
import type { DocSourceFile } from "./sources.ts";
import { rstTags } from "./tag-pages.ts";

export function stemOf(relative: string): string {
  return relative.replace(/\.(md|rst)$/, "");
}

export function collectionOf(relative: string): Collection {
  return relative.startsWith("blog/") ? "blog" : "docs";
}

export function routeFor(relative: string): string {
  const stem = stemOf(relative);
  return collectionOf(relative) === "blog" ? `/${stem}.html` : `/docs/${stem}.html`;
}

export function contentIdFor(relative: string): string {
  const stem = stemOf(relative);
  return collectionOf(relative) === "blog" ? stem : `docs/${stem}`;
}

export function rstTitle(raw: string): string | undefined {
  const lines = raw.split("\n");
  for (let index = 1; index < lines.length; index += 1) {
    const underline = lines[index].trim();
    const title = lines[index - 1].trim();
    if (title && underline.length >= title.length && /^([=\-~^"#*+])\1+$/.test(underline)) return title;
  }
  return undefined;
}

export function placeholderInfo(source: { relative: string }, format: "md" | "rst"): DocInfo {
  return {
    path: source.relative,
    route: routeFor(source.relative),
    title: stemOf(source.relative).split("/").pop() ?? source.relative,
    format,
    collection: collectionOf(source.relative),
    labels: new Map(),
    ids: [],
    toctrees: [],
    toc: [],
    tags: [],
    orphan: false,
  };
}

export class DocsIndex {
  private readonly docs = new Map<string, DocInfo>();
  private readonly labels = new Map<string, { path: string; info: LabelInfo }>();

  constructor(infos: Iterable<DocInfo>) {
    for (const info of infos) {
      this.docs.set(info.path, info);
      for (const [name, label] of info.labels) {
        const existing = this.labels.get(name);
        if (existing && existing.path !== info.path) {
          throw new ConverterError(info.path, 1, `label ${name} is already defined in ${existing.path}`);
        }
        this.labels.set(name, { path: info.path, info: label });
      }
    }
  }

  static fromRstSources(sources: DocSourceFile[]): DocInfo[] {
    return sources.map((source) => {
      const info = placeholderInfo(source, "rst");
      const raw = readFileSync(source.absolute, "utf-8");
      info.title = rstTitle(raw) ?? info.title;
      info.tags = rstTags(raw);
      return info;
    });
  }

  paths(): string[] {
    return [...this.docs.keys()].sort();
  }

  get(path: string): DocInfo | undefined {
    return this.docs.get(path);
  }

  findDoc(from: string, target: string): ResolvedDoc | undefined {
    const stem = this.stemFor(from, target);
    if (stem === undefined) return undefined;
    for (const candidate of [`${stem}.md`, `${stem}.rst`]) {
      const info = this.docs.get(candidate);
      if (info) return { path: info.path, route: info.route, title: info.title };
    }
    return undefined;
  }

  private stemFor(from: string, target: string): string | undefined {
    const cleaned = target.replace(/\.(md|rst)$/, "");
    const segments = cleaned.startsWith("/") ? cleaned.slice(1).split("/") : [...from.split("/").slice(0, -1), ...cleaned.split("/")];
    const resolved: string[] = [];
    for (const segment of segments) {
      if (segment === "..") {
        if (resolved.pop() === undefined) return undefined;
      } else if (segment !== "." && segment !== "") resolved.push(segment);
    }
    return resolved.join("/");
  }

  resolveDoc(from: string, target: string, at: SourcePosition, kind = "doc"): ResolvedDoc {
    const found = this.findDoc(from, target);
    if (found) return found;
    const stem = this.stemFor(from, target);
    const detail = stem === undefined ? "points outside docs/" : `does not match a document under docs/ (looked for ${stem}.md)`;
    throw new UnresolvedReferenceError(at.file, at.line, `${kind}:${target}`, detail);
  }

  resolveLabel(label: string, at: SourcePosition): ResolvedLabel {
    const found = this.labels.get(label);
    if (!found) throw new UnresolvedReferenceError(at.file, at.line, `ref:${label}`, "does not match any label");
    const info = this.docs.get(found.path);
    if (!info) throw new UnresolvedReferenceError(at.file, at.line, `ref:${label}`, "points at a missing document");
    return { route: info.route, id: found.info.id, title: found.info.title };
  }
}
