import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { XMLParser, XMLValidator } from "fast-xml-parser";
import { describe, expect, it } from "vitest";

const websiteRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const feedPath = path.join(websiteRoot, "dist", "blog", "atom.xml");

type Link = { href: string; rel?: string };
type Node = Record<string, unknown>;

const reference = JSON.parse(readFileSync(path.join(websiteRoot, "tests", "fixtures", "ablog-atom-ids.json"), "utf-8")) as { id: string; links: Link[]; entries: { id: string; links: Link[] }[] };

const links = (node: Node): Link[] =>
  (Array.isArray(node.link) ? (node.link as Node[]) : []).map((link) => ({ href: String(link["@_href"]), ...(link["@_rel"] ? { rel: String(link["@_rel"]) } : {}) }));

describe.skipIf(!existsSync(feedPath))("built dist/blog/atom.xml", () => {
  it("exists", () => {
    expect(existsSync(feedPath)).toBe(true);
  });

  const xml = existsSync(feedPath) ? readFileSync(feedPath, "utf-8") : "";
  const parsed = (new XMLParser({ ignoreAttributes: false, isArray: (name) => ["entry", "link"].includes(name) }).parse(xml) as { feed: Node }).feed ?? {};

  it("is well-formed Atom", () => {
    expect(XMLValidator.validate(xml)).toBe(true);
    expect(parsed["@_xmlns"]).toBe("http://www.w3.org/2005/Atom");
  });

  it("has the ids and links of the ablog feed", () => {
    expect(parsed.id).toBe(reference.id);
    expect(links(parsed)).toEqual(reference.links);
    const entries = Array.isArray(parsed.entry) ? (parsed.entry as Node[]) : [];
    expect(entries.map((entry) => ({ id: entry.id, links: links(entry) }))).toEqual(reference.entries);
  });

  it("holds plain code blocks without scripts, stylesheets or buttons", () => {
    expect(xml).not.toMatch(/&lt;(script|link|button)|style=&quot;--|_astro\//);
  });
});
