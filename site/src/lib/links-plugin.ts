// A Sätteri mdast plugin: links between repository files become links between site pages (src/lib/site.ts).
import { relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import { siteLink, TREE } from './site';

const fromOf = (url: URL | undefined) => (url ? relative(TREE, fileURLToPath(url)).split('\\').join('/') : null);

export const linksPlugin = {
  name: 'bobina-site-links',
  link(node: { url: string }, ctx: any) {
    const from = fromOf(ctx.fileURL);
    const to = from && siteLink(node.url, from);
    if (to) ctx.setField(node, 'url', to);
  },
  definition(node: { url: string }, ctx: any) {
    const from = fromOf(ctx.fileURL);
    const to = from && siteLink(node.url, from);
    if (to) ctx.setField(node, 'url', to);
  },
  inlineCode(node: { value: string }, ctx: any) {
    // short spans never break (`--strict` must not become `--` + `strict` on a phone); long ones may
    if (node.value.length <= 28) ctx.setField(node, 'data', { hProperties: { className: ['nw'] } });
  },
  image(node: { url: string; alt?: string }, ctx: any) {
    const from = fromOf(ctx.fileURL);
    const to = from && siteLink(node.url, from, { image: true });
    if (to) ctx.setField(node, 'url', to);
    else if (!/^[a-z][a-z0-9+.-]*:|^\//i.test(node.url)) {
      // names no file: an example of the syntax in prose (docs/problems/I107.md); show it as written
      const url = /\s/.test(node.url) ? `<${node.url}>` : node.url;
      ctx.replaceNode(node, { type: 'inlineCode', value: `![${node.alt ?? ''}](${url})` });
    }
  },
};
