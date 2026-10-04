import { getCollection } from "astro:content";
import { buildAtomFeed } from "../../lib/atom.ts";
import { toPost } from "../../lib/blog.ts";

export async function GET() {
  const posts = (await getCollection("blog")).filter((entry) => entry.id !== "blog/index").map(toPost);
  return new Response(buildAtomFeed(posts), { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } });
}
