import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { htmlUrl, SITE_URL, slugOf } from '../lib/site';

export const GET: APIRoute = async () => {
  const slugs = (await getCollection('docs')).map((e) => slugOf(e.id)).filter((s): s is string => s !== null);
  const urls = [...new Set([...slugs, 'guides', 'printers'])].sort().map((s) => `<url><loc>${SITE_URL}${htmlUrl(s)}</loc></url>`);
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls.join('\n')}\n</urlset>\n`;
  return new Response(xml, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
};
