// What the site is made of: the release it describes, which repository file becomes which page, and how a link
// between repository files becomes a link between pages. Used by the content config, the Markdown plugin (HTML
// pages) and the .md twins, so both say the same thing.
import { existsSync, readFileSync, statSync } from 'node:fs';
import { join, posix } from 'node:path';

// npm runs every script from site/; an editor or `astro --root site` may start at the repository root
const SITE_DIR = existsSync(join(process.cwd(), 'astro.config.mjs')) ? process.cwd() : join(process.cwd(), 'site');
export const SITE_URL = (process.env.BOBINA_SITE_URL || 'https://bobina.md').replace(/\/$/, '');

export interface Release {
  mode: 'release' | 'ref' | 'worktree';
  ref: string;
  tag: string | null;
  commit: string | null;
  root: string;
  version: string;
  repo: string;
}

export const release: Release = JSON.parse(readFileSync(join(SITE_DIR, '.release', 'release.json'), 'utf8'));
/** The folder holding the release's files (README.md, docs/, examples/...). */
export const TREE = join(SITE_DIR, release.root);
/** Links to files that are not pages point at GitHub, at the release they were read from. */
export const GITHUB_REF = release.tag ?? (release.mode === 'worktree' ? 'main' : release.commit ?? release.ref);
export const githubUrl = (rel: string, dir = false) => `${release.repo}/${dir ? 'tree' : 'blob'}/${GITHUB_REF}/${rel}`;

/** The page a repository file becomes ('' is the home page), or null when it is not a page. */
export function slugOf(rel: string): string | null {
  if (rel === 'README.md') return '';
  if (rel === 'CHANGELOG.md') return 'changelog';
  if (!rel.startsWith('docs/') || !rel.endsWith('.md')) return null;
  return rel.slice(5, -3).replace(/(^|\/)README$/, '').toLowerCase();
}

export const htmlUrl = (slug: string) => (slug ? `/${slug}/` : '/');
export const mdUrl = (slug: string) => (slug ? `/${slug}.md` : '/index.md');

const exists = (rel: string) => existsSync(join(TREE, rel));

/**
 * Where a link written in the repository file `from` should point on the site; null keeps it as written (a URL,
 * an anchor, or a syntax example such as `![alt](photo.jpg)` that names no file).
 * `md`: for the .md twins and llms.txt, absolute URLs of other .md twins.
 */
export function siteLink(target: string, from: string, opts: { md?: boolean; image?: boolean } = {}): string | null {
  if (/^[a-z][a-z0-9+.-]*:/i.test(target) || target.startsWith('#') || target.startsWith('/') || !target) return null;
  const hashAt = target.indexOf('#');
  const path = hashAt < 0 ? target : target.slice(0, hashAt);
  const anchor = hashAt < 0 ? '' : target.slice(hashAt);
  let rel: string;
  try {
    rel = posix.normalize(posix.join(posix.dirname(from), decodeURI(path))).replace(/\/$/, '');
  } catch {
    return null;
  }
  if (!path || rel.startsWith('..') || !exists(rel)) return null;
  const base = opts.md ? SITE_URL : '';
  if (opts.image) return `${base}/repo/${rel}`; // copied by the repoImages integration (astro.config.mjs)
  const slug = slugOf(rel);
  if (slug !== null) return (opts.md ? SITE_URL + mdUrl(slug) : htmlUrl(slug)) + anchor;
  if (rel === 'llms.txt' || rel === 'llms-full.txt') return `${base}/${rel}`;
  if (/^docs\/schemas\/[\w.-]+\.json$/.test(rel)) return `${base}/schemas/${posix.basename(rel)}`;
  return githubUrl(rel, statSync(join(TREE, rel)).isDirectory()) + anchor;
}

/**
 * A Markdown text cut into prose and fenced code, alternately (odd parts are code). A fence closes only with the
 * same character, at least as many times: ```` ```` ```` holds ``` lines (README.md, FORMAT.md, pay.md).
 */
export function splitFences(text: string): string[] {
  const parts: string[] = [];
  let current = '';
  let fence: { char: string; size: number } | null = null;
  for (const line of text.split(/(?<=\n)/)) {
    const m = line.match(/^ {0,3}(`{3,}|~{3,})/);
    // CommonMark: the info string of a backtick fence holds no backtick (```` ```pix ```` is inline code)
    const opens = m && (m[1][0] === "~" || !line.trimStart().slice(m[1].length).includes("`"));
    if (!fence && opens) {
      parts.push(current);
      current = line;
      fence = { char: m[1][0], size: m[1].length };
    } else if (fence && m && m[1][0] === fence.char && m[1].length >= fence.size && /^\s*[`~]+\s*$/.test(line)) {
      parts.push(current + line);
      current = '';
      fence = null;
    } else current += line;
  }
  parts.push(current);
  return parts;
}

/** Rewrite the links of a Markdown text (outside fenced code) for its .md twin. */
export function rewriteMarkdown(text: string, from: string): string {
  return splitFences(text)
    .map((part, i) =>
      i % 2
        ? part
        : part.replace(/(!?)\[([^\]\n]*)\]\(([^)\s]+)\)/g, (m, bang, label, target) => {
            const to = siteLink(target, from, { md: true, image: bang === '!' });
            return to ? `${bang}[${label}](${to})` : m; // a link that names no file (a syntax example) stays
          }),
    )
    .join('');
}

/** The first `# ` heading of a Markdown text. */
export function titleOf(body: string, fallback: string): string {
  const m = body.match(/^#\s+(.+?)\s*$/m);
  return m ? m[1].replace(/`/g, '') : fallback;
}

/** Estimated tokens, the rule of tests/test_token_budget.py (characters / 4). */
export const tokens = (text: string) => Math.floor(text.length / 4);
