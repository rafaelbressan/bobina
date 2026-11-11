// The JSON schemas of the release (docs/schemas/*.json), served as they are.
import type { APIRoute } from 'astro';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { TREE } from '../../lib/site';

const DIR = join(TREE, 'docs', 'schemas');

export function getStaticPaths() {
  return readdirSync(DIR)
    .filter((f) => f.endsWith('.json'))
    .map((f) => ({ params: { name: f.slice(0, -5) } }));
}

export const GET: APIRoute = ({ params }) =>
  new Response(readFileSync(join(DIR, `${params.name}.json`), 'utf8'), { headers: { 'Content-Type': 'application/schema+json' } });
