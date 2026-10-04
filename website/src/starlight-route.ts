import { defineRouteMiddleware } from "@astrojs/starlight/route-data";
import { editUrlFor } from "./lib/edit-url.ts";

export const onRequest = defineRouteMiddleware((context) => {
  const route = context.locals.starlightRoute;
  const sourcePath = (route.entry.data as { sourcePath?: string }).sourcePath;
  const url = editUrlFor(sourcePath);
  route.editUrl = url ? new URL(url) : undefined;
});
