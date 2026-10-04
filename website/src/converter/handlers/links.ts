import { statSync, type Stats } from "node:fs";
import path from "node:path";
import { routeFor } from "../docs-index.ts";
import { UnresolvedReferenceError } from "../errors.ts";
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

function resolveTarget(target: string, context: ConvertContext, at: SourcePosition, fragment: string): string {
  const unresolved = (detail: string): UnresolvedReferenceError => new UnresolvedReferenceError(at.file, at.line, `link:${withFragment(target, fragment)}`, detail);
  const absolute = target.startsWith("/") ? path.join(context.docsRoot, target) : path.resolve(context.docsRoot, path.dirname(context.file), target);
  const insideDocs = path.relative(context.docsRoot, absolute);
  if (insideDocs.startsWith("..") || path.isAbsolute(insideDocs)) return repositoryTarget(absolute, context.docsRoot, fragment, unresolved);
  if (DOC_SUFFIX.test(target)) {
    const resolved = context.resolveDoc(target, at, "link");
    if (fragment !== "") context.checkFragment(resolved.path, fragment, at);
    return withFragment(resolved.route, fragment);
  }
  const doc = context.findDoc(target);
  if (doc) {
    if (fragment !== "") throw unresolved("names a document without its suffix, which Sphinx cannot resolve with a fragment; link to the .md file");
    return doc.route;
  }
  const stats = statOf(absolute);
  if (stats?.isFile()) return withFragment(target, fragment);
  const index = stats?.isDirectory() ? context.findDoc(`${target.replace(/\/+$/, "")}/index`) : undefined;
  if (index && fragment === "") return index.route;
  throw unresolved("does not match a document or file under docs/");
}

export const linkSyntax: SyntaxHandler<"link"> = {
  kind: "syntax",
  name: "link",
  handle(node, at, context) {
    if (SCHEME.test(node.url)) return [node];
    const hash = node.url.indexOf("#");
    const target = hash < 0 ? node.url : node.url.slice(0, hash);
    const fragment = hash < 0 ? "" : node.url.slice(hash + 1);
    if (target === "") {
      context.checkFragment(context.file, fragment, at);
      return [node];
    }
    if (context.pass === "collect") return [node];
    try {
      node.url = resolveTarget(decode(target), context, at, fragment);
    } catch (error) {
      if (!(error instanceof UnresolvedReferenceError) || !context.knownBroken(`${routeFor(context.file)}#${node.url}`)) throw error;
    }
    return [node];
  },
};
