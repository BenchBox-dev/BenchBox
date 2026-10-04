import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { XMLParser, XMLValidator } from "fast-xml-parser";
import { parse } from "yaml";
import { describe, expect, it } from "vitest";
import { absoluteUrls, buildAtomFeed } from "../src/lib/atom.ts";
import { authorPath, slugify, tagGroups, tagPath, toPost, type BlogPost } from "../src/lib/blog.ts";

const websiteRoot = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const blogRoot = path.join(websiteRoot, "..", "docs", "blog");

type Link = { href: string; rel?: string };
type Reference = { id: string; links: Link[]; entries: { id: string; links: Link[] }[] };

const reference = JSON.parse(readFileSync(path.join(websiteRoot, "tests", "fixtures", "ablog-atom-ids.json"), "utf-8")) as Reference;

function loadPosts(): BlogPost[] {
  return readdirSync(blogRoot)
    .filter((name) => /^\d{4}-\d{2}-\d{2}-.+\.md$/.test(name))
    .map((name) => {
      const raw = readFileSync(path.join(blogRoot, name), "utf-8");
      const front = parse(/^---\n([\s\S]*?)\n---/.exec(raw)?.[1] ?? "") as Record<string, unknown>;
      const title = /^# (.+)$/m.exec(raw)?.[1] ?? name;
      return toPost({
        id: `blog/${name.replace(/\.md$/, "")}`,
        data: {
          title,
          date: String(front.date),
          author: typeof front.author === "string" ? front.author : undefined,
          tags: String(front.tags ?? "")
            .split(",")
            .map((tag) => tag.trim())
            .filter(Boolean),
          series: typeof front.series === "string" ? front.series : undefined,
        },
        rendered: { html: `<p>${title}</p>` },
      });
    });
}

const posts = loadPosts();
const feed = buildAtomFeed(posts);
const parser = new XMLParser({ ignoreAttributes: false, attributeNamePrefix: "@_", isArray: (name) => ["entry", "link", "category", "author"].includes(name) });
type Node = Record<string, unknown>;
const parsed = (parser.parse(feed) as { feed: Node }).feed;
const asList = (value: unknown): Node[] => (Array.isArray(value) ? (value as Node[]) : []);
const toLinks = (node: Node): Link[] => asList(node.link).map((link) => ({ href: String(link["@_href"]), ...(link["@_rel"] ? { rel: String(link["@_rel"]) } : {}) }));

describe("blog sources", () => {
  it("covers all sixteen posts", () => {
    expect(posts).toHaveLength(16);
  });
});

describe("atom feed matches the ablog feed", () => {
  it("keeps the feed id and links", () => {
    expect(parsed.id).toBe(reference.id);
    expect(toLinks(parsed)).toEqual(reference.links);
  });

  it("keeps every entry id and link, in order", () => {
    const entries = asList(parsed.entry);
    expect(entries.map((entry) => ({ id: entry.id, links: toLinks(entry) }))).toEqual(reference.entries);
  });
});

const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;
const text = (value: unknown): string => (typeof value === "object" && value !== null ? String((value as Node)["#text"] ?? "") : String(value ?? ""));

