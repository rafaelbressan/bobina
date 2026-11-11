// Pages that no single file holds: the guides and printers indexes (and the search page), as HTML and as .md.
import { getCollection } from 'astro:content';
import { htmlUrl, mdUrl, SITE_URL, slugOf, titleOf } from './site';

export interface HubItem {
  title: string;
  href: string;
  md: string;
  summary: string;
}
export interface Hub {
  slug: string;
  title: string;
  intro: string;
  items: HubItem[];
  markdown: string;
}

function summaryOf(body: string): string {
  const p = body.split(/\n\s*\n/).find((x) => x.trim() && !/^(#|\||```|>|-|\d+\.)/.test(x.trim()));
  return p ? p.replace(/\s+/g, ' ').replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').trim() : '';
}

function hub(slug: string, title: string, intro: string, items: HubItem[]): Hub {
  const lines = [`# ${title}`, '', intro, ''];
  for (const i of items) lines.push(`- [${i.title}](${SITE_URL}${i.md}): ${i.summary}`);
  return { slug, title, intro, items, markdown: lines.join('\n') + '\n' };
}

export async function hubs(): Promise<Hub[]> {
  const entries = await getCollection('docs');
  const itemOf = (id: string, title?: string): HubItem | null => {
    const e = entries.find((x) => x.id === id);
    if (!e) return null;
    const slug = slugOf(id)!;
    return { title: title ?? titleOf(e.body ?? '', slug), href: htmlUrl(slug), md: mdUrl(slug), summary: summaryOf(e.body ?? '') };
  };
  const ids = entries.map((e) => e.id).sort();
  const guides = ids.filter((id) => id.startsWith('docs/guides/')).map((id) => itemOf(id)!);
  const printers = [
    ...ids.filter((id) => id.startsWith('docs/printers/')).map((id) => itemOf(id)!),
    itemOf('docs/TESTED.md', 'What was tested on paper'),
  ].filter((x): x is HubItem => x !== null);
  return [
    hub('guides', 'Guides', 'Step by step, with real files from the repository.', guides),
    hub(
      'printers',
      'Printers',
      'bobina was calibrated on a minimum-quality printer: every default of a measured profile comes from a printed and photographed test. Other profiles are imported from escpos-printer-db and conservative until calibrated (`bobina profile list` says which are measured; `bobina calibrate tear` and `bobina calibrate feed` measure yours).',
      printers,
    ),
    hub('search', 'Search', 'Search runs in your browser. Without JavaScript, the whole docs are also one file, `llms-full.txt`, to read or search as text.', [
      { title: 'llms-full.txt', href: '/llms-full.txt', md: '/llms-full.txt', summary: 'the docs in one file' },
      { title: 'llms.txt', href: '/llms.txt', md: '/llms.txt', summary: 'the index, with the facts an agent needs first' },
    ]),
  ];
}
