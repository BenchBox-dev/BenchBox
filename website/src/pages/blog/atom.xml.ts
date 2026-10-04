import { buildAtomFeed } from "../../lib/atom.ts";
import { loadBlog } from "../../lib/blog-posts.ts";

export async function GET() {
  const posts = (await loadBlog()).published;
  return new Response(buildAtomFeed(posts), { headers: { "Content-Type": "application/atom+xml; charset=utf-8" } });
}
