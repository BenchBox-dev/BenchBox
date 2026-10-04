export function htmlSitemapUrl(url: string): string {
  const { pathname } = new URL(url);
  if (pathname === "/" || pathname.endsWith(".html")) return url;
  return `${url.replace(/\/$/, "")}.html`;
}
