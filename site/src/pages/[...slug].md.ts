// The .md twin of every page: the release's Markdown file as it is, with its links pointing at the site's other
// .md twins (absolute URLs, so an agent can follow them).
import type { APIRoute } from 'astro';
import { getCollection } from 'astro:content';
import { hubs } from '../lib/hubs';
import { rewriteMarkdown, slugOf } from '../lib/site';

export async function getStaticPaths() {
  const entries = await getCollection('docs');
  const pages = entries
    .filter((e) => slugOf(e.id) !== null)
    .map((e) => ({ params: { slug: slugOf(e.id) || 'index' }, props: { text: rewriteMarkdown(e.body ?? '', e.id) } }));
  const extra = (await hubs()).map((h) => ({ params: { slug: h.slug }, props: { text: h.markdown } }));
  return [...pages, ...extra];
}

export const GET: APIRoute = ({ props }) =>
  new Response(props.text, { headers: { 'Content-Type': 'text/markdown; charset=utf-8' } });
