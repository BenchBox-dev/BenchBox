import { defineRouteMiddleware } from "@astrojs/starlight/route-data";
import { editUrlFor } from "./lib/edit-url.ts";
import { pageMeta } from "./lib/page-meta.ts";

export const onRequest = defineRouteMiddleware((context) => {
  const route = context.locals.starlightRoute;
  const sourcePath = (route.entry.data as { sourcePath?: string }).sourcePath;
  const url = editUrlFor(sourcePath);
  route.editUrl = url ? new URL(url) : undefined;

  for (const entry of route.head) {
    if (entry.attrs?.rel === "sitemap") entry.attrs.href = "/sitemap.xml";
  }

  const title = route.entry.data.title;
  const description = route.entry.data.description ?? `${title} - BenchBox documentation.`;
  const present = new Set(route.head.map((entry) => entry.attrs?.name ?? entry.attrs?.property ?? entry.attrs?.rel));
  for (const entry of pageMeta({ title, description, pathname: context.url.pathname, type: "article", card: "summary_large_image" })) {
    const key = entry.attrs.name ?? entry.attrs.property ?? entry.attrs.rel;
    if (!present.has(key)) route.head.push({ tag: entry.tag, attrs: entry.attrs, content: "" });
  }
});
