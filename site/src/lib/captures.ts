// Casts and tickets recorded by capture/capture.py from the released bobina. The build stops when they were
// recorded with another version than the release the site describes: run `npm run capture` after a release.
import data from '../captures/captures.json';
import { release } from './site';

export interface Step {
  cmd: string;
  exit: number;
  text: string;
  html: string;
}
export interface Cast {
  id: string;
  title: string;
  steps: Step[];
}
export interface Ticket {
  id: string;
  group: string;
  png: string;
  width: number;
  height: number;
  file: string;
  label: string;
}

// A release commits its captures a moment after its tag (release-commit.yml): until then the site builds with the
// captures it has, and says so. CI sets BOBINA_SITE_STRICT=1 to fail instead.
if (data.bobina !== release.version) {
  const msg = `the casts and tickets were recorded with bobina ${data.bobina}, the site describes ${release.version} (${release.ref}); release-commit.yml records them for a release, or run \`npm run capture\` in site/`;
  if (process.env.BOBINA_SITE_STRICT === '1' && release.mode === 'release') throw new Error(msg);
  console.warn(`\n\x1b[33mWARNING: ${msg}\x1b[0m\n`);
}

export const captures = data as {
  bobina: string;
  release: string;
  files: Record<string, { path: string; text: string }>;
  casts: Cast[];
  tickets: Ticket[];
};

export const cast = (id: string) => {
  const c = captures.casts.find((x) => x.id === id);
  if (!c) throw new Error(`no cast ${id}`);
  return c;
};
export const ticket = (id: string) => {
  const t = captures.tickets.find((x) => x.id === id);
  if (!t) throw new Error(`no ticket ${id}`);
  return t;
};
export const tickets = (group: string) => captures.tickets.filter((t) => t.group === group);
export const file = (name: string) => captures.files[name];
