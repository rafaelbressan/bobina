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

if (data.bobina !== release.version) {
  const msg = `the captures are of bobina ${data.bobina}, the site describes ${release.version} (${release.ref}): run \`npm run capture\` in site/`;
  if (release.mode === 'release') throw new Error(msg);
  console.warn(`warning: ${msg}`);
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