describe("atom feed is valid Atom 1.0", () => {
  it("is well-formed XML in the Atom namespace", () => {
    expect(XMLValidator.validate(feed)).toBe(true);
    expect(feed.startsWith('<?xml version="1.0" encoding="UTF-8"?>')).toBe(true);
    expect(parsed["@_xmlns"]).toBe("http://www.w3.org/2005/Atom");
  });

  it("has the feed elements RFC 4287 requires", () => {
    expect(text(parsed.id)).not.toBe("");
    expect(text(parsed.title)).not.toBe("");
    expect(text(parsed.updated)).toMatch(RFC3339);
    expect(toLinks(parsed).some((link) => link.rel === "self")).toBe(true);
    expect(asList(parsed.entry).length).toBeGreaterThan(0);
  });

  it("gives every entry an id, title, updated stamp, author, link and content", () => {
    const ids = new Set<string>();
    for (const entry of asList(parsed.entry)) {
      const id = text(entry.id);
      expect(id).toMatch(/^https:\/\//);
      expect(ids.has(id)).toBe(false);
      ids.add(id);
      expect(text(entry.title)).not.toBe("");
      expect(text(entry.updated)).toMatch(RFC3339);
      expect(text(entry.published)).toMatch(RFC3339);
      expect(asList(entry.author).every((author) => text(author.name) !== "")).toBe(true);
      expect(asList(entry.author).length).toBeGreaterThan(0);
      expect(toLinks(entry).length).toBeGreaterThan(0);
      const content = entry.content as Node;
      expect(content["@_type"]).toBe("html");
      expect(text(content)).not.toBe("");
      for (const category of asList(entry.category)) expect(category["@_term"]).toBeTruthy();
    }
  });

  it("uses Atom elements, not RSS", () => {
    expect(feed).not.toMatch(/<rss|<channel|<item>|<pubDate>/);
  });

  it("escapes markup in content and titles", () => {
    const risky = toPost({ id: "blog/2026-01-01-x", data: { title: "A <b> & \"q\"", date: "Jan 1, 2026" }, rendered: { html: '<p><a href="/docs/x.html">x</a> & y</p>' } });
    const output = buildAtomFeed([risky]);
    expect(XMLValidator.validate(output)).toBe(true);
    expect(output).toContain("A &lt;b&gt; &amp; &quot;q&quot;");
    expect(output).toContain("https://benchbox.dev/docs/x.html");
  });
});

describe("blog urls", () => {
  it("makes site-absolute links absolute without touching other targets", () => {
    expect(absoluteUrls('<a href="/a.html">a</a><a href="//cdn/x">b</a><img src="/_images/i.png"><a href="https://e.org/">c</a>')).toBe(
      '<a href="https://benchbox.dev/a.html">a</a><a href="//cdn/x">b</a><img src="https://benchbox.dev/_images/i.png"><a href="https://e.org/">c</a>',
    );
  });

  it("slugs tags, authors and versions as ablog does", () => {
    expect(slugify("v0.2.1")).toBe("v021");
    expect(slugify("Joe Harris")).toBe("joe-harris");
    expect(slugify("approximate-analytics")).toBe("approximate-analytics");
    expect(tagPath("duckdb-wasm")).toBe("/blog/tag/duckdb-wasm.html");
    expect(authorPath("Joe Harris")).toBe("/blog/author/joe-harris.html");
  });

  it("groups posts under every tag, newest first", () => {
    const groups = tagGroups(posts);
    expect(groups.get("duckdb")?.map((post) => post.slug)).toEqual(["2026-05-18-sketch-functions-databricks-response", "2026-03-03-duckdb-tpch-extension-vs-benchbox"]);
    expect(groups.size).toBe(64);
  });
});

describe("editorial drafts", () => {
  it("never reach the feed or the post list", () => {
    const draftsRoot = path.join(websiteRoot, "..", "_blog");
    const drafts = readdirSync(draftsRoot, { recursive: true, encoding: "utf-8" })
      .filter((entry) => entry.endsWith(".md"))
      .map((entry) => path.basename(entry, ".md"));
    expect(drafts.length).toBeGreaterThan(0);
    const published = new Set(posts.map((post) => post.slug));
    for (const draft of drafts) {
      expect(published.has(draft)).toBe(false);
      expect(feed).not.toContain(draft);
    }
  });

  it("are not read by any site source", () => {
    const sources = ["astro.config.ts", "src/content.config.ts", "src/converter/sources.ts"].map((file) => readFileSync(path.join(websiteRoot, file), "utf-8"));
    for (const source of sources) expect(source).not.toMatch(/_blog/);
  });
});
