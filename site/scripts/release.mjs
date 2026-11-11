#!/usr/bin/env node
// Which docs the site describes: the latest release, never main. Writes .release/release.json and, for a tag,
// extracts that tag's files into .release/tree/ (README.md, CHANGELOG.md, docs/, examples/, llms*.txt...).
//
//   default                     the newest vX.Y.Z tag (pre-releases skipped) of the public repository
//   BOBINA_SITE_REF=v0.1.0      that tag, branch or commit
//   BOBINA_SITE_REF=WORKTREE    the files of this checkout as they are (to work on docs before a release)
//
// Works in a full clone, in a shallow clone without tags (Vercel, CI) and without git at all (GitHub tarball).
import { execFileSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE = dirname(dirname(fileURLToPath(import.meta.url)));
const ROOT = dirname(SITE);
const OUT = join(SITE, '.release');
const TREE = join(OUT, 'tree');
const REPO = (process.env.BOBINA_SITE_REPO || 'https://github.com/rafaelbressan/bobina').replace(/\.git$/, '');
const STABLE = /^v(\d+)\.(\d+)\.(\d+)(?:\.post(\d+))?$/; // a release (v0.1.1, v0.1.1.post1), never an rc

const log = (msg) => console.log(`release: ${msg}`);
const git = (args, env) =>
  execFileSync('git', args, { cwd: ROOT, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], env: { ...process.env, ...env } }).trim();
const tryGit = (args, env) => {
  try {
    return git(args, env);
  } catch {
    return null;
  }
};

function newest(tags) {
  const key = (t) => t.match(STABLE).slice(1).map((n) => Number(n ?? -1)); // v0.1.1 before v0.1.1.post1
  const stable = tags.filter((t) => STABLE.test(t));
  stable.sort((a, b) => {
    const [x, y] = [key(a), key(b)];
    return x[0] - y[0] || x[1] - y[1] || x[2] - y[2] || x[3] - y[3];
  });
  return stable.at(-1) ?? null;
}

async function latestTag() {
  const remote = tryGit(['ls-remote', '--tags', '--refs', REPO, 'v*']);
  if (remote) {
    const tag = newest(remote.split('\n').map((l) => l.split('refs/tags/')[1]).filter(Boolean));
    if (tag) return tag;
  }
  log(`git ls-remote ${REPO} failed: trying the GitHub API`);
  try {
    const api = REPO.replace('https://github.com/', 'https://api.github.com/repos/');
    const res = await fetch(`${api}/releases/latest`, { headers: { accept: 'application/vnd.github+json' } });
    if (res.ok) return (await res.json()).tag_name;
  } catch {}
  const local = tryGit(['tag', '--list', 'v*']);
  const tag = local && newest(local.split('\n'));
  if (tag) {
    log(`offline: using the newest local tag ${tag}`);
    return tag;
  }
  throw new Error('no release tag found (no network and no local tags): set BOBINA_SITE_REF');
}

function haveLocally(ref) {
  return tryGit(['rev-parse', '--verify', '--quiet', `${ref}^{commit}`]);
}

function extractWithGit(ref) {
  if (tryGit(['rev-parse', '--git-dir']) === null) return null;
  let commit = haveLocally(ref);
  if (!commit) {
    const spec = STABLE.test(ref) || /^v\d/.test(ref) ? `+refs/tags/${ref}:refs/tags/${ref}` : ref;
    if (tryGit(['fetch', '--quiet', '--depth=1', '--no-tags', REPO, spec]) === null) return null;
    commit = haveLocally(/^v\d/.test(ref) ? ref : 'FETCH_HEAD');
    if (!commit) return null;
  }
  rmSync(TREE, { recursive: true, force: true });
  mkdirSync(TREE, { recursive: true });
  const env = { GIT_INDEX_FILE: join(OUT, 'index') };
  git(['read-tree', commit], env); // a private index: the checkout's own index and files are not touched
  git(['checkout-index', '--all', '--force', `--prefix=${TREE}/`], env);
  rmSync(env.GIT_INDEX_FILE, { force: true });
  return commit;
}

async function extractTarball(ref) {
  const url = `${REPO.replace('https://github.com/', 'https://codeload.github.com/')}/tar.gz/${ref}`;
  log(`git is not usable here: downloading ${url}`);
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: HTTP ${res.status}`);
  const file = join(OUT, 'tree.tar.gz');
  writeFileSync(file, Buffer.from(await res.arrayBuffer()));
  rmSync(TREE, { recursive: true, force: true });
  mkdirSync(TREE, { recursive: true });
  execFileSync('tar', ['-xzf', file, '-C', TREE, '--strip-components=1']);
  rmSync(file);
  return null;
}

function versionOf(dir) {
  const m = readFileSync(join(dir, 'pyproject.toml'), 'utf8').match(/^version\s*=\s*"([^"]+)"/m);
  return m ? m[1] : null;
}

async function main() {
  mkdirSync(OUT, { recursive: true });
  const wanted = process.env.BOBINA_SITE_REF;
  let info;
  if (wanted === 'WORKTREE') {
    info = { mode: 'worktree', ref: tryGit(['rev-parse', '--abbrev-ref', 'HEAD']) || 'main', tag: null, commit: tryGit(['rev-parse', 'HEAD']), root: '..' };
  } else {
    const ref = wanted || (await latestTag());
    const commit = extractWithGit(ref) ?? (await extractTarball(ref));
    info = { mode: wanted ? 'ref' : 'release', ref, tag: STABLE.test(ref) ? ref : null, commit, root: relative(SITE, TREE) };
  }
  const dir = join(SITE, info.root);
  info.version = versionOf(dir);
  info.repo = REPO;
  for (const f of ['README.md', 'docs/CLI.md', 'llms.txt', 'llms-full.txt']) {
    if (!existsSync(join(dir, f))) throw new Error(`${info.ref}: ${f} is missing`);
  }
  writeFileSync(join(OUT, 'release.json'), JSON.stringify(info, null, 2) + '\n');
  // Astro caches rendered content between builds; a new release or a changed plugin must render again
  rmSync(join(SITE, 'node_modules', '.astro'), { recursive: true, force: true });
  rmSync(join(SITE, '.astro'), { recursive: true, force: true });
  log(`${info.mode} ${info.ref} (bobina ${info.version}) from ${info.root}`);
}

main().catch((e) => {
  console.error(`release: ${e.message}`);
  process.exit(1);
});
