#!/usr/bin/env node
// Checks of the built site (dist/), run by `npm run build` and in CI. It fails when:
// - a page has no .md twin, or does not announce it (<link rel="alternate" type="text/markdown">);
// - an internal link or image (HTML, .md twins, llms.txt, llms-full.txt) points at a file or anchor that is not there;
// - vercel.json would not send `Accept: text/markdown` for a page to that page's twin;
// - a page holds a personal home folder or a Bluetooth address other than the documented AA:BB:CC:DD:EE:FF;
// - a page needs JavaScript for its content, or ships more JavaScript than the budget.
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = dirname(dirname(fileURLToPath(import.meta.url)));
const DIST = join(SITE, 'dist');
const SITE_URL = (process.env.BOBINA_SITE_URL || 'https://bobina.md').replace(/\/$/, '');
const JS_BUDGET = 8 * 1024; // bytes of our own JavaScript on any page (Pagefind on /search/ excluded)

const problems = [];
const fail = (msg) => problems.push(msg);

const files = [];
(function walk(d) {
  for (const f of readdirSync(d, { withFileTypes: true })) {
    const p = join(d, f.name);
    if (f.isDirectory()) walk(p);
    else files.push(relative(DIST, p).split('\\').join('/'));
  }
})(DIST);
const has = (rel) => files.includes(rel);
const read = (rel) => readFileSync(join(DIST, rel), 'utf8');
const pages = files.filter((f) => f.endsWith('.html') && !f.startsWith('pagefind/'));

