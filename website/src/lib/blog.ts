export const BLOG_TITLE = "BenchBox Blog";
export const BLOG_BASE_URL = "https://benchbox.dev/blog/";
export const FEED_LENGTH = 10;
export const DEFAULT_AUTHOR = "Joe Harris";

export const AUTHORS: Readonly<Record<string, string>> = {
  "Joe Harris": "https://github.com/joeharris76",
};

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export type BlogPost = {
  slug: string;
  title: string;
  date: Date;
  author: string;
  tags: string[];
  series?: string;
  description?: string;
  html?: string;
};

export type PostSource = {
  id: string;
  data: { title: string; blogpost?: boolean; date?: string; author?: string; tags?: string[]; series?: string; description?: string };
  rendered?: { html: string };
};

export function parseBlogDate(value: string): Date {
  const match = /^([A-Za-z]+)\.?\s+(\d{1,2}),\s*(\d{4})$/.exec(value.trim());
  if (!match) throw new Error(`unrecognised blog date: ${value}`);
  const month = MONTHS.findIndex((name) => name.toLowerCase().startsWith(match[1].toLowerCase().slice(0, 3)));
  if (month < 0) throw new Error(`unrecognised blog month: ${value}`);
  return new Date(Date.UTC(Number(match[3]), month, Number(match[2])));
}

export function formatBlogDate(date: Date): string {
  return `${MONTHS[date.getUTCMonth()]} ${String(date.getUTCDate()).padStart(2, "0")}, ${date.getUTCFullYear()}`;
}

export function atomTimestamp(date: Date): string {
  return `${date.toISOString().slice(0, 19)}+00:00`;
}

export function slugify(value: string): string {
  return value
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}_\s-]/gu, "")
    .trim()
    .toLowerCase()
    .replace(/[-\s]+/g, "-");
}

export function feedCategory(tag: string): string {
  return tag.replace(/ /g, "");
}

export function startOfTomorrow(now: Date): Date {
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1));
}

export function splitDrafts(posts: readonly BlogPost[], now: Date = new Date()): { published: BlogPost[]; drafts: BlogPost[] } {
  const cutoff = startOfTomorrow(now).getTime();
  return {
    published: posts.filter((post) => post.date.getTime() < cutoff),
    drafts: posts.filter((post) => post.date.getTime() >= cutoff),
  };
}

export function toPost(source: PostSource): BlogPost {
  if (source.data.date === undefined) throw new Error(`blog post ${source.id} has no date`);
  return {
    slug: source.id.replace(/^blog\//, ""),
    title: source.data.title,
    date: parseBlogDate(source.data.date),
    author: source.data.author ?? DEFAULT_AUTHOR,
    tags: source.data.tags ?? [],
    series: source.data.series,
    description: source.data.description,
    html: source.rendered?.html,
  };
}

export function postPath(post: Pick<BlogPost, "slug">): string {
  return `/blog/${post.slug}.html`;
}

export function tagPath(tag: string): string {
  return `/blog/tag/${slugify(tag)}.html`;
}

export function authorPath(author: string): string {
  return `/blog/author/${slugify(author)}.html`;
}

export function yearPath(year: number | string): string {
  return `/blog/${year}.html`;
}

export function newestFirst(posts: readonly BlogPost[]): BlogPost[] {
  return [...posts].sort((a, b) => b.date.getTime() - a.date.getTime() || (a.title < b.title ? 1 : a.title > b.title ? -1 : 0));
}

export function oldestFirst(posts: readonly BlogPost[]): BlogPost[] {
  return newestFirst(posts).reverse();
}

export function groupBy(posts: readonly BlogPost[], keys: (post: BlogPost) => string[]): Map<string, BlogPost[]> {
  const groups = new Map<string, BlogPost[]>();
  for (const post of newestFirst(posts)) {
    for (const key of new Set(keys(post))) groups.set(key, [...(groups.get(key) ?? []), post]);
  }
  return groups;
}

export function tagGroups(posts: readonly BlogPost[]): Map<string, BlogPost[]> {
  const byTag = new Map<string, { label: string; posts: BlogPost[] }>();
  for (const post of newestFirst(posts)) {
    for (const tag of post.tags) {
      const key = slugify(tag);
      if (key === "") continue;
      const entry = byTag.get(key) ?? { label: tag, posts: [] };
      if (!entry.posts.includes(post)) entry.posts.push(post);
      byTag.set(key, entry);
    }
  }
  return new Map([...byTag.values()].sort((a, b) => (a.label < b.label ? -1 : a.label > b.label ? 1 : 0)).map((entry) => [entry.label, entry.posts]));
}

export function yearGroups(posts: readonly BlogPost[]): Map<string, BlogPost[]> {
  return groupBy(posts, (post) => [String(post.date.getUTCFullYear())]);
}

export function authorGroups(posts: readonly BlogPost[]): Map<string, BlogPost[]> {
  return groupBy(posts, (post) => [post.author]);
}

export type Neighbours = { previous?: BlogPost; next?: BlogPost };

export function neighbours(posts: readonly BlogPost[], post: BlogPost): Neighbours {
  const ordered = oldestFirst(posts);
  const position = ordered.findIndex((candidate) => candidate.slug === post.slug);
  if (position < 0) return {};
  return { previous: ordered[position - 1], next: ordered[position + 1] };
}

export function seriesOf(posts: readonly BlogPost[], post: BlogPost): BlogPost[] {
  if (post.series === undefined) return [];
  return oldestFirst(posts.filter((candidate) => candidate.series === post.series));
}

export function seriesTitle(series: string): string {
  return series
    .split("-")
    .map((word) => (word === "benchbox" ? "BenchBox" : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(" ");
}
