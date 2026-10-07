import { getCollection } from "astro:content";
import { splitDrafts, toPost, type BlogPost } from "./blog.ts";

export async function loadBlog(now: Date = new Date()): Promise<{ published: BlogPost[]; drafts: BlogPost[] }> {
  const entries = (await getCollection("blog")).filter((entry) => entry.data.blogpost === true);
  return splitDrafts(entries.map(toPost), now);
}
