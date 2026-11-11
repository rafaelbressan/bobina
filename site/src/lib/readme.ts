// Pieces of the release's README.md for the home page, so the home says what the release says.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { siteLink, TREE } from './site';

const README = readFileSync(join(TREE, 'README.md'), 'utf8');

const escape = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** Inline Markdown (code, bold, links) to HTML, with links made site links. */
export function inline(md: string, from = 'README.md'): string {
  const parts = md.replace(/\s+/g, ' ').trim().split(/(`[^`]+`)/);
  return parts
    .map((p, i) => {
      if (i % 2) return `<code>${escape(p.slice(1, -1))}</code>`;
      return escape(p)
        .replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>')
        .replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, (_, text, href) => `<a href="${siteLink(href, from) ?? href}">${text}</a>`);
    })
    .join('');
}

const section = (heading: string) => {
  const m = README.match(new RegExp(`^## ${heading}\\n([\\s\\S]*?)(?=^## |$(?![\\s\\S]))`, 'm'));
  return m ? m[1] : '';
};

/** The paragraph under the title. */
export const lede = inline(README.split(/\n\s*\n/)[1] ?? '');

/** "## Why": its first paragraph and its bullets. */
const why = section('Why');
export const whyIntro = inline(why.trim().split(/\n\s*\n/)[0] ?? '');
export const whyPoints = why
  .split(/\n(?=- )/)
  .filter((b) => b.startsWith('- '))
  .map((b) => inline(b.slice(2)));
