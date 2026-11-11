// The release's llms.txt and llms-full.txt (tools/gen_llms_full.py writes the latter), with their links pointing
// at the site's .md pages instead of repository paths. No second copy is kept.
import type { APIRoute } from 'astro';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { rewriteMarkdown, TREE } from '../lib/site';

export const llms = (name: 'llms.txt' | 'llms-full.txt') => rewriteMarkdown(readFileSync(join(TREE, name), 'utf8'), name);

export const GET: APIRoute = () => new Response(llms('llms.txt'), { headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
