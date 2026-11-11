import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { htmlUrl, TREE } from './site';

export interface NavItem {
  slug: string;
  label: string;
  href: string;
}

const item = (slug: string, label: string, fallback?: string): NavItem => ({
  slug,
  label,
  href: htmlUrl(slug),
  ...(fallback ? { href: fallback } : {}),
});

/** The main sections. A release older than docs/agents.md has the MCP section in the CLI reference. */
export const NAV: NavItem[] = [
  item('install', 'Install'),
  item('guides', 'Guides'),
  item('cli', 'CLI'),
  item('format', 'Format'),
  item('printers', 'Printers'),
  existsSync(join(TREE, 'docs/agents.md')) ? item('agents', 'Agents') : item('agents', 'Agents', '/cli/#agents-bobina-mcp'),
  item('pay', 'Pay codes'),
  item('problems', 'Problems'),
  item('changelog', 'Changelog'),
];

export const MORE: NavItem[] = [item('security', 'Security'), item('tested', 'Tested on paper'), item('schemas', 'JSON schemas')];

/** Which section a page belongs to (for the "you are here" mark). */
export function sectionOf(slug: string): string {
  const top = slug.split('/')[0];
  if (top === 'tested') return 'printers';
  if (top === 'diagrams') return 'problems';
  if (top === 'mcp') return 'agents';
  return top;
}

/** Short names for page titles where the first heading is long. */
export const SHORT_TITLES: Record<string, string> = {
  cli: 'CLI reference',
  format: 'Document format',
  install: 'Install',
  pay: 'Payment codes',
  problems: 'Problem codes',
  changelog: 'Changelog',
  security: 'Security',
  tested: 'What was tested on paper',
  schemas: 'JSON schemas',
  agents: 'bobina for agents',
  mcp: 'The MCP server',
};
