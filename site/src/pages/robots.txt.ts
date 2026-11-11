import type { APIRoute } from 'astro';
import { SITE_URL } from '../lib/site';

// Open to every crawler and agent; the docs are meant to be read.
export const GET: APIRoute = () =>
  new Response(`User-agent: *\nAllow: /\n\nSitemap: ${SITE_URL}/sitemap.xml\n`, { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