/** URL path of a page file: about/index.html → /about/ */
const pathOf = (f) => '/' + f.replace(/index\.html$/, '').replace(/\.html$/, '');
/** The file a URL path is served from, or null. */
function fileFor(path) {
  const p = decodeURIComponent(path).replace(/^\//, '');
  for (const c of [p, p + 'index.html', p + '/index.html', p + '.html']) if (c && has(c)) return c;
  return p === '' && has('index.html') ? 'index.html' : null;
}
const idsCache = new Map();
function idsOf(file) {
  if (!idsCache.has(file)) idsCache.set(file, new Set([...read(file).matchAll(/\sid="([^"]+)"/g)].map((m) => m[1])));
  return idsCache.get(file);
}
/** The HTML page a .md twin stands for: /cli.md → cli/index.html, /index.md → index.html. */
const pageOfTwin = (twin) => (twin === 'index.md' ? 'index.html' : twin.replace(/\.md$/, '/index.html'));

function checkTarget(where, url) {
  let u;
  try {
    u = new URL(url, SITE_URL + '/');
  } catch {
    return fail(`${where}: bad URL ${url}`);
  }
  if (u.origin !== new URL(SITE_URL).origin) return;
  if (u.pathname.startsWith('/pagefind/')) return; // written by pagefind after astro
  const file = fileFor(u.pathname);
  if (!file) return fail(`${where}: ${url} does not exist`);
  if (u.hash && u.hash !== '#') {
    const page = file.endsWith('.md') ? pageOfTwin(file) : file;
    if (page.endsWith('.html') && has(page) && !idsOf(page).has(decodeURIComponent(u.hash.slice(1))))
      fail(`${where}: ${url}: no anchor ${u.hash} in ${page}`);
  }
}

// 1. pages, twins, links, JavaScript
let jsMax = 0;
for (const page of pages) {
  const html = read(page);
  const path = pathOf(page);
  const twin = path === '/' ? 'index.md' : page === '404.html' ? null : path.slice(1, -1) + '.md';
  if (twin) {
    if (!has(twin)) fail(`${path}: no Markdown twin ${twin}`);
    const alt = html.match(/<link rel="alternate" type="text\/markdown" href="([^"]+)"/);
    if (!alt || alt[1] !== '/' + twin) fail(`${path}: no <link rel="alternate" type="text/markdown" href="/${twin}">`);
    if (!html.includes(`href="/${twin}"`) || !/View as Markdown/.test(html)) fail(`${path}: no "View as Markdown" link (Copy for AI needs JS)`);
  }
  for (const m of html.matchAll(/\s(?:href|src)="([^"]+)"/g)) {
    const url = m[1].replace(/&amp;/g, '&');
    if (url.startsWith('#')) {
      if (url.length > 1 && !idsOf(page).has(decodeURIComponent(url.slice(1)))) fail(`${path}: no anchor ${url}`);
    } else checkTarget(path, url);
  }
  if (!/<main[\s>]/.test(html)) fail(`${path}: no <main>`);
  let js = 0;
  for (const m of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) js += m[1].length;
  for (const m of html.matchAll(/<script[^>]+src="(\/_astro\/[^"]+)"/g)) js += statSync(join(DIST, m[1])).size;
  if (path !== '/search/') jsMax = Math.max(jsMax, js);
  if (path !== '/search/' && js > JS_BUDGET) fail(`${path}: ${js} bytes of JavaScript, budget ${JS_BUDGET}`);
}

// 2. the Markdown side: twins, llms.txt, llms-full.txt

/** The text outside fenced code. A fence closes only with the same character, at least as many times (```` holds ```). */
function prose(text) {
  let out = '';
  let fence = null;
  for (const line of text.split(/(?<=\n)/)) {
    const m = line.match(/^ {0,3}(`{3,}|~{3,})/);
    const opens = m && (m[1][0] === "~" || !line.trimStart().slice(m[1].length).includes("`")); // CommonMark
    if (!fence && opens) fence = { char: m[1][0], size: m[1].length };
    else if (fence && m && m[1][0] === fence.char && m[1].length >= fence.size && /^\s*[`~]+\s*$/.test(line)) fence = null;
    else if (!fence) out += line;
  }
  return out;
}

const twins = files.filter((f) => f.endsWith('.md'));
for (const f of [...twins, 'llms.txt', 'llms-full.txt']) {
  if (!has(f)) {
    fail(`/${f} is missing`);
    continue;
  }
  const text = prose(read(f)).replace(/`[^`\n]*`/g, '');
  for (const m of text.matchAll(/\]\(([^)\s]+)\)/g)) {
    if (m[1].startsWith(SITE_URL) || m[1].startsWith('/')) checkTarget(`/${f}`, m[1]);
    else if (!/^[a-z][a-z0-9+.-]*:|^#/i.test(m[1]) && /\.md(#|$)/.test(m[1])) fail(`/${f}: a repository link left as is: ${m[1]}`);
  }
}
if (!/^# bobina/.test(read('llms.txt'))) fail('/llms.txt does not start with "# bobina"');
if (!read('llms.txt').includes(`${SITE_URL}/cli.md`)) fail('/llms.txt does not link the .md pages');

// 3. vercel.json: Accept: text/markdown on a page path is routed to its twin
const vercel = JSON.parse(readFileSync(join(SITE, '..', 'vercel.json'), 'utf8'));
const negotiation = (vercel.routes || []).filter((r) => (r.has || []).some((h) => h.type === 'header' && h.key === 'accept'));
if (!negotiation.length) fail('vercel.json: no route on the accept header');
for (const page of pages.filter((p) => p !== '404.html')) {
  for (const path of [pathOf(page), pathOf(page).replace(/\/$/, '') || '/']) {
    const route = negotiation.find((r) => new RegExp(r.src).test(path));
    if (!route) {
      fail(`vercel.json: ${path} with Accept: text/markdown matches no route`);
      continue;
    }
    const m = path.match(new RegExp(route.src));
    const dest = route.dest.replace(/\$(\d)/g, (_, i) => m[i] ?? '');
    if (!has(dest.slice(1))) fail(`vercel.json: ${path} → ${dest}, which does not exist`);
  }
}
// a problem code as bobina prints it (E107) redirects to its page and its twin, which are lower case
const redirects = (vercel.routes || []).filter((r) => r.status === 308 && r.headers?.Location);
for (const page of pages.filter((p) => /^problems\/[a-z]\d{3}\/index\.html$/.test(p))) {
  const code = page.split('/')[1];
  for (const path of [`/problems/${code.toUpperCase()}/`, `/problems/${code.toUpperCase()}`, `/problems/${code.toUpperCase()}.md`]) {
    const route = redirects.find((r) => new RegExp(r.src).test(path));
    if (!route) {
      fail(`vercel.json: ${path} is not redirected`);
      continue;
    }
    const m = path.match(new RegExp(route.src));
    const to = route.headers.Location.replace(/\$(\d)/g, (_, i) => m[i] ?? '');
    if (!fileFor(to)) fail(`vercel.json: ${path} → ${to}, which does not exist`);
  }
}
for (const asset of ['/llms.txt', '/fonts/terminus.woff2', '/captures/receipt.png', '/cli.md']) {
  if (negotiation.some((r) => new RegExp(r.src).test(asset))) fail(`vercel.json: ${asset} would be negotiated too`);
}

// 4. personal data (the same generic rules as tools/leakscan.py)
const LEAKS = {
  'home folder': /\/(?:home|Users)\/(?!user\b|runner\b|you\b|me\b)[a-z][\w.-]+/,
  'bluetooth address': /(?<![0-9A-Fa-f:])(?!AA:BB:CC:DD:EE:FF)[0-9A-F]{2}(?::[0-9A-F]{2}){5}(?![0-9A-Fa-f:])/,
};
for (const f of files.filter((x) => /\.(html|md|txt|json|xml|js|css)$/.test(x) && !x.startsWith('pagefind/'))) {
  const text = read(f);
  for (const [name, rx] of Object.entries(LEAKS)) {
    const m = text.match(rx);
    if (m) fail(`/${f}: a ${name} (${m[0].slice(0, 3)}…)`);
  }
}

if (!existsSync(join(DIST, 'pagefind', 'pagefind-ui.js'))) fail('no Pagefind index (run pagefind --site dist)');

if (problems.length) {
  console.error(problems.map((p) => `check: ${p}`).join('\n'));
  console.error(`check: ${problems.length} problem(s)`);
  process.exit(1);
}
console.log(`check: ${pages.length} pages, ${twins.length} .md twins, links and anchors resolve, JavaScript ≤ ${jsMax} bytes/page`);
