import { statSync, type Stats } from "node:fs";
import path from "node:path";
import { routeFor } from "../docs-index.ts";
import { UnresolvedReferenceError } from "../errors.ts";
import type { Link, PhrasingContent } from "mdast";
import type { SourcePosition } from "../model.ts";
import type { ConvertContext, SyntaxHandler } from "../types.ts";

const SCHEME = /^[a-z][a-z0-9+.-]*:/i;
const DOC_SUFFIX = /\.(md|rst)$/;
const REPOSITORY_URL = "https://github.com/BenchBox-dev/BenchBox";
const REPOSITORY_REF = "develop";

function decode(target: string): string {
  try {
    return decodeURI(target);
  } catch {
    return target;
  }
}

function statOf(absolute: string): Stats | undefined {
  try {
    return statSync(absolute);
  } catch {
    return undefined;
  }
}

function withFragment(url: string, fragment: string): string {
  return fragment === "" ? url : `${url}#${fragment}`;
}

function repositoryTarget(absolute: string, docsRoot: string, fragment: string, unresolved: (detail: string) => UnresolvedReferenceError): string {
  const relative = path.relative(path.dirname(docsRoot), absolute).split(path.sep).join("/");
  const stats = statOf(absolute);
  if (relative.startsWith("..") || stats === undefined) throw unresolved("does not match a file in the repository");
  const kind = stats.isDirectory() ? "tree" : "blob";
  return withFragment(relative === "" ? `${REPOSITORY_URL}/tree/${REPOSITORY_REF}` : `${REPOSITORY_URL}/${kind}/${REPOSITORY_REF}/${relative}`, fragment);
}

export const UNBUILT_TARGETS: Readonly<Record<string, string>> = {
  "blog/archive.html": "ablog archive page; the Astro blog does not build it yet",
  "blog/tag.html": "ablog tag index; the Astro blog does not build it yet",
  "blog/author.html": "ablog author index; the Astro blog does not build it yet",
};

type Resolution = { url: string; title?: string } | { unbuilt: string };

function resolveTarget(target: string, context: ConvertContext, at: SourcePosition, fragment: string): Resolution {
  const unresolved = (detail: string): UnresolvedReferenceError => new UnresolvedReferenceError(at.file, at.line, `link:${withFragment(target, fragment)}`, detail);
  const absolute = target.startsWith("/") ? path.join(context.docsRoot, target) : path.resolve(context.docsRoot, path.dirname(context.file), target);
  const insideDocs = path.relative(context.docsRoot, absolute);
  if (insideDocs.startsWith("..") || path.isAbsolute(insideDocs)) return { url: repositoryTarget(absolute, context.docsRoot, fragment, unresolved) };
  const relative = insideDocs.split(path.sep).join("/");
  if (relative in UNBUILT_TARGETS) return { unbuilt: relative };
  if (DOC_SUFFIX.test(target)) {
    const resolved = context.resolveDoc(target, at, "link");
    if (fragment !== "") context.checkFragment(resolved.path, fragment, at);
    return fragment === "" ? { url: resolved.route, title: resolved.title } : { url: withFragment(resolved.route, fragment) };
  }
  const doc = context.findDoc(target);
  if (doc) {
    if (fragment !== "") throw unresolved("names a document without its suffix, which Sphinx cannot resolve with a fragment; link to the .md file");
    return { url: doc.route, title: doc.title };
  }
  const stats = statOf(absolute);
  if (stats?.isFile()) return { url: repositoryTarget(absolute, context.docsRoot, fragment, unresolved) };
  const index = stats?.isDirectory() ? context.findDoc(`${target.replace(/\/+$/, "")}/index`) : undefined;
  if (index && fragment === "") return { url: index.route, title: index.title };
  throw unresolved("does not match a document or file under docs/");
}

function isEmpty(node: Link): boolean {
  return node.children.every((child) => child.type === "text" && child.value.trim() === "");
}

function emptyText(node: Link, at: SourcePosition, detail: string): UnresolvedReferenceError {
  return new UnresolvedReferenceError(at.file, at.line, `link:${node.url}`, `has no link text and ${detail}; write the text`);
}

function localLink(node: Link, fragment: string, at: SourcePosition, context: ConvertContext): PhrasingContent[] {
  if (!isEmpty(node)) {
    context.checkFragment(context.file, fragment, at);
    return [node];
  }
  if (context.pass === "collect") return [node];
  const label = context.index.get(context.file)?.labels.get(fragment);
  if (label?.title === undefined) throw emptyText(node, at, "MyST fills empty text only from a label on a heading");
  node.url = `#${label.id}`;
  node.children = [{ type: "text", value: label.title }];
  return [node];
}

export const linkSyntax: SyntaxHandler<"link"> = {
  kind: "syntax",
  name: "link",
  handle(node, at, context) {
    const link = node.type === "link" ? node : undefined;
    if (SCHEME.test(node.url)) {
      if (link && isEmpty(link)) throw emptyText(link, at, "points outside the site");
      return [node];
    }
    const hash = node.url.indexOf("#");
    const target = hash < 0 ? node.url : node.url.slice(0, hash);
    const fragment = hash < 0 ? "" : node.url.slice(hash + 1);
    if (target === "" && link) return localLink(link, fragment, at, context);
    if (target === "") {
      context.checkFragment(context.file, fragment, at);
      return [node];
    }
    if (context.pass === "collect") return [node];
    let resolution: Resolution;
    try {
      resolution = resolveTarget(decode(target), context, at, fragment);
    } catch (error) {
      if (!(error instanceof UnresolvedReferenceError) || !context.knownBroken(`${routeFor(context.file)}#${node.url}`)) throw error;
      if (link && isEmpty(link)) throw emptyText(link, at, "its target is broken");
      return [node];
    }
    if ("unbuilt" in resolution) {
      if (!link) throw new UnresolvedReferenceError(at.file, at.line, `link:${node.url}`, `points at ${resolution.unbuilt}, which is not built: ${UNBUILT_TARGETS[resolution.unbuilt]}`);
      return link.children;
    }
    if (link && isEmpty(link)) {
      if (resolution.title === undefined) throw emptyText(link, at, "MyST fills empty text only for a whole page");
      link.children = [{ type: "text", value: resolution.title }];
    }
    node.url = resolution.url;
    return [node];
  },
};
